"""
Tests for the campaign tools (tools/*.py).

Run:  python3 -m unittest discover -s tests -v

Stdlib only — no pytest needed. Tools that write state (combat_tracker,
narrate) run against a temp directory via the DND_ROOT env override, so
running the suite never touches live campaign state.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass introspection needs the module registered
    spec.loader.exec_module(mod)
    return mod


dice = load_module("dice", TOOLS / "dice.py")
check_resolver = load_module("check_resolver", TOOLS / "check_resolver.py")


class TestDiceParse(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(dice.parse("1d20+5"), (1, 20, 5))
        self.assertEqual(dice.parse("2d6"), (2, 6, 0))
        self.assertEqual(dice.parse("d8"), (1, 8, 0))
        self.assertEqual(dice.parse("1d20-2"), (1, 20, -2))

    def test_rejects_garbage(self):
        for bad in ("banana", "1d", "d", "0d6", "1d1", "101d6", "1d20+"):
            with self.assertRaises(SystemExit, msg=bad):
                dice.parse(bad)


class TestDiceRoll(unittest.TestCase):
    def test_normal_bounds_and_modifier(self):
        for _ in range(50):
            r = dice.do_roll("2d6+3", "normal", None)
            self.assertEqual(len(r.dice), 2)
            self.assertEqual(r.kept, r.dice)
            self.assertTrue(all(1 <= d <= 6 for d in r.dice))
            self.assertEqual(r.total, sum(r.kept) + 3)

    def test_advantage_keeps_max(self):
        for _ in range(50):
            r = dice.do_roll("1d20+0", "advantage", None)
            self.assertEqual(len(r.dice), 2)
            self.assertEqual(r.kept, [max(r.dice)])

    def test_disadvantage_keeps_min(self):
        for _ in range(50):
            r = dice.do_roll("1d20+0", "disadvantage", None)
            self.assertEqual(r.kept, [min(r.dice)])

    def test_advantage_requires_1d20(self):
        with self.assertRaises(SystemExit):
            dice.do_roll("2d6", "advantage", None)

    def test_drop_lowest(self):
        for _ in range(50):
            r = dice.do_roll("4d6", "drop-lowest", None)
            self.assertEqual(len(r.dice), 4)
            self.assertEqual(len(r.kept), 3)
            self.assertEqual(sum(r.kept), sum(r.dice) - min(r.dice))

    def test_drop_lowest_needs_two_dice(self):
        with self.assertRaises(SystemExit):
            dice.do_roll("1d6", "drop-lowest", None)

    def test_crit_flags(self):
        original = dice.roll_one
        try:
            dice.roll_one = lambda sides: 20
            self.assertIs(dice.do_roll("1d20+5", "normal", None).crit, True)
            dice.roll_one = lambda sides: 1
            self.assertIs(dice.do_roll("1d20+5", "normal", None).crit, False)
            dice.roll_one = lambda sides: 10
            self.assertIsNone(dice.do_roll("1d20+5", "normal", None).crit)
            # crit is only meaningful on 1d20
            dice.roll_one = lambda sides: 6
            self.assertIsNone(dice.do_roll("2d6", "normal", None).crit)
        finally:
            dice.roll_one = original

    def test_cli_emits_json(self):
        out = subprocess.check_output(
            [sys.executable, str(TOOLS / "dice.py"), "1d20+5", "--label", "test roll"]
        )
        r = json.loads(out)
        self.assertEqual(r["expression"], "1d20+5")
        self.assertEqual(r["label"], "test roll")
        self.assertEqual(r["total"], r["kept"][0] + 5)


class TestCheckResolver(unittest.TestCase):
    CHAR = {
        "name": "Testa",
        "proficiency_bonus": 3,
        "abilities": {"str": 8, "dex": 16, "con": 10, "int": 13, "wis": 14, "cha": 12},
        "skills": {"stealth": "proficient", "perception": "expertise"},
        "save_proficiencies": ["dex", "int"],
    }

    def test_ability_mod(self):
        cases = {1: -5, 8: -1, 10: 0, 11: 0, 15: 2, 16: 3, 20: 5}
        for score, expected in cases.items():
            self.assertEqual(check_resolver.ability_mod(score), expected)

    def test_skill_bonus(self):
        # proficient: dex 16 (+3) + prof 3
        self.assertEqual(check_resolver.get_skill_bonus(self.CHAR, "stealth"), (6, "dex"))
        # expertise: wis 14 (+2) + 2*prof
        self.assertEqual(check_resolver.get_skill_bonus(self.CHAR, "perception"), (8, "wis"))
        # untrained: cha 12 (+1)
        self.assertEqual(check_resolver.get_skill_bonus(self.CHAR, "persuasion"), (1, "cha"))
        # name normalization
        self.assertEqual(check_resolver.get_skill_bonus(self.CHAR, "Sleight of Hand"), (3, "dex"))

    def test_unknown_skill(self):
        with self.assertRaises(SystemExit):
            check_resolver.get_skill_bonus(self.CHAR, "lockpicking")

    def test_save_bonus(self):
        self.assertEqual(check_resolver.get_save_bonus(self.CHAR, "dex"), 6)   # proficient
        self.assertEqual(check_resolver.get_save_bonus(self.CHAR, "wis"), 2)   # not proficient
        with self.assertRaises(SystemExit):
            check_resolver.get_save_bonus(self.CHAR, "luck")

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            char_path = Path(tmp) / "pc-test.json"
            char_path.write_text(json.dumps(self.CHAR))
            out = subprocess.check_output([
                sys.executable, str(TOOLS / "check_resolver.py"),
                "--char", str(char_path), "--skill", "stealth", "--dc", "10",
            ])
            r = json.loads(out)
            self.assertEqual(r["bonus"], 6)
            self.assertEqual(r["success"], r["roll"]["total"] >= 10)
            self.assertEqual(r["margin"], r["roll"]["total"] - 10)


class TestCombatTracker(unittest.TestCase):
    """Drive the tracker CLI against a temp DND_ROOT so live state is untouched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.env = {**os.environ, "DND_ROOT": str(self.root)}

    def tearDown(self):
        self._tmp.cleanup()

    def run_cmd(self, *args, check=True):
        proc = subprocess.run(
            [sys.executable, str(TOOLS / "combat_tracker.py"), *args],
            env=self.env, capture_output=True, text=True,
        )
        if check:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def state(self) -> dict:
        return json.loads((self.root / "state" / "combat.json").read_text())

    def test_full_encounter_flow(self):
        self.run_cmd("start", "--participants", "Alex:+3", "Goblin1:+2", "Goblin2:0")
        s = self.state()
        self.assertTrue(s["active"])
        self.assertEqual(s["round"], 1)
        self.assertEqual(len(s["order"]), 3)
        inits = [o["init"] for o in s["order"]]
        self.assertEqual(inits, sorted(inits, reverse=True))

        self.run_cmd("sethp", "--who", "Goblin1", "--current", "7", "--max", "7")
        out = self.run_cmd("damage", "--who", "Goblin1", "--amount", "9").stdout
        self.assertIn("DOWN", out)
        self.assertEqual(next(o for o in self.state()["order"] if o["name"] == "Goblin1")["hp"], -2)

        # heal caps at max_hp
        self.run_cmd("heal", "--who", "Goblin1", "--amount", "50")
        self.assertEqual(next(o for o in self.state()["order"] if o["name"] == "Goblin1")["hp"], 7)

        self.run_cmd("condition", "--who", "Alex", "--add", "prone")
        alex = next(o for o in self.state()["order"] if o["name"] == "Alex")
        self.assertIn("prone", alex["conditions"])
        self.run_cmd("condition", "--who", "Alex", "--remove", "prone")
        alex = next(o for o in self.state()["order"] if o["name"] == "Alex")
        self.assertNotIn("prone", alex["conditions"])

        # advance through a full round -> round counter increments
        for _ in range(3):
            self.run_cmd("next")
        self.assertEqual(self.state()["round"], 2)

        self.run_cmd("end")
        self.assertFalse(self.state()["active"])

    def test_unknown_combatant_fails(self):
        self.run_cmd("start", "--participants", "Alex:+3")
        proc = self.run_cmd("damage", "--who", "Nobody", "--amount", "1", check=False)
        self.assertNotEqual(proc.returncode, 0)

    def test_next_without_combat_fails(self):
        proc = self.run_cmd("next", check=False)
        self.assertNotEqual(proc.returncode, 0)


