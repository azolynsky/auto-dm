"""Style gate in narrate.py — the banned-habits regexes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import narrate


class TestStyleViolations(unittest.TestCase):
    def test_flags_recurring_reflexes(self):
        bad = [
            "Marl answers the easy questions like a man reading a shopping list.",
            "They sit down on the deck like schoolboys.",
            "He studies the thing the way he'd study a rock.",
            "She hits the door like a landslide.",
            "He cracks his knuckles and grins.",
            "Vhalak lets out a breath he seems to have held for years.",
            "The hall falls silent.\n\nWhat do you want to do next?",
            "The path splits ahead.\nWhat do you do?",
            "The inn settles.\n\n- Head up the hill to the shrine.\n- Search the village.\n- Set up defenses.",
            "Night falls.\n\n1. Rest until dawn.\n2) Press on in the dark.",
        ]
        for text in bad:
            self.assertTrue(narrate.style_violations(text), f"missed: {text}")

    def test_passes_clean_prose(self):
        clean = [
            "The Eel rocks like a bathtub with a bear in it.",  # object simile, allowed
            "Mira slips back along the quay, quiet as a cat.",
            "He reads the old words without stumbling once.",
            "The fog is lifting off the harbor. You hold the warehouse now.",
            "Relthus points the way to the water door.",
            "\"What do you want to do about the rats?\" Maera asks, hands on hips.",
            "The gnome squints. \"And what do you do, exactly, for coin?\"",
            "On the shelf sit three jars:\n- pickled eggs\n- a gray powder\n- something moving\nThe stew bubbles on.",
        ]
        for text in clean:
            self.assertEqual(narrate.style_violations(text), [], f"false positive: {text}")


if __name__ == "__main__":
    unittest.main()
