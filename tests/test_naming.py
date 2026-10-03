import unittest
from engine.naming import (
    parse_match_identifiers,
    slugify_moment,
    get_master_video_filename,
    get_social_clip_filename,
    get_highlight_reel_filename,
    get_match_folder_name,
    get_manifest_filename,
    get_target_subfolder_path,
    FOLDER_HIGHLIGHTS,
    FOLDER_TRIES,
    FOLDER_SCRUMS,
    FOLDER_LINEOUTS,
    FOLDER_KICKS,
    FOLDER_GENERAL,
    FOLDER_OPPOSING_TEAM,
    FOLDER_NEEDS_REVIEW,
)

class TestNaming(unittest.TestCase):
    def test_parse_match_identifiers(self):
        slug = "20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0"
        m_date, uid, opp = parse_match_identifiers(slug)
        self.assertEqual(m_date, "20260822")
        self.assertEqual(uid, "v4fb17b0")
        self.assertEqual(opp, "sydney-convicts-1")

    def test_get_master_video_filename(self):
        slug = "20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0"
        fn = get_master_video_filename(slug, quality="1080p")
        self.assertEqual(fn, "20260822_v4fb17b0_sf-fog-rugby_vs_sydney-convicts-1_1080p.mp4")

    def test_get_social_clip_filename(self):
        slug = "20260822-san-francisco-fog-rfc-a-side-vs-sydney-convicts-1-v4fb17b0"
        fn = get_social_clip_filename(slug, dimensions="9:16", moment_type="try-1-breakaway")
        self.assertEqual(fn, "20260822_v4fb17b0_fog-rugby_9x16_try-1-breakaway.mp4")

    def test_get_target_subfolder_path_fog_positive(self):
        primary, nested = get_target_subfolder_path("try", sentiment="fog_positive")
        self.assertEqual(primary, FOLDER_TRIES)
        self.assertIsNone(nested)

        primary, nested = get_target_subfolder_path("scrum", sentiment="fog_positive")
        self.assertEqual(primary, FOLDER_SCRUMS)
        self.assertIsNone(nested)

        primary, nested = get_target_subfolder_path("highlights", sentiment="fog_positive")
        self.assertEqual(primary, FOLDER_HIGHLIGHTS)
        self.assertIsNone(nested)

    def test_get_target_subfolder_path_opposing_team(self):
        primary, nested = get_target_subfolder_path("try", sentiment="fog_negative")
        self.assertEqual(primary, FOLDER_OPPOSING_TEAM)
        self.assertEqual(nested, FOLDER_TRIES)

        primary, nested = get_target_subfolder_path("conversion", sentiment="fog_negative")
        self.assertEqual(primary, FOLDER_OPPOSING_TEAM)
        self.assertEqual(nested, FOLDER_KICKS)

    def test_get_target_subfolder_path_needs_review(self):
        primary, nested = get_target_subfolder_path("scrum", sentiment="neutral")
        self.assertEqual(primary, FOLDER_NEEDS_REVIEW)
        self.assertEqual(nested, FOLDER_SCRUMS)

if __name__ == "__main__":
    unittest.main()