class TestNarrate(unittest.TestCase):
    def test_appends_feed_entry_with_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            (root / "sessions").mkdir()
            (root / "state" / "current.json").write_text(json.dumps(
                {"location": {"specific": "The Stonehill Inn"}}
            ))
            (root / "sessions" / "session-03.md").write_text("# log\n")
            env = {**os.environ, "DND_ROOT": str(root)}

            for i, text in enumerate(["First line.", "Second line."]):
                subprocess.run(
                    [sys.executable, str(TOOLS / "narrate.py"), text],
                    env=env, check=True, capture_output=True,
                )

            lines = (root / "state" / "player-feed.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 2)
            entry = json.loads(lines[0])
            self.assertEqual(entry["text"], "First line.")
            self.assertEqual(entry["type"], "narration")
            self.assertEqual(entry["location"], "The Stonehill Inn")
            self.assertEqual(entry["session"], "session-03")
            self.assertTrue(entry["id"])
            # ids must be unique per entry
            self.assertNotEqual(entry["id"], json.loads(lines[1])["id"])


class TestBudgetRecap(unittest.TestCase):
    budget = load_module("budget_recap", TOOLS / "budget_recap.py")

    def test_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recap.md"
            path.write_text("x" * 100)
            self.assertEqual(self.budget.report(path, 1000)["status"], "under")
            path.write_text("x" * 900)
            self.assertEqual(self.budget.report(path, 1000)["status"], "ok")
            path.write_text("x" * 1500)
            self.assertEqual(self.budget.report(path, 1000)["status"], "over")

    def test_missing_file(self):
        with self.assertRaises(SystemExit):
            self.budget.report(Path("/nonexistent/recap.md"), 1000)


if __name__ == "__main__":
    unittest.main()
