import unittest
from unittest.mock import patch, MagicMock
from engine.team_analyzer import (
    classify_moment_with_gemini,
    fallback_heuristic_classification,
    classify_event,
)

class TestTeamAnalyzer(unittest.TestCase):
    def test_fallback_heuristic_fog(self):
        res = fallback_heuristic_classification("try", "Veo AI Try", "Sydney Convicts")
        self.assertEqual(res["sentiment"], "fog_positive")
        self.assertEqual(res["team"], "sf_fog")
        self.assertEqual(res["team_display"], "SF Fog RFC")

    def test_fallback_heuristic_opponent(self):
        res = fallback_heuristic_classification("try", "Sydney Convicts Try Left Wing", "Sydney Convicts")
        self.assertEqual(res["sentiment"], "fog_negative")
        self.assertEqual(res["team"], "opponent")
        self.assertEqual(res["team_display"], "Sydney Convicts")

    @patch("engine.team_analyzer.requests.post")
    def test_classify_moment_with_gemini_success_fog(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"sentiment": "fog_positive", "team": "sf_fog", "team_display": "SF Fog RFC", "confidence": 0.95, "rationale": "Rainbow band jersey grounded ball"}'
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        res = classify_moment_with_gemini(
            keyframe_paths=["/tmp/fake_frame.jpg"],
            event_type="try",
            event_description="Try",
            opponent_name="Sydney Convicts",
            api_key="mock_key",
        )

        self.assertEqual(res["sentiment"], "fog_positive")
        self.assertEqual(res["team"], "sf_fog")
        self.assertAlmostEqual(res["sentiment_confidence"], 0.95)
        self.assertIn("Rainbow", res["sentiment_rationale"])

    @patch("engine.team_analyzer.requests.post")
    def test_classify_moment_with_gemini_low_confidence_routes_neutral(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"sentiment": "fog_positive", "team": "sf_fog", "team_display": "SF Fog RFC", "confidence": 0.60, "rationale": "Unclear jersey view"}'
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        res = classify_moment_with_gemini(
            keyframe_paths=["/tmp/fake_frame.jpg"],
            event_type="scrum",
            api_key="mock_key",
        )

        self.assertEqual(res["sentiment"], "neutral")
        self.assertAlmostEqual(res["sentiment_confidence"], 0.60)

    @patch("engine.team_analyzer.requests.post")
    def test_classify_moment_with_gemini_opponent_try(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"sentiment": "fog_negative", "team": "opponent", "team_display": "Sydney Convicts", "confidence": 0.98, "rationale": "White jersey player scored in corner"}'
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        res = classify_moment_with_gemini(
            keyframe_paths=["/tmp/fake_frame.jpg"],
            event_type="try",
            opponent_name="Sydney Convicts",
            api_key="mock_key",
        )

        self.assertEqual(res["sentiment"], "fog_negative")
        self.assertEqual(res["team"], "opponent")
        self.assertEqual(res["team_display"], "Sydney Convicts")
        self.assertAlmostEqual(res["sentiment_confidence"], 0.98)

if __name__ == "__main__":
    unittest.main()
