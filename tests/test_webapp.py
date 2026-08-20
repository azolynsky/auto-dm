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

    def test_hooks_pitch_opt_in(self):
        self.write_quests({"active": [], "hooks": [
            {"id": "h1", "title": "Shown", "pitch": "Player-facing pitch.",
             "summary": "GM shorthand", "consequence_if_ignored": "GM ONLY"},
            {"id": "h2", "title": "No pitch — hidden", "summary": "GM only"},
        ]})
        hooks = server.load_quest_hooks()
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0], {"title": "Shown", "pitch": "Player-facing pitch."})

    def test_hooks_missing_file_returns_empty(self):
        server.QUESTS_FILE = self.tmp / "nope.json"
        self.assertEqual(server.load_quest_hooks(), [])


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

    def test_only_true_flags_with_fact_shown_and_note_hidden(self):
        path = self.tmp / "world-flags.json"
        path.write_text(json.dumps({"flags": {
            "met_sildar": {"value": True, "note": "GM shorthand", "fact": "You met Sildar."},
            "dm_only": {"value": True, "note": "GM: players never see this"},
            "spider_revealed": {"value": False, "note": "GM: not yet", "fact": "nope"},
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
class TestPartySetup(unittest.TestCase):
    """The setup screen's pregen listing and party seating."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "characters").mkdir()
        self._orig = (server.CHARACTERS_DIR, server.CURRENT_FILE)
        server.CHARACTERS_DIR = self.tmp / "characters"
        server.CURRENT_FILE = self.tmp / "current.json"
        for pc_id, name in (("pc-a", "Aye"), ("pc-b", "Bee")):
            (self.tmp / "characters" / f"{pc_id}.json").write_text(json.dumps({
                "id": pc_id, "name": name, "race": "Human", "class": "Fighter",
                "player": "", "personality": {"traits": ["Checks the exits."]},
            }))
        server.CURRENT_FILE.write_text(json.dumps({"party": []}))

    def tearDown(self):
        server.CHARACTERS_DIR, server.CURRENT_FILE = self._orig
        self._tmp.cleanup()

    def test_pregens_listed_with_card_fields(self):
        cards = server.list_pregens()
        self.assertEqual([c["id"] for c in cards], ["pc-a", "pc-b"])
        self.assertEqual(cards[0]["blurb"], "Checks the exits.")

    def test_seat_party_writes_current_and_player_names(self):
        server.seat_party([{"id": "pc-b", "player": "Olive"}, {"id": "pc-a"}])
        current = json.loads(server.CURRENT_FILE.read_text())
        self.assertEqual(current["party"], ["pc-b", "pc-a"])
        sheet = json.loads((self.tmp / "characters" / "pc-b.json").read_text())
        self.assertEqual(sheet["player"], "Olive")

    def test_save_new_hero_assigns_unique_id_and_returns_card(self):
        sheet = {"name": "Aye", "race": "Elf", "class": "Monk",
                 "abilities": {"str": 10}, "hp": {"max": 9, "current": 9},
                 "personality": {"traits": ["Punches first."]}}
        card = server.save_new_hero(dict(sheet))
        self.assertEqual(card["id"], "pc-aye")
        self.assertEqual(card["blurb"], "Punches first.")
        card2 = server.save_new_hero(dict(sheet))
        self.assertEqual(card2["id"], "pc-aye-2")  # same name → suffixed id
        saved = json.loads((self.tmp / "characters" / "pc-aye.json").read_text())
        self.assertEqual(saved["player"], "")

    def test_save_new_hero_rejects_malformed_sheet(self):
        with self.assertRaises(Exception):
            server.save_new_hero({"name": "No Class"})

    def test_seat_party_refuses_unknown_id(self):
        with self.assertRaises(Exception):
            server.seat_party([{"id": "pc-ghost"}])
        self.assertEqual(json.loads(server.CURRENT_FILE.read_text())["party"], [])


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

    def test_only_party_members_shown_in_party_order(self):
        self.write_char("guest-gundren", "Gundren")  # on disk but no longer in party
        self.write_char("pc-b", "Bee")
        self.write_char("pc-a", "Aye")
        (self.tmp / "current.json").write_text(json.dumps({"party": ["pc-b", "pc-a"]}))
        ids = [c["id"] for c in server.load_characters()]
        self.assertEqual(ids, ["pc-b", "pc-a"])

    def test_non_sheet_json_skipped(self):
        (self.tmp / "characters" / "junk.json").write_text(json.dumps({"whatever": 1}))
        self.write_char("pc-a", "Aye")
        (self.tmp / "current.json").write_text(json.dumps({"party": ["pc-a"]}))
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


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestIdleGap(unittest.TestCase):
    """Coming back after a long gap nudges the DM to wrap the previous
    sitting; an empty feed (brand-new campaign) never nudges."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = server.FEED_FILE
        server.FEED_FILE = self.tmp / "player-feed.jsonl"

    def tearDown(self):
        server.FEED_FILE = self.saved

    def _write(self, ts):
        server.FEED_FILE.write_text(
            json.dumps({"text": "x", "ts": ts}) + "\n", encoding="utf-8")

    def test_empty_feed_is_no_gap(self):
        self.assertIsNone(server.idle_gap_hours())

    def test_old_entry_measures_the_gap(self):
        from datetime import datetime, timedelta
        self._write((datetime.now() - timedelta(hours=30)).isoformat())
        self.assertAlmostEqual(server.idle_gap_hours(), 30, delta=0.1)

    def test_real_feed_format_with_z_suffix(self):
        from datetime import datetime, timedelta, timezone
        ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._write(ts.replace("+00:00", "Z"))  # campaign_lib's exact format
        self.assertAlmostEqual(server.idle_gap_hours(), 30, delta=0.1)

    def test_recent_entry_is_under_threshold(self):
        from datetime import datetime
        self._write(datetime.now().isoformat())
        self.assertLess(server.idle_gap_hours(), server.IDLE_GAP_HOURS)

    def test_bad_timestamp_is_no_gap(self):
        self._write("not-a-date")
        self.assertIsNone(server.idle_gap_hours())


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestSayGuard(unittest.TestCase):
    """One turn at a time: a message sent while the DM is working is refused
    (409), never silently queued behind the running turn."""

    def test_rejects_while_dm_busy(self):
        from fastapi.testclient import TestClient
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        server.DM_BUSY = True
        try:
            with TestClient(server.app) as client:
                res = client.post("/api/say", json={"text": "hi"})
        finally:
            server.DM_BUSY = False
            os.environ.pop("OPENROUTER_API_KEY")
        self.assertEqual(res.status_code, 409)
        self.assertIn("still working", res.json()["detail"])


@unittest.skipUnless(HAVE_DEPS, "webapp dependencies not installed")
class TestWorldChoice(unittest.TestCase):
    """The setup screen's world chooser: bundled templates, re-runs, and the
    generated-world writer. Above all the guard: a seated (= played) campaign
    must never be reseeded."""

    SERVER_FILES = ("ROOT", "CURRENT_FILE", "QUESTS_FILE", "DRAMATIS_FILE")

    def setUp(self):
        import shutil
        self.shutil = shutil
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        (tmp / "campaigns").mkdir()
        self.campaign = tmp / "campaigns" / "table-9"
        shutil.copytree(REPO / "campaigns" / "starter", self.campaign)

        ac = server.appconfig
        self._ac_saved = {"CAMPAIGN": ac.CAMPAIGN, "APP_DIR": ac.APP_DIR,
                          "CONFIG_FILE": ac.CONFIG_FILE,
                          "on_campaign_switched": ac.on_campaign_switched}
        ac.CAMPAIGN, ac.APP_DIR = self.campaign, tmp
        ac.CONFIG_FILE = tmp / "config.json"
        ac.on_campaign_switched = None
        self._srv_saved = {k: getattr(server, k) for k in self.SERVER_FILES}
        server.ROOT = self.campaign
        server.CURRENT_FILE = self.campaign / "state" / "current.json"
        server.QUESTS_FILE = self.campaign / "state" / "quests.json"
        server.DRAMATIS_FILE = self.campaign / "state" / "dramatis-personae.json"

    def tearDown(self):
        for k, v in self._ac_saved.items():
            setattr(server.appconfig, k, v)
        for k, v in self._srv_saved.items():
            setattr(server, k, v)
        self._tmp.cleanup()

    def client(self):
        from fastapi.testclient import TestClient
        return TestClient(server.app)

    def add_campaign(self, slug: str, name: str) -> Path:
        path = server.appconfig.campaigns_dir() / slug
        self.shutil.copytree(REPO / "campaigns" / "starter", path)
        current_file = path / "state" / "current.json"
        current = json.loads(current_file.read_text())
        current["campaign"] = name
        current_file.write_text(json.dumps(current))
        return path

    def seat_party(self):
        current_file = self.campaign / "state" / "current.json"
        current = json.loads(current_file.read_text())
        current["party"] = ["pc-fighter"]
        current_file.write_text(json.dumps(current))

    WORLD_PKG = {
        "campaign_name": "Ashes of the Ninth Fleet",
        "overview_md": "# Setting overview\n\nA drowned archipelago.",
        "lore_md": "# Lore\n\nThe fleet burned.",
        "regions_md": "# Regions\n\n- The Shallows",
        "current": {"in_game_date": "3rd of Brine, 412", "time_of_day": "dusk",
                    "weather": "salt wind",
                    "location": {"region": "The Shallows", "settlement": "Port Grieve",
                                 "specific": "The Anchor's Rest, taproom"}},
        "location": {"name": "Port Grieve",
                     "summary_md": "# Port Grieve\n\nA town on stilts.",
                     "secrets_md": "# GM secrets\n\nThe harbormaster smuggles."},
        "npc": {"name": "Salla Wrack", "summary_md": "# Salla Wrack\n\nDockmistress.",
                "voice_md": "# Voice\n\nClipped.",
                "motivations_md": "# Motivations\n\nWants her ship back.",
                "dramatis_note": "Dockmistress of Port Grieve; hiring."},
        "quest": {"id": "quest-lost-tide", "title": "The Lost Tide",
                  "given_by": "Salla Wrack",
                  "summary": "A fishing boat came back empty.",
                  "objectives": ["Find the crew"],
                  "obstacles": "GM ONLY", "secret_truth": "GM ONLY",
                  "rewards": "20 gp", "known_to_party": False},
        "hooks": [{"title": "The Ninth Light", "pitch": "A lighthouse burns green.",
                   "summary": "GM shorthand"}],
    }

    def test_worlds_listing_excludes_active_campaign(self):
        self.add_campaign("table-2", "Curse of the Salt Peddler")
        with self.client() as client:
            data = client.get("/api/worlds").json()
        self.assertIn("starter", [t["id"] for t in data["templates"]])
        self.assertEqual(data["campaigns"],
                         [{"slug": "table-2", "name": "Curse of the Salt Peddler"}])

    def test_switch_campaign_saves_and_fires_the_relaunch_hook(self):
        self.add_campaign("table-2", "Curse of the Salt Peddler")
        with self.client() as client:
            # no desktop shell registered: saved, not relaunching
            res = client.post("/api/campaigns/switch", json={"slug": "table-2"})
            self.assertEqual(res.status_code, 200)
            self.assertFalse(res.json()["relaunching"])
            self.assertEqual(server.appconfig.load()["campaign"], "table-2")
            # the abandoned table was pristine (unnamed, unseated, unplayed):
            # continuing another campaign must not leave it behind
            self.assertFalse(self.campaign.exists())

            seen = []
            server.appconfig.on_campaign_switched = seen.append
            res = client.post("/api/campaigns/switch", json={"slug": "table-2"})
            self.assertTrue(res.json()["relaunching"])
            self.assertEqual(seen, ["table-2"])

            for slug in ("nope", "../starter", ""):
                res = client.post("/api/campaigns/switch", json={"slug": slug})
                self.assertEqual(res.status_code, 400, slug)

    def test_rename_campaign_endpoint(self):
        path = self.add_campaign("table-2", "Old Name")
        with self.client() as client:
            res = client.post("/api/campaigns/rename",
                              json={"slug": "table-2", "name": "  Guest Campaign  "})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["name"], "Guest Campaign")
            current = json.loads((path / "state" / "current.json").read_text())
            self.assertEqual(current["campaign"], "Guest Campaign")
            for body in ({"slug": "table-2", "name": "  "},
                         {"slug": "nope", "name": "x"},
                         {"slug": "../starter", "name": "x"}):
                self.assertEqual(
                    client.post("/api/campaigns/rename", json=body).status_code,
                    400, body)

    def test_delete_and_restore_roundtrip(self):
        path = self.add_campaign("table-2", "Oops")
        with self.client() as client:
            res = client.post("/api/campaigns/delete", json={"slug": "table-2"})
            self.assertEqual(res.status_code, 200)
            trash_id = res.json()["trash_id"]
            self.assertFalse(path.exists())  # gone from campaigns/
            self.assertTrue(  # ...but intact in the trash
                (server.appconfig.trash_dir() / trash_id /
                 "state" / "current.json").exists())

            res = client.post("/api/campaigns/restore", json={"trash_id": trash_id})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["slug"], "table-2")
            self.assertEqual(res.json()["name"], "Oops")
            self.assertTrue((path / "state" / "current.json").exists())

    def test_delete_refuses_the_active_campaign(self):
        with self.client() as client:
            res = client.post("/api/campaigns/delete",
                              json={"slug": self.campaign.name})
        self.assertEqual(res.status_code, 400)
        self.assertTrue(self.campaign.exists())

    def test_template_choice_seeds_and_names(self):
        with self.client() as client:
            res = client.post("/api/worlds", json={"source": "template",
                                                   "id": "starter"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "The Vale of Emberwick")
        self.assertFalse((self.campaign / "template.json").exists())

    def test_seated_campaign_refuses_reseed(self):
        self.seat_party()
        with self.client() as client:
            res = client.post("/api/worlds", json={"source": "template",
                                                   "id": "starter"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("already started", res.json()["detail"])

    def test_unknown_sources_rejected(self):
        with self.client() as client:
            for body in ({"source": "template", "id": "nope"},
                         {"source": "rerun", "slug": "nope"},
                         {"source": "rerun", "slug": "../starter"},
                         {"source": "sideload"}):
                self.assertEqual(client.post("/api/worlds", json=body).status_code,
                                 400, body)

    def test_rerun_copies_world_and_strips_group(self):
        source = self.add_campaign("table-2", "Curse of the Salt Peddler")
        (source / "sessions" / "session-05.md").write_text("old story")
        current_file = source / "state" / "current.json"
        current = json.loads(current_file.read_text())
        current["party"] = ["pc-fighter"]
        current_file.write_text(json.dumps(current))

        with self.client() as client:
            res = client.post("/api/worlds", json={"source": "rerun",
                                                   "slug": "table-2"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Curse of the Salt Peddler")
        new_current = json.loads(
            (self.campaign / "state" / "current.json").read_text())
        self.assertEqual(new_current["party"], [])
        self.assertFalse((self.campaign / "sessions" / "session-05.md").exists())
        # the source campaign is untouched — a re-run is a copy, not a move
        self.assertTrue((source / "sessions" / "session-05.md").exists())
        self.assertEqual(
            json.loads(current_file.read_text())["party"], ["pc-fighter"])

    def test_apply_world_package_writes_a_coherent_world(self):
        name = server.apply_world_package(dict(self.WORLD_PKG))
        self.assertEqual(name, "Ashes of the Ninth Fleet")

        current = json.loads((self.campaign / "state" / "current.json").read_text())
        self.assertEqual(current["campaign"], "Ashes of the Ninth Fleet")
        self.assertEqual(current["campaign_day"], 1)
        self.assertEqual(current["location"]["settlement"], "Port Grieve")
        self.assertEqual(current["present_entities"],
                         ["npcs/recurring/salla-wrack",
                          "world/locations/port-grieve"])
        # the starter's opening entities made way for the new world's
        self.assertFalse(
            (self.campaign / "npcs" / "recurring" / "maera-thistle").exists())
        self.assertFalse(
            (self.campaign / "world" / "locations" / "emberwick").exists())
        for rel in ("npcs/recurring/salla-wrack/summary.md",
                    "npcs/recurring/salla-wrack/voice.md",
                    "npcs/recurring/salla-wrack/motivations.md",
                    "world/locations/port-grieve/summary.md",
                    "world/locations/port-grieve/secrets.md",
                    "world/overview.md", "world/lore.md"):
            self.assertTrue((self.campaign / rel).exists(), rel)
        self.assertIn("salla-wrack",
                      (self.campaign / "npcs" / "INDEX.md").read_text())

        quests = json.loads((self.campaign / "state" / "quests.json").read_text())
        self.assertTrue(quests["active"][0]["known_to_party"])  # forced visible
        self.assertEqual(quests["hooks"][0]["title"], "The Ninth Light")
        # and the player API still strips the GM-only fields
        server.QUESTS_FILE = self.campaign / "state" / "quests.json"
        visible = server.load_quests()[0]
        self.assertNotIn("secret_truth", visible)

    def test_apply_world_package_rejects_missing_fields(self):
        from fastapi import HTTPException
        broken = dict(self.WORLD_PKG)
        broken.pop("npc")
        with self.assertRaises(HTTPException):
            server.apply_world_package(broken)

    def test_generate_uses_the_agent_and_writes_the_world(self):
        import types
        stub = types.ModuleType("agent")
        stub.DMError = RuntimeError
        stub.generate_campaign = lambda description: dict(self.WORLD_PKG)
        real = sys.modules.get("agent")
        sys.modules["agent"] = stub
        try:
            with self.client() as client:
                res = client.post("/api/worlds",
                                  json={"source": "generate",
                                        "description": "drowned pirate fleet"})
        finally:
            if real is not None:
                sys.modules["agent"] = real
            else:
                sys.modules.pop("agent", None)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Ashes of the Ninth Fleet")
        self.assertTrue((self.campaign / "npcs" / "recurring" / "salla-wrack"
                         / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()
