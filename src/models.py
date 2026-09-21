from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """User profile information."""
    name: str = Field(..., description="Full display name of the user")
    headline: Optional[str] = Field(default="", description="User headline or job title")
    profile_url: Optional[str] = Field(default="", description="Public LinkedIn profile URL")
    avatar_url: Optional[str] = Field(default="", description="Avatar image URL")
    public_identifier: Optional[str] = Field(default="", description="LinkedIn vanity identifier")


class CommentItem(BaseModel):
    """Comment on a post."""
    comment_id: str
    author: UserProfile
    text: str
    created_at_desc: Optional[str] = Field(default="", description="Relative or absolute date description")
    created_time_ms: Optional[int] = Field(default=None, description="Timestamp in milliseconds")
    likes_count: int = 0
    replies_count: int = 0
    is_reply: bool = False
    parent_comment_id: Optional[str] = None
    post_urn: str


class ReactionItem(BaseModel):
    """Reaction (like, praise, etc.) on a post."""
    reaction_type: str = Field(default="LIKE", description="LIKE, PRAISE, EMPATHY, LOVE, INTEREST, APPRECIATION")
    reactor: UserProfile
    created_time_ms: Optional[int] = None
    post_urn: str


class PostEntity(BaseModel):
    """Parsed LinkedIn post entity."""
    entity_type: str  # 'ugcPost' or 'activity'
    entity_id: str
    urn: str          # e.g., 'urn:li:ugcPost:7463758057899147265'
    activity_urn: Optional[str] = None  # Canonical activity URN if resolved from page
    original_url: str


class ExtractionResult(BaseModel):
    """Combined extraction results."""
    post: PostEntity
    total_comments: int = 0
    total_reactions: int = 0
    comments: List[CommentItem] = Field(default_factory=list)
    reactions: List[ReactionItem] = Field(default_factory=list)
