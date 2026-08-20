"""
Tests for the desktop app's DM agent — above all the write guard: the agent's
tools must never write outside the player's campaign directory, and must never
reach outside the app bundle at all.

Also covers the prompt registry (prompts/), since a variant that silently fails
to resolve would run an A/B test against the wrong prompt.

Run:  python3 -m unittest discover -s tests -v

Stdlib only — none of this needs langgraph installed.
"""
from __future__ import annotations

import datetime
import json
import threading
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "desktop"))
sys.path.insert(0, str(REPO / "tools"))


class DesktopTestCase(unittest.TestCase):
    """Each test gets a throwaway campaign and app-config directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.campaign = self.tmp / "campaign"
        shutil.copytree(REPO / "campaigns" / "starter", self.campaign)
        os.environ["CAMPAIGN_ROOT"] = str(self.campaign)

        # Reimport under the temp root: config caches CAMPAIGN at import time.
        for name in ("config", "prompts", "campaign_tools", "agent", "campaign_lib"):
            sys.modules.pop(name, None)
        import agent
        import config
        import prompts
        self.agent, self.config, self.prompts = agent, config, prompts
        # Keep the test off the real user config file.
        config.APP_DIR = self.tmp / "appdir"
        config.CONFIG_FILE = config.APP_DIR / "config.json"

    def tearDown(self):
        os.environ.pop("CAMPAIGN_ROOT", None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        for name in ("config", "prompts", "campaign_tools", "agent", "campaign_lib"):
            sys.modules.pop(name, None)


class TestReadiness(DesktopTestCase):
    """Setup shows until a party is seated — campaign files always exist
    (ensure_campaign recreates them at boot), so they can't be the signal."""

    def test_not_ready_until_party_seated(self):
        self.config.APP_DIR.mkdir(parents=True)
        self.config.save(api_key="sk-or-test")
        self.assertFalse(self.config.is_ready())  # starter party is empty
        current_file = self.campaign / "state" / "current.json"
        current = json.loads(current_file.read_text())
        current["party"] = ["pc-fighter"]
        current_file.write_text(json.dumps(current))
        self.assertTrue(self.config.is_ready())

    def test_not_ready_without_key(self):
        self.assertFalse(self.config.is_ready())


class TestMultiCampaign(DesktopTestCase):
    """Campaigns live side by side under APP_DIR/campaigns/<slug>/; the
    active one is named in config.json and only changes across a relaunch."""

    def setUp(self):
        super().setUp()
        self.config.APP_DIR.mkdir(parents=True)
        # These tests exercise the config-derived layout, not the env override.
        os.environ.pop("CAMPAIGN_ROOT", None)
        self.config.CAMPAIGN = self.config.campaigns_dir() / "table-1"

    def test_create_campaign_mints_unique_slugs(self):
        first = self.config.create_campaign()
        second = self.config.create_campaign()
        self.assertNotEqual(first, second)
        for slug in (first, second):
            self.assertTrue(
                (self.config.campaigns_dir() / slug / "state" / "current.json").exists())

    def test_list_campaigns_reads_display_names(self):
        slug = self.config.create_campaign()
        current_file = (self.config.campaigns_dir() / slug / "state" / "current.json")
        current = json.loads(current_file.read_text())
        current["campaign"] = "Curse of the Salt Peddler"
        current_file.write_text(json.dumps(current))
        self.assertIn((slug, "Curse of the Salt Peddler"), self.config.list_campaigns())

    def test_set_active_campaign_validates(self):
        slug = self.config.create_campaign()
        self.config.set_active_campaign(slug)
        self.assertEqual(self.config.load()["campaign"], slug)
        with self.assertRaises(ValueError):
            self.config.set_active_campaign("no-such-table")

    def test_switching_away_discards_a_pristine_table(self):
        """Choosing "New Campaign" mints a table before the setup screen can
        offer "continue" — continuing another campaign from there must not
        leave the untouched table behind as a phantom "New Campaign"."""
        self.config.ensure_campaign()  # table-1: unnamed, unseated, unplayed
        other = self.config.create_campaign()
        self.config.set_active_campaign(other)
        self.assertEqual(self.config.load()["campaign"], other)
        self.assertFalse((self.config.campaigns_dir() / "table-1").exists())

    def test_switching_away_keeps_touched_tables(self):
        self.config.ensure_campaign()
        other = self.config.create_campaign()
        # any single touch — a name, a seated party, or a chronicle — keeps it
        for touch in ("name", "party", "feed"):
            root = self.config.CAMPAIGN
            if touch == "name":
                self.config.set_campaign_name("Guest Campaign")
            elif touch == "party":
                current_file = root / "state" / "current.json"
                current = json.loads(current_file.read_text())
                current.update(campaign="New Campaign", party=["pc-fighter"])
                current_file.write_text(json.dumps(current))
            else:
                current_file = root / "state" / "current.json"
                current = json.loads(current_file.read_text())
                current.update(campaign="New Campaign", party=[])
                current_file.write_text(json.dumps(current))
                (root / "state" / "player-feed.jsonl").write_text("{}\n")
            self.config.set_active_campaign(other)
            self.assertTrue(root.exists(), touch)
            self.config.save(campaign=root.name)  # switch back for the next arm

    def test_rename_campaign(self):
        slug = self.config.create_campaign()
        self.config.rename_campaign(slug, "Tuesdays with Mitch and Olive")
        self.assertIn((slug, "Tuesdays with Mitch and Olive"),
                      self.config.list_campaigns())
        with self.assertRaises(ValueError):
            self.config.rename_campaign("no-such-table", "x")
        with self.assertRaises(ValueError):
            self.config.rename_campaign("../starter", "x")

    def test_rename_active_campaign_goes_through_the_hook(self):
        self.config.ensure_campaign()
        seen = []
        self.config.on_campaign_renamed = seen.append
        self.config.rename_campaign(self.config.CAMPAIGN.name, "Guest Campaign")
        self.assertEqual(seen, ["Guest Campaign"])
        self.assertEqual(self.config.campaign_label(self.config.CAMPAIGN),
                         "Guest Campaign")

    def test_delete_campaign_is_a_move_to_trash(self):
        self.config.ensure_campaign()  # so create_campaign mints a non-active slug
        slug = self.config.create_campaign()
        self.config.rename_campaign(slug, "Oops")
        trash_id = self.config.delete_campaign(slug)
        self.assertFalse((self.config.campaigns_dir() / slug).exists())
        trashed = self.config.trash_dir() / trash_id
        self.assertTrue((trashed / "state" / "current.json").exists())
        # restore brings it back, content intact
        restored = self.config.restore_campaign(trash_id)
        self.assertEqual(restored, slug)
        self.assertIn((slug, "Oops"), self.config.list_campaigns())
        self.assertFalse(trashed.exists())

    def test_delete_refuses_the_active_campaign_and_bad_slugs(self):
        self.config.ensure_campaign()
        with self.assertRaises(ValueError):
            self.config.delete_campaign(self.config.CAMPAIGN.name)
        for slug in ("no-such-table", "../starter", "", "."):
            with self.assertRaises(ValueError, msg=slug):
                self.config.delete_campaign(slug)

    def test_restore_reslugs_when_the_slot_is_retaken(self):
        self.config.ensure_campaign()  # so create_campaign mints a non-active slug
        slug = self.config.create_campaign()
        trash_id = self.config.delete_campaign(slug)
        # a new campaign mints the freed slug before the restore
        self.assertEqual(self.config.create_campaign(), slug)
        restored = self.config.restore_campaign(trash_id)
        self.assertNotEqual(restored, slug)
        self.assertTrue((self.config.campaigns_dir() / restored /
                         "state" / "current.json").exists())
        with self.assertRaises(ValueError):
            self.config.restore_campaign("nothing-here")
        with self.assertRaises(ValueError):
            self.config.restore_campaign("../campaigns/" + slug)

    def test_legacy_campaign_migrates_once(self):
        legacy = self.config.APP_DIR / "campaign"
        shutil.copytree(REPO / "campaigns" / "starter", legacy)
        marker = legacy / "state" / "current.json"
        current = json.loads(marker.read_text())
        current["campaign"] = "The Old Table"
        marker.write_text(json.dumps(current))

        self.config.ensure_campaign()
        self.assertFalse(legacy.exists())
        self.assertEqual(self.config.campaign_label(self.config.CAMPAIGN),
                         "The Old Table")
        self.assertEqual(self.config.load()["campaign"], "table-1")

        # idempotent: a second boot (even with a stray legacy dir) is a no-op
        shutil.copytree(REPO / "campaigns" / "starter", legacy)
        self.config.ensure_campaign()
        self.assertEqual(self.config.campaign_label(self.config.CAMPAIGN),
                         "The Old Table")

    def test_env_override_skips_migration_and_menu_layout(self):
        os.environ["CAMPAIGN_ROOT"] = str(self.campaign)
        legacy = self.config.APP_DIR / "campaign"
        shutil.copytree(REPO / "campaigns" / "starter", legacy)
        self.config.ensure_campaign()
        self.assertTrue(legacy.exists())  # pinned root: nothing moves


