from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .dataset import normalize_genre, normalize_genre_list

PASSWORD_ITERATIONS = 220_000
PASSWORD_ALGORITHM = "pbkdf2_sha256"
AVATAR_PRESETS = {"violet", "magenta", "blue", "green", "amber"}


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _utc_now_sql() -> str:
    return "CURRENT_TIMESTAMP"


def normalize_username(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text)
    return text


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def migrate_custom_tracks(self, items: Sequence[Dict[str, Any]]) -> None:
        for item in items:
            if item.get("isrc") or item.get("artist_key"):
                self.upsert_custom_track(item)

    def upsert_custom_track(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(item)
        payload.setdefault("track_key", payload.get("isrc") or payload.get("artist_key"))
        payload.setdefault("genre", "")
        payload.setdefault("top_genres", payload.get("top_genres") or [])
        payload.setdefault("similar_artists", payload.get("similar_artists") or [])
        payload.setdefault("metrics", payload.get("metrics") or {})
        payload.setdefault("audio_signature", payload.get("audio_signature") or {})
        payload.setdefault("discovery_labels", payload.get("discovery_labels") or [])
        payload.setdefault("mood_profile", payload.get("mood_profile") or {})
        payload.setdefault("estimated_mood_profile", payload.get("estimated_mood_profile") or {})
        payload.setdefault("tags", payload.get("tags") or [])
        payload.setdefault("cluster_id", -1)
        payload.setdefault("cluster_label", "")
        payload.setdefault("small_artist_score", 0.0)
        payload.setdefault("source_weight", 1.0)
        audio_validated = bool(payload.get("audio_validated", payload["metrics"].get("audio_features_validated")))
        stored_mood_profile = payload.get("mood_profile", {}) if audio_validated else {}

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO custom_tracks (
                    isrc, track_key, deezer_track_id, deezer_artist_id, album_id,
                    artist_key, track_name, artist_name, album_name, genre,
                    top_genres_json, similar_artists_json, metrics_json,
                    audio_signature_json, mood_profile_json, tags_json,
                    discovery_labels_json, cluster_id, cluster_label,
                    small_artist_score, source_weight, image, preview,
                    deezer_link, lastfm_link, note, user_id, profile_username,
                    added_at, updated_at
                ) VALUES (
                    :isrc, :track_key, :deezer_track_id, :deezer_artist_id, :album_id,
                    :artist_key, :song, :artist, :album, :genre,
                    :top_genres_json, :similar_artists_json, :metrics_json,
                    :audio_signature_json, :mood_profile_json, :tags_json,
                    :discovery_labels_json, :cluster_id, :cluster_label,
                    :small_artist_score, :source_weight, :image, :preview,
                    :deezer_link, :lastfm_link, :note, :user_id, :profile_username,
                    :added_at, :updated_at
                )
                ON CONFLICT(isrc) DO UPDATE SET
                    track_key=excluded.track_key,
                    deezer_track_id=excluded.deezer_track_id,
                    deezer_artist_id=excluded.deezer_artist_id,
                    album_id=excluded.album_id,
                    artist_key=excluded.artist_key,
                    track_name=excluded.track_name,
                    artist_name=excluded.artist_name,
                    album_name=excluded.album_name,
                    genre=excluded.genre,
                    top_genres_json=excluded.top_genres_json,
                    similar_artists_json=excluded.similar_artists_json,
                    metrics_json=excluded.metrics_json,
                    audio_signature_json=excluded.audio_signature_json,
                    mood_profile_json=excluded.mood_profile_json,
                    tags_json=excluded.tags_json,
                    discovery_labels_json=excluded.discovery_labels_json,
                    cluster_id=excluded.cluster_id,
                    cluster_label=excluded.cluster_label,
                    small_artist_score=excluded.small_artist_score,
                    source_weight=excluded.source_weight,
                    image=excluded.image,
                    preview=excluded.preview,
                    deezer_link=excluded.deezer_link,
                    lastfm_link=excluded.lastfm_link,
                    note=excluded.note,
                    user_id=excluded.user_id,
                    profile_username=excluded.profile_username,
                    updated_at=excluded.updated_at
                """,
                {
                    "isrc": payload.get("isrc"),
                    "track_key": payload.get("track_key"),
                    "deezer_track_id": payload.get("track_id"),
                    "deezer_artist_id": payload.get("deezer_artist_id"),
                    "album_id": payload.get("album_id"),
                    "artist_key": payload.get("artist_key"),
                    "song": payload.get("song"),
                    "artist": payload.get("artist"),
                    "album": payload.get("album"),
                    "genre": payload.get("genre", ""),
                    "top_genres_json": _json_dumps(payload.get("top_genres", [])),
                    "similar_artists_json": _json_dumps(payload.get("similar_artists", [])),
                    "metrics_json": _json_dumps(payload.get("metrics", {})),
                    "audio_signature_json": _json_dumps(payload.get("audio_signature", {})),
                    "mood_profile_json": _json_dumps(stored_mood_profile),
                    "tags_json": _json_dumps(payload.get("tags", [])),
                    "discovery_labels_json": _json_dumps(payload.get("discovery_labels", [])),
                    "cluster_id": payload.get("cluster_id", -1),
                    "cluster_label": payload.get("cluster_label", ""),
                    "small_artist_score": float(payload.get("small_artist_score", 0.0) or 0.0),
                    "source_weight": float(payload.get("source_weight", 1.0) or 1.0),
                    "image": payload.get("image"),
                    "preview": payload.get("preview"),
                    "deezer_link": payload.get("deezer_link"),
                    "lastfm_link": payload.get("lastfm_link"),
                    "note": payload.get("note", ""),
                    "user_id": payload.get("user_id"),
                    "profile_username": payload.get("profile_username"),
                    "added_at": payload.get("added_at"),
                    "updated_at": payload.get("updated_at") or payload.get("added_at"),
                },
            )
            self.conn.commit()

        return payload

    def list_custom_tracks(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT *
                FROM custom_tracks
                ORDER BY COALESCE(added_at, updated_at) DESC
                """
            ).fetchall()
        return [self._row_to_custom_track(row) for row in rows]

    def list_custom_tracks_for_owner(self, owner: Dict[str, Any] | None, include_legacy: bool = False) -> List[Dict[str, Any]]:
        return [
            item
            for item in self.list_custom_tracks()
            if self._owner_matches(item, owner, include_legacy=include_legacy)
        ]

    def delete_custom_track(
        self,
        artist_key: str,
        owner: Dict[str, Any] | None = None,
        include_legacy: bool = False,
    ) -> None:
        with self._lock:
            if owner is None and not include_legacy:
                self.conn.execute("DELETE FROM custom_tracks WHERE artist_key = ?", (artist_key,))
            else:
                rows = self.conn.execute(
                    "SELECT id, user_id, profile_username FROM custom_tracks WHERE artist_key = ?",
                    (artist_key,),
                ).fetchall()
                ids = [
                    row["id"]
                    for row in rows
                    if self._owner_matches(dict(row), owner, include_legacy=include_legacy)
                ]
                if ids:
                    placeholders = ", ".join("?" for _ in ids)
                    self.conn.execute(f"DELETE FROM custom_tracks WHERE id IN ({placeholders})", ids)
            self.conn.commit()

    def record_feed_event(self, context: str, item: Dict[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO feed_history (
                    context, artist_key, track_key, cluster_id, source, shown_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    context,
                    item.get("artist_key"),
                    item.get("track_key") or item.get("track_id") or item.get("song"),
                    item.get("cluster_id"),
                    item.get("source"),
                ),
            )
            self.conn.commit()

    def recent_feed_events(self, limit: int = 40, context: str | None = None) -> List[Dict[str, Any]]:
        query = """
            SELECT context, artist_key, track_key, cluster_id, source, shown_at
            FROM feed_history
            {where}
            ORDER BY id DESC
            LIMIT ?
        """
        params: list[Any] = [limit]
        where = ""
        if context:
            where = "WHERE context = ?"
            params = [context, limit]

        with self._lock:
            rows = self.conn.execute(query.format(where=where), params).fetchall()
        return [dict(row) for row in rows]

    def custom_track_artist_keys(self) -> List[str]:
        with self._lock:
            rows = self.conn.execute("SELECT artist_key FROM custom_tracks").fetchall()
        return [str(row["artist_key"]) for row in rows if row["artist_key"]]

    def current_account(self) -> Dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT accounts.*
                FROM app_session
                JOIN accounts ON accounts.id = app_session.current_account_id
                WHERE app_session.id = 1
                """
            ).fetchone()
        return self._row_to_account(row) if row else None

    def register_account(
        self,
        username: str,
        password: str,
        avatar_kind: str = "preset",
        avatar_value: str = "violet",
    ) -> Dict[str, Any]:
        username = self._validate_username(username)
        normalized = normalize_username(username)
        password_hash = self._hash_password(self._validate_password(password))
        avatar_kind, avatar_value = self._validate_avatar(avatar_kind, avatar_value)

        with self._lock:
            existing = self.conn.execute(
                "SELECT id FROM accounts WHERE username_normalized = ?",
                (normalized,),
            ).fetchone()
            if existing:
                raise ValueError("Profilnamnet är redan upptaget.")

            legacy_aliases: List[str] = []
            cursor = self.conn.execute(
                """
                INSERT INTO accounts (
                    username, username_normalized, display_name, password_hash,
                    avatar_kind, avatar_value, library_public, legacy_aliases_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    normalized,
                    username,
                    password_hash,
                    avatar_kind,
                    avatar_value,
                    1,
                    _json_dumps(legacy_aliases),
                ),
            )
            account_id = cursor.lastrowid
            self._set_current_account_locked(account_id)
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()

        return self.safe_account(row)

    def login_account(self, username: str, password: str) -> Dict[str, Any]:
        normalized = normalize_username(username)
        if not normalized or not password:
            raise ValueError("Ange profilnamn och lösenord.")

        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE username_normalized = ?",
                (normalized,),
            ).fetchone()
            if not row or not self._verify_password(password, row["password_hash"]):
                raise ValueError("Fel profilnamn eller lösenord.")
            self._set_current_account_locked(row["id"])
            self.conn.commit()

        return self.safe_account(row)

    def logout_account(self) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO app_session (id, current_account_id, updated_at)
                VALUES (1, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    current_account_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
            self.conn.commit()

    def safe_current_account(self) -> Dict[str, Any] | None:
        account = self.current_account()
        return self.safe_account(account) if account else None

    def account_by_username(self, username: str) -> Dict[str, Any] | None:
        normalized = normalize_username(username)
        if not normalized:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE username_normalized = ?",
                (normalized,),
            ).fetchone()
        return self.safe_account(row) if row else None

    def safe_account(self, account: sqlite3.Row | Dict[str, Any] | None) -> Dict[str, Any] | None:
        payload = self._row_to_account(account)
        if not payload:
            return None
        return {
            "id": payload.get("id"),
            "username": payload.get("username"),
            "display_name": payload.get("display_name") or payload.get("username"),
            "avatar_kind": payload.get("avatar_kind") or "preset",
            "avatar_value": payload.get("avatar_value") or "violet",
            "library_public": bool(payload.get("library_public", True)),
            "legacy_aliases": payload.get("legacy_aliases", []),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }

    def username_aliases_for_account(self, account: Dict[str, Any] | None) -> List[str]:
        if not account:
            return ["du", "Anonym"]
        aliases = [
            account.get("username"),
            account.get("display_name"),
            *(account.get("legacy_aliases") or []),
        ]
        cleaned: List[str] = []
        seen: set[str] = set()
        for alias in aliases:
            text = str(alias or "").strip()
            key = normalize_username(text)
            if text and key and key not in seen:
                cleaned.append(text)
                seen.add(key)
        return cleaned

    def _owner_matches(self, item: Dict[str, Any], owner: Dict[str, Any] | None, include_legacy: bool = False) -> bool:
        if owner:
            owner_id = owner.get("user_id") or owner.get("id")
            if owner_id is not None and item.get("user_id") is not None and str(item.get("user_id")) == str(owner_id):
                return True

            owner_names = {
                normalize_username(owner.get("profile_username")),
                normalize_username(owner.get("username")),
                normalize_username(owner.get("display_name")),
            }
            owner_names.discard("")
            item_name = normalize_username(item.get("profile_username"))
            if item_name and item_name in owner_names:
                return True

        return include_legacy and self._owner_token(item) == "legacy"

    def _comment_owner_matches(
        self,
        item: Dict[str, Any],
        owner: Dict[str, Any] | None,
        username_aliases: Sequence[str] = (),
        include_legacy: bool = False,
    ) -> bool:
        if self._owner_matches(item, owner, include_legacy=False):
            return True
        if not include_legacy or self._owner_token(item) != "legacy":
            return False
        alias_keys = {normalize_username(alias) for alias in username_aliases if normalize_username(alias)}
        return normalize_username(item.get("username")) in alias_keys

    def _owner_token(self, item: Dict[str, Any]) -> str:
        if item.get("user_id") is not None:
            return f"user:{item.get('user_id')}"
        profile_name = normalize_username(item.get("profile_username"))
        if profile_name:
            return f"name:{profile_name}"
        return "legacy"

    def _set_current_account_locked(self, account_id: Any) -> None:
        self.conn.execute(
            """
            INSERT INTO app_session (id, current_account_id, updated_at)
            VALUES (1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                current_account_id = excluded.current_account_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (account_id,),
        )

    def _row_to_account(self, row: sqlite3.Row | Dict[str, Any] | None) -> Dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        payload["legacy_aliases"] = _json_loads(payload.get("legacy_aliases_json"), [])
        return payload

    def _validate_username(self, value: Any) -> str:
        username = str(value or "").strip()
        if not 3 <= len(username) <= 24:
            raise ValueError("Profilnamn måste vara 3-24 tecken.")
        if not re.fullmatch(r"[A-Za-z0-9ÅÄÖåäö._ -]+", username):
            raise ValueError("Profilnamn får bara innehålla bokstäver, siffror, punkt, bindestreck och mellanslag.")
        if normalize_username(username) in {"du", "anonym"}:
            raise ValueError("Välj ett mer personligt profilnamn.")
        return username

    def _validate_password(self, value: Any) -> str:
        password = str(value or "")
        if len(password) < 8:
            raise ValueError("Lösenordet måste vara minst 8 tecken.")
        if len(password) > 256:
            raise ValueError("Lösenordet är för långt.")
        return password

    def _validate_avatar(self, avatar_kind: Any, avatar_value: Any) -> tuple[str, str]:
        kind = str(avatar_kind or "preset").strip().lower()
        value = str(avatar_value or "violet").strip()
        if kind != "preset":
            raise ValueError("Endast avatar-presets stöds i den här prototypen.")
        if value not in AVATAR_PRESETS:
            raise ValueError("Välj en giltig avatar.")
        return kind, value

    def _hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"

    def _verify_password(self, password: str, stored_hash: str | None) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = str(stored_hash or "").split("$", 3)
            if algorithm != PASSWORD_ALGORITHM:
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    def list_song_comments(self, song_key: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, song_key, track_key, track_id, artist_key, artist_name,
                       track_title, username, user_id, profile_username, text, created_at
                FROM song_comments
                WHERE song_key = ?
                ORDER BY id ASC
                """,
                (song_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_song_comments_by_username(self, username: str) -> List[Dict[str, Any]]:
        normalized = str(username or "").strip().lower()
        if not normalized:
            return []

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, song_key, track_key, track_id, artist_key, artist_name,
                       track_title, username, user_id, profile_username, text, created_at
                FROM song_comments
                WHERE lower(trim(username)) = ?
                ORDER BY id DESC
                """,
                (normalized,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_song_comments_for_owner(
        self,
        owner: Dict[str, Any] | None,
        username_aliases: Sequence[str] = (),
        include_legacy: bool = False,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, song_key, track_key, track_id, artist_key, artist_name,
                       track_title, username, user_id, profile_username, text, created_at
                FROM song_comments
                ORDER BY id DESC
                """
            ).fetchall()
        return [
            dict(row)
            for row in rows
            if self._comment_owner_matches(dict(row), owner, username_aliases, include_legacy=include_legacy)
        ]

    def list_song_comments_for_song_keys(self, song_keys: Sequence[Any]) -> List[Dict[str, Any]]:
        keys: List[str] = []
        seen: set[str] = set()
        for value in song_keys:
            text = str(value or "").strip()
            if text and text.lower() not in {"nan", "none", "null", "undefined"} and text not in seen:
                keys.append(text)
                seen.add(text)

        if not keys:
            return []

        placeholders = ", ".join("?" for _ in keys)
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT id, song_key, track_key, track_id, artist_key, artist_name,
                       track_title, username, user_id, profile_username, text, created_at
                FROM song_comments
                WHERE song_key IN ({placeholders})
                   OR track_key IN ({placeholders})
                   OR track_id IN ({placeholders})
                ORDER BY id DESC
                """,
                [*keys, *keys, *keys],
            ).fetchall()
        return [dict(row) for row in rows]

    def list_song_comments_for_song_keys_by_owner(
        self,
        song_keys: Sequence[Any],
        owner: Dict[str, Any] | None,
        username_aliases: Sequence[str] = (),
        include_legacy: bool = False,
    ) -> List[Dict[str, Any]]:
        return [
            comment
            for comment in self.list_song_comments_for_song_keys(song_keys)
            if self._comment_owner_matches(comment, owner, username_aliases, include_legacy=include_legacy)
        ]

    def add_song_comment(self, song_key: str, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(item)
        payload["song_key"] = song_key
        payload["username"] = payload.get("username") or "Anonym"

        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT INTO song_comments (
                    song_key, track_key, track_id, artist_key, artist_name,
                    track_title, username, user_id, profile_username, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("song_key"),
                    payload.get("track_key"),
                    payload.get("track_id"),
                    payload.get("artist_key"),
                    payload.get("artist_name"),
                    payload.get("track_title"),
                    payload.get("username"),
                    payload.get("user_id"),
                    payload.get("profile_username"),
                    payload.get("text"),
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                """
                SELECT id, song_key, track_key, track_id, artist_key, artist_name,
                       track_title, username, user_id, profile_username, text, created_at
                FROM song_comments
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        return dict(row) if row else payload

    def _row_to_custom_track(self, row: sqlite3.Row) -> Dict[str, Any]:
        metrics = _json_loads(row["metrics_json"], {})
        audio_validated = bool(metrics.get("audio_features_validated"))
        audio_signature = _json_loads(row["audio_signature_json"], {})
        if not audio_validated:
            audio_signature = {}
        stored_mood_profile = _json_loads(row["mood_profile_json"], {})
        mood_profile = stored_mood_profile if audio_validated else {}
        estimated_mood_profile = {}
        mood_source = "dataset" if audio_validated else ""
        payload = {
            "isrc": row["isrc"],
            "song_key": row["track_key"],
            "track_key": row["track_key"],
            "track_id": row["deezer_track_id"],
            "deezer_artist_id": row["deezer_artist_id"],
            "album_id": row["album_id"],
            "artist_key": row["artist_key"],
            "song": row["track_name"],
            "title": row["track_name"],
            "artist": row["artist_name"],
            "album": row["album_name"],
            "genre": normalize_genre(row["genre"] or ""),
            "top_genres": normalize_genre_list(_json_loads(row["top_genres_json"], [])),
            "similar_artists": _json_loads(row["similar_artists_json"], []),
            "metrics": metrics,
            "audio_signature": audio_signature,
            "mood_profile": mood_profile,
            "estimated_mood_profile": estimated_mood_profile,
            "audio_validated": audio_validated,
            "mood_source": mood_source,
            "tags": _json_loads(row["tags_json"], []),
            "discovery_labels": _json_loads(row["discovery_labels_json"], []),
            "cluster_id": row["cluster_id"],
            "cluster_label": row["cluster_label"] or "",
            "small_artist_score": row["small_artist_score"] or 0.0,
            "source_weight": row["source_weight"] or 1.0,
            "image": row["image"],
            "preview": row["preview"],
            "deezer_link": row["deezer_link"],
            "lastfm_link": row["lastfm_link"],
            "note": row["note"] or "",
            "user_id": row["user_id"],
            "profile_username": row["profile_username"],
            "added_at": row["added_at"],
            "updated_at": row["updated_at"],
            "source": "custom",
            "is_custom": True,
        }
        if "spotify_popularity" not in metrics and row["small_artist_score"] is not None:
            metrics["custom_small_artist_score"] = row["small_artist_score"]
        return payload

    def _create_schema(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    username_normalized TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    avatar_kind TEXT DEFAULT 'preset',
                    avatar_value TEXT DEFAULT 'violet',
                    library_public INTEGER DEFAULT 1,
                    legacy_aliases_json TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_accounts_username
                    ON accounts (username_normalized);

                CREATE TABLE IF NOT EXISTS app_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_account_id INTEGER,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(current_account_id) REFERENCES accounts(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS custom_tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    isrc TEXT UNIQUE,
                    track_key TEXT,
                    deezer_track_id INTEGER,
                    deezer_artist_id INTEGER,
                    album_id INTEGER,
                    artist_key TEXT NOT NULL,
                    track_name TEXT,
                    artist_name TEXT,
                    album_name TEXT,
                    genre TEXT,
                    top_genres_json TEXT,
                    similar_artists_json TEXT,
                    metrics_json TEXT,
                    audio_signature_json TEXT,
                    mood_profile_json TEXT,
                    tags_json TEXT,
                    discovery_labels_json TEXT,
                    cluster_id INTEGER DEFAULT -1,
                    cluster_label TEXT,
                    small_artist_score REAL DEFAULT 0,
                    source_weight REAL DEFAULT 1,
                    image TEXT,
                    preview TEXT,
                    deezer_link TEXT,
                    lastfm_link TEXT,
                    note TEXT,
                    user_id INTEGER,
                    profile_username TEXT,
                    added_at TEXT,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_custom_tracks_artist_key
                    ON custom_tracks (artist_key);

                CREATE INDEX IF NOT EXISTS idx_custom_tracks_genre
                    ON custom_tracks (genre);

                CREATE TABLE IF NOT EXISTS feed_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context TEXT,
                    artist_key TEXT,
                    track_key TEXT,
                    cluster_id INTEGER,
                    source TEXT,
                    shown_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_feed_history_context
                    ON feed_history (context, id DESC);

                CREATE TABLE IF NOT EXISTS song_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    song_key TEXT NOT NULL,
                    track_key TEXT,
                    track_id TEXT,
                    artist_key TEXT,
                    artist_name TEXT,
                    track_title TEXT,
                    username TEXT,
                    user_id INTEGER,
                    profile_username TEXT,
                    text TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_song_comments_song_key
                    ON song_comments (song_key, id ASC);
                """
            )
            self._ensure_column_locked("custom_tracks", "user_id", "INTEGER")
            self._ensure_column_locked("custom_tracks", "profile_username", "TEXT")
            self._ensure_column_locked("song_comments", "user_id", "INTEGER")
            self._ensure_column_locked("song_comments", "profile_username", "TEXT")
            self.conn.commit()

    def _ensure_column_locked(self, table: str, column: str, definition: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {row["name"] for row in rows}:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
