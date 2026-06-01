#Startar appen
#→ laddar inställningar
#→ laddar Spotify-datasetet
#→ startar databaser/lagring
#→ startar K-means/rekommendationslogik
#→ skapar API-endpoints
#→ serverar frontend

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .dataset import DatasetCatalog
from .k_means_dataset import KMeansDataset
from .external_services import MusicApis
from .models import (
    CommunityCreateRequest,
    CommunityPostRequest,
    CommunityReplyRequest,
    FeedRequest,
    LoginRequest,
    PropertySearchRequest,
    RegisterRequest,
    SaveArtistRequest,
    SongCommentRequest,
    SuggestArtistRequest,
)
from .recommendations import RecommendationEngine
from .sqlite_store import SQLiteStore
from .storage import JsonStore


settings = get_settings()


class AppContainer:
    def __init__(self) -> None:
        self.dataset = DatasetCatalog(settings.spotify_csv_path)
        self.store = JsonStore(settings.user_state_path)
        self.sqlite_store = SQLiteStore(settings.sqlite_path)
        self.sqlite_store.migrate_custom_tracks(self.store.snapshot().get("custom_artists", []))
        # A deployed/restarted prototype should not inherit whoever was logged in on
        # the previous server run. Users must explicitly log in for each fresh startup.
        self.sqlite_store.logout_account()
        self.apis = MusicApis(settings)
        self.intelligence = KMeansDataset(settings, self.dataset.df)
        self.engine = RecommendationEngine(
            settings,
            self.dataset,
            self.apis,
            self.store,
            self.sqlite_store,
            self.intelligence,
        )

    def close(self) -> None:
        self.apis.close()
        self.sqlite_store.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = AppContainer()
    app.state.container = container
    yield
    container.close()


