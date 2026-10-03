import unittest
from unittest.mock import MagicMock, patch
from cloud_service.veo_api_client import VeoApiClient

class TestVeoApiClient(unittest.TestCase):
    def setUp(self):
        self.client = VeoApiClient(token="mock_token")

    def test_parse_slug_or_id(self):
        url = "https://app.veo.co/matches/20260822-sf-fog-vs-convicts-v4fb17b0/"
        self.assertEqual(self.client.parse_slug_or_id(url), "20260822-sf-fog-vs-convicts-v4fb17b0")

    @patch.object(VeoApiClient, "get_match_videos")
    @patch.object(VeoApiClient, "get_match_highlights")
    def test_resolve_match_details_selects_highest_res(self, mock_highlights, mock_videos):
        mock_videos.return_value = [
            {"url": "https://c.veocdn.com/720p.mp4", "width": 1280, "height": 720, "render_type": "standard"},
            {"url": "https://c.veocdn.com/4k.mp4", "width": 3840, "height": 2160, "render_type": "high_res"},
            {"url": "https://c.veocdn.com/1080p.mp4", "width": 1920, "height": 1080, "render_type": "standard"},
        ]
        mock_highlights.return_value = [{"type": "try", "start": 100, "duration": 20}]

        details = self.client.resolve_match_details("v4fb17b0")
        self.assertIsNotNone(details)
        self.assertEqual(details["width"], 3840)
        self.assertEqual(details["height"], 2160)
        self.assertEqual(details["video_url"], "https://c.veocdn.com/4k.mp4")

    @patch.object(VeoApiClient, "get_match_videos")
    @patch.object(VeoApiClient, "get_match_highlights")
    def test_resolve_match_details_prefer_panoramic(self, mock_highlights, mock_videos):
        mock_videos.return_value = [
            {"url": "https://c.veocdn.com/1080p.mp4", "width": 1920, "height": 1080, "render_type": "standard"},
            {"url": "https://c.veocdn.com/panoramic.mp4", "width": 3840, "height": 1080, "render_type": "panoramic"},
        ]
        mock_highlights.return_value = []

        details = self.client.resolve_match_details("v4fb17b0", prefer_panoramic=True)
        self.assertIsNotNone(details)
        self.assertEqual(details["video_url"], "https://c.veocdn.com/panoramic.mp4")
        self.assertEqual(details["render_type"], "panoramic")

if __name__ == "__main__":
    unittest.main()
