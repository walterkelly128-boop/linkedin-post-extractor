import unittest
import tempfile
import os
from pathlib import Path

from src.models import (
    PostEntity, UserProfile, CommentItem, ReactionItem, ExtractionResult
)
from src.exporter import export_to_json, export_to_csv, export_to_excel


class TestExporter(unittest.TestCase):
    def setUp(self):
        self.post = PostEntity(
            entity_type="ugcPost",
            entity_id="7463758057899147265",
            urn="urn:li:ugcPost:7463758057899147265",
            original_url="https://www.linkedin.com/posts/example",
        )
        self.user = UserProfile(
            name="Alice Smith",
            headline="Senior Data Engineer",
            profile_url="https://www.linkedin.com/in/alicesmith/",
            avatar_url="https://media.licdn.com/example.jpg",
            public_identifier="alicesmith",
        )
        self.comment = CommentItem(
            comment_id="comment_001",
            author=self.user,
            text="Very insightful post!",
            likes_count=5,
            replies_count=1,
            post_urn=self.post.urn,
        )
        self.reaction = ReactionItem(
            reaction_type="LIKE",
            reactor=self.user,
            post_urn=self.post.urn,
        )
        self.result = ExtractionResult(
            post=self.post,
            total_comments=1,
            total_reactions=1,
            comments=[self.comment],
            reactions=[self.reaction],
        )

    def test_export_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_path = Path(tf.name)
        try:
            out_file = export_to_json(self.result, filepath=temp_path)
            self.assertTrue(out_file.exists())
            self.assertGreater(os.path.getsize(out_file), 10)
        finally:
            if temp_path.exists():
                os.remove(temp_path)

    def test_export_excel(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            temp_path = Path(tf.name)
        try:
            out_file = export_to_excel(self.result, filepath=temp_path)
            self.assertTrue(out_file.exists())
            self.assertGreater(os.path.getsize(out_file), 10)
        finally:
            if temp_path.exists():
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
