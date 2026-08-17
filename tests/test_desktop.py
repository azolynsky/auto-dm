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

import json
import os
import shutil
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
        for name in ("config", "prompts", "agent", "campaign_lib"):
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
        for name in ("config", "prompts", "agent", "campaign_lib"):
            sys.modules.pop(name, None)


class TestWriteGuard(DesktopTestCase):
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
        self.agent._narrated = False
        self.agent.run_tool("dice.py", ["1d20"])
        self.assertFalse(self.agent._narrated)
        self.agent.run_tool("narrate.py", ["The door opens."])
        self.assertTrue(self.agent._narrated)

    def test_narrate_reaches_the_feed(self):
        self.agent.run_tool("narrate.py", ["-"], stdin="The gate groans open.")
        feed = (self.campaign / "state" / "player-feed.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(feed[-1])["text"], "The gate groans open.")


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