class TestMenuOrder(unittest.TestCase):
    """The Campaign menu sits right after the application menu — pywebview
    appends custom menus last, so app.py reorders the live NSMenu bar."""

    @unittest.skipUnless(sys.platform == "darwin", "AppKit menu bar is macOS-only")
    def test_campaign_menu_moves_after_app_menu(self):
        import AppKit
        sys.modules.pop("app", None)
        import app

        bar = AppKit.NSMenu.alloc().init()
        for title in ("Auto-DM", "View", "Edit", app.CAMPAIGN_MENU_TITLE):
            item = AppKit.NSMenuItem.alloc().init()
            item.setTitle_(title)
            bar.addItem_(item)

        self.assertTrue(app.move_after_app_menu(bar, app.CAMPAIGN_MENU_TITLE))
        self.assertEqual([i.title() for i in bar.itemArray()],
                         ["Auto-DM", app.CAMPAIGN_MENU_TITLE, "View", "Edit"])
        # missing item / missing bar are no-ops, not crashes
        self.assertFalse(app.move_after_app_menu(bar, "No Such Menu"))
        self.assertFalse(app.move_after_app_menu(None, app.CAMPAIGN_MENU_TITLE))


class TestWorldSources(DesktopTestCase):
    """The setup screen's "choose your world": bundled templates, and re-runs
    of a table's own campaigns with the previous group's traces stripped."""

    def setUp(self):
        super().setUp()
        self.config.APP_DIR.mkdir(parents=True)
        os.environ.pop("CAMPAIGN_ROOT", None)
        self.config.CAMPAIGN = self.config.campaigns_dir() / "table-1"
        self.config.ensure_campaign()

    def test_templates_listed_with_card_metadata(self):
        templates = self.config.list_world_templates()
        starter = next(t for t in templates if t["id"] == "starter")
        self.assertEqual(starter["name"], "The Vale of Emberwick")
        self.assertTrue(starter["blurb"])

    def test_templates_ship_in_lineup_order_starter_first(self):
        ids = [t["id"] for t in self.config.list_world_templates()]
        self.assertEqual(ids[:4], ["starter", "harrowmoor", "kraghold",
                                   "glasswash"])

    def test_bundled_worlds_are_complete_and_starter_free(self):
        """Every bundled world stands alone: card metadata, a visible opening
        quest, an opening scene whose entities exist — and none of the
        starter's Emberwick content leaked in."""
        for slug in ("harrowmoor", "kraghold", "glasswash"):
            root = self.config.BUNDLE / "campaigns" / slug
            meta = json.loads((root / "template.json").read_text())
            self.assertTrue(meta["name"] and meta["blurb"], slug)
            current = json.loads(
                (root / "state" / "current.json").read_text())
            self.assertEqual(current["party"], [], slug)
            for entity in current["present_entities"]:
                self.assertTrue((root / entity / "summary.md").exists(),
                                f"{slug}: {entity}")
            quests = json.loads((root / "state" / "quests.json").read_text())
            self.assertTrue(quests["active"][0]["known_to_party"], slug)
            self.assertTrue(all(h["pitch"] for h in quests["hooks"]), slug)
            self.assertFalse((root / "characters").exists(), slug)
            self.assertFalse(
                (root / "npcs" / "recurring" / "maera-thistle").exists(), slug)
            self.assertFalse(
                (root / "world" / "locations" / "emberwick").exists(), slug)

    def test_seeding_a_characterless_template_borrows_the_pregens(self):
        self.config.seed_campaign(self.config.BUNDLE / "campaigns" / "kraghold")
        self.assertEqual(self.config.campaign_label(self.config.CAMPAIGN),
                         "New Campaign")
        self.assertTrue((self.config.CAMPAIGN / "characters" /
                         "pc-fighter.json").exists())
        self.assertTrue((self.config.CAMPAIGN / "npcs" / "recurring" /
                         "brunna-stonehewn" / "summary.md").exists())

    def test_template_metadata_never_enters_a_campaign(self):
        self.assertFalse((self.config.CAMPAIGN / "template.json").exists())
        slug = self.config.create_campaign()
        self.assertFalse(
            (self.config.campaigns_dir() / slug / "template.json").exists())

    def test_seed_replaces_contents_and_respects_seated_guard(self):
        source = self.config.campaigns_dir() / self.config.create_campaign()
        (source / "sessions" / "session-01.md").write_text("old table's story")
        current_file = source / "state" / "current.json"
        current = json.loads(current_file.read_text())
        current["campaign"] = "Curse of the Salt Peddler"
        current_file.write_text(json.dumps(current))

        self.config.seed_campaign(source)
        self.assertEqual(self.config.campaign_label(self.config.CAMPAIGN),
                         "Curse of the Salt Peddler")
        self.assertTrue(
            (self.config.CAMPAIGN / "sessions" / "session-01.md").exists())

        # a seated (= played) campaign refuses to be reseeded
        target_current = self.config.CAMPAIGN / "state" / "current.json"
        seated = json.loads(target_current.read_text())
        seated["party"] = ["pc-fighter"]
        target_current.write_text(json.dumps(seated))
        with self.assertRaises(ValueError):
            self.config.seed_campaign(source)
        with self.assertRaises(ValueError):  # and never from itself
            self.config.seed_campaign(self.config.CAMPAIGN)

    def test_reset_for_new_table_strips_group_keeps_world(self):
        root = self.config.CAMPAIGN
        state = root / "state"
        (state / "player-feed.jsonl").write_text('{"type":"narration"}\n')
        (state / "dm-thread.sqlite").write_text("old conversation")
        (root / "sessions" / "session-07.md").write_text("old log")
        current = json.loads((state / "current.json").read_text())
        current["party"] = ["pc-fighter"]
        (state / "current.json").write_text(json.dumps(current))
        sheet_path = root / "characters" / "pc-fighter.json"
        sheet = json.loads(sheet_path.read_text())
        sheet["player"] = "Old Alice"
        sheet_path.write_text(json.dumps(sheet))

        self.config.reset_for_new_table()

        self.assertFalse((state / "player-feed.jsonl").exists())
        self.assertFalse((state / "dm-thread.sqlite").exists())
        self.assertFalse((root / "sessions" / "session-07.md").exists())
        self.assertIn("new table", (root / "sessions" / "recap.md").read_text())
        self.assertEqual(
            json.loads((state / "current.json").read_text())["party"], [])
        self.assertEqual(json.loads(sheet_path.read_text())["player"], "")
        self.assertFalse(
            json.loads((state / "combat.json").read_text())["active"])
        # world state survives: quests and entity files are the world
        self.assertTrue((state / "quests.json").exists())
        self.assertTrue(
            (root / "npcs" / "recurring" / "maera-thistle" / "summary.md").exists())


