"""Guard against accidental reintroduction of non-public research code."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicBoundaryTest(unittest.TestCase):
    def test_private_feature_sources_are_not_shipped(self):
        for path in (
            "studylog_autonomy.py", "studylog_srl.py",
            "docs/private/algorithm_spec.md",
            "tests/test_analysis.py", "tests/test_planning.py",
            "tests/test_effects.py", "tests/http_plan_smoke.py",
            "tests/http_effects_smoke.py",
        ):
            self.assertFalse((ROOT / path).exists(), path)

    def test_public_interface_disables_research_features(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from studylog_analysis import (
            studylog_analyze_log, studylog_build_next_plan, studylog_valid_tracking
        )
        row = {"id": 1, "category": "公開サンプル", "task": "学習", "goal": "計画"}
        self.assertEqual(studylog_analyze_log(row, [])["state"], "unavailable")
        self.assertFalse(studylog_build_next_plan(row, {})["enabled"])
        self.assertFalse(studylog_valid_tracking({}))

    def test_readme_has_public_private_boundary(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("公開版に含まれないもの", readme)
        self.assertNotIn("0.90 - 0.15", readme)
        self.assertNotIn("STUDYLOG_HISTORY_LIMIT", (ROOT / "studylog_analysis.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
