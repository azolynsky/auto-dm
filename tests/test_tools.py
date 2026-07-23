"""
Tests for the campaign tools (tools/*.py).

Run:  python3 -m unittest discover -s tests -v

Stdlib only — no pytest needed. Tools that read/write state run against a
temp directory via the CAMPAIGN_ROOT env override, so running the suite never
touches live campaign state.
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


campaign_lib = load_module("campaign_lib", TOOLS / "campaign_lib.py")
dice = load_module("dice", TOOLS / "dice.py")
check_resolver = load_module("check_resolver", TOOLS / "check_resolver.py")


class TempRootMixin(unittest.TestCase):
    """A temp campaign root wired through CAMPAIGN_ROOT for subprocess calls."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir()
        (self.root / "sessions").mkdir()
        self.env = {**os.environ, "CAMPAIGN_ROOT": str(self.root)}

    def tearDown(self):
        self._tmp.cleanup()


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


class TestDiceCli(TempRootMixin):
    def test_single_expression_emits_object(self):
        out = subprocess.check_output(
            [sys.executable, str(TOOLS / "dice.py"), "1d20+5", "--label", "test roll"],
            env=self.env,
        )
        r = json.loads(out)
        self.assertEqual(r["expression"], "1d20+5")
        self.assertEqual(r["label"], "test roll")
        self.assertEqual(r["total"], r["kept"][0] + 5)

    def test_positional_mode_back_compat(self):
        out = subprocess.check_output(
            [sys.executable, str(TOOLS / "dice.py"), "1d20+2", "advantage"],
            env=self.env,
        )
        r = json.loads(out)
        self.assertEqual(r["mode"], "advantage")
        self.assertEqual(len(r["dice"]), 2)

    def test_batch_emits_array_with_ordered_labels(self):
        out = subprocess.check_output(
            [sys.executable, str(TOOLS / "dice.py"), "1d20+5", "2d6+3",
             "--label", "to-hit", "--label", "damage"],
            env=self.env,
        )
        rolls = json.loads(out)
        self.assertEqual([r["label"] for r in rolls], ["to-hit", "damage"])
        self.assertEqual([r["expression"] for r in rolls], ["1d20+5", "2d6+3"])

    def test_show_rolls_queues_public_effects(self):
        (self.root / "state" / "settings.json").write_text(json.dumps({"show_rolls": True}))
        subprocess.check_output(
            [sys.executable, str(TOOLS / "dice.py"), "1d20+5", "--label", "open roll"],
            env=self.env,
        )
        pending = self.root / "state" / "pending-effects.jsonl"
        self.assertTrue(pending.exists())
        self.assertIn("open roll", pending.read_text())

    def test_no_settings_means_secret_rolls(self):
        subprocess.check_output(
            [sys.executable, str(TOOLS / "dice.py"), "1d20+5", "--label", "secret"],
            env=self.env,
        )
        self.assertFalse((self.root / "state" / "pending-effects.jsonl").exists())


class TestEffectsQueue(TempRootMixin):
    def test_queue_and_drain(self):
        campaign_lib.queue_effect(self.root, "Goblin1 takes 7 damage")
        campaign_lib.queue_effect(self.root, "Goblin1 is prone")
        self.assertEqual(campaign_lib.drain_effects(self.root),
                         ["Goblin1 takes 7 damage", "Goblin1 is prone"])
        # drained means gone
        self.assertEqual(campaign_lib.drain_effects(self.root), [])

    def test_settings_defaults_and_merge(self):
        s = campaign_lib.load_settings(self.root)
        self.assertEqual(s, campaign_lib.DEFAULT_SETTINGS)
        (self.root / "state" / "settings.json").write_text(
            json.dumps({"show_rolls": True, "bogus_key": 1}))
        s = campaign_lib.load_settings(self.root)
        self.assertTrue(s["show_rolls"])
        self.assertNotIn("bogus_key", s)


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
            ], env={**os.environ, "CAMPAIGN_ROOT": tmp})
            r = json.loads(out)
            self.assertEqual(r["bonus"], 6)
            self.assertEqual(r["success"], r["roll"]["total"] >= 10)
            self.assertEqual(r["margin"], r["roll"]["total"] - 10)