class TestCampaignRename(DesktopTestCase):
    """Naming a campaign mid-process (the setup screen does) must reach the
    live window/menu — they're built once per launch, before the name exists."""

    def test_set_campaign_name_fires_rename_hook(self):
        seen = []
        self.config.on_campaign_renamed = seen.append
        self.config.set_campaign_name("The Salt Road")
        self.assertEqual(seen, ["The Salt Road"])
        current = json.loads(
            (self.campaign / "state" / "current.json").read_text())
        self.assertEqual(current["campaign"], "The Salt Road")

    def test_no_hook_is_fine(self):
        self.config.set_campaign_name("Quiet Table")  # must not raise

    @unittest.skipUnless(sys.platform == "darwin", "AppKit menu is macOS-only")
    def test_retitle_active_campaign_menu_item(self):
        import AppKit
        sys.modules.pop("app", None)
        import app

        submenu = AppKit.NSMenu.alloc().init()
        for title in ("New Campaign", app.ACTIVE_MARK + "New Campaign",
                      app.IDLE_MARK + "Elsewhere"):
            item = AppKit.NSMenuItem.alloc().init()
            item.setTitle_(title)
            submenu.addItem_(item)

        self.assertTrue(app.retitle_active_campaign(submenu, "The Salt Road"))
        titles = [str(i.title()) for i in submenu.itemArray()]
        self.assertIn(app.ACTIVE_MARK + "The Salt Road", titles)
        self.assertNotIn(app.ACTIVE_MARK + "New Campaign", titles)
        self.assertIn(app.IDLE_MARK + "Elsewhere", titles)  # others untouched
        # missing menu is a no-op, not a crash
        self.assertFalse(app.retitle_active_campaign(None, "x"))