app = FastAPI(title="Small Web Smaller Artists App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(settings.frontend_dir)), name="static")


def get_engine() -> RecommendationEngine:
    return app.state.container.engine


def get_current_account() -> Dict[str, Any] | None:
    return app.state.container.sqlite_store.current_account()


def get_current_profile_name(fallback: str = "du") -> str:
    account = get_current_account()
    if not account:
        return fallback
    return str(account.get("display_name") or account.get("username") or fallback).strip() or fallback


def get_current_owner_fields() -> Dict[str, Any]:
    account = get_current_account()
    if not account:
        return {}
    profile_username = str(account.get("display_name") or account.get("username") or "").strip()
    return {
        "user_id": account.get("id"),
        "profile_username": profile_username,
    }


def session_payload() -> Dict[str, Any]:
    user = app.state.container.sqlite_store.safe_current_account()
    return {"authenticated": bool(user), "user": user}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        settings.frontend_dir / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/health")
def health() -> Dict[str, Any]:
    engine = get_engine()
    return {
        "status": "ok",
        "dataset": engine.bootstrap_payload()["stats"],
        "lastfm_configured": bool(settings.lastfm_api_key),
        "sqlite_path": str(settings.sqlite_path),
    }


@app.get("/api/bootstrap")
def bootstrap() -> Dict[str, Any]:
    return get_engine().bootstrap_payload()


@app.post("/api/property-search")
def property_search(payload: PropertySearchRequest) -> Dict[str, Any]:
    limit = max(1, min(payload.limit, 12))
    try:
        return get_engine().property_search(payload.targets, payload.genres, payload.label, limit=limit, mode=payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/feed")
def feed(payload: FeedRequest) -> Dict[str, Any]:
    return get_engine().feed_payload(payload.exclude_artist_keys)


@app.get("/api/communities")
def communities() -> Dict[str, Any]:
    return get_engine().communities_payload()


@app.post("/api/communities")
def create_community(payload: CommunityCreateRequest) -> Dict[str, Any]:
    account = get_current_account()
    if not account:
        raise HTTPException(status_code=401, detail="Logga in fÃ¶r att skapa ett musikrum.")
    try:
        community = get_engine().create_custom_community(
            name=payload.name,
            description=payload.description,
            tags=payload.tags,
            account=account,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"community": community}


@app.get("/api/session")
def session() -> Dict[str, Any]:
    return session_payload()


@app.post("/api/auth/register")
def register(payload: RegisterRequest) -> Dict[str, Any]:
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Lösenorden matchar inte.")
    try:
        app.state.container.sqlite_store.register_account(
            username=payload.username,
            password=payload.password,
            avatar_kind=payload.avatar_kind,
            avatar_value=payload.avatar_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session_payload()


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> Dict[str, Any]:
    try:
        app.state.container.sqlite_store.login_account(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return session_payload()


@app.post("/api/auth/logout")
def logout() -> Dict[str, Any]:
    app.state.container.sqlite_store.logout_account()
    return session_payload()


@app.get("/api/profile")
def profile() -> Dict[str, Any]:
    return get_engine().profile_payload(get_current_account())


@app.get("/api/profiles/{username}")
def public_profile(username: str) -> Dict[str, Any]:
    clean_username = username.strip()
    if not clean_username:
        raise HTTPException(status_code=400, detail="Profilnamn saknas.")

    account = app.state.container.sqlite_store.account_by_username(clean_username)
    payload = get_engine().public_profile_payload(clean_username, account)
    if payload is None:
        raise HTTPException(status_code=404, detail="Profilen hittades inte.")
    return payload


@app.get("/api/artists/{artist_key}")
def artist_detail(artist_key: str) -> Dict[str, Any]:
    try:
        return {"item": get_engine().artist_detail_payload(artist_key)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/songs/search")
def song_search(q: str = "", limit: int = 12) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 50))
    return get_engine().search_songs(q, safe_limit)


@app.get("/api/songs/{song_key}/comments")
def song_comments(
    song_key: str,
    track_key: str | None = None,
    track_id: str | None = None,
    isrc: str | None = None,
    artist_key: str | None = None,
    artist_name: str | None = None,
    track_title: str | None = None,
) -> Dict[str, Any]:
    if not song_key.strip():
        raise HTTPException(status_code=400, detail="Låtnyckel saknas.")
    comments = app.state.container.sqlite_store.list_song_comments(song_key.strip())
    community_discussions = get_engine().community_discussions_for_song(
        {
            "song_key": song_key.strip(),
            "track_key": track_key,
            "track_id": track_id,
            "isrc": isrc,
            "artist_key": artist_key,
            "artist": artist_name,
            "artist_name": artist_name,
            "track_title": track_title,
            "song": track_title,
            "title": track_title,
        }
    )
    return {"comments": comments, "community_discussions": community_discussions}


@app.post("/api/songs/{song_key}/comments")
def create_song_comment(song_key: str, payload: SongCommentRequest) -> Dict[str, Any]:
    if not song_key.strip():
        raise HTTPException(status_code=400, detail="Låtnyckel saknas.")
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Skriv en kommentar först.")

    comment = app.state.container.sqlite_store.add_song_comment(
        song_key.strip(),
        {
            "track_key": payload.track_key,
            "track_id": payload.track_id,
            "artist_key": payload.artist_key,
            "artist_name": payload.artist_name,
            "track_title": payload.track_title,
            "username": get_current_profile_name((payload.username or "du").strip() or "du"),
            **get_current_owner_fields(),
            "text": payload.text.strip(),
        },
    )
    return {"comment": comment}


@app.post("/api/save")
def save(payload: SaveArtistRequest) -> Dict[str, Any]:
    item = payload.model_dump()
    item.update(get_current_owner_fields())
    return get_engine().toggle_saved_artist(item)


@app.delete("/api/library/{artist_key}")
def delete_library_artist(artist_key: str) -> Dict[str, Any]:
    get_engine().remove_artist(artist_key, get_current_owner_fields())
    return {"removed": True, "artist_key": artist_key}


@app.post("/api/suggestions")
def add_suggestion(payload: SuggestArtistRequest) -> Dict[str, Any]:
    if not payload.confirm_smaller_artist:
        raise HTTPException(
            status_code=400,
            detail="Bekräfta att du vill lägga till artisten innan du skickar in.",
        )

    try:
        item = get_engine().add_custom_artist(
            payload.isrc,
            note=payload.note,
            community_slug=payload.community_slug.strip() if payload.community_slug else None,
            username=get_current_profile_name(),
            **get_current_owner_fields(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"saved": True, "item": item}


@app.post("/api/community")
def create_community_post(payload: CommunityPostRequest) -> Dict[str, Any]:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Skriv något innan du postar.")

    item = get_engine().add_community_post(
        text=payload.text.strip(),
        username=get_current_profile_name(payload.username.strip() or "du"),
        tip_artist=payload.tip_artist.strip() if payload.tip_artist else None,
        tip_song=payload.tip_song.strip() if payload.tip_song else None,
        community_slug=payload.community_slug.strip() if payload.community_slug else None,
        song_key=payload.song_key.strip() if payload.song_key else None,
        track_key=payload.track_key.strip() if payload.track_key else None,
        track_id=payload.track_id,
        isrc=payload.isrc.strip() if payload.isrc else None,
        **get_current_owner_fields(),
    )
    return {"item": item}


@app.post("/api/community/{post_id}/replies")
def create_community_reply(post_id: str, payload: CommunityReplyRequest) -> Dict[str, Any]:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Skriv en kommentar innan du svarar.")

    try:
        post = get_engine().add_community_reply(
            post_id=post_id,
            text=payload.text.strip(),
            username=get_current_profile_name(payload.username.strip() or "du"),
            **get_current_owner_fields(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"saved": True, "post": post}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    candidate = settings.frontend_dir / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(
        settings.frontend_dir / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )
