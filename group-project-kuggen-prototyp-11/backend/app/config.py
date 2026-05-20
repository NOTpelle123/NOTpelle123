from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional before dependencies are installed
    def load_dotenv() -> bool:
        return False


load_dotenv()


@dataclass(slots=True)
class Settings:
    base_dir: Path
    frontend_dir: Path
    data_dir: Path
    spotify_csv_path: Path
    user_state_path: Path
    api_cache_path: Path
    sqlite_path: Path
    lastfm_api_key: str
    request_timeout_seconds: float
    result_limit: int
    max_local_popularity: float
    max_lastfm_listeners: int
    max_deezer_fans: int
    nlp_max_features: int
    cluster_count: int
    cluster_sample_size: int
    recent_artist_window: int
    recent_track_window: int


def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parents[2]
    data_dir = base_dir / "data"

    return Settings(
        base_dir=base_dir,
        frontend_dir=base_dir / "frontend",
        data_dir=data_dir,
        spotify_csv_path=data_dir / "cleaned_dataset6.csv",
        user_state_path=data_dir / "user_state.json",
        api_cache_path=data_dir / "api_cache.json",
        sqlite_path=data_dir / "prototype2.sqlite3",
        lastfm_api_key=os.getenv("LASTFM_API_KEY", "").strip(),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "12")),
        result_limit=int(os.getenv("RESULT_LIMIT", "6")),
        max_local_popularity=float(os.getenv("MAX_LOCAL_POPULARITY", "45")),
        max_lastfm_listeners=int(os.getenv("MAX_LASTFM_LISTENERS", "50000")),
        max_deezer_fans=int(os.getenv("MAX_DEEZER_FANS", "50000")),
        nlp_max_features=int(os.getenv("NLP_MAX_FEATURES", "96")),
        cluster_count=int(os.getenv("CLUSTER_COUNT", "5")),
        cluster_sample_size=int(os.getenv("CLUSTER_SAMPLE_SIZE", "5000")),
        recent_artist_window=int(os.getenv("RECENT_ARTIST_WINDOW", "12")),
        recent_track_window=int(os.getenv("RECENT_TRACK_WINDOW", "18")),
    )