class TestConsultBrief(DesktopTestCase):
    """Every consult gets the scene state and PC sheet paths pre-injected,
    so stateless specialists don't burn model rounds rediscovering them."""

    def test_brief_carries_state_and_roster(self):
        brief = self.agent._consult_brief()
        self.assertIn("campaign/state/current.json", brief)
        self.assertIn("campaign/state/settings.json", brief)
        self.assertIn("campaign/house-rules.md", brief)
        # exact sheet paths with names, so nobody guesses campaign/pcs/*.md
        self.assertIn("campaign/characters/pc-warlock.json", brief)
        self.assertIn("Ember Vex", brief)

    def test_brief_survives_missing_files(self):
        shutil.rmtree(self.campaign / "characters")
        (self.campaign / "state" / "current.json").unlink()
        brief = self.agent._consult_brief()  # must not raise
        self.assertIn("campaign/state/settings.json", brief)
        self.assertNotIn("--- PC sheets", brief)

    def test_entity_pack_respects_motivations_firewall(self):
        # starter current.json lists world/locations/emberwick, which has
        # summary.md + secrets.md — everyone gets the summary, only the
        # director gets the secrets (invariant #7).
        for role in ("director", "narrator", "rules-lawyer"):
            brief = self.agent._consult_brief(role)
            self.assertIn("world/locations/emberwick/summary.md", brief, role)
        # "--- campaign/<ent>/<file>" headers mark actual inclusion; bare
        # "secrets.md" mentions in summary prose are fine.
        self.assertIn("--- campaign/world/locations/emberwick/secrets.md",
                      self.agent._consult_brief("director"))
        for role in ("narrator", "rules-lawyer", "bookkeeper", ""):
            brief = self.agent._consult_brief(role)
            self.assertNotIn("/secrets.md\n", brief, role)
            self.assertNotIn("/motivations.md\n", brief, role)

    def test_briefs_are_siloed_by_role(self):
        director = self.agent._consult_brief("director")
        narrator = self.agent._consult_brief("narrator")
        lawyer = self.agent._consult_brief("rules-lawyer")
        # GM-only state stays out of the narrator's view: quests carry
        # secret_truth, world-flags notes and dramatis' hidden entries
        # pre-stage reveals.
        for gm_file in ("state/quests.json", "state/world-flags.json",
                        "state/dramatis-personae.json"):
            self.assertIn(f"--- campaign/{gm_file}", director)
            self.assertNotIn(f"--- campaign/{gm_file}", narrator)
            self.assertNotIn(f"--- campaign/{gm_file}", lawyer)
        # story context the lawyer doesn't need
        self.assertIn("--- campaign/sessions/recap.md", narrator)
        self.assertNotIn("--- campaign/sessions/recap.md", lawyer)
        # prose-editor gets no world state at all
        self.assertEqual(self.agent._consult_brief("prose-editor"), "")

    def test_narration_requires_narrator_consult(self):
        self.agent.begin_turn()
        out = self.agent.run_tool("narrate.py", ["The gate opens."])
        self.assertIn("error", out)
        self.assertIn("narrator", out)
        # system announcements are exempt
        out = self.agent.run_tool(
            "narrate.py", ["Back in five.", "--type", "system"])
        self.assertNotIn("must come from the narrator", out)
        # once the narrator was consulted this turn, pushes go through
        self.agent.allow_narration()
        out = self.agent.run_tool("narrate.py", ["The gate opens."])
        self.assertNotIn("must come from the narrator", out)

    def test_fallback_only_narrates_clean_blockquotes(self):
        # A reply with no blockquote is orchestrator chatter, not narration.
        self.assertEqual(self.agent.players_text(
            "1. **Maera is deceased**\n2. the apron is Ember's",
            quoted_only=True), "")
        self.assertEqual(self.agent.players_text(
            "[DIRECTOR] x\n> The gate groans open.", quoted_only=True),
            "The gate groans open.")
        # and the fallback applies the same gate the tool does
        self.assertTrue(self.agent.narrate_gate("she pins him (24 vs 17)"))
        self.assertEqual(self.agent.narrate_gate("She pins him flat."), [])

    def test_checkpoint_roles_wait_for_the_beat(self):
        self.agent.begin_turn()
        for role in ("continuity-checker", "prose-editor", "session-prep"):
            out = self.agent.consult_role(role, "check the last scene")
            self.assertIn("after the beat is on screen", out, role)
        # director/rules-lawyer/bookkeeper are live-loop roles, never blocked
        self.assertNotIn("after the beat is on screen",
                         self.agent.consult_role("director", "x") or "")

    def test_entities_named_in_the_task_are_preloaded(self):
        # present_entities drifts stale; the task text is the live signal.
        cur_path = self.campaign / "state" / "current.json"
        cur = json.loads(cur_path.read_text())
        cur["present_entities"] = []
        cur_path.write_text(json.dumps(cur))
        brief = self.agent._consult_brief(
            "narrator", "Yara asks Maera Thistle about the strongbox")
        self.assertIn("--- campaign/npcs/recurring/maera-thistle/summary.md",
                      brief)
        self.assertIn("--- campaign/npcs/recurring/maera-thistle/voice.md",
                      brief)
        # by folder id too, and the firewall still holds for non-directors
        brief = self.agent._consult_brief("narrator", "scene at maera-thistle")
        self.assertIn("maera-thistle/summary.md", brief)
        self.assertNotIn("/motivations.md\n", brief)
        self.assertIn("--- campaign/npcs/recurring/maera-thistle/motivations.md",
                      self.agent._consult_brief("director", "Maera Thistle"))
        # an unmentioned entity is not pulled in
        self.assertNotIn("maera-thistle/summary.md",
                         self.agent._consult_brief("narrator", "an empty road"))

    def test_consult_pair_runs_both_concurrently(self):
        import time
        calls, real = [], self.agent.consult_role

        def slow(role, task):
            calls.append(role)
            time.sleep(0.4)
            return f"{role} says ok"
        self.agent.consult_role = slow
        try:
            start = time.time()
            out = self.agent.consult_pair("director", "a", "rules-lawyer", "b")
        finally:
            self.agent.consult_role = real
        self.assertLess(time.time() - start, 0.7)  # 0.8s if serialized
        self.assertIn("=== director ===", out)
        self.assertIn("=== rules-lawyer ===", out)
        self.assertEqual(sorted(calls), ["director", "rules-lawyer"])

    def test_rules_lawyer_brief_carries_the_rules(self):
        brief = self.agent._consult_brief("rules-lawyer", "does a potion revive?")
        self.assertIn("--- rules/srd-reference.md", brief)
        self.assertIn("--- rules/skill-checks.md", brief)
        self.assertIn("rules/srd index", brief)
        self.assertIn("rules/srd/06_Gameplay/", brief)
        # other roles don't carry the rules payload
        self.assertNotIn("rules/srd index",
                         self.agent._consult_brief("narrator", "x"))

    def test_narrator_cannot_run_tools(self):
        names = [t.__name__ for t in self.agent.role_tools("narrator")]
        self.assertNotIn("run_tool", names)  # it double-posted via narrate.py

    def test_party_sheets_inline_for_live_loop_roles(self):
        cur_path = self.campaign / "state" / "current.json"
        cur = json.loads(cur_path.read_text())
        cur["party"] = ["pc-warlock"]
        cur_path.write_text(json.dumps(cur))
        for role in ("director", "rules-lawyer", "narrator"):
            brief = self.agent._consult_brief(role)
            self.assertIn("--- campaign/characters/pc-warlock.json", brief, role)
        # background roles keep the one-line roster
        brief = self.agent._consult_brief("bookkeeper")
        self.assertNotIn("--- campaign/characters/pc-warlock.json", brief)
        self.assertIn("pc-warlock.json — Ember Vex", brief)

    def test_free_text_entities_are_skipped(self):
        cur_path = self.campaign / "state" / "current.json"
        cur = json.loads(cur_path.read_text())
        cur["present_entities"] = ["a nervous gnome at the bar (no file)"]
        cur_path.write_text(json.dumps(cur))
        self.agent._consult_brief("director")  # must not raise


