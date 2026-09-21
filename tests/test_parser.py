import unittest
from src.parser import parse_post_url


class TestLinkedInParser(unittest.TestCase):
    def test_user_ugc_post_url(self):
        url = "https://www.linkedin.com/posts/holliszhang_keyoung-hpmc-the-professional-choice-for-ugcPost-7463758057899147265-mOJK"
        entity = parse_post_url(url)
        self.assertEqual(entity.entity_type, "ugcPost")
        self.assertEqual(entity.entity_id, "7463758057899147265")
        self.assertEqual(entity.urn, "urn:li:ugcPost:7463758057899147265")

    def test_activity_post_url(self):
        url = "https://www.linkedin.com/posts/username_title-activity-7302346926123798528-dMnz"
        entity = parse_post_url(url)
        self.assertEqual(entity.entity_type, "activity")
        self.assertEqual(entity.entity_id, "7302346926123798528")
        self.assertEqual(entity.urn, "urn:li:activity:7302346926123798528")

    def test_feed_update_urn_url(self):
        url = "https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/"
        entity = parse_post_url(url)
        self.assertEqual(entity.entity_type, "activity")
        self.assertEqual(entity.entity_id, "7302346926123798528")

    def test_raw_urn(self):
        url = "urn:li:ugcPost:7463758057899147265"
        entity = parse_post_url(url)
        self.assertEqual(entity.entity_type, "ugcPost")
        self.assertEqual(entity.entity_id, "7463758057899147265")

    def test_raw_numeric_id(self):
        url = "7463758057899147265"
        entity = parse_post_url(url)
        self.assertEqual(entity.entity_id, "7463758057899147265")
        self.assertEqual(entity.entity_type, "activity")

    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            parse_post_url("https://www.google.com")


if __name__ == "__main__":
    unittest.main()
