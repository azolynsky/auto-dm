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


class TestActivity(DesktopTestCase):
    """Tool calls publish player-safe progress labels to dm-activity.json —
    fixed strings only, never paths or arguments that could spoil a secret."""

    def _read(self):
        return json.loads((self.campaign / "state" / "dm-activity.json").read_text())

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

    def test_role_model_falls_back_to_global(self):
        self.config.APP_DIR.mkdir(parents=True)
        self.config.save(model="global/model",
                         role_models={"narrator": "cheap/model",
                                      "director": "user/model"})
        # user setting beats the role default beats the global model
        self.assertEqual(self.agent.role_model("narrator"), "cheap/model")
        self.assertEqual(self.agent.role_model("director"), "user/model")
        self.assertEqual(self.agent.role_model("rules-lawyer"),
                         self.config.DEV_DEFAULTS["role_models"]["rules-lawyer"])
        self.assertEqual(self.agent.role_model("dm"), "global/model")


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