class TestLocalClaudeCli(DesktopTestCase):
    """Any specialist role can run on `claude -p` locally instead of OpenRouter."""

    def test_model_id_parsing(self):
        c = self.config
        self.assertTrue(c.is_cli_model("claude-cli"))
        self.assertTrue(c.is_cli_model("claude-cli:opus"))
        self.assertFalse(c.is_cli_model("google/gemini-3.7-flash"))
        self.assertIsNone(c.cli_model_alias("claude-cli"))
        self.assertEqual(c.cli_model_alias("claude-cli:opus"), "opus")

    def test_picker_names_every_cli_model_explicitly(self):
        # A bare "claude-cli" inherits the machine's own Claude Code model
        # setting, so the picker must not offer it — every choice names one.
        cli = [i for i, _ in self.config.MODEL_CHOICES
               if self.config.is_cli_model(i)]
        self.assertEqual(cli, ["claude-cli:haiku", "claude-cli:sonnet",
                               "claude-cli:opus", "claude-cli:fable"])

    def test_dm_is_never_offered_a_cli_model(self):
        # Rejecting the save is not enough: an unpickable option in the dm's
        # dropdown is a defect. The setup screen (which sets the dm) and the
        # dm's dev-panel row both render from model_choices("dm").
        dm = [i for i, _ in self.config.model_choices("dm")]
        self.assertTrue(dm, "the dm must still have models to pick")
        self.assertFalse([i for i in dm if self.config.is_cli_model(i)])
        for role in (None, "narrator", "bookkeeper"):
            offered = [i for i, _ in self.config.model_choices(role)]
            self.assertTrue([i for i in offered if self.config.is_cli_model(i)],
                            f"{role} should be offered the local CLI")

    def test_dm_never_runs_on_the_cli(self):
        # It needs structured tool-calling; a hand-edited config must not brick.
        self.config.save(role_models={"dm": "claude-cli", "director": "claude-cli"})
        self.assertFalse(self.config.is_cli_model(self.config.role_model("dm")))
        self.assertTrue(self.config.is_cli_model(self.config.role_model("director")))

    def test_consult_routes_to_the_cli(self):
        self.config.save(role_models={"director": "claude-cli:opus"})
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return subprocess.CompletedProcess(cmd, 0, stdout="DECISION\n ok\n",
                                               stderr="")
        real_run, real_bin = self.agent.subprocess.run, self.agent.claude_binary
        self.agent.subprocess.run = fake_run
        self.agent.claude_binary = lambda: "/usr/bin/claude"
        try:
            out = self.agent.consult_role("director", "the party opens the door")
        finally:
            self.agent.subprocess.run = real_run
            self.agent.claude_binary = real_bin
        self.assertIn("DECISION", out)
        cmd = seen["cmd"]
        self.assertEqual(cmd[:2], ["/usr/bin/claude", "-p"])
        self.assertIn("the party opens the door", cmd[2])
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")
        # the role's own prompt is the system prompt, and the brief rode along
        self.assertIn("You are the Director", cmd[cmd.index("--system-prompt") + 1])
        self.assertIn("Pre-read state", cmd[2])
        # never blocks on a permission prompt, never gets a shell
        self.assertIn("Bash WebFetch WebSearch Task",
                      cmd[cmd.index("--disallowed-tools") + 1])
        self.assertEqual(seen["kw"]["timeout"], self.agent.CLI_TIMEOUT)

    def test_narrator_on_cli_gets_no_file_access(self):
        # The motivations firewall is a tool-level guarantee; `claude -p` has no
        # per-file hook, so the narrator runs brief-only.
        self.assertEqual(self.agent._CLI_ROLE_TOOLS["narrator"], [])
        self.config.save(role_models={"narrator": "claude-cli"})
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="> prose", stderr="")
        real_run, real_bin = self.agent.subprocess.run, self.agent.claude_binary
        self.agent.subprocess.run = fake_run
        self.agent.claude_binary = lambda: "/usr/bin/claude"
        try:
            self.agent.consult_role("narrator", "render the beat")
        finally:
            self.agent.subprocess.run = real_run
            self.agent.claude_binary = real_bin
        self.assertEqual(seen["cmd"][seen["cmd"].index("--allowed-tools") + 1], "")
        self.assertNotIn("--add-dir", seen["cmd"])

    def test_missing_cli_is_a_clear_error_not_a_crash(self):
        self.config.save(role_models={"director": "claude-cli"})
        real_bin = self.agent.claude_binary
        self.agent.claude_binary = lambda: None
        try:
            out = self.agent.consult_role("director", "x")
        finally:
            self.agent.claude_binary = real_bin
        self.assertIn("isn't installed", out)
        self.assertIn("Settings", out)

    def test_binary_resolution_falls_back_off_path(self):
        # A GUI-launched .app has a bare PATH; the resolver checks real
        # install locations too.
        real_which = self.agent.shutil.which
        self.agent.shutil.which = lambda _: None
        try:
            found = self.agent.claude_binary()
        finally:
            self.agent.shutil.which = real_which
        if found is not None:  # this machine has it installed somewhere known
            self.assertTrue(Path(found).is_file())


