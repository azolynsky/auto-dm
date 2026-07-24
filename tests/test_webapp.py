"""
Tests for the web companion server helpers — above all the secrecy firewall:
the player-facing API must never leak secret_truth, GM planning fields, or
non-display character keys.

Run:  python3 -m unittest discover -s tests -v

Skipped automatically if the webapp dependencies aren't installed.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Import the server against a throwaway campaign root so the suite works (and
# never touches live state) regardless of whether <repo>/campaign exists.
_ROOT_TMP = tempfile.TemporaryDirectory()
for sub in ("state", "characters", "sessions"):
    (Path(_ROOT_TMP.name) / sub).mkdir()
os.environ["CAMPAIGN_ROOT"] = _ROOT_TMP.name

try:
    spec = importlib.util.spec_from_file_location("webapp_server", REPO / "webapp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    sys.modules["webapp_server"] = server
    spec.loader.exec_module(server)
    HAVE_DEPS = True
except SystemExit:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestQuestRedaction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig_quests = server.QUESTS_FILE

    def tearDown(self):
        server.QUESTS_FILE = self._orig_quests
        self._tmp.cleanup()

    def write_quests(self, data: dict):
        path = self.tmp / "quests.json"
        path.write_text(json.dumps(data))
        server.QUESTS_FILE = path

    def test_secret_fields_stripped(self):
        self.write_quests({"active": [{
            "id": "q1", "title": "Find the thing", "known_to_party": True,
            "summary": "public", "secret_truth": "GM ONLY", "obstacles": "GM ONLY",
        }]})
        quests = server.load_quests()
        self.assertEqual(len(quests), 1)
        self.assertNotIn("secret_truth", quests[0])
        self.assertNotIn("obstacles", quests[0])
        self.assertEqual(quests[0]["summary"], "public")

    def test_unknown_quests_hidden(self):
        self.write_quests({"active": [
            {"id": "q1", "title": "Known", "known_to_party": True},
            {"id": "q2", "title": "Secret plot", "known_to_party": False},
            {"id": "q3", "title": "No flag at all"},
        ]})
        titles = [q["title"] for q in server.load_quests()]
        self.assertEqual(titles, ["Known"])

    def test_missing_file_returns_empty(self):
        server.QUESTS_FILE = self.tmp / "nope.json"
        self.assertEqual(server.load_quests(), [])


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestCharacterDisplaySubset(unittest.TestCase):
    def test_non_display_keys_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pc-test.json"
            path.write_text(json.dumps({
                "id": "pc-test", "name": "Testa", "hp": {"current": 5, "max": 10},
                "dm_notes": "secretly cursed", "backstory_secrets": "hidden twin",
            }))
            subset = server.char_display_subset(path)
            self.assertEqual(subset["name"], "Testa")
            self.assertNotIn("dm_notes", subset)
            self.assertNotIn("backstory_secrets", subset)

    def test_display_keys_cover_schema_essentials(self):
        for key in ("hp", "ac", "abilities", "conditions", "death_saves", "inventory"):
            self.assertIn(key, server.DISPLAY_KEYS)


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestWorldFlags(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = server.FLAGS_FILE

    def tearDown(self):
        server.FLAGS_FILE = self._orig
        self._tmp.cleanup()

    def test_only_true_flags_shown(self):
        path = self.tmp / "world-flags.json"
        path.write_text(json.dumps({"flags": {
            "met_sildar": {"value": True, "note": "You met Sildar."},
            "spider_revealed": {"value": False, "note": "GM: not yet"},
        }}))
        server.FLAGS_FILE = path
        flags = server.load_world_flags()
        self.assertEqual(flags, {"met_sildar": "You met Sildar."})


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestDramatisPersonae(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = server.DRAMATIS_FILE

    def tearDown(self):
        server.DRAMATIS_FILE = self._orig
        self._tmp.cleanup()

    def write_dramatis(self, data: dict):
        path = self.tmp / "dramatis-personae.json"
        path.write_text(json.dumps(data))
        server.DRAMATIS_FILE = path

    def test_unknown_characters_hidden(self):
        self.write_dramatis({"characters": [
            {"name": "Sildar", "disposition": "friend", "note": "ok", "known_to_party": True},
            {"name": "Nezznar", "disposition": "enemy", "note": "GM staging", "known_to_party": False},
            {"name": "No flag at all", "disposition": "unknown"},
        ]})
        names = [c["name"] for c in server.load_dramatis()]
        self.assertEqual(names, ["Sildar"])

    def test_extra_keys_stripped(self):
        self.write_dramatis({"characters": [{
            "name": "Sildar", "disposition": "friend", "note": "ok",
            "known_to_party": True, "gm_notes": "SECRET", "secret_truth": "SECRET",
        }]})
        chars = server.load_dramatis()
        self.assertEqual(chars, [{"name": "Sildar", "disposition": "friend", "note": "ok"}])

    def test_missing_file_returns_empty(self):
        server.DRAMATIS_FILE = self.tmp / "nope.json"
        self.assertEqual(server.load_dramatis(), [])


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestFeedReading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = server.FEED_FILE

    def tearDown(self):
        server.FEED_FILE = self._orig
        self._tmp.cleanup()

    def test_incremental_read(self):
        path = self.tmp / "player-feed.jsonl"
        server.FEED_FILE = path

        entries, pos = server.read_new_feed_lines(0)
        self.assertEqual(entries, [])  # no file yet

        with open(path, "a") as f:
            f.write(json.dumps({"id": "a", "text": "one"}) + "\n")
        entries, pos = server.read_new_feed_lines(pos)
        self.assertEqual([e["id"] for e in entries], ["a"])

        with open(path, "a") as f:
            f.write(json.dumps({"id": "b", "text": "two"}) + "\n")
            f.write("not json, should be skipped\n")
            f.write(json.dumps({"id": "c", "text": "three"}) + "\n")
        entries, pos = server.read_new_feed_lines(pos)
        self.assertEqual([e["id"] for e in entries], ["b", "c"])

        # nothing new
        entries, pos = server.read_new_feed_lines(pos)
        self.assertEqual(entries, [])

    def test_load_feed_limit(self):
        path = self.tmp / "player-feed.jsonl"
        server.FEED_FILE = path
        with open(path, "w") as f:
            for i in range(60):
                f.write(json.dumps({"id": str(i)}) + "\n")
        feed = server.load_feed(50)
        self.assertEqual(len(feed), 50)
        self.assertEqual(feed[0]["id"], "10")
        self.assertEqual(feed[-1]["id"], "59")


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestCharacterListing(unittest.TestCase):
    """Any sheet in characters/ shows (guests included), party order first."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "characters").mkdir()
        self._orig = (server.CHARACTERS_DIR, server.CURRENT_FILE)
        server.CHARACTERS_DIR = self.tmp / "characters"
        server.CURRENT_FILE = self.tmp / "current.json"

    def tearDown(self):
        server.CHARACTERS_DIR, server.CURRENT_FILE = self._orig
        self._tmp.cleanup()

    def write_char(self, cid: str, name: str):
        (self.tmp / "characters" / f"{cid}.json").write_text(
            json.dumps({"id": cid, "name": name, "hp": {"current": 1, "max": 1}}))

    def test_guests_included_party_first(self):
        self.write_char("guest-gundren", "Gundren")
        self.write_char("pc-b", "Bee")
        self.write_char("pc-a", "Aye")
        (self.tmp / "current.json").write_text(json.dumps({"party": ["pc-b", "pc-a"]}))
        ids = [c["id"] for c in server.load_characters()]
        self.assertEqual(ids, ["pc-b", "pc-a", "guest-gundren"])

    def test_non_sheet_json_skipped(self):
        (self.tmp / "characters" / "junk.json").write_text(json.dumps({"whatever": 1}))
        self.write_char("pc-a", "Aye")
        self.assertEqual([c["id"] for c in server.load_characters()], ["pc-a"])


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestPortraitUpload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "characters" / "images").mkdir(parents=True)
        self._orig = (server.CHARACTERS_DIR, server.IMAGES_DIR)
        server.CHARACTERS_DIR = self.tmp / "characters"
        server.IMAGES_DIR = self.tmp / "characters" / "images"
        (self.tmp / "characters" / "pc-a.json").write_text(json.dumps({"id": "pc-a", "name": "Aye"}))

    def tearDown(self):
        server.CHARACTERS_DIR, server.IMAGES_DIR = self._orig
        self._tmp.cleanup()

    def test_saves_and_replaces_other_extensions(self):
        server.save_portrait("pc-a", "image/png", b"png-bytes")
        self.assertEqual((server.IMAGES_DIR / "pc-a.png").read_bytes(), b"png-bytes")
        server.save_portrait("pc-a", "image/jpeg", b"jpg-bytes")
        self.assertTrue((server.IMAGES_DIR / "pc-a.jpg").exists())
        self.assertFalse((server.IMAGES_DIR / "pc-a.png").exists())

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):   # unknown character / path traversal
            server.save_portrait("../../etc/passwd", "image/png", b"x")
        with self.assertRaises(ValueError):   # unsupported type
            server.save_portrait("pc-a", "image/gif", b"x")
        with self.assertRaises(ValueError):   # empty body
            server.save_portrait("pc-a", "image/png", b"")


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestFeedTruncation(unittest.TestCase):
    def test_truncated_feed_resets_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "player-feed.jsonl"
            orig = server.FEED_FILE
            server.FEED_FILE = path
            try:
                path.write_text(json.dumps({"id": "a"}) + "\n" + json.dumps({"id": "b"}) + "\n")
                entries, pos = server.read_new_feed_lines(0)
                self.assertEqual([e["id"] for e in entries], ["a", "b"])
                # file rewritten shorter (e.g. feed trimmed) — cursor must reset
                path.write_text(json.dumps({"id": "c"}) + "\n")
                entries, pos = server.read_new_feed_lines(pos)
                self.assertEqual([e["id"] for e in entries], ["c"])
            finally:
                server.FEED_FILE = orig


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestSettings(unittest.TestCase):
    def test_defaults_when_missing(self):
        s = server.load_settings()
        self.assertIn("rules_strictness", s)
        self.assertIn("custom_rules", s)


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestCombatVisibility(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = server.COMBAT_FILE

    def tearDown(self):
        server.COMBAT_FILE = self._orig
        self._tmp.cleanup()

    def test_inactive_combat_hidden(self):
        path = self.tmp / "combat.json"
        path.write_text(json.dumps({"active": False, "order": [{"name": "Goblin1"}]}))
        server.COMBAT_FILE = path
        self.assertIsNone(server.load_combat())

    def test_active_combat_shown(self):
        path = self.tmp / "combat.json"
        path.write_text(json.dumps({"active": True, "round": 2, "order": []}))
        server.COMBAT_FILE = path
        self.assertEqual(server.load_combat()["round"], 2)


if __name__ == "__main__":
    unittest.main()
