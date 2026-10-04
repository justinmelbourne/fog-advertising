import unittest
from unittest.mock import patch, MagicMock
from engine.team_analyzer import (
    classify_moment_with_gemini,
    fallback_heuristic_classification,
    classify_event,
)

class TestTeamAnalyzer(unittest.TestCase):
    def test_fallback_heuristic_untagged_needs_review(self):
        # Unverified moments must never be filed as Fog positive
        res = fallback_heuristic_classification("try", "Veo AI Try", "Sydney Convicts")
        self.assertEqual(res["sentiment"], "neutral")
        self.assertEqual(res["team"], "unknown")
        self.assertEqual(res["sentiment_confidence"], 0.0)

    def test_generic_opponent_name_not_matched_by_accident(self):
        res = fallback_heuristic_classification("try", "Veo AI Try", "Opponent")
        self.assertEqual(res["sentiment"], "neutral")

    def test_classify_event_without_video_needs_review(self):
        res = classify_event({"event_type": "try", "description": "Veo AI Try"}, video_path=None)
        self.assertEqual(res["sentiment"], "neutral")

    @patch("engine.team_analyzer.requests.post", side_effect=ConnectionError("boom"))
    def test_gemini_failure_routes_needs_review(self, _mock_post):
        res = classify_moment_with_gemini(["/tmp/fake_frame.jpg"], "try", api_key="k")
        self.assertEqual(res["sentiment"], "neutral")

    @patch.dict("os.environ", {"GEMINI_MODEL": "gemini-test-model"})
    @patch("engine.team_analyzer.requests.post")
    def test_api_key_in_header_not_url_and_model_configurable(self, mock_post):
        mock_post.return_value = MagicMock(json=MagicMock(return_value={}))
        classify_moment_with_gemini(["/tmp/fake_frame.jpg"], "try", api_key="secret-key")
        url = mock_post.call_args.args[0]
        self.assertNotIn("secret-key", url)
        self.assertIn("gemini-test-model", url)
        self.assertEqual(mock_post.call_args.kwargs["headers"]["x-goog-api-key"], "secret-key")

    @patch("engine.team_analyzer.requests.post")
    def test_unknown_sentiment_label_routes_needs_review(self, mock_post):
        mock_post.return_value = MagicMock(json=MagicMock(return_value={
            "candidates": [{"content": {"parts": [{"text": '{"sentiment": "great", "confidence": 0.99}'}]}}]
        }))
        res = classify_moment_with_gemini(["/tmp/fake_frame.jpg"], "try", api_key="k")
        self.assertEqual(res["sentiment"], "neutral")

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

class TestVertexBackend(unittest.TestCase):
    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "sffog-video-analysis", "GEMINI_MODEL": "m1"}, clear=True)
    @patch("engine.team_analyzer._vertex_access_token", return_value="sa-token")
    @patch("engine.team_analyzer.requests.post")
    def test_vertex_uses_service_account_not_key(self, mock_post, _tok):
        mock_post.return_value = MagicMock(json=MagicMock(return_value={
            "candidates": [{"content": {"parts": [{"text": '{"sentiment": "fog_positive", "confidence": 0.9}'}]}}]
        }))
        res = classify_moment_with_gemini(["/tmp/fake_frame.jpg"], "try")
        url = mock_post.call_args.args[0]
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(
            url,
            "https://aiplatform.googleapis.com/v1/projects/sffog-video-analysis/locations/global/publishers/google/models/m1:generateContent",
        )
        self.assertEqual(headers, {"Authorization": "Bearer sa-token"})
        self.assertEqual(res["sentiment"], "fog_positive")
        self.assertEqual(res["classified_by"], "gemini:vertex:m1")

    @patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "p", "GEMINI_API_KEY": "k", "GEMINI_BACKEND": "vertex"}, clear=True)
    def test_explicit_backend_wins_over_key(self):
        from engine.team_analyzer import gemini_backend
        self.assertEqual(gemini_backend(), "vertex")

    @patch.dict("os.environ", {}, clear=True)
    def test_no_backend_needs_review(self):
        res = classify_moment_with_gemini(["/tmp/fake_frame.jpg"], "try")
        self.assertEqual(res["sentiment"], "neutral")


class TestGeminiErrorLogging(unittest.TestCase):
    @patch("engine.team_analyzer.requests.post")
    def test_http_error_logs_status_without_key(self, mock_post):
        import requests as _rq
        resp = MagicMock(status_code=429)
        resp.json.return_value = {"error": {"status": "RESOURCE_EXHAUSTED"}}
        mock_post.return_value = MagicMock(raise_for_status=MagicMock(side_effect=_rq.HTTPError(response=resp)))
        with self.assertLogs("engine.team_analyzer", level="WARNING") as logs:
            res = classify_moment_with_gemini(["/tmp/fake_frame.jpg"], "try", api_key="secret-key")
        self.assertEqual(res["sentiment"], "neutral")
        joined = "\n".join(logs.output)
        self.assertIn("HTTP 429 RESOURCE_EXHAUSTED", joined)
        self.assertNotIn("secret-key", joined)


if __name__ == "__main__":
    unittest.main()


import shutil as _shutil
import subprocess as _subprocess
import pytest as _pytest


@_pytest.mark.skipif(_shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_classify_event_sends_small_video_proxy(tmp_path):
    clip = tmp_path / "clip.mp4"
    _subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=40",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest", str(clip)], check=True, capture_output=True)

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return MagicMock(json=MagicMock(return_value={
            "candidates": [{"content": {"parts": [{"text": '{"sentiment": "fog_positive", "confidence": 0.9, "kit_observed": "rainbow band", "decisive_action": "try"}'}]}}]
        }))

    with patch.dict("os.environ", {"GEMINI_API_KEY": "k"}, clear=True), \
         patch("engine.team_analyzer.requests.post", side_effect=fake_post):
        res = classify_event({"event_type": "try", "start_time": 0.0, "duration": 40.0}, video_path=str(clip))

    parts = captured["payload"]["contents"][0]["parts"]
    media = [p for p in parts if "inline_data" in p]
    assert len(media) == 1 and media[0]["inline_data"]["mime_type"] == "video/mp4"
    import base64
    proxy_bytes = len(base64.b64decode(media[0]["inline_data"]["data"]))
    assert proxy_bytes < 5 * 1024 * 1024  # fits comfortably inline
    assert res["sentiment"] == "fog_positive"
    assert "rainbow band" in res["sentiment_rationale"]