class TestActivity(DesktopTestCase):
    """Tool calls publish player-safe progress labels to dm-activity.json —
    fixed strings only, never paths or arguments that could spoil a secret."""

    def _read(self):
        return json.loads((self.campaign / "state" / "dm-activity.json").read_text())

    def _devlog(self):
        return (self.campaign / "state" / "dev-log.jsonl").read_text().splitlines()

    def test_tool_calls_publish_steps(self):
        self.agent.run_tool("dice.py", ["1d20"])
        data = self._read()
        self.assertTrue(data["busy"])
        self.assertIn("Rolling dice", data["steps"])

    def test_role_reads_name_the_role(self):
        self.agent.read_file(".claude/agents/director.md")
        self.assertIn("The Director is deciding what the world does",
                      self._read()["steps"])

    def test_labels_never_leak_paths(self):
        self.agent.read_file("campaign/npcs/recurring/villain/motivations.md")
        for step in self._read()["steps"]:
            self.assertNotIn("motivations", step)
            self.assertNotIn("villain", step)

    def test_turn_end_clears(self):
        self.agent.run_tool("dice.py", ["1d20"])
        self.agent._activity(None, busy=False)
        data = self._read()
        self.assertFalse(data["busy"])
        self.assertEqual(data["steps"], [])

    def test_tool_calls_land_in_devlog(self):
        self.agent.run_tool("dice.py", ["1d20", "--label", "test roll"])
        entry = json.loads(self._devlog()[-1])
        self.assertEqual(entry["tool"], "run_tool")
        self.assertIn("dice.py", entry["args"]["tool"])
        self.assertIn("test roll", entry["result"])

    def test_ticker_window_stays_short(self):
        """The ticker is player-facing furniture: 8 canned steps, no raw stream."""
        for _ in range(12):
            self.agent.run_tool("dice.py", ["1d20"])
            self.agent.read_file("rules/README.md")
        self.assertLessEqual(len(self._read()["steps"]), 8)

    def test_devlog_names_the_thread(self):
        """A subagent's tool calls are attributable in the sidebar."""
        self.agent.run_tool("dice.py", ["1d20"])
        self.assertEqual(json.loads(self._devlog()[-1])["thread"], "main")
        token = self.agent._thread.set("narrator")
        try:
            self.agent.read_file("rules/README.md")
        finally:
            self.agent._thread.reset(token)
        self.assertEqual(json.loads(self._devlog()[-1])["thread"], "narrator")

    def test_devlog_times_every_call(self):
        self.agent.run_tool("dice.py", ["1d20"])
        entry = json.loads(self._devlog()[-1])
        started = datetime.datetime.fromisoformat(entry["started"])
        finished = datetime.datetime.fromisoformat(entry["finished"])
        self.assertLessEqual(started, finished)
        self.assertGreaterEqual(entry["ms"], 0)
        # milliseconds, not seconds — parallel calls overlap well under a second
        self.assertRegex(entry["started"], r"\.\d{3}")

    def test_parallel_threads_keep_their_own_names_and_lines(self):
        """Two role agents running at once must not blend in the log."""
        def work(role):
            token = self.agent._thread.set(role)
            try:
                for _ in range(15):
                    self.agent.run_tool("dice.py", ["1d20", "--label", role])
                    self.agent.read_file("rules/README.md")
            finally:
                self.agent._thread.reset(token)

        threads = [threading.Thread(target=work, args=(r,))
                   for r in ("narrator", "director", "rules-lawyer")]
        [t.start() for t in threads]
        [t.join() for t in threads]

        lines = self._devlog()
        entries = [json.loads(line) for line in lines]   # no torn/interleaved lines
        self.assertEqual(len(entries), len(lines))
        by_thread = {}
        for e in entries:
            by_thread.setdefault(e["thread"], []).append(e)
        for role in ("narrator", "director", "rules-lawyer"):
            self.assertEqual(len(by_thread[role]), 30, role)
            # a thread only ever logs its own dice label
            for e in by_thread[role]:
                if e["args"].get("tool") == "dice.py":
                    self.assertIn(role, e["args"]["argv"])

    def test_narrator_firewall_refusal_is_logged(self):
        read = [t for t in self.agent.role_tools("narrator")
                if t.__name__ == "read_file_safe"][0]
        self.assertIn("GM-eyes-only", read("campaign/npcs/x/secrets.md"))
        entry = json.loads(self._devlog()[-1])
        self.assertEqual(entry["tool"], "read_file")
        self.assertIn("GM-eyes-only", entry["result"])


