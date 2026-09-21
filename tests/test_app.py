import unittest
from unittest.mock import patch
import os

from app import Draft, ROOT, main, read_json, settings, validate_citations


class DraftTests(unittest.TestCase):
    def test_deepseek_never_reuses_openai_key(self):
        with patch.dict(os.environ, {"TUTOR_PROVIDER":"deepseek", "TUTOR_API_KEY":"openai-test-key"}, clear=True), patch("app.load_dotenv"):
            with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
                settings()

    def test_deepseek_uses_separate_key(self):
        env = {"TUTOR_PROVIDER":"deepseek", "TUTOR_API_KEY":"openai-test-key", "DEEPSEEK_API_KEY":"deepseek-test-key", "TUTOR_MODEL":"openai/deepseek-flash", "TUTOR_BASE_URL":"https://api.deepseek.com"}
        with patch.dict(os.environ, env, clear=True), patch("app.load_dotenv"):
            self.assertEqual(settings()["TUTOR_API_KEY"], "deepseek-test-key")

    def draft(self, evidence):
        return Draft(student_reply="请提供知识点，我先核对记录。", evidence=evidence,
                     assistant_checks=["找老师核对评价记录"], missing_info=["知识点"],
                     suggested_status="待老师核实")

    def test_valid_source(self):
        validate_citations(self.draft([{"knowledge_id": "K001", "quote": "能条理清晰地自行表述"}]), read_json(ROOT / "knowledge.json"))

    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            validate_citations(self.draft([{"knowledge_id": "K999", "quote": "系统延迟"}]), read_json(ROOT / "knowledge.json"))

    def test_invented_quote_rejected(self):
        with self.assertRaises(ValueError):
            validate_citations(self.draft([{"knowledge_id": "K001", "quote": "做对三题就掌握"}]), read_json(ROOT / "knowledge.json"))

    def test_no_evidence_allowed_for_missing_rules(self):
        validate_citations(self.draft([]), read_json(ROOT / "knowledge.json"))

    def test_model_cannot_close_case(self):
        with self.assertRaises(ValueError):
            Draft(student_reply="已解决", evidence=[], assistant_checks=["核对"], missing_info=[], suggested_status="已解决")

    def test_missing_config_stops_before_model(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.load_dotenv"), patch("app.generate") as generate:
            self.assertEqual(main(["--case", "F010"]), 2)
            generate.assert_not_called()

    def test_all_previews_are_offline(self):
        with patch("app.generate") as generate, patch("builtins.print"):
            for case in ("F009", "F010", "F004"):
                self.assertEqual(main(["--case", case, "--preview"]), 0)
            generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
