"""
Pydantic data models for LinkedIn Post Extractor.
"""

from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class CommentRecord(BaseModel):
    """Represents a single comment or reply on a LinkedIn post."""

    type: Literal["comment"] = "comment"
    comment_id: Optional[str] = None
    comment_type: Literal["comment", "reply"] = "comment"
    parent_comment_id: Optional[str] = None

    author_name: Optional[str] = None
    author_headline: Optional[str] = None
    author_profile_url: Optional[str] = None
    author_avatar: Optional[str] = None

    comment_text: Optional[str] = None
    comment_time_ms: Optional[int] = None       # Unix timestamp in milliseconds
    comment_time_str: Optional[str] = None      # Human-readable

    is_edited: bool = False
    is_pinned: bool = False
    total_reactions: int = 0
    total_replies: int = 0

    post_url: Optional[str] = None


class ReactionRecord(BaseModel):
    """Represents a single reaction (like, celebrate, etc.) on a LinkedIn post."""

    type: Literal["reaction"] = "reaction"
    reaction_type: Optional[str] = None         # LIKE, PRAISE, EMPATHY, APPRECIATION, INTEREST

    author_name: Optional[str] = None
    author_headline: Optional[str] = None
    author_profile_url: Optional[str] = None
    author_avatar: Optional[str] = None

    post_url: Optional[str] = None


class ExtractResult(BaseModel):
    """Full extraction result for one LinkedIn post."""

    post_url: str
    activity_id: Optional[str] = None
    extracted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    comments: List[CommentRecord] = []
    reactions: List[ReactionRecord] = []

    total_comments: int = 0
    total_reactions: int = 0
    errors: List[str] = []

    def finalize(self) -> None:
        self.total_comments = len(self.comments)
        self.total_reactions = len(self.reactions)


class ExtractRequest(BaseModel):
    """API request model."""

    url: str = Field(..., description="LinkedIn post URL or Activity ID")
    include_comments: bool = True
    include_reactions: bool = True
    scroll_count: int = Field(default=5, ge=1, le=30,
                              description="Number of scroll iterations to load more content")