class TestWriteGuard(DesktopTestCase):
    def test_reads_follow_bundle_symlinks(self):
        # The frozen app reaches its data through PyInstaller's symlinks
        # (Contents/Frameworks/rules -> ../Resources/rules). resolve_path must
        # not treat following them as an escape.
        resources = self.tmp / "Resources"
        (resources / "rules").mkdir(parents=True)
        (resources / "rules" / "poison.md").write_text("ouch")
        bundle = self.tmp / "Frameworks"
        bundle.mkdir()
        (bundle / "rules").symlink_to(resources / "rules")
        old = self.config.BUNDLE
        self.config.BUNDLE = bundle
        try:
            self.assertEqual(self.agent.read_file("rules/poison.md"), "ouch")
        finally:
            self.config.BUNDLE = old

    def test_campaign_writes_allowed(self):
        result = self.agent.write_file("campaign/state/scratch.md", "hello")
        self.assertIn("wrote", result)
        self.assertEqual((self.campaign / "state" / "scratch.md").read_text(), "hello")

    def test_reference_tree_is_read_only(self):
        for path in ("rules/pwned.md", "CLAUDE.md", ".claude/agents/narrator.md"):
            self.assertIn("error", self.agent.write_file(path, "x"), path)
        self.assertFalse((REPO / "rules" / "pwned.md").exists())

    def test_absolute_and_traversal_paths_refused(self):
        for path in ("/etc/passwd", "campaign/../../escaped.md", "../CLAUDE.md",
                     "campaign/../../../tmp/x"):
            with self.assertRaises(ValueError, msg=path):
                self.agent.resolve_path(path, write=True)

    def test_traversal_refused_on_read_too(self):
        self.assertIn("error", self.agent.read_file("../../../etc/passwd"))

    def test_edit_requires_unique_match(self):
        self.agent.write_file("campaign/state/scratch.md", "a\na\n")
        self.assertIn("appears 2 times",
                      self.agent.edit_file("campaign/state/scratch.md", "a", "b"))
        self.assertIn("not found",
                      self.agent.edit_file("campaign/state/scratch.md", "zzz", "b"))


class TestDottedPaths(DesktopTestCase):
    """The DM reads its own role prompts from .claude/agents/ — a naive
    lstrip('./') eats that leading dot and every read fails."""

    def test_dotted_path_reads(self):
        for path in (".claude/agents/narrator.md", "./.claude/agents/narrator.md"):
            self.assertEqual(self.agent.resolve_path(path, write=False).name,
                             "narrator.md", path)
            self.assertNotIn("error", self.agent.read_file(path)[:40].lower(), path)

    def test_dotted_glob_lists(self):
        self.assertIn(".claude/agents/director.md",
                      self.agent.list_files(".claude/agents/*.md"))


class TestToolWhitelist(DesktopTestCase):
    def test_unknown_tool_refused(self):
        self.assertIn("unknown tool", self.agent.run_tool("rm", ["-rf", "/"]))
        self.assertIn("unknown tool", self.agent.run_tool("../../evil.py", []))

    def test_dice_runs_in_process(self):
        self.assertIn("1d20", self.agent.run_tool("dice.py", ["1d20"]))

    def test_narration_flag_only_set_by_narrate(self):
        self.agent.begin_turn()
        self.agent.allow_narration()  # plumbing test, not routing policy
        self.agent.run_tool("dice.py", ["1d20"])
        self.assertFalse(self.agent.narrated())
        self.agent.run_tool("narrate.py", ["The door opens."])
        self.assertTrue(self.agent.narrated())

    def test_narrate_reaches_the_feed(self):
        self.agent.allow_narration()  # plumbing test, not routing policy
        self.agent.run_tool("narrate.py", ["-"], stdin="The gate groans open.")
        feed = (self.campaign / "state" / "player-feed.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(feed[-1])["text"], "The gate groans open.")


try:
    import langchain_core  # noqa: F401
    HAVE_LANGCHAIN = True
except ImportError:
    HAVE_LANGCHAIN = False


@unittest.skipUnless(HAVE_LANGCHAIN, "langchain not installed")
class TestPromptCache(DesktopTestCase):
    """Cache breakpoints: placed on the newest markable messages, never on
    empty content, and surviving serialization into the request payload —
    a marker langchain silently drops caches nothing."""

    def _msgs(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        return [HumanMessage(content="attack the goblin"),
                AIMessage(content="", tool_calls=[
                    {"name": "run_tool", "args": {}, "id": "c1"}]),
                ToolMessage(content="rolled 17", tool_call_id="c1")]

    def test_marks_newest_two_and_skips_empty(self):
        msgs = self._msgs()
        marked = self.agent._mark_cache(msgs)
        self.assertEqual(marked[2].content[-1]["cache_control"],
                         self.agent.CACHE_CONTROL)   # tool result
        self.assertEqual(marked[0].content[-1]["cache_control"],
                         self.agent.CACHE_CONTROL)   # human, skipping empty AI
        self.assertEqual(marked[1].content, "")      # empty AIMessage untouched
        self.assertEqual(msgs[0].content, "attack the goblin")  # originals intact

    def test_cache_control_reaches_the_payload(self):
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="x", api_key="k", base_url="http://localhost")
        payload = model._get_request_payload(
            [self.agent._cached_system("manual")] +
            self.agent._mark_cache(self._msgs()))
        system, human = payload["messages"][0], payload["messages"][1]
        self.assertEqual(system["content"][0]["cache_control"],
                         self.agent.CACHE_CONTROL)
        self.assertEqual(human["content"][0]["cache_control"],
                         self.agent.CACHE_CONTROL)


class TestRoleAgents(DesktopTestCase):
    """consult_role subagents: the narrator's tool-level motivations firewall,
    per-role write access, and per-role model resolution."""

    def test_narrator_read_is_firewalled(self):
        secret = self.campaign / "npcs" / "x" / "motivations.md"
        secret.parent.mkdir(parents=True)
        secret.write_text("the mayor is the villain")
        (secret.parent / "summary.md").write_text("the mayor")
        narrator_read = self.agent.role_tools("narrator")[0]
        for path in ("campaign/npcs/x/motivations.md", "campaign/npcs/x/secrets.md"):
            self.assertIn("GM-eyes-only", narrator_read(path), path)
        self.assertEqual(narrator_read("campaign/npcs/x/summary.md"), "the mayor")

    def test_only_bookkeeper_writes(self):
        self.assertIn(self.agent.write_file, self.agent.role_tools("bookkeeper"))
        for role in ("narrator", "director", "rules-lawyer"):
            self.assertNotIn(self.agent.write_file, self.agent.role_tools(role), role)

    def test_unknown_role_refused(self):
        self.assertIn("error: unknown role", self.agent.consult_role("dm", "x"))
        self.assertIn("error: unknown role", self.agent.consult_role("wizard", "x"))

    def test_env_model_override(self):
        os.environ["AUTODM_MODEL"] = "sandbox/model"
        try:
            self.assertEqual(self.config.model(), "sandbox/model")
        finally:
            os.environ.pop("AUTODM_MODEL")

    def test_every_role_picks_its_own_model(self):
        self.config.APP_DIR.mkdir(parents=True)
        self.config.save(role_models={"narrator": "cheap/model",
                                      "dm": "fast/model"})
        # a user's pick beats the shipped per-role default; there is no global
        self.assertEqual(self.agent.role_model("narrator"), "cheap/model")
        self.assertEqual(self.agent.role_model("dm"), "fast/model")
        self.assertEqual(self.config.model(), "fast/model")
        self.assertEqual(self.agent.role_model("rules-lawyer"),
                         self.config.DEV_DEFAULTS["role_models"]["rules-lawyer"])
        for role in self.prompts.ROLES:
            self.assertIn(role, self.config.DEV_DEFAULTS["role_models"], role)

    def test_legacy_global_model_still_drives_the_dm(self):
        """A config written before per-role models keeps its DM choice."""
        self.config.APP_DIR.mkdir(parents=True)
        self.config.save(model="legacy/model")
        self.assertEqual(self.agent.role_model("dm"), "legacy/model")
        self.assertEqual(self.agent.role_model("narrator"),
                         self.config.DEV_DEFAULTS["role_models"]["narrator"])


class TestPlayersText(DesktopTestCase):
    """Fallback prose for a turn that forgot to call narrate.py — the DM layer
    ([DIRECTOR], roll:, result:) must never reach the players."""

    def test_blockquote_layer_preferred(self):
        self.assertEqual(
            self.agent.players_text("[DIRECTOR] goblin flees\n> The door opens.\n> Dust falls."),
            "The door opens.\nDust falls.")

    def test_label_lines_stripped(self):
        self.assertEqual(
            self.agent.players_text("[BOOKKEEPER] hp 4\nresult: 12\nThe door opens."),
            "The door opens.")


class TestPromptRegistry(DesktopTestCase):
    def test_every_role_resolves_to_a_real_file(self):
        for entry in self.prompts.registry():
            self.assertTrue(self.prompts.resolve(entry["role"]).exists(), entry)

    def test_default_falls_back_to_shipped_agent_file(self):
        self.assertEqual(self.prompts.resolve("narrator"),
                         REPO / ".claude" / "agents" / "narrator.md")
        self.assertIsNone(self.prompts.override_for(".claude/agents/narrator.md"))

    def test_selected_variant_overrides_the_agent_file(self):
        variant = REPO / "prompts" / "narrator" / "_test_arm.md"
        variant.parent.mkdir(parents=True, exist_ok=True)
        variant.write_text("# test arm\n", encoding="utf-8")
        try:
            self.config.save(prompts={"narrator": "_test_arm"})
            self.assertEqual(self.prompts.override_for(".claude/agents/narrator.md"),
                             variant)
            self.assertIn("test arm",
                          self.agent.read_file(".claude/agents/narrator.md"))
        finally:
            variant.unlink()
            if not any(variant.parent.iterdir()):
                variant.parent.rmdir()

    def test_override_only_applies_to_agent_paths(self):
        for path in ("rules/srd.md", "campaign/state/current.json",
                     ".claude/agents/../../etc/passwd.md",
                     ".claude/skills/combat-encounter/SKILL.md"):
            self.assertIsNone(self.prompts.override_for(path), path)

    def test_unknown_role_rejected(self):
        with self.assertRaises(ValueError):
            self.prompts.resolve("dungeon-master")


class TestSessionBrief(DesktopTestCase):
    def test_brief_covers_the_session_start_reads(self):
        brief = self.agent.session_brief()
        for expected in ("campaign/state/current.json", "campaign/state/quests.json",
                         "campaign/house-rules.md"):
            self.assertIn(expected, brief)

    def test_brief_includes_character_sheets(self):
        brief = self.agent.session_brief()
        for sheet in (self.campaign / "characters").glob("*.json"):
            self.assertIn(f"campaign/characters/{sheet.name}", brief)


if __name__ == "__main__":
    unittest.main()
