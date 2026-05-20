from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .config import Settings
from .dataset import normalize_key, normalize_track_title


def parse_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


class JsonTTLCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({})

    def get(self, section: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            payload = data.get(section, {}).get(key)
            if not payload:
                return None
            if payload.get("expires_at", 0) < time.time():
                return None
            return payload.get("value")

    def set(self, section: str, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        with self._lock:
            data = self._read()
            bucket = data.setdefault(section, {})
            bucket[key] = {
                "expires_at": int(time.time() + ttl_seconds),
                "value": value,
            }
            self._write(data)

    def _read(self) -> Dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: Dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)


class MusicApis:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.Client(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            follow_redirects=True,
        )
        self.cache = JsonTTLCache(settings.api_cache_path)

    def close(self) -> None:
        self.client.close()

    def get_lastfm_artist(self, artist_name: str) -> Dict[str, Any]:
        if not self.settings.lastfm_api_key:
            return {}

        cache_key = normalize_key(artist_name)
        cached = self.cache.get("lastfm_artist", cache_key)
        if cached is not None:
            return cached

        payload = self._get_json(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "artist.getinfo",
                "artist": artist_name,
                "api_key": self.settings.lastfm_api_key,
                "format": "json",
                "autocorrect": 1,
            },
        )

        if not payload or payload.get("error"):
            return {}

        artist = payload.get("artist", {})
        similar = artist.get("similar", {}).get("artist", [])
        result = {
            "name": artist.get("name") or artist_name,
            "listeners": parse_int(artist.get("stats", {}).get("listeners")),
            "playcount": parse_int(artist.get("stats", {}).get("playcount")),
            "bio": strip_html(artist.get("bio", {}).get("summary", "")),
            "url": artist.get("url"),
            "similar_artists": [item.get("name") for item in similar[:6] if item.get("name")],
        }
        self.cache.set("lastfm_artist", cache_key, result, ttl_seconds=60 * 60 * 24 * 7)
        return result

    def get_deezer_artist(self, artist_name: str) -> Dict[str, Any]:
        cache_key = normalize_key(artist_name)
        cached = self.cache.get("deezer_artist", cache_key)
        if cached is not None:
            return cached

        search = self._get_json(
            "https://api.deezer.com/search/artist",
            params={"q": artist_name, "limit": 5},
        )
        candidates = search.get("data", []) if search else []
        if not candidates:
            return {}

        best = self._pick_best_artist(artist_name, candidates)
        artist_id = best.get("id")
        if not artist_id:
            return {}

        details = self._get_json(f"https://api.deezer.com/artist/{artist_id}") or {}
        top_tracks_payload = self._get_json(
            f"https://api.deezer.com/artist/{artist_id}/top",
            params={"limit": 3},
        ) or {}
        top_tracks = top_tracks_payload.get("data", [])
        first_track = top_tracks[0] if top_tracks else {}

        result = {
            "artist_id": artist_id,
            "name": details.get("name") or best.get("name") or artist_name,
            "fans": parse_int(details.get("nb_fan") or best.get("nb_fan")),
            "image": details.get("picture_xl")
            or details.get("picture_big")
            or best.get("picture_xl")
            or best.get("picture_big")
            or best.get("picture_medium"),
            "link": details.get("link") or best.get("link"),
            "preview": first_track.get("preview"),
            "top_tracks": [
                {
                    "title": item.get("title"),
                    "preview": item.get("preview"),
                    "release_date": item.get("release_date"),
                }
                for item in top_tracks
            ],
            "release_date": first_track.get("release_date"),
        }
        self.cache.set("deezer_artist", cache_key, result, ttl_seconds=60 * 60 * 24 * 3)
        return result

    def get_deezer_album(self, album_id: int | str | None) -> Dict[str, Any]:
        if not album_id:
            return {}

        cache_key = str(album_id)
        cached = self.cache.get("deezer_album", cache_key)
        if cached is not None:
            return cached

        payload = self._get_json(f"https://api.deezer.com/album/{album_id}") or {}
        if not payload.get("id"):
            return {}

        genres = payload.get("genres", {}).get("data", []) or []
        result = {
            "album_id": payload.get("id"),
            "title": payload.get("title"),
            "genres": [item.get("name") for item in genres if item.get("name")],
            "label": payload.get("label"),
            "release_date": payload.get("release_date"),
            "cover": payload.get("cover_xl") or payload.get("cover_big") or payload.get("cover_medium"),
        }
        self.cache.set("deezer_album", cache_key, result, ttl_seconds=60 * 60 * 24 * 14)
        return result

    def get_deezer_track(self, track_id: int | str | None) -> Dict[str, Any]:
        if not track_id:
            return {}

        cache_key = str(track_id)
        cached = self.cache.get("deezer_track", cache_key)
        if cached is not None:
            return cached

        payload = self._get_json(f"https://api.deezer.com/track/{track_id}") or {}
        if not payload.get("id"):
            return {}

        result = {
            "track_id": payload.get("id"),
            "artist": payload.get("artist", {}).get("name"),
            "deezer_artist_id": payload.get("artist", {}).get("id"),
            "song": payload.get("title"),
            "album": payload.get("album", {}).get("title"),
            "album_id": payload.get("album", {}).get("id"),
            "image": payload.get("album", {}).get("cover_xl")
            or payload.get("album", {}).get("cover_big")
            or payload.get("album", {}).get("cover_medium"),
            "preview": payload.get("preview"),
            "deezer_link": payload.get("link"),
            "release_date": payload.get("release_date"),
            "isrc": payload.get("isrc"),
        }
        # Preview links are signed and expire, so keep this cache short.
        self.cache.set("deezer_track", cache_key, result, ttl_seconds=60 * 30)
        return result

    def get_spotify_track_image(self, track_id: int | str | None) -> Dict[str, Any]:
        spotify_id = str(track_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{22}", spotify_id):
            return {}

        cached = self.cache.get("spotify_track_image", spotify_id)
        if cached is not None:
            return cached

        payload = self._get_json(
            "https://open.spotify.com/oembed",
            params={"url": f"https://open.spotify.com/track/{spotify_id}"},
        ) or {}
        result = {"image": payload.get("thumbnail_url")} if payload.get("thumbnail_url") else {}
        self.cache.set("spotify_track_image", spotify_id, result, ttl_seconds=60 * 60 * 24 * 7)
        return result

    def search_deezer_track(self, artist_name: str | None, track_name: str | None) -> Dict[str, Any]:
        artist = str(artist_name or "").strip()
        track = str(track_name or "").strip()
        if not artist or not track:
            return {}

        cache_key = f"{normalize_key(artist)}::{normalize_track_title(track)}"
        cached = self.cache.get("deezer_track_search", cache_key)
        if cached is not None:
            return cached

        queries = [
            f'artist:"{artist}" track:"{track}"',
            f"{artist} {track}",
        ]
        for query in queries:
            payload = self._get_json(
                "https://api.deezer.com/search/track",
                params={"q": query, "limit": 8},
            ) or {}
            candidates = payload.get("data", []) or []
            best = self._pick_best_track(artist, track, candidates)
            if best:
                details = self.get_deezer_track(best.get("id")) if best.get("id") else {}
                result = details or self._track_search_result(best)
                self.cache.set("deezer_track_search", cache_key, result, ttl_seconds=60 * 60 * 3)
                return result

        self.cache.set("deezer_track_search", cache_key, {}, ttl_seconds=60 * 30)
        return {}

    def lookup_track_by_isrc(self, isrc: str) -> Dict[str, Any]:
        normalized = isrc.strip().upper()
        cached = self.cache.get("deezer_isrc", normalized)
        if cached is not None:
            return cached

        track_payload = self._get_json(f"https://api.deezer.com/track/isrc:{normalized}") or {}
        if not track_payload.get("id"):
            track_payload = self._search_track_by_isrc(normalized)

        if not track_payload.get("id"):
            return {}

        track_id = track_payload.get("id")
        details = self._get_json(f"https://api.deezer.com/track/{track_id}") or track_payload
        album_id = details.get("album", {}).get("id")
        album = self.get_deezer_album(album_id)
        album_genres = album.get("genres", [])
        fallback_genre = album_genres[0] if album_genres else ""

        result = {
            "track_id": details.get("id"),
            "track_key": details.get("id") or normalized,
            "artist": details.get("artist", {}).get("name"),
            "deezer_artist_id": details.get("artist", {}).get("id"),
            "song": details.get("title"),
            "album": details.get("album", {}).get("title"),
            "album_id": album_id,
            "image": details.get("album", {}).get("cover_xl")
            or details.get("album", {}).get("cover_big")
            or details.get("album", {}).get("cover_medium"),
            "preview": details.get("preview"),
            "deezer_link": details.get("link"),
            "release_date": details.get("release_date"),
            "isrc": details.get("isrc") or normalized,
            "genre": fallback_genre,
            "album_genres": album_genres,
            "album_label": album.get("label"),
        }
        # The metadata is stable, but preview URLs can expire, so use a shorter cache.
        self.cache.set("deezer_isrc", normalized, result, ttl_seconds=60 * 60 * 6)
        return result

    def _search_track_by_isrc(self, isrc: str) -> Dict[str, Any]:
        for query in (f'isrc:"{isrc}"', isrc):
            payload = self._get_json(
                "https://api.deezer.com/search/track",
                params={"q": query, "limit": 10},
            ) or {}
            for item in payload.get("data", []):
                if str(item.get("isrc", "")).upper() == isrc:
                    return item
        return {}

    def _track_search_result(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "track_id": item.get("id"),
            "artist": item.get("artist", {}).get("name"),
            "deezer_artist_id": item.get("artist", {}).get("id"),
            "song": item.get("title"),
            "album": item.get("album", {}).get("title"),
            "album_id": item.get("album", {}).get("id"),
            "image": item.get("album", {}).get("cover_xl")
            or item.get("album", {}).get("cover_big")
            or item.get("album", {}).get("cover_medium"),
            "preview": item.get("preview"),
            "deezer_link": item.get("link"),
            "release_date": item.get("release_date"),
            "isrc": item.get("isrc"),
        }

    def _pick_best_track(self, artist_name: str, track_name: str, candidates: list[dict[str, Any]]) -> Dict[str, Any]:
        track_key = normalize_track_title(track_name)
        artist_key = normalize_key(artist_name)
        if not track_key or not candidates:
            return {}

        exact_title = [
            item for item in candidates
            if normalize_track_title(item.get("title")) == track_key
        ]
        exact_artist = [
            item for item in exact_title
            if artist_key and artist_key in normalize_key(item.get("artist", {}).get("name"))
        ]
        if exact_artist:
            return exact_artist[0]
        if exact_title:
            return exact_title[0]

        compact_track = track_key.replace(" ", "")
        close_title = [
            item for item in candidates
            if compact_track and compact_track in normalize_track_title(item.get("title")).replace(" ", "")
        ]
        close_artist = [
            item for item in close_title
            if artist_key and artist_key in normalize_key(item.get("artist", {}).get("name"))
        ]
        if close_artist:
            return close_artist[0]
        if close_title:
            return close_title[0]
        return {}

    def _pick_best_artist(self, artist_name: str, candidates: list[dict[str, Any]]) -> Dict[str, Any]:
        needle = normalize_key(artist_name)
        exact = [item for item in candidates if normalize_key(item.get("name")) == needle]
        if exact:
            return exact[0]

        startswith = [
            item for item in candidates
            if normalize_key(item.get("name", "")).startswith(needle[:8])
        ]
        if startswith:
            return startswith[0]

        return candidates[0]

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}
