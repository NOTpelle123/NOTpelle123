from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PropertySearchRequest(BaseModel):
    targets: Dict[str, float] = Field(default_factory=dict)
    genres: List[str] = Field(default_factory=list)
    label: str = "Egen mix"
    limit: int = 6
    mode: str = "surprise"


class FeedRequest(BaseModel):
    exclude_artist_keys: List[str] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    username: str
    password: str
    confirm_password: str
    avatar_kind: str = "preset"
    avatar_value: str = "violet"


class LoginRequest(BaseModel):
    username: str
    password: str


class SaveArtistRequest(BaseModel):
    artist_key: str
    artist: str
    song_key: Optional[str] = None
    track_key: Optional[str] = None
    track_id: Optional[str] = None
    song: Optional[str] = None
    title: Optional[str] = None
    genre: Optional[str] = None
    image: Optional[str] = None
    preview: Optional[str] = None
    deezer_link: Optional[str] = None
    lastfm_link: Optional[str] = None
    reason: Optional[str] = None
    top_genres: List[str] = Field(default_factory=list)
    similar_artists: List[str] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    audio_signature: Dict[str, float] = Field(default_factory=dict)
    mood_profile: Dict[str, Any] = Field(default_factory=dict)
    estimated_mood_profile: Dict[str, Any] = Field(default_factory=dict)
    audio_validated: Optional[bool] = None
    mood_source: Optional[str] = None
    discovery_labels: List[str] = Field(default_factory=list)
    cluster_id: Optional[int] = None
    cluster_label: Optional[str] = None
    small_artist_score: Optional[float] = None
    source: str = "discover"
    is_custom: bool = False


class SuggestArtistRequest(BaseModel):
    isrc: str
    confirm_smaller_artist: bool = False
    note: str = ""
    community_slug: Optional[str] = None


class CommunityPostRequest(BaseModel):
    text: str
    username: str = "du"
    tip_artist: Optional[str] = None
    tip_song: Optional[str] = None
    community_slug: Optional[str] = None
    song_key: Optional[str] = None
    track_key: Optional[str] = None
    track_id: Optional[Any] = None
    isrc: Optional[str] = None


class CommunityCreateRequest(BaseModel):
    name: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)


class CommunityReplyRequest(BaseModel):
    text: str
    username: str = "du"


class SongCommentRequest(BaseModel):
    text: str
    username: Optional[str] = "du"
    track_key: Optional[str] = None
    track_id: Optional[Any] = None
    artist_key: Optional[str] = None
    artist_name: Optional[str] = None
    track_title: Optional[str] = None
