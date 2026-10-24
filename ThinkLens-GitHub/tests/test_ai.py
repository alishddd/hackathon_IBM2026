import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_engine as ai


def finding(quote="Everyone knows", **changes):
    result = dict(quote=quote, context_before="", context_after="", category="general",
                  why="This wording suggests consensus.", effect="It may discourage disagreement.",
                  question="What evidence establishes the agreement?", alternative="It may be informal shorthand.",
                  status="Context required")
    result.update(changes)
    return result


class AITests(unittest.TestCase):
    def align(self, text, findings):
        return ai.align_findings(text, {"summary": "Possible rhetorical cues.", "findings": findings})

    def test_unicode_offsets(self):
        text = "😀 Everyone knows."
        result = self.align(text, [finding()])["findings"][0]
        self.assertEqual(result["start"], 3)
        self.assertEqual(result["end"], 17)
        encoded = text.encode("utf-16-le")
        self.assertEqual(encoded[result["start"]*2:result["end"]*2].decode("utf-16-le"), result["quote"])

    def test_repeated_context(self):
        text = "Everyone knows A. Everyone knows B."
        result = self.align(text, [finding(context_after=" B.")])
        self.assertEqual(result["findings"][0]["start"], 18)

    def test_ambiguous_and_invented_quotes_rejected(self):
        for text, quote in [("Everyone knows. Everyone knows.", "Everyone knows"), ("A neutral sentence.", "Not in the text")]:
            with self.subTest(text=text), self.assertRaises(ai.AIError):
                self.align(text, [finding(quote)])

    def test_partial_discard_is_visible(self):
        result = self.align("Everyone knows.", [finding(), finding("Invented words")])
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["discarded"], 1)

    def test_overlaps_preserved_duplicates_removed(self):
        result = self.align("Everyone knows.", [finding(), finding("knows", category="loaded"), finding()])
        self.assertEqual(len(result["findings"]), 2)
        self.assertLess(result["findings"][1]["start"], result["findings"][0]["end"])

    def test_zero_findings(self):
        self.assertEqual(self.align("Library opening hours.", [])["findings"], [])

    def test_invalid_category_and_fields(self):
        for entry in [finding(category="dishonesty"), finding(status="Fact checked"), finding(why=""), {"quote": "Everyone knows"}]:
            with self.subTest(entry=entry), self.assertRaises(ai.AIError):
                self.align("Everyone knows.", [entry])

    def test_empty_and_long_inputs(self):
        for text in ["", "  ", "a"*12001, "😀"*6001, None]:
            with self.subTest(length=len(text) if text else 0), self.assertRaises(ai.AIError) as error:
                ai.analyze(text)
            self.assertEqual(error.exception.status, 400)

    def test_cli_json_pipeline(self):
        response = {"summary": "Consensus wording.", "findings": [finding()]}
        with patch.object(ai, "connection_status", return_value={"ready": True}), patch.object(ai, "cli_path", return_value="codex.exe"), patch.object(ai.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")) as run:
            result = ai.analyze("Everyone knows.")
        args, options = run.call_args
        command = args[0]
        self.assertIn("--ephemeral", command)
        self.assertIn("read-only", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--output-schema", command)
        self.assertIn("shell_tool", command)
        self.assertEqual(json.loads(options["input"]), {"article_text": "Everyone knows."})
        self.assertEqual(result["mode"], "live")

    def test_timeout_and_failure_no_fallback(self):
        with patch.object(ai, "connection_status", return_value={"ready": True}), patch.object(ai, "cli_path", return_value="codex.exe"):
            for side_effect in [subprocess.TimeoutExpired("codex", 180), None]:
                with self.subTest(timeout=bool(side_effect)), patch.object(ai.subprocess, "run", side_effect=side_effect, return_value=subprocess.CompletedProcess([], 1, "", "secret diagnostic")):
                    with self.assertRaises(ai.AIError) as error:
                        ai.analyze("Everyone knows.")
                    self.assertNotIn("secret diagnostic", str(error.exception))

    def test_malformed_output(self):
        with patch.object(ai, "connection_status", return_value={"ready": True}), patch.object(ai, "cli_path", return_value="codex.exe"), patch.object(ai.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "invalid json", "")):
            with self.assertRaises(ai.AIError):
                ai.analyze("Everyone knows.")

    def test_auth_required(self):
        with patch.object(ai, "connection_status", return_value={"ready": False}), self.assertRaises(ai.AIError) as error:
            ai.analyze("Everyone knows.")
        self.assertEqual(error.exception.status, 503)


if __name__ == "__main__":
    unittest.main()