class TestCombatTracker(TempRootMixin):
    """Drive the tracker CLI against a temp CAMPAIGN_ROOT so live state is untouched."""

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

    def pending(self) -> str:
        p = self.root / "state" / "pending-effects.jsonl"
        return p.read_text() if p.exists() else ""

    def feed(self) -> list[dict]:
        p = self.root / "state" / "player-feed.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    def test_full_encounter_flow(self):
        self.run_cmd("start", "--participants", "Ren:+3", "Goblin1:+2:7", "Goblin2:0")
        s = self.state()
        self.assertTrue(s["active"])
        self.assertEqual(s["round"], 1)
        self.assertEqual(len(s["order"]), 3)
        inits = [o["init"] for o in s["order"]]
        self.assertEqual(inits, sorted(inits, reverse=True))
        # HP came from the participant spec
        goblin = next(o for o in s["order"] if o["name"] == "Goblin1")
        self.assertEqual((goblin["hp"], goblin["max_hp"]), (7, 7))
        # combat start posted a system banner to the feed
        banners = self.feed()
        self.assertEqual(len(banners), 1)
        self.assertEqual(banners[0]["type"], "system")
        self.assertIn("Combat", banners[0]["text"])

        out = json.loads(self.run_cmd("damage", "--who", "Goblin1", "--amount", "9").stdout)
        self.assertEqual(out["action"], "damage")
        self.assertTrue(out["down"])
        self.assertEqual(out["hp"], -2)
        # damage queued as an effect, NOT posted to the feed
        self.assertIn("takes 9 damage", self.pending())
        self.assertEqual(len(self.feed()), 1)

        # heal caps at max_hp
        out = json.loads(self.run_cmd("heal", "--who", "Goblin1", "--amount", "50").stdout)
        self.assertEqual(out["hp"], 7)

        self.run_cmd("condition", "--who", "Ren", "--add", "prone")
        ren = next(o for o in self.state()["order"] if o["name"] == "Ren")
        self.assertIn("prone", ren["conditions"])
        self.run_cmd("condition", "--who", "Ren", "--remove", "prone")
        ren = next(o for o in self.state()["order"] if o["name"] == "Ren")
        self.assertNotIn("prone", ren["conditions"])

        # advance through a full round -> round counter increments
        for _ in range(3):
            out = json.loads(self.run_cmd("next").stdout)
        self.assertEqual(out["round"], 2)
        self.assertEqual(self.state()["round"], 2)

        self.run_cmd("end")
        self.assertFalse(self.state()["active"])
        self.assertEqual(self.feed()[-1]["type"], "system")

    def test_sethp_still_works(self):
        self.run_cmd("start", "--participants", "Wolf:+1")
        out = json.loads(self.run_cmd("sethp", "--who", "Wolf", "--current", "11", "--max", "11").stdout)
        self.assertEqual((out["hp"], out["max_hp"]), (11, 11))

    def test_unknown_combatant_fails(self):
        self.run_cmd("start", "--participants", "Ren:+3")
        proc = self.run_cmd("damage", "--who", "Nobody", "--amount", "1", check=False)
        self.assertNotEqual(proc.returncode, 0)

    def test_next_without_combat_fails(self):
        proc = self.run_cmd("next", check=False)
        self.assertNotEqual(proc.returncode, 0)


class TestNarrate(TempRootMixin):
    def setUp(self):
        super().setUp()
        (self.root / "state" / "current.json").write_text(json.dumps(
            {"location": {"specific": "The Stonehill Inn"}}
        ))
        (self.root / "sessions" / "session-03.md").write_text("# log\n")

    def run_narrate(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, str(TOOLS / "narrate.py"), *args],
            env=self.env, check=True, capture_output=True, text=True, input=stdin,
        )

    def feed_lines(self) -> list[dict]:
        text = (self.root / "state" / "player-feed.jsonl").read_text()
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    def test_appends_feed_entry_with_context(self):
        for text in ("First line.", "Second line."):
            self.run_narrate(text)
        lines = self.feed_lines()
        self.assertEqual(len(lines), 2)
        entry = lines[0]
        self.assertEqual(entry["text"], "First line.")
        self.assertEqual(entry["type"], "narration")
        self.assertEqual(entry["location"], "The Stonehill Inn")
        self.assertEqual(entry["session"], "session-03")
        self.assertTrue(entry["id"])
        # ids must be unique per entry
        self.assertNotEqual(entry["id"], lines[1]["id"])

    def test_stdout_echoes_entry_and_settings(self):
        out = json.loads(self.run_narrate("Hello.").stdout)
        self.assertEqual(out["entry"]["text"], "Hello.")
        self.assertIn("rules_strictness", out["settings"])

    def test_stdin_input(self):
        self.run_narrate("-", stdin='Prose with "quotes" and\n\nparagraphs.')
        self.assertEqual(self.feed_lines()[0]["text"], 'Prose with "quotes" and\n\nparagraphs.')

    def test_drains_queued_effects_and_inline_effects(self):
        campaign_lib.queue_effect(self.root, "Goblin1 takes 7 damage (now 0 HP) — DOWN")
        self.run_narrate("The goblin crumples.", "--effect", "Ren marks his kill")
        entry = self.feed_lines()[0]
        self.assertEqual(entry["effects"], [
            "Goblin1 takes 7 damage (now 0 HP) — DOWN",
            "Ren marks his kill",
        ])
        # queue is drained: next narration has no effects
        self.run_narrate("Silence falls.")
        self.assertNotIn("effects", self.feed_lines()[1])


class TestNarrateNormalize(unittest.TestCase):
    narrate = load_module("narrate", TOOLS / "narrate.py")

    def test_strips_markdown_artifacts(self):
        n = self.narrate.normalize
        self.assertEqual(n("> The goblin **crumples**."), "The goblin crumples.")
        self.assertEqual(n("## Scene\n\n\n\n*Quiet* falls."), "Scene\n\nQuiet falls.")
        self.assertEqual(n("_whisper_ and stone"), "whisper and stone")

    def test_preserves_plain_prose(self):
        n = self.narrate.normalize
        text = "First paragraph.\n\nSecond paragraph with 2 * 3 math left alone."
        self.assertEqual(n(text), text)

    def test_empty_after_normalize_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(TOOLS / "narrate.py"), "> "],
                env={**os.environ, "CAMPAIGN_ROOT": tmp},
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)


class TestNewCampaign(unittest.TestCase):
    def test_creates_from_starter_and_sets_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "campaign"
            subprocess.run(
                [sys.executable, str(TOOLS / "new_campaign.py"),
                 "--name", "Test Vale", "--dest", str(dest)],
                check=True, capture_output=True,
            )
            current = json.loads((dest / "state" / "current.json").read_text())
            self.assertEqual(current["campaign"], "Test Vale")
            self.assertTrue((dest / "house-rules.md").exists())
            self.assertTrue(list((dest / "characters").glob("*.json")))

            # refuses to clobber without --force
            proc = subprocess.run(
                [sys.executable, str(TOOLS / "new_campaign.py"),
                 "--name", "Again", "--dest", str(dest)],
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)


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
