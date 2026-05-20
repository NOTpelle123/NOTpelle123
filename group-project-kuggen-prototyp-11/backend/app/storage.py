from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import re
import unicodedata


DEFAULT_POSTS = [
    {
        "id": "seed-1",
        "username": "musikalskare92",
        "text": "Lyssnade precis pa detta mastarverk!",
        "tip_artist": "Bon Iver",
        "tip_song": "Holocene",
        "created_at": "2026-04-28T09:17:00Z",
    },
    {
        "id": "seed-2",
        "username": "vibes_only",
        "text": "Har nagon fler tips i samma stil?",
        "tip_artist": "James Blake",
        "tip_song": "Retrograde",
        "created_at": "2026-04-28T07:58:00Z",
    },
    {
        "id": "seed-3",
        "username": "slow.days",
        "text": "Den har var perfekt under kvallens promenad.",
        "tip_artist": "Daughter",
        "tip_song": "Youth",
        "created_at": "2026-04-27T20:24:00Z",
    },
]

DEFAULT_STATE = {
    "saved_artists": [],
    "custom_artists": [],
    "community_posts": DEFAULT_POSTS,
    "custom_communities": [],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write_data(deepcopy(DEFAULT_STATE))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._read_data()

    def saved_artists_for_owner(self, owner: Dict[str, Any] | None, include_legacy: bool = False) -> List[Dict[str, Any]]:
        state = self.snapshot()
        return [
            item
            for item in state.get("saved_artists", [])
            if self._owner_matches(item, owner, include_legacy=include_legacy)
        ]

    def saved_artist_keys_for_owner(self, owner: Dict[str, Any] | None, include_legacy: bool = False) -> List[str]:
        return [
            item.get("artist_key", "")
            for item in self.saved_artists_for_owner(owner, include_legacy=include_legacy)
            if item.get("artist_key")
        ]

    def custom_artists_for_owner(self, owner: Dict[str, Any] | None, include_legacy: bool = False) -> List[Dict[str, Any]]:
        state = self.snapshot()
        return [
            item
            for item in state.get("custom_artists", [])
            if self._owner_matches(item, owner, include_legacy=include_legacy)
        ]

    def custom_communities(self) -> List[Dict[str, Any]]:
        state = self.snapshot()
        return [deepcopy(item) for item in state.get("custom_communities", [])]

    def upsert_saved_artist(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(item)
        payload["saved_at"] = payload.get("saved_at") or utc_now_iso()

        with self._lock:
            state = self._read_data()
            state["saved_artists"] = self._upsert_owned_item(state["saved_artists"], payload, "artist_key")
            self._write_data(state)

        return payload

    def remove_artist_everywhere(self, artist_key: str) -> None:
        with self._lock:
            state = self._read_data()
            state["saved_artists"] = [
                item for item in state["saved_artists"] if item.get("artist_key") != artist_key
            ]
            state["custom_artists"] = [
                item for item in state["custom_artists"] if item.get("artist_key") != artist_key
            ]
            state["community_posts"] = [
                item
                for item in state["community_posts"]
                if item.get("artist_key") != artist_key
            ]
            self._write_data(state)

    def remove_saved_artist(self, artist_key: str, owner: Dict[str, Any] | None = None, include_legacy: bool = False) -> None:
        with self._lock:
            state = self._read_data()
            if owner is None and not include_legacy:
                state["saved_artists"] = [
                    item for item in state["saved_artists"] if item.get("artist_key") != artist_key
                ]
            else:
                state["saved_artists"] = [
                    item
                    for item in state["saved_artists"]
                    if item.get("artist_key") != artist_key or not self._owner_matches(item, owner, include_legacy=include_legacy)
                ]
            self._write_data(state)

    def saved_artist_keys(self) -> List[str]:
        state = self.snapshot()
        return [item.get("artist_key", "") for item in state.get("saved_artists", []) if item.get("artist_key")]

    def add_custom_artist(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(item)
        payload["added_at"] = payload.get("added_at") or utc_now_iso()

        with self._lock:
            state = self._read_data()
            state["custom_artists"] = self._upsert_owned_item(state["custom_artists"], payload, "artist_key")
            self._write_data(state)

        return payload

    def add_custom_community(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(item)
        payload["created_at"] = payload.get("created_at") or utc_now_iso()

        with self._lock:
            state = self._read_data()
            state["custom_communities"] = [
                existing
                for existing in state.get("custom_communities", [])
                if existing.get("slug") != payload.get("slug")
            ]
            state["custom_communities"].append(payload)
            state["custom_communities"].sort(
                key=lambda entry: entry.get("created_at") or "",
                reverse=True,
            )
            self._write_data(state)

        return payload

    def remove_custom_artist(self, artist_key: str, owner: Dict[str, Any] | None = None, include_legacy: bool = False) -> None:
        with self._lock:
            state = self._read_data()
            if owner is None and not include_legacy:
                state["custom_artists"] = [
                    item for item in state["custom_artists"] if item.get("artist_key") != artist_key
                ]
            else:
                state["custom_artists"] = [
                    item
                    for item in state["custom_artists"]
                    if item.get("artist_key") != artist_key or not self._owner_matches(item, owner, include_legacy=include_legacy)
                ]
            self._write_data(state)

    def add_community_post(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(item)
        payload["created_at"] = payload.get("created_at") or utc_now_iso()
        payload["id"] = payload.get("id") or f"post-{payload['created_at']}-{payload.get('username', 'anon')}"
        payload["replies"] = payload.get("replies") or []

        with self._lock:
            state = self._read_data()
            state["community_posts"] = [payload, *state["community_posts"]]
            self._write_data(state)

        return payload

    def add_community_reply(self, post_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(item)
        payload["created_at"] = payload.get("created_at") or utc_now_iso()
        payload["id"] = payload.get("id") or f"reply-{payload['created_at']}-{payload.get('username', 'anon')}"

        with self._lock:
            state = self._read_data()
            updated_post: Dict[str, Any] | None = None
            posts: List[Dict[str, Any]] = []
            for post in state["community_posts"]:
                if post.get("id") == post_id:
                    post = deepcopy(post)
                    if not isinstance(post.get("replies"), list):
                        post["replies"] = []
                    post["replies"].append(payload)
                    updated_post = post
                posts.append(post)

            if updated_post is None:
                raise ValueError("Community-posten hittades inte.")

            state["community_posts"] = posts
            self._write_data(state)

        return updated_post

    def _upsert_item(self, items: List[Dict[str, Any]], payload: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
        updated = [payload]
        for item in items:
            if item.get(key) != payload.get(key):
                updated.append(item)

        updated.sort(
            key=lambda item: item.get("saved_at") or item.get("added_at") or item.get("created_at") or "",
            reverse=True,
        )
        return updated

    def _upsert_owned_item(self, items: List[Dict[str, Any]], payload: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
        payload_owner = self._owner_token(payload)
        updated = [payload]
        for item in items:
            if item.get(key) == payload.get(key) and self._owner_token(item) == payload_owner:
                continue
            updated.append(item)

        updated.sort(
            key=lambda item: item.get("saved_at") or item.get("added_at") or item.get("created_at") or "",
            reverse=True,
        )
        return updated

    def _owner_matches(self, item: Dict[str, Any], owner: Dict[str, Any] | None, include_legacy: bool = False) -> bool:
        if owner:
            owner_id = owner.get("user_id") or owner.get("id")
            if owner_id is not None and item.get("user_id") is not None and str(item.get("user_id")) == str(owner_id):
                return True

            owner_names = {
                self._normalize_owner_name(owner.get("profile_username")),
                self._normalize_owner_name(owner.get("username")),
                self._normalize_owner_name(owner.get("display_name")),
            }
            owner_names.discard("")
            item_name = self._normalize_owner_name(item.get("profile_username"))
            if item_name and item_name in owner_names:
                return True

        return include_legacy and self._owner_token(item) == "legacy"

    def _owner_token(self, item: Dict[str, Any]) -> str:
        if item.get("user_id") is not None:
            return f"user:{item.get('user_id')}"
        profile_name = self._normalize_owner_name(item.get("profile_username"))
        if profile_name:
            return f"name:{profile_name}"
        return "legacy"

    @staticmethod
    def _normalize_owner_name(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"\s+", " ", text)
        return text

    def _read_data(self) -> Dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            data = deepcopy(DEFAULT_STATE)

        for key, default in DEFAULT_STATE.items():
            data.setdefault(key, deepcopy(default))
        for post in data.get("community_posts", []):
            if not isinstance(post.get("replies"), list):
                post["replies"] = []
        return data

    def _write_data(self, data: Dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
