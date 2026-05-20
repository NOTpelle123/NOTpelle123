from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd

from .config import Settings
from .dataset import (
    DISCOVER_GENRES,
    FEATURE_COLUMNS,
    DatasetCatalog,
    normalize_genre,
    normalize_genre_list,
    normalize_key,
    normalize_track_title,
)
from .k_means_dataset import KMeansDataset, normalize_text
from .external_services import MusicApis
from .sqlite_store import SQLiteStore
from .storage import JsonStore, utc_now_iso


LOCAL_PROFILE_USERNAME = "du"
LOCAL_PROFILE_USERNAME_LOOKUPS = (LOCAL_PROFILE_USERNAME, "Anonym")
LEGACY_PROFILE_NAMES = {"legacy", "legacy local", "local legacy", "__legacy_local__"}
RESERVED_COMMUNITY_SLUGS = {
    "api",
    "community",
    "communities",
    "create",
    "feed",
    "login",
    "new",
    "profile",
    "search",
}


@dataclass(slots=True)
class LibraryContext:
    seed_names: List[str]
    preferred_genres: List[str]
    similar_artist_keys: set[str]
    avg_vector: Dict[str, float]
    preferred_clusters: List[int]
    preferred_tags: List[str]


MICRO_COMMUNITIES = [
    {
        "slug": "late-night-discoveries",
        "name": "Late night discoveries",
        "description": "Songs people pass around after midnight.",
        "tone": "slow, nocturnal and intimate",
        "motto": "For songs that make sense after the rest of the city logs off.",
        "submission_prompt": "Share something that feels like headphones, rain, or a 02:00 message.",
        "belongs_here": "Soft, moody, after-hours finds and small artists with late-night energy.",
        "genres": ["ambient", "trip-hop", "indie", "acoustic", "jazz", "r-n-b"],
        "terms": ["night", "natt", "kvall", "rain", "regn", "late", "moody", "after-hours"],
    },
    {
        "slug": "swedish-underground",
        "name": "Swedish underground",
        "description": "Small Swedish scenes, local tips and quiet releases.",
        "tone": "local, scene-aware and quietly proud",
        "motto": "Small Swedish rooms, demos, blogs and scenes before they become obvious.",
        "submission_prompt": "Share a Swedish or local artist people should hear before the algorithm notices.",
        "belongs_here": "Swedish artists, local scenes, small city sounds and regional discoveries.",
        "genres": ["swedish", "indie", "indie-pop", "pop", "songwriter", "r-n-b"],
        "terms": ["swedish", "svensk", "gothenburg", "goteborg", "stockholm", "malmo"],
    },
    {
        "slug": "bedroom-pop",
        "name": "Bedroom pop",
        "description": "Soft, homemade and intimate discoveries.",
        "tone": "homemade, vulnerable and close to the room",
        "motto": "Tiny songs that still sound like they were made by a person, not a campaign.",
        "submission_prompt": "Share a soft, handmade or intimate track that feels found rather than promoted.",
        "belongs_here": "Bedroom pop, lo-fi, soft indie, acoustic sketches and intimate vocals.",
        "genres": ["bedroom-pop", "indie-pop", "indie", "lo-fi", "songwriter", "acoustic"],
        "terms": ["bedroom", "lofi", "lo-fi", "intimate", "home", "soft"],
    },
]


class RecommendationEngine:
    def __init__(
        self,
        settings: Settings,
        dataset: DatasetCatalog,
        apis: MusicApis,
        store: JsonStore,
        sqlite_store: SQLiteStore,
        intelligence: KMeansDataset,
    ) -> None:
        self.settings = settings
        self.dataset = dataset
        self.apis = apis
        self.store = store
        self.sqlite_store = sqlite_store
        self.intelligence = intelligence
        self.small_artist_filter_paused = False
        self.dataset_genre_values = sorted(self.dataset.df["track_genre"].dropna().astype(str).unique().tolist())
        self.artist_stats_map = self.dataset.artist_map
        self.artist_small_score_map = {
            artist_key: self._calculate_small_artist_score(
                local_stats=row.to_dict(),
                metrics={
                    "spotify_popularity": row.get("avg_popularity"),
                    "spotify_tracks": row.get("track_count"),
                },
                is_custom=False,
            )
            for artist_key, row in self.dataset.artist_frame.set_index("artist_key").iterrows()
        }
        self.dataset.df["local_small_artist_score"] = self.dataset.df["artist_key"].map(self.artist_small_score_map).fillna(0.28)

    # Public payloads used by API routes.
    def _small_artist_thresholds(self) -> Dict[str, Any]:
        return {
            "spotify_avg_popularity_max": float(min(self.settings.max_local_popularity, 50.0)),
            "lastfm_listeners_max": int(min(self.settings.max_lastfm_listeners, 50000)),
            "deezer_fans_max": int(min(self.settings.max_deezer_fans, 50000)),
        }

    def bootstrap_payload(self) -> Dict[str, Any]:
        summary = self.dataset.summary()
        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        all_genres = {item["label"]: dict(item) for item in self.dataset.all_genres()}
        for track in custom_tracks:
            for genre in normalize_genre_list([track.get("genre"), *(track.get("top_genres") or [])]):
                all_genres[genre] = {
                    "label": genre,
                    "count": int(all_genres.get(genre, {}).get("count", 0)) + 1,
                }
        return {
            "genres": self.dataset.discover_genres(),
            "all_genres": sorted(all_genres.values(), key=lambda item: item["label"]),
            "small_artist_definition": self.small_artist_definition(),
            "stats": {
                "spotify_rows": summary.spotify_rows,
                "artist_count": summary.artist_count,
                "genre_count": summary.genre_count,
                "saved_count": len(state.get("saved_artists", [])),
                "custom_count": len(custom_tracks),
                "cluster_count": self.settings.cluster_count,
            },
            "saved_artist_keys": self.store.saved_artist_keys(),
        }

    def small_artist_definition(self) -> Dict[str, Any]:
        thresholds = self._small_artist_thresholds()
        return {
            "title": "Hur Prototype 2 lyfter mindre artister",
            "text": (
                "Varje rekommendation far en small artist score. Plattformen filtrerar hart mot "
                "hog popularitet och prioriterar artister under tydliga lyssnar- och fanstak, med "
                "datasetet som bas och SQLite-tillskott som vaxande discovery-lager."
            ),
            "thresholds": thresholds,
        }

    def property_search(
        self,
        targets: Dict[str, float],
        genres: Sequence[str],
        label: str,
        limit: int,
        mode: str = "surprise",
    ) -> Dict[str, Any]:
        clean_targets = self._normalize_property_targets(targets)
        genre_values = normalize_genre_list([*genres, *self.dataset.map_genre_labels(genres)])
        if mode == "new_added":
            if not genre_values:
                raise ValueError("Välj minst en genre innan du genererar nya tillagda låtar.")
            custom_tracks = self.sqlite_store.list_custom_tracks()
            results = [
                self._with_song_identity(item)
                for item in custom_tracks
                if set(normalize_genre_list([item.get("genre"), *(item.get("top_genres") or [])])).intersection(genre_values)
            ][:limit]
            return {
                "view": "search",
                "query_label": label,
                "interpretation": {
                    "genres": genre_values,
                    "tokens": [],
                    "year_filter": None,
                    "top_prompt_clusters": [],
                    "targets": {},
                },
                "results": results,
                "saved_artist_keys": self.store.saved_artist_keys(),
            }

        if not clean_targets and not genre_values:
            raise ValueError("Välj minst en genre eller egenskap innan du genererar.")

        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        context = self._build_library_context(state, custom_tracks)

        property_terms = self._property_terms(clean_targets)
        request = {
            "genres": [],
            "explicit_genre_terms": genre_values,
            "primary_dataset_genres": genre_values[:3],
            "supporting_dataset_genres": genre_values[3:],
            "dataset_genres": genre_values,
            "query_text": " ".join([label, *genre_values, *property_terms]),
            "tokens": property_terms,
            "intent_terms": property_terms,
            "base_mood_targets": clean_targets,
            "mood_targets": clean_targets,
            "intensity_modifier": "custom",
            "intensity_matches": [],
            "intensity_strength": 1.0,
            "audio_emphasis": 1.0,
            "prompt_mode": "property" if clean_targets else "genre_only",
            "prompt_cluster_scores": {},
            "top_prompt_clusters": [],
            "year_filter": None,
            "source_label": "Matchad via din egenskapsmix" if clean_targets else "Genrebaserad random discovery",
            "underground_focus": True,
            "mode": "search",
            "disable_text_similarity": True,
        }

        candidate_frame = self._build_candidate_frame([], request, context, custom_tracks, mode="search")

        if clean_targets:
            candidate_frame, predicted_cluster = self.intelligence.rank_frame_by_selected_features(
                candidate_frame,
                clean_targets,
                limit,
            )
            if predicted_cluster is not None:
                cluster_label = self._cluster_label(predicted_cluster)
                request["prompt_cluster_scores"] = {predicted_cluster: 4.2}
                request["top_prompt_clusters"] = [
                    {
                        "cluster_id": predicted_cluster,
                        "score": 4.2,
                        "label": cluster_label,
                        "matches": property_terms[:6],
                    }
                ]

        ranked = self._score_candidate_frame(candidate_frame, request, context, mode="search")
        results = self._assemble_results(ranked, request, context, limit, context_name="property-search")
        self._record_impressions("search", results)
        return {
            "view": "search",
            "query_label": label,
            "interpretation": {
                "genres": genre_values,
                "tokens": request["tokens"][:6],
                "year_filter": None,
                "top_prompt_clusters": request.get("top_prompt_clusters", [])[:3],
                "targets": clean_targets,
            },
            "results": results,
            "saved_artist_keys": self.store.saved_artist_keys(),
        }

    def search_songs(self, query: str, limit: int = 12) -> Dict[str, Any]:
        clean_query = normalize_key(query)
        limit = max(1, min(int(limit or 12), 50))
        if not clean_query:
            return {"query": "", "results": []}

        tokens = [token for token in re.split(r"\s+", clean_query) if token]

        def clean_value(value: Any) -> Any:
            if value is None:
                return None
            try:
                if pd.isna(value):
                    return None
            except (TypeError, ValueError):
                pass
            return value.item() if hasattr(value, "item") else value

        def search_text_for_item(item: Dict[str, Any]) -> str:
            parts: List[str] = []
            for value in (
                item.get("song"),
                item.get("title"),
                item.get("track_name"),
                item.get("artist"),
                item.get("primary_artist"),
                item.get("album"),
                item.get("album_name"),
                item.get("genre"),
                item.get("track_genre"),
                item.get("isrc"),
                item.get("note"),
            ):
                if value:
                    parts.append(str(value))
            for value in item.get("tags") or []:
                if value:
                    parts.append(str(value))
            return " ".join(parts)

        def matches_query(value: str) -> bool:
            searchable_value = normalize_key(value)
            return bool(
                searchable_value
                and (
                    clean_query in searchable_value
                    or (tokens and all(token in searchable_value for token in tokens))
                )
            )

        def score_text(song: Any, artist: Any, album: Any, searchable_value: str) -> float:
            track_name = normalize_key(song)
            artist_name = normalize_key(artist)
            album_name = normalize_key(album)
            search_blob = normalize_key(searchable_value)
            score = 0.0
            score += 100.0 if track_name == clean_query else 0.0
            score += 60.0 if track_name.startswith(clean_query) else 0.0
            score += 40.0 if clean_query in track_name else 0.0
            score += 35.0 if artist_name == clean_query else 0.0
            score += 20.0 if clean_query in artist_name else 0.0
            score += 12.0 if clean_query in album_name else 0.0
            for token in tokens:
                score += 4.0 if token in track_name else 0.0
                score += 2.0 if token in artist_name else 0.0
                score += 1.0 if token in search_blob else 0.0
            return score

        candidates: List[Dict[str, Any]] = []
        frame = self.dataset.df.copy()
        searchable = frame["search_blob"].fillna("").map(normalize_key)
        exact_mask = searchable.str.contains(re.escape(clean_query), na=False)
        token_mask = searchable.map(lambda value: all(token in value for token in tokens)) if tokens else exact_mask
        matches = frame[exact_mask | token_mask].copy()
        if not matches.empty:
            track_names = matches["track_name"].fillna("").map(normalize_key)
            artist_names = matches["primary_artist"].fillna("").map(normalize_key)
            album_names = matches["album_name"].fillna("").map(normalize_key)
            scores = pd.Series(0.0, index=matches.index)
            scores += (track_names == clean_query).astype(float) * 100
            scores += track_names.str.startswith(clean_query, na=False).astype(float) * 60
            scores += track_names.str.contains(re.escape(clean_query), na=False).astype(float) * 40
            scores += (artist_names == clean_query).astype(float) * 35
            scores += artist_names.str.contains(re.escape(clean_query), na=False).astype(float) * 20
            scores += album_names.str.contains(re.escape(clean_query), na=False).astype(float) * 12
            for token in tokens:
                escaped = re.escape(token)
                scores += track_names.str.contains(escaped, na=False).astype(float) * 4
                scores += artist_names.str.contains(escaped, na=False).astype(float) * 2
                scores += searchable.loc[matches.index].str.contains(escaped, na=False).astype(float)

            matches["_song_search_score"] = scores
            popularity = pd.to_numeric(matches["popularity"], errors="coerce").fillna(0)
            matches["_song_search_popularity"] = popularity
            ranked = matches.sort_values(
                ["_song_search_score", "_song_search_popularity"],
                ascending=[False, False],
            ).drop_duplicates(subset=["track_key"]).head(max(limit * 4, 40))

            for _, row in ranked.iterrows():
                item = self._with_song_identity(
                    {
                        "song_key": clean_value(row.get("track_key")),
                        "track_key": clean_value(row.get("track_key")),
                        "track_id": clean_value(row.get("track_id")),
                        "song": clean_value(row.get("track_name")),
                        "title": clean_value(row.get("track_name")),
                        "artist": clean_value(row.get("primary_artist")),
                        "artist_key": clean_value(row.get("artist_key")),
                        "genre": clean_value(row.get("track_genre")),
                        "album": clean_value(row.get("album_name")),
                        "preview": clean_value(row.get("preview")),
                        "isrc": clean_value(row.get("isrc")),
                        "metrics": {"spotify_popularity": clean_value(row.get("popularity"))},
                        "audio_signature": self._row_audio_signature(row.to_dict()),
                        "discovery_labels": ["Dataset song match"],
                        "reason": "Matched directly from the local dataset.",
                        "source": "song-search",
                        "is_custom": False,
                    }
                )
                candidates.append(
                    {
                        "item": item,
                        "score": float(row.get("_song_search_score", 0.0) or 0.0),
                        "popularity": float(row.get("_song_search_popularity", 0.0) or 0.0),
                        "source_priority": 0,
                    }
                )

        for custom in self.sqlite_store.list_custom_tracks():
            search_text = search_text_for_item(custom)
            if not matches_query(search_text):
                continue
            item = self._with_song_identity(
                {
                    **custom,
                    "title": custom.get("title") or custom.get("song"),
                    "song": custom.get("song") or custom.get("title"),
                    "metrics": custom.get("metrics") or {},
                    "audio_signature": custom.get("audio_signature") or {},
                    "source": custom.get("source") or "custom",
                    "is_custom": True,
                }
            )
            candidates.append(
                {
                    "item": item,
                    "score": score_text(item.get("song"), item.get("artist"), item.get("album"), search_text),
                    "popularity": float((item.get("metrics") or {}).get("spotify_popularity") or 0.0),
                    "source_priority": 1,
                }
            )

        def identity_keys(item: Dict[str, Any]) -> List[str]:
            keys: List[str] = []
            for field in ("song_key", "track_key", "track_id", "isrc"):
                value = item.get(field)
                if value is not None and str(value).strip():
                    keys.append(f"{field}:{normalize_key(value)}")
            artist_key = normalize_key(item.get("artist") or item.get("primary_artist"))
            title_key = normalize_track_title(item.get("song") or item.get("title") or item.get("track_name"))
            if artist_key and title_key:
                keys.append(f"artist_song:{artist_key}:{title_key}")
            return keys

        deduped: List[Dict[str, Any]] = []
        seen: Dict[str, int] = {}
        for candidate in sorted(
            candidates,
            key=lambda entry: (-entry["score"], entry["source_priority"], -entry["popularity"]),
        ):
            keys = identity_keys(candidate["item"])
            existing_index = next((seen[key] for key in keys if key in seen), None)
            if existing_index is None:
                seen_index = len(deduped)
                deduped.append(candidate)
                for key in keys:
                    seen[key] = seen_index
                continue

            existing = deduped[existing_index]
            if candidate["source_priority"] < existing["source_priority"]:
                deduped[existing_index] = candidate
                for key in keys:
                    seen[key] = existing_index

        results = [
            self._with_track_media(candidate["item"])
            for candidate in sorted(
                deduped,
                key=lambda entry: (-entry["score"], entry["source_priority"], -entry["popularity"]),
            )[:limit]
        ]

        return {"query": clean_query, "results": results}

    def feed_payload(self, exclude_artist_keys: Sequence[str]) -> Dict[str, Any]:
        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        context = self._build_library_context(state, custom_tracks)
        request = {
            "genres": self._preferred_labels_from_genres(context.preferred_genres),
            "query_text": " ".join(context.seed_names + context.preferred_tags[:6]),
            "tokens": context.preferred_tags[:8],
            "mood_targets": context.avg_vector,
            "year_filter": None,
            "source_label": "Vald for ditt Small Web-flode",
            "mode": "feed",
            "underground_focus": True,
        }
        candidate_frame = self._build_candidate_frame(request["genres"], request, context, custom_tracks, mode="feed")
        if exclude_artist_keys:
            candidate_frame = candidate_frame[~candidate_frame["artist_key"].isin(set(exclude_artist_keys))].copy()
        ranked = self._score_candidate_frame(candidate_frame, request, context, mode="feed")
        results = self._assemble_results(ranked, request, context, limit=8, context_name="feed")
        card = results[0] if results else self._fallback_feed_card(state, custom_tracks, exclude_artist_keys)
        feed_extras = self._build_feed_extras(
            card=card,
            ranked_results=results[1:],
            state=state,
            custom_tracks=custom_tracks,
        )
        if card:
            enriched_posts = feed_extras["community_posts"]
            card["reason_chips"] = self._structured_reason_chips_for_item(card, enriched_posts)
            card["community_signals"] = self._community_signals_for_item(card, enriched_posts)
            card["discovery_trail"] = self._discovery_trail_for_item(card, enriched_posts)
        if card:
            self.sqlite_store.record_feed_event("feed", card)
        return {
            "card": card,
            "community_posts": feed_extras["community_posts"],
            "trending_quietly": feed_extras["trending_quietly"],
            "micro_communities": feed_extras["micro_communities"],
            "community_activity": feed_extras["community_activity"],
            "discovery_trail": feed_extras["discovery_trail"],
            "saved_artist_keys": self.store.saved_artist_keys(),
        }

    def communities_payload(self) -> Dict[str, Any]:
        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        artist_pool = self._feed_artist_pool({}, [], state, custom_tracks)
        community_posts = self._community_scoped_posts(state.get("community_posts", []))
        scoped_posts = self._enrich_community_posts(community_posts, artist_pool, state)
        return {"communities": self._derive_micro_communities(artist_pool, scoped_posts)}

    def create_custom_community(
        self,
        name: str,
        description: str,
        tags: Sequence[str] | None,
        account: Dict[str, Any],
    ) -> Dict[str, Any]:
        safe_account = self.sqlite_store.safe_account(account)
        if not safe_account:
            raise ValueError("Logga in fÃ¶r att skapa ett musikrum.")

        clean_name = self._validate_community_name(name)
        clean_description = self._validate_community_description(description)
        clean_tags = self._validate_community_tags(tags or [])
        slug = self._unique_community_slug(clean_name)
        payload = {
            "slug": slug,
            "name": clean_name,
            "description": clean_description or f"Ett Ã¶ppet musikrum fÃ¶r {clean_name}.",
            "created_by_user_id": safe_account.get("id"),
            "created_by_username": safe_account.get("display_name") or safe_account.get("username"),
            "created_at": utc_now_iso(),
            "visibility": "public",
            "source": "user",
            "tags": clean_tags,
        }
        stored = self.store.add_custom_community(payload)
        return self._custom_community_spec(stored)

    def profile_payload(self, account: Dict[str, Any] | None = None) -> Dict[str, Any]:
        state = self.store.snapshot()
        safe_account = self.sqlite_store.safe_account(account) if account else None
        owner, username_aliases, include_legacy = self._profile_owner_context(safe_account)
        saved_items = self.store.saved_artists_for_owner(owner, include_legacy=include_legacy)
        custom_items = self.sqlite_store.list_custom_tracks_for_owner(owner, include_legacy=include_legacy)
        activity = self._profile_activity(state, saved_items, custom_items, owner, username_aliases, include_legacy)
        return {
            "authenticated": bool(safe_account),
            "account": safe_account,
            "local_username": safe_account.get("display_name") if safe_account else LOCAL_PROFILE_USERNAME,
            "saved_artists": saved_items,
            "custom_artists": custom_items,
            "saved_count": len(saved_items),
            "custom_count": len(custom_items),
            "small_artist_definition": self.small_artist_definition(),
            **activity,
        }

    def public_profile_payload(
        self,
        username: str,
        account: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | None:
        clean_username = str(username or "").strip()
        if not clean_username:
            return None

        state = self.store.snapshot()
        safe_account = self.sqlite_store.safe_account(account) if account else None
        if safe_account:
            owner, username_aliases, include_legacy = self._profile_owner_context(safe_account)
            library_public = bool(safe_account.get("library_public", True))
            saved_items = self.store.saved_artists_for_owner(owner, include_legacy=include_legacy) if library_public else []
            custom_items = self.sqlite_store.list_custom_tracks_for_owner(owner, include_legacy=include_legacy) if library_public else []
            display_name = safe_account.get("display_name") or safe_account.get("username") or clean_username
            profile = {
                "username": safe_account.get("username") or display_name,
                "display_name": display_name,
                "avatar_kind": safe_account.get("avatar_kind") or "preset",
                "avatar_value": safe_account.get("avatar_value") or "violet",
                "library_public": library_public,
                "created_at": safe_account.get("created_at"),
                "is_legacy": False,
            }
        else:
            owner = {
                "username": clean_username,
                "display_name": clean_username,
                "profile_username": clean_username,
            }
            username_aliases = [clean_username]
            include_legacy = True
            library_public = False
            saved_items = []
            custom_items = []
            profile = {
                "username": clean_username,
                "display_name": clean_username,
                "avatar_kind": "preset",
                "avatar_value": "violet",
                "library_public": False,
                "created_at": None,
                "is_legacy": True,
            }

        activity = self._profile_activity(state, saved_items, custom_items, owner, username_aliases, include_legacy)
        has_public_legacy_activity = any(
            activity.get(key)
            for key in ("profile_posts", "profile_replies", "profile_song_comments", "profile_discussions")
        )
        if not safe_account and not has_public_legacy_activity:
            return None

        return {
            "profile": profile,
            "saved_artists": [self._public_music_item(item) for item in saved_items],
            "custom_artists": [self._public_music_item(item) for item in custom_items],
            "saved_count": len(saved_items),
            "custom_count": len(custom_items),
            "library_public": library_public,
            "communities": self._profile_communities_from_activity(activity),
            **activity,
        }

    def _profile_activity(
        self,
        state: Dict[str, Any],
        saved_items: Sequence[Dict[str, Any]],
        custom_items: Sequence[Dict[str, Any]],
        owner: Dict[str, Any] | None,
        username_aliases: Sequence[str],
        include_legacy: bool,
    ) -> Dict[str, Any]:
        posts = state.get("community_posts", [])
        local_song_keys: set[str] = set()
        profile_posts: List[Dict[str, Any]] = []
        profile_replies: List[Dict[str, Any]] = []

        for item in [*saved_items, *custom_items]:
            local_song_keys.update(self._profile_song_identity_values(item))

        for post in posts:
            origin = self._community_origin(post)
            post_song_keys = self._profile_song_identity_values(post)
            if self._profile_item_owned_by(post, owner, username_aliases, include_legacy):
                profile_posts.append(self._profile_post_activity(post, origin))
                local_song_keys.update(post_song_keys)

            for reply in post.get("replies") or []:
                if not self._profile_item_owned_by(reply, owner, username_aliases, include_legacy):
                    continue
                profile_replies.append(self._profile_reply_activity(reply, post, origin))
                local_song_keys.update(post_song_keys)

        comments_by_id: Dict[str, Dict[str, Any]] = {}
        for comment in self.sqlite_store.list_song_comments_for_owner(owner, username_aliases, include_legacy=include_legacy):
            comments_by_id[f"song-comment-{comment.get('id')}"] = self._profile_song_comment_activity(comment)

        return {
            "profile_posts": self._sorted_profile_activity(profile_posts, 24),
            "profile_replies": self._sorted_profile_activity(profile_replies, 24),
            "profile_song_comments": self._sorted_profile_activity(list(comments_by_id.values()), 24),
            "profile_discussions": self._profile_discussions_for_song_keys(
                local_song_keys,
                posts,
                owner,
                username_aliases,
                include_legacy,
            ),
        }

    def _profile_discussions_for_song_keys(
        self,
        song_keys: set[str],
        posts: Sequence[Dict[str, Any]],
        owner: Dict[str, Any] | None,
        username_aliases: Sequence[str],
        include_legacy: bool,
    ) -> List[Dict[str, Any]]:
        if not song_keys:
            return []

        discussions: List[Dict[str, Any]] = []
        for comment in self.sqlite_store.list_song_comments_for_song_keys_by_owner(
            song_keys,
            owner,
            username_aliases,
            include_legacy=include_legacy,
        ):
            if not comment.get("text"):
                continue
            discussions.append(
                {
                    **self._profile_song_comment_activity(comment),
                    "id": f"discussion-song-comment-{comment.get('id')}",
                    "type": "song_comment",
                    "origin_label": "Låtkommentar",
                    "is_local_user": True,
                }
            )

        for post in posts:
            post_song_keys = self._profile_song_identity_values(post)
            if not post_song_keys.intersection(song_keys):
                continue

            origin = self._community_origin(post)
            if post.get("text") and self._profile_item_owned_by(post, owner, username_aliases, include_legacy):
                discussions.append(
                    {
                        **self._profile_post_activity(post, origin),
                        "id": f"discussion-post-{post.get('id')}",
                        "type": "community_post",
                        "is_local_user": True,
                    }
                )

            parent_summary = self._short_summary(post.get("text") or "")
            for reply in post.get("replies") or []:
                if not reply.get("text") or not self._profile_item_owned_by(reply, owner, username_aliases, include_legacy):
                    continue
                discussions.append(
                    {
                        **self._profile_reply_activity(reply, post, origin),
                        "id": f"discussion-reply-{reply.get('id')}",
                        "type": "community_reply",
                        "parent_summary": parent_summary,
                        "is_local_user": True,
                    }
                )

        return self._sorted_profile_activity(discussions, 30)

    def _profile_post_activity(self, post: Dict[str, Any], origin: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": post.get("id"),
            "type": "post",
            "post_id": post.get("id"),
            "username": post.get("username") or LOCAL_PROFILE_USERNAME,
            "text": post.get("text") or "",
            "created_at": post.get("created_at"),
            "source": origin.get("source"),
            "community_slug": origin.get("community_slug"),
            "community_name": origin.get("community_name"),
            "origin_label": origin.get("origin_label"),
            "tip_artist": post.get("tip_artist"),
            "tip_song": post.get("tip_song"),
            "artist_key": post.get("artist_key"),
            "song_key": post.get("song_key") or post.get("track_key") or post.get("track_id") or post.get("isrc"),
            "track_key": post.get("track_key"),
            "track_id": post.get("track_id"),
            "isrc": post.get("isrc"),
            "song_label": self._profile_song_label(post),
            "reply_count": len(post.get("replies") or []),
        }

    def _profile_reply_activity(
        self,
        reply: Dict[str, Any],
        post: Dict[str, Any],
        origin: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "id": reply.get("id"),
            "type": "reply",
            "reply_id": reply.get("id"),
            "post_id": post.get("id"),
            "username": reply.get("username") or LOCAL_PROFILE_USERNAME,
            "text": reply.get("text") or "",
            "created_at": reply.get("created_at"),
            "source": origin.get("source"),
            "community_slug": origin.get("community_slug"),
            "community_name": origin.get("community_name"),
            "origin_label": origin.get("origin_label"),
            "parent_text": post.get("text") or "",
            "parent_summary": self._short_summary(post.get("text") or ""),
            "parent_username": post.get("username") or LOCAL_PROFILE_USERNAME,
            "tip_artist": post.get("tip_artist"),
            "tip_song": post.get("tip_song"),
            "song_key": post.get("song_key") or post.get("track_key") or post.get("track_id") or post.get("isrc"),
            "song_label": self._profile_song_label(post),
        }

    def _profile_song_comment_activity(self, comment: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": comment.get("id"),
            "type": "song_comment",
            "username": comment.get("username") or LOCAL_PROFILE_USERNAME,
            "text": comment.get("text") or "",
            "created_at": comment.get("created_at"),
            "origin_label": "Låtkommentar",
            "song_key": comment.get("song_key"),
            "track_key": comment.get("track_key"),
            "track_id": comment.get("track_id"),
            "artist_key": comment.get("artist_key"),
            "artist_name": comment.get("artist_name"),
            "track_title": comment.get("track_title"),
            "song_label": self._profile_song_label(comment),
        }

    def _profile_song_identity_values(self, item: Dict[str, Any]) -> set[str]:
        values: set[str] = set()
        for field in ("song_key", "track_key", "track_id", "isrc"):
            value = item.get(field)
            if value is None:
                continue
            text = str(value).strip()
            normalized = normalize_key(text)
            if text and normalized not in {"nan", "none", "null", "undefined"}:
                values.add(text)
                values.add(normalized)

        artist_key = normalize_key(item.get("artist_key") or item.get("artist") or item.get("artist_name") or item.get("tip_artist"))
        title_key = normalize_track_title(item.get("song") or item.get("title") or item.get("track_title") or item.get("tip_song"))
        if artist_key and title_key:
            values.add(f"{artist_key}:{title_key}")

        stable_key = self._stable_song_key(item)
        if stable_key:
            values.add(stable_key)
        return values

    def _profile_song_label(self, item: Dict[str, Any]) -> str:
        title = item.get("tip_song") or item.get("track_title") or item.get("song") or item.get("title")
        artist = item.get("tip_artist") or item.get("artist_name") or item.get("artist")
        if title and artist:
            return f"{title} - {artist}"
        return str(title or artist or "").strip()

    @staticmethod
    def _sorted_profile_activity(items: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:limit]

    @staticmethod
    def _public_music_item(item: Dict[str, Any]) -> Dict[str, Any]:
        hidden_fields = {"user_id", "profile_username"}
        return {
            key: value
            for key, value in dict(item).items()
            if key not in hidden_fields and not str(key).startswith("_")
        }

    @staticmethod
    def _profile_communities_from_activity(activity: Dict[str, Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        communities: Dict[str, Dict[str, Any]] = {}
        for bucket in ("profile_posts", "profile_replies", "profile_discussions"):
            for item in activity.get(bucket, []) or []:
                slug = str(item.get("community_slug") or "").strip()
                if not slug:
                    continue
                current = communities.setdefault(
                    slug,
                    {
                        "slug": slug,
                        "name": item.get("community_name") or item.get("origin_label") or slug,
                        "activity_count": 0,
                    },
                )
                current["activity_count"] += 1
                if item.get("community_name"):
                    current["name"] = item.get("community_name")
        return sorted(communities.values(), key=lambda item: (-int(item.get("activity_count") or 0), str(item.get("name") or "")))

    def _profile_owner_context(self, account: Dict[str, Any] | None) -> tuple[Dict[str, Any] | None, List[str], bool]:
        if not account:
            return None, [], False

        owner = {
            "id": account.get("id"),
            "user_id": account.get("id"),
            "username": account.get("username"),
            "display_name": account.get("display_name"),
            "profile_username": account.get("display_name") or account.get("username"),
        }
        aliases = [
            value
            for value in (account.get("username"), account.get("display_name"))
            if value
        ]
        include_legacy = self._is_legacy_profile_account(account)
        if include_legacy:
            aliases.extend(LOCAL_PROFILE_USERNAME_LOOKUPS)
        return owner, aliases, include_legacy

    def _profile_item_owned_by(
        self,
        item: Dict[str, Any],
        owner: Dict[str, Any] | None,
        username_aliases: Sequence[str],
        include_legacy: bool,
    ) -> bool:
        if owner:
            owner_id = owner.get("user_id") or owner.get("id")
            if owner_id is not None and item.get("user_id") is not None and str(item.get("user_id")) == str(owner_id):
                return True

            owner_names = {
                normalize_key(owner.get("profile_username")),
                normalize_key(owner.get("username")),
                normalize_key(owner.get("display_name")),
            }
            owner_names.discard("")
            item_name = normalize_key(item.get("profile_username"))
            if item_name and item_name in owner_names:
                return True

        if not include_legacy or item.get("user_id") is not None or item.get("profile_username"):
            return False
        return self._is_profile_username(item.get("username"), username_aliases)

    @staticmethod
    def _is_legacy_profile_account(account: Dict[str, Any]) -> bool:
        names = {normalize_key(account.get("username")), normalize_key(account.get("display_name"))}
        return bool(names.intersection(LEGACY_PROFILE_NAMES))

    @staticmethod
    def _is_profile_username(value: Any, username_aliases: Sequence[str]) -> bool:
        normalized = normalize_key(value)
        return bool(normalized) and normalized in {normalize_key(alias) for alias in username_aliases}

    def _stable_song_key(self, item: Dict[str, Any]) -> str:
        for key in ("song_key", "track_key", "track_id", "isrc"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        artist_key = normalize_key(item.get("artist_key") or item.get("artist") or item.get("primary_artist"))
        title_key = normalize_track_title(item.get("song") or item.get("title") or item.get("track_name"))
        if artist_key and title_key:
            return f"{artist_key}:{title_key}"
        return ""

    def _with_song_identity(self, item: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(item)
        song_key = self._stable_song_key(payload)
        if song_key:
            payload["song_key"] = song_key
            payload["track_key"] = payload.get("track_key") or song_key
        if payload.get("song") and not payload.get("title"):
            payload["title"] = payload.get("song")
        elif payload.get("title") and not payload.get("song"):
            payload["song"] = payload.get("title")
        return payload

    def artist_detail_payload(self, artist_key: str) -> Dict[str, Any]:
        normalized = normalize_key(artist_key)
        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        posts = state.get("community_posts", [])

        for item in [*custom_tracks, *state.get("saved_artists", []), *state.get("custom_artists", [])]:
            if normalize_key(item.get("artist_key") or item.get("artist")) == normalized:
                return self._artist_detail_from_item(item, posts)

        local = self.dataset.artist_record(normalized)
        if not local:
            raise ValueError("Artist hittades inte i det lokala discovery-indexet.")

        profile = self._profile_artist(local.get("primary_artist") or artist_key, local)
        rows = self.dataset.rows_for_artist_key(normalized).sort_values("popularity", ascending=True).head(5)
        tracks = [
            self._with_song_identity(
                self._with_track_media(
                    {
                        "track_key": row.get("track_key"),
                        "track_id": row.get("track_id"),
                        "song": row.get("track_name"),
                        "title": row.get("track_name"),
                        "artist": row.get("primary_artist"),
                        "artist_key": row.get("artist_key"),
                        "album": row.get("album_name"),
                        "genre": row.get("track_genre"),
                        "preview": row.get("preview"),
                        "deezer_link": row.get("deezer_link"),
                        "source": "dataset",
                    }
                )
            )
            for _, row in rows.iterrows()
        ]
        detail = {
            "song_key": tracks[0]["song_key"] if tracks else "",
            "track_key": tracks[0]["track_key"] if tracks else "",
            "track_id": tracks[0].get("track_id") if tracks else None,
            "artist_key": normalized,
            "artist": profile.get("artist") or local.get("primary_artist") or artist_key,
            "song": tracks[0]["song"] if tracks else "",
            "title": tracks[0]["title"] if tracks else "",
            "genre": (profile.get("top_genres") or local.get("top_genres") or ["unknown"])[0],
            "image": profile.get("image"),
            "preview": profile.get("preview"),
            "deezer_link": profile.get("deezer_link"),
            "lastfm_link": profile.get("lastfm_link"),
            "bio": profile.get("bio") or "En mindre artist från datasetet och community-flödet.",
            "top_genres": profile.get("top_genres", local.get("top_genres", [])),
            "similar_artists": profile.get("similar_artists", []),
            "metrics": profile.get("metrics", {}),
            "audio_signature": profile.get("audio_signature", {}),
            "mood_profile": profile.get("mood_profile", {}),
            "estimated_mood_profile": profile.get("estimated_mood_profile", {}),
            "audio_validated": profile.get("audio_validated", False),
            "mood_source": profile.get("mood_source", ""),
            "small_artist_score": profile.get("small_artist_score", 0.0),
            "tracks": tracks,
            "discovery_labels": ["Dataset match"],
            "cluster_label": "",
            "source": "dataset",
            "is_custom": False,
        }
        return self._artist_detail_from_item(detail, posts)

    def add_custom_artist(
        self,
        isrc: str,
        note: str = "",
        community_slug: str | None = None,
        username: str = LOCAL_PROFILE_USERNAME,
        user_id: Any | None = None,
        profile_username: str | None = None,
    ) -> Dict[str, Any]:
        track = self.apis.lookup_track_by_isrc(isrc)
        if not track:
            raise ValueError("Vi kunde inte hitta nagon lat via Deezer for den ISRC-koden.")

        artist_name = track.get("artist") or "Okand artist"
        artist_key = normalize_key(artist_name)
        local = self.dataset.artist_record(artist_key)
        profile = self._profile_artist(artist_name, local)
        genre = self._resolve_custom_genre(track, local, profile)
        top_genres = self._resolve_top_genres(track, local, profile, genre)
        audio_signature, audio_validated, audio_signature_source = self._resolve_custom_audio_signature(track, artist_key)
        metrics = dict(profile.get("metrics", {}))
        metrics["audio_features_validated"] = audio_validated
        metrics["audio_signature_source"] = audio_signature_source
        metadata_text = self._compose_metadata_text(
            song=track.get("song"),
            artist=artist_name,
            album=track.get("album"),
            genre=genre,
            tags=top_genres,
            note=note,
        )
        candidate_row = self._build_custom_candidate_row(
            {
                "track_key": track.get("track_key") or track.get("track_id") or isrc.upper(),
                "track_id": track.get("track_id"),
                "artist_key": artist_key,
                "song": track.get("song"),
                "artist": artist_name,
                "album": track.get("album"),
                "genre": genre,
                "top_genres": top_genres,
                "audio_signature": audio_signature,
                "metrics": metrics,
                "metadata_text": metadata_text,
                "is_custom": True,
                "image": track.get("image") or profile.get("image"),
                "preview": track.get("preview") or profile.get("preview"),
                "deezer_link": track.get("deezer_link") or profile.get("deezer_link"),
                "lastfm_link": profile.get("lastfm_link"),
                "similar_artists": profile.get("similar_artists", []),
                "note": note,
            }
        )
        cluster_id = int(self.intelligence.assign_cluster_ids(pd.DataFrame([candidate_row]))[0])
        candidate_row["cluster_id"] = cluster_id
        candidate_row["cluster_label"] = self._cluster_label(cluster_id)
        mood_profile: Dict[str, Any] = {}
        estimated_mood_profile: Dict[str, Any] = {}
        mood_source = "dataset" if audio_validated else ""
        metrics["mood_source"] = mood_source
        small_artist_score = self._calculate_small_artist_score(local, profile.get("metrics", {}), is_custom=True)
        discovery_labels = self._build_discovery_labels(
            row=candidate_row,
            similarity_score=0.32,
            small_artist_score=small_artist_score,
            custom_recency_boost=0.35,
        )

        item = {
            "song_key": candidate_row["track_key"],
            "track_key": candidate_row["track_key"],
            "artist_key": artist_key,
            "artist": artist_name,
            "song": track.get("song"),
            "title": track.get("song"),
            "album": track.get("album"),
            "genre": genre,
            "image": candidate_row.get("image"),
            "preview": candidate_row.get("preview"),
            "deezer_link": candidate_row.get("deezer_link"),
            "lastfm_link": candidate_row.get("lastfm_link"),
            "reason": "Egen inlagd artist som nu blir en del av framtida discovery-logik.",
            "top_genres": top_genres,
            "similar_artists": profile.get("similar_artists", []),
            "metrics": metrics,
            "audio_signature": audio_signature,
            "mood_profile": mood_profile,
            "estimated_mood_profile": estimated_mood_profile,
            "audio_validated": audio_validated,
            "mood_source": mood_source,
            "discovery_labels": discovery_labels,
            "cluster_id": cluster_id,
            "cluster_label": candidate_row["cluster_label"],
            "small_artist_score": small_artist_score,
            "source": "custom",
            "is_custom": True,
            "note": note,
            "community_slug": community_slug,
            "isrc": track.get("isrc"),
            "track_id": track.get("track_id"),
            "deezer_artist_id": track.get("deezer_artist_id"),
            "album_id": track.get("album_id"),
            "added_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "user_id": user_id,
            "profile_username": profile_username or username or LOCAL_PROFILE_USERNAME,
            "tags": self._basic_tags(candidate_row, top_genres),
            "source_weight": 1.25,
        }

        self.sqlite_store.upsert_custom_track(item)
        self.store.add_custom_artist(item)
        self.store.upsert_saved_artist(item)
        self.store.add_community_post(
            {
                "username": username or LOCAL_PROFILE_USERNAME,
                "user_id": user_id,
                "profile_username": profile_username or username or LOCAL_PROFILE_USERNAME,
                "text": "Delade en ny mindre artist till community-flodet.",
                "tip_artist": artist_name,
                "tip_song": track.get("song"),
                "artist_key": artist_key,
                "community_slug": community_slug,
                "source": "community" if community_slug else "feed",
                "song_key": item.get("song_key"),
                "track_key": item.get("track_key"),
                "track_id": item.get("track_id"),
                "isrc": item.get("isrc"),
            }
        )
        return item

    def toggle_saved_artist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        artist_key = normalize_key(payload.get("artist_key") or payload.get("artist"))
        include_legacy = not payload.get("user_id") and not payload.get("profile_username")
        current_keys = set(self.store.saved_artist_keys_for_owner(payload, include_legacy=include_legacy))

        if artist_key in current_keys:
            self.store.remove_saved_artist(artist_key, payload, include_legacy=include_legacy)
            return {"saved": False, "artist_key": artist_key}

        item = dict(payload)
        item["artist_key"] = artist_key
        item["saved_at"] = utc_now_iso()
        stored = self.store.upsert_saved_artist(item)
        return {"saved": True, "artist_key": artist_key, "item": stored}

    def remove_artist(self, artist_key: str, owner: Dict[str, Any] | None = None) -> None:
        normalized = normalize_key(artist_key)
        if owner is not None:
            self.store.remove_saved_artist(normalized, owner)
            self.store.remove_custom_artist(normalized, owner)
            self.sqlite_store.delete_custom_track(normalized, owner)
            return
        self.store.remove_artist_everywhere(normalized)
        self.sqlite_store.delete_custom_track(normalized)

    def add_community_post(
        self,
        text: str,
        username: str,
        tip_artist: str | None,
        tip_song: str | None,
        community_slug: str | None = None,
        song_key: str | None = None,
        track_key: str | None = None,
        track_id: Any | None = None,
        isrc: str | None = None,
        user_id: Any | None = None,
        profile_username: str | None = None,
    ) -> Dict[str, Any]:
        artist_key = normalize_key(tip_artist) if tip_artist else ""
        post_source = "community" if community_slug else "feed"
        resolved_slug = community_slug or self._community_slug_for_text(" ".join([text, tip_artist or "", tip_song or ""]))
        post = self.store.add_community_post(
            {
                "username": username or "du",
                "user_id": user_id,
                "profile_username": profile_username or username or "du",
                "text": text,
                "tip_artist": tip_artist,
                "tip_song": tip_song,
                "artist_key": artist_key or None,
                "community_slug": resolved_slug,
                "source": post_source,
                "song_key": song_key,
                "track_key": track_key,
                "track_id": track_id,
                "isrc": isrc,
                "replies": [],
            }
        )
        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        artist_pool = self._feed_artist_pool({}, [], state, custom_tracks)
        enriched = self._enrich_community_posts([post], artist_pool, state)
        return enriched[0] if enriched else post

    def add_community_reply(
        self,
        post_id: str,
        text: str,
        username: str,
        user_id: Any | None = None,
        profile_username: str | None = None,
    ) -> Dict[str, Any]:
        post = self.store.add_community_reply(
            post_id,
            {
                "username": username or "du",
                "user_id": user_id,
                "profile_username": profile_username or username or "du",
                "text": text,
            },
        )
        state = self.store.snapshot()
        custom_tracks = self.sqlite_store.list_custom_tracks()
        artist_pool = self._feed_artist_pool({}, [], state, custom_tracks)
        enriched = self._enrich_community_posts([post], artist_pool, state)
        return enriched[0] if enriched else post

    def _build_feed_extras(
        self,
        card: Dict[str, Any],
        ranked_results: Sequence[Dict[str, Any]],
        state: Dict[str, Any],
        custom_tracks: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        raw_posts = state.get("community_posts", [])
        feed_posts = self._feed_scoped_posts(raw_posts)
        community_scoped_posts = self._community_scoped_posts(raw_posts)
        feed_state = {**state, "community_posts": feed_posts}
        artist_pool = self._feed_artist_pool(card, ranked_results, feed_state, custom_tracks)
        community_posts = self._enrich_community_posts(feed_posts, artist_pool, feed_state)
        scoped_community_posts = self._enrich_community_posts(community_scoped_posts, artist_pool, state)
        trending_quietly = self._build_trending_quietly(artist_pool, community_posts)
        micro_communities = self._derive_micro_communities(artist_pool, scoped_community_posts)
        return {
            "community_posts": community_posts,
            "trending_quietly": trending_quietly,
            "micro_communities": micro_communities,
            "community_activity": self._community_activity(artist_pool, community_posts),
            "discovery_trail": self._discovery_trail_for_item(card or {}, community_posts),
        }

    def _post_scope(self, post: Dict[str, Any]) -> str:
        source = normalize_key(post.get("source") or post.get("visibility"))
        if source in {"feed", "community"}:
            return source
        slug = post.get("community_slug")
        if slug and self._community_spec(slug):
            return "community"
        return "feed"

    def _feed_scoped_posts(self, posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [post for post in posts if self._post_scope(post) == "feed"]

    def _community_scoped_posts(self, posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [post for post in posts if self._post_scope(post) == "community"]

    def _feed_artist_pool(
        self,
        card: Dict[str, Any],
        ranked_results: Sequence[Dict[str, Any]],
        state: Dict[str, Any],
        custom_tracks: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for item in [card, *ranked_results, *custom_tracks, *state.get("saved_artists", [])]:
            if item and item.get("artist_key"):
                items.append(dict(item))

        deduped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            key = normalize_key(item.get("artist_key") or item.get("artist"))
            if not key:
                continue
            existing = deduped.get(key, {})
            merged = {**existing, **item}
            merged["preview"] = self._first_usable_preview(item.get("preview"), existing.get("preview"))
            labels = list(dict.fromkeys([*(existing.get("discovery_labels") or []), *(item.get("discovery_labels") or [])]))
            if item.get("is_custom") or item.get("isrc"):
                labels = list(dict.fromkeys(["Community submitted", "ISRC submitted", *labels]))
            merged["discovery_labels"] = labels[:5]
            merged["reason_chips"] = self._structured_reason_chips_for_item(merged, state.get("community_posts", []))
            merged["community_signals"] = self._community_signals_for_item(merged, state.get("community_posts", []))
            merged["discovery_trail"] = self._discovery_trail_for_item(merged, state.get("community_posts", []))
            deduped[key] = merged
        return list(deduped.values())

    def _enrich_community_posts(
        self,
        posts: Sequence[Dict[str, Any]],
        artist_pool: Sequence[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        by_key = {normalize_key(item.get("artist_key") or item.get("artist")): item for item in artist_pool if item.get("artist_key") or item.get("artist")}
        saved_keys = {
            normalize_key(item.get("artist_key") or item.get("artist"))
            for item in state.get("saved_artists", [])
            if item.get("artist_key") or item.get("artist")
        }
        enriched: List[Dict[str, Any]] = []
        for post in posts[:16]:
            item = dict(post)
            artist_key = normalize_key(item.get("artist_key") or item.get("tip_artist"))
            linked_artist = by_key.get(artist_key)
            if not linked_artist and item.get("tip_artist"):
                linked_artist = {
                    "artist_key": artist_key,
                    "artist": item.get("tip_artist"),
                    "song": item.get("tip_song"),
                    "discovery_labels": ["Community tip"],
                    "source": "community",
                }
            text_blob = " ".join(str(item.get(key) or "") for key in ("text", "tip_artist", "tip_song"))
            item["community_slug"] = item.get("community_slug") or self._community_slug_for_text(text_blob)
            item["community_name"] = self._community_name(item["community_slug"])
            item["replies"] = item.get("replies") or []
            item["reply_count"] = len(item["replies"])
            item["saved_count"] = 1 if artist_key and artist_key in saved_keys else 0
            item["saved_by_you"] = bool(item["saved_count"])
            item["activity_label"] = self._activity_label(item)
            if linked_artist:
                item["linked_artist"] = self._with_track_media(linked_artist)
            enriched.append(item)
        return enriched

    def _build_trending_quietly(
        self,
        artist_pool: Sequence[Dict[str, Any]],
        community_posts: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        weekly_items: List[tuple[datetime, Dict[str, Any]]] = []
        for item in artist_pool:
            added_at = self._parse_datetime(item.get("added_at") or item.get("updated_at"))
            if not added_at or not self._is_current_week(added_at):
                continue
            if not (item.get("is_custom") or item.get("isrc")):
                continue
            weekly_items.append((added_at, item))

        weekly_items.sort(key=lambda entry: entry[0], reverse=True)
        latest_items = [item for _, item in weekly_items[:10]]
        if len(latest_items) > 1:
            order = np.random.default_rng().permutation(len(latest_items))
            latest_items = [latest_items[index] for index in order]
        return [self._compact_artist_card(item, "trending") for item in latest_items]

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _is_current_week(self, value: datetime) -> bool:
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return week_start <= value <= now

    def _derive_micro_communities(
        self,
        artist_pool: Sequence[Dict[str, Any]],
        community_posts: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        communities: List[Dict[str, Any]] = []
        for spec in self._community_specs():
            posts = [post for post in community_posts if post.get("community_slug") == spec["slug"]]
            post_artists = [post.get("linked_artist") for post in posts if post.get("linked_artist")]
            shared_by_key: Dict[str, Dict[str, Any]] = {}
            for item in post_artists:
                key = normalize_key(item.get("artist_key") or item.get("artist"))
                if key and key not in shared_by_key:
                    shared_by_key[key] = dict(item)

            related_by_key: Dict[str, Dict[str, Any]] = {}
            for item in artist_pool:
                key = normalize_key(item.get("artist_key") or item.get("artist"))
                if not key or key in shared_by_key or not self._item_matches_community(item, spec):
                    continue
                related_by_key[key] = dict(item)

            shared_artists = list(shared_by_key.values())
            related_discoveries = list(related_by_key.values())
            used_fallback = False
            if spec.get("source") != "user" and not shared_artists and not related_discoveries:
                fallback_by_key = {}
                for item in artist_pool[:3]:
                    key = normalize_key(item.get("artist_key") or item.get("artist"))
                    if key:
                        fallback_by_key[key] = dict(item)
                related_discoveries = list(fallback_by_key.values())
                used_fallback = True

            combined_artists = [*shared_artists, *related_discoveries]
            communities.append(
                {
                    "slug": spec["slug"],
                    "name": spec["name"],
                    "description": spec["description"],
                    "tone": spec.get("tone"),
                    "motto": spec.get("motto"),
                    "submission_prompt": spec.get("submission_prompt"),
                    "belongs_here": spec.get("belongs_here"),
                    "post_count": len(posts),
                    "shared_count": len(shared_artists),
                    "suggested_count": len(related_discoveries),
                    "artists_are_fallback": used_fallback,
                    "artist_section_label": "Shared by this community" if shared_artists else "Related discoveries",
                    "activity": f"{len(posts)} stored community posts" if posts else "No posts yet",
                    "tags": (spec.get("tags") or spec.get("genres") or [])[:3],
                    "source": spec.get("source", "default"),
                    "visibility": spec.get("visibility", "public"),
                    "created_by_username": spec.get("created_by_username"),
                    "shared_artists": [self._compact_artist_card(item, spec["slug"]) for item in shared_artists[:4]],
                    "related_discoveries": [self._compact_artist_card(item, spec["slug"]) for item in related_discoveries[:4]],
                    "artists": [self._compact_artist_card(item, spec["slug"]) for item in combined_artists[:4]],
                    "posts": posts[:3],
                }
            )
        return communities

    def _compact_artist_card(self, item: Dict[str, Any], source: str) -> Dict[str, Any]:
        payload = self._with_song_identity(item)
        payload.setdefault("source", source)
        payload.setdefault("reason_chips", self._structured_reason_chips_for_item(payload, []))
        payload.setdefault("community_signals", self._community_signals_for_item(payload, []))
        payload.setdefault("discovery_trail", self._discovery_trail_for_item(payload, []))
        if payload.get("is_custom") or payload.get("isrc"):
            labels = list(dict.fromkeys(["Community submitted", "Found through the community", *(payload.get("discovery_labels") or [])]))
            payload["discovery_labels"] = labels[:5]
        return payload

    def _artist_detail_from_item(self, item: Dict[str, Any], posts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        payload = self._with_song_identity(item)
        tracks = []
        if payload.get("song") or payload.get("preview"):
            tracks.append(
                self._with_song_identity(
                    {
                        "song_key": payload.get("song_key"),
                        "track_key": payload.get("track_key"),
                        "track_id": payload.get("track_id"),
                        "isrc": payload.get("isrc"),
                        "song": payload.get("song") or "Unknown track",
                        "title": payload.get("title") or payload.get("song") or "Unknown track",
                        "artist": payload.get("artist"),
                        "artist_key": payload.get("artist_key"),
                        "album": payload.get("album"),
                        "genre": payload.get("genre"),
                        "preview": payload.get("preview"),
                        "deezer_link": payload.get("deezer_link"),
                        "source": "isrc" if payload.get("isrc") else payload.get("source", "community"),
                    }
                )
            )
        for title in payload.get("secondary_tracks", []) or []:
            track_match = self.dataset.track_record(payload.get("artist_key") or "", title)
            tracks.append(
                self._with_song_identity(
                    {
                        "track_key": track_match.get("track_key"),
                        "track_id": track_match.get("track_id"),
                        "song": title,
                        "title": title,
                        "artist": payload.get("artist"),
                        "artist_key": payload.get("artist_key"),
                        "album": track_match.get("album_name") or "",
                        "genre": track_match.get("track_genre") or payload.get("genre"),
                        "preview": None,
                        "source": "dataset",
                    }
                )
            )
        payload["tracks"] = [
            self._with_song_identity(self._with_track_media(track))
            for track in (payload.get("tracks") or tracks[:5])
        ]
        payload["reason_chips"] = self._structured_reason_chips_for_item(payload, posts)
        payload["community_signals"] = self._community_signals_for_item(payload, posts)
        payload["community_appearances"] = self._community_appearances_for_item(payload, posts)
        payload["discussion_posts"] = payload["community_appearances"][:3]
        payload["related_artist_links"] = self._related_artist_links(payload.get("similar_artists", []))
        payload["discovery_trail"] = self._discovery_trail_for_item(payload, posts)
        if payload.get("is_custom") or payload.get("isrc"):
            payload["discovery_labels"] = list(
                dict.fromkeys(["Community submitted", "ISRC submitted", "Found through the community", *(payload.get("discovery_labels") or [])])
            )[:6]
        return payload

    def _community_spec(self, slug: str | None) -> Dict[str, Any] | None:
        for spec in self._community_specs():
            if spec["slug"] == slug:
                return spec
        return None

    def _community_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        for spec in MICRO_COMMUNITIES:
            payload = dict(spec)
            payload.setdefault("source", "default")
            payload.setdefault("visibility", "public")
            payload.setdefault("tags", payload.get("genres", [])[:3])
            specs.append(payload)
        specs.extend(self._custom_community_spec(item) for item in self.store.custom_communities())
        return specs

    def _custom_community_spec(self, item: Dict[str, Any]) -> Dict[str, Any]:
        name = str(item.get("name") or "Untitled room").strip()
        description = str(item.get("description") or "").strip()
        tags = self._validate_community_tags(item.get("tags") or [])
        terms = [
            term
            for term in re.split(r"[\s,;#]+", normalize_text(" ".join([name, description, " ".join(tags)])))
            if len(term) >= 3
        ]
        return {
            "slug": item.get("slug"),
            "name": name,
            "description": description or f"Ett Ã¶ppet musikrum fÃ¶r {name}.",
            "tone": item.get("tone") or "community-created",
            "motto": item.get("motto") or "",
            "submission_prompt": item.get("submission_prompt") or f"Dela en lÃ¥t eller tanke som passar i {name}.",
            "belongs_here": item.get("belongs_here") or description or f"Musik och diskussioner som hÃ¶r hemma i {name}.",
            "genres": tags,
            "tags": tags,
            "terms": terms,
            "source": "user",
            "visibility": item.get("visibility") or "public",
            "created_by_username": item.get("created_by_username"),
            "created_at": item.get("created_at"),
        }

    def _validate_community_name(self, value: Any) -> str:
        name = re.sub(r"\s+", " ", str(value or "")).strip()
        if not 3 <= len(name) <= 48:
            raise ValueError("Rumsnamnet mÃ¥ste vara 3-48 tecken.")
        if not any(char.isalnum() for char in name):
            raise ValueError("Rumsnamnet behÃ¶ver innehÃ¥lla minst en bokstav eller siffra.")
        if any(ord(char) < 32 for char in name):
            raise ValueError("Rumsnamnet innehÃ¥ller ogiltiga tecken.")
        return name

    def _validate_community_description(self, value: Any) -> str:
        description = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(description) > 180:
            raise ValueError("Beskrivningen fÃ¥r vara max 180 tecken.")
        return description

    def _validate_community_tags(self, values: Sequence[Any]) -> List[str]:
        tags: List[str] = []
        seen: set[str] = set()
        for value in values[:5]:
            tag = re.sub(r"\s+", " ", str(value or "")).strip()
            if not tag or len(tag) > 24:
                continue
            key = normalize_key(tag)
            if key and key not in seen:
                tags.append(tag)
                seen.add(key)
        return tags

    def _unique_community_slug(self, name: str) -> str:
        base = self._slugify_community_name(name)
        if base in RESERVED_COMMUNITY_SLUGS:
            base = f"room-{base}"

        existing = {
            normalize_key(spec.get("slug"))
            for spec in self._community_specs()
            if spec.get("slug")
        }
        slug = base
        suffix = 2
        while normalize_key(slug) in existing:
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    @staticmethod
    def _slugify_community_name(name: str) -> str:
        text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
        text = re.sub(r"-{2,}", "-", text)
        if not text:
            raise ValueError("Rumsnamnet kunde inte gÃ¶ras till en sÃ¤ker slug.")
        return text[:64].strip("-") or "music-room"

    def _matching_posts_for_item(self, item: Dict[str, Any], posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        key = normalize_key(item.get("artist_key") or item.get("artist"))
        if not key:
            return []
        return [
            post for post in posts
            if normalize_key(post.get("artist_key") or post.get("tip_artist")) == key
        ]

    def _structured_reason_chips_for_item(self, item: Dict[str, Any], posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chips: List[Dict[str, Any]] = []
        matching_posts = self._matching_posts_for_item(item, posts)

        if item.get("isrc"):
            chips.append(
                {
                    "label": "ISRC submitted",
                    "kind": "source",
                    "target_type": "explanation",
                    "explanation": "This track entered the prototype through a community ISRC submission and uses Deezer metadata when available.",
                }
            )
        elif item.get("is_custom"):
            chips.append(
                {
                    "label": "Community submitted",
                    "kind": "source",
                    "target_type": "explanation",
                    "explanation": "This artist was added by a user and is stored locally so it can reappear in discovery.",
                }
            )
        elif item.get("source") in {"dataset", "feed", "discover", "search", "trending"}:
            chips.append(
                {
                    "label": "Dataset match",
                    "kind": "source",
                    "target_type": "explanation",
                    "explanation": "This artist comes from the local Spotify-track dataset used as the prototype discovery base.",
                }
            )

        seen_slugs: set[str] = set()
        for post in matching_posts:
            slug = post.get("community_slug") or self._community_slug_for_text(
                " ".join(str(post.get(key) or "") for key in ("text", "tip_artist", "tip_song"))
            )
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            chips.append(
                {
                    "label": f"Shared in {self._community_name(slug)}",
                    "kind": "community",
                    "target_type": "community",
                    "target_key": slug,
                    "explanation": "Backed by a stored community post, not a fake activity count.",
                }
            )

        metrics = item.get("metrics") or {}
        listeners = metrics.get("lastfm_listeners") or metrics.get("deezer_fans")
        if listeners is not None:
            try:
                if float(listeners) <= 50000:
                    chips.append(
                        {
                            "label": "Under 50k listeners/fans",
                            "kind": "small_artist",
                            "target_type": "explanation",
                            "explanation": "The available listener/fan proxy is below the prototype's small-artist threshold.",
                        }
                    )
            except (TypeError, ValueError):
                pass

        if item.get("cluster_label"):
            chips.append(
                {
                    "label": f"Underground cluster: {item['cluster_label']}",
                    "kind": "cluster",
                    "target_type": "explanation",
                    "explanation": "A K-means cluster is used as a loose discovery context, not as absolute recommendation truth.",
                }
            )

        if item.get("small_artist_score") is not None:
            chips.append(
                {
                    "label": f"Small score {round(float(item.get('small_artist_score') or 0) * 100)}",
                    "kind": "small_score",
                    "target_type": "explanation",
                    "explanation": "Higher small score means the ranking system sees this as less mainstream based on available proxies.",
                }
            )

        return chips[:6]

    def _community_signals_for_item(self, item: Dict[str, Any], posts: Sequence[Dict[str, Any]]) -> List[str]:
        return [chip["label"] for chip in self._structured_reason_chips_for_item(item, posts)][:4]

    def _community_appearances_for_item(self, item: Dict[str, Any], posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        appearances: List[Dict[str, Any]] = []
        for post in self._matching_posts_for_item(item, posts):
            slug = post.get("community_slug") or self._community_slug_for_text(
                " ".join(str(post.get(key) or "") for key in ("text", "tip_artist", "tip_song"))
            )
            appearances.append(
                {
                    "post_id": post.get("id"),
                    "community_slug": slug,
                    "community_name": self._community_name(slug),
                    "text": post.get("text"),
                    "username": post.get("username"),
                    "created_at": post.get("created_at"),
                    "reply_count": len(post.get("replies") or []),
                }
            )
        return appearances[:6]

    def community_discussions_for_song(self, item: Dict[str, Any], limit: int = 12) -> List[Dict[str, Any]]:
        target = self._with_song_identity(item)
        state = self.store.snapshot()
        discussions: List[Dict[str, Any]] = []

        for post in state.get("community_posts", []):
            match_reason = self._community_post_song_match_reason(target, post)
            if not match_reason:
                continue

            origin = self._community_origin(post)
            parent_text = post.get("text") or ""
            parent_summary = self._short_summary(parent_text)

            if parent_text:
                discussions.append(
                    {
                        "post_id": post.get("id"),
                        "reply_id": None,
                        "text": parent_text,
                        "username": post.get("username") or "du",
                        "created_at": post.get("created_at"),
                        "source": origin["source"],
                        "community_slug": origin["community_slug"],
                        "community_name": origin["community_name"],
                        "origin_label": origin["origin_label"],
                        "parent_text": parent_text,
                        "parent_summary": parent_summary,
                        "match_reason": match_reason,
                    }
                )

            for reply in post.get("replies") or []:
                if not reply.get("text"):
                    continue
                discussions.append(
                    {
                        "post_id": post.get("id"),
                        "reply_id": reply.get("id"),
                        "text": reply.get("text"),
                        "username": reply.get("username") or "du",
                        "created_at": reply.get("created_at"),
                        "source": origin["source"],
                        "community_slug": origin["community_slug"],
                        "community_name": origin["community_name"],
                        "origin_label": origin["origin_label"],
                        "parent_text": parent_text,
                        "parent_summary": parent_summary,
                        "match_reason": match_reason,
                    }
                )

        discussions.sort(key=lambda entry: entry.get("created_at") or "", reverse=True)
        return discussions[: max(1, min(int(limit or 12), 50))]

    def _community_post_song_match_reason(self, target: Dict[str, Any], post: Dict[str, Any]) -> str:
        for field in ("song_key", "track_key", "track_id", "isrc"):
            target_value = normalize_key(target.get(field))
            post_value = normalize_key(post.get(field))
            if target_value and post_value and target_value == post_value:
                return field

        target_artist = normalize_key(target.get("artist_key") or target.get("artist") or target.get("artist_name"))
        post_artist = normalize_key(post.get("artist_key") or post.get("tip_artist") or post.get("artist"))
        target_title = normalize_track_title(target.get("song") or target.get("title") or target.get("track_title"))
        post_title = normalize_track_title(post.get("song") or post.get("title") or post.get("tip_song") or post.get("track_title"))
        if target_artist and post_artist and target_artist == post_artist and target_title and post_title and target_title == post_title:
            return "artist_title"

        return ""

    def _community_origin(self, post: Dict[str, Any]) -> Dict[str, Any]:
        source = normalize_key(post.get("source") or post.get("visibility"))
        slug = post.get("community_slug")
        if source == "feed":
            return {
                "source": "feed",
                "community_slug": None,
                "community_name": "Allmänt community",
                "origin_label": "Från allmänt community",
            }
        if source == "community":
            community_name = self._community_name(slug)
            return {
                "source": "community",
                "community_slug": slug,
                "community_name": community_name,
                "origin_label": f"Från {community_name}",
            }
        return {
            "source": source or "",
            "community_slug": slug,
            "community_name": self._community_name(slug) if slug else "Community",
            "origin_label": "Äldre communitypost",
        }

    @staticmethod
    def _short_summary(value: Any, limit: int = 120) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"

    def _related_artist_links(self, artists: Sequence[str]) -> List[Dict[str, Any]]:
        links: List[Dict[str, Any]] = []
        for artist in artists[:8]:
            key = normalize_key(artist)
            links.append(
                {
                    "artist": artist,
                    "artist_key": key,
                    "available": bool(self.dataset.artist_record(key)),
                }
            )
        return links

    def _discovery_trail_for_item(self, item: Dict[str, Any], posts: Sequence[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
        if not item:
            return []
        posts = posts or []
        trail: List[Dict[str, Any]] = []
        if item.get("is_custom") or item.get("isrc"):
            trail.append(
                {
                    "label": "ISRC/community submitted",
                    "kind": "source",
                    "target_type": "explanation",
                    "explanation": "This track was added through the community submission flow and stored locally for future discovery.",
                }
            )
        else:
            trail.append(
                {
                    "label": "Found in the underground dataset",
                    "kind": "source",
                    "target_type": "explanation",
                    "explanation": "This comes from the local Spotify tracks dataset, which acts as the prototype's discovery base.",
                }
            )

        matching_posts = self._matching_posts_for_item(item, posts)
        if matching_posts:
            slug = matching_posts[0].get("community_slug") or self._community_slug_for_text(
                " ".join(str(matching_posts[0].get(key) or "") for key in ("text", "tip_artist", "tip_song"))
            )
            trail.append(
                {
                    "label": f"Shared in {self._community_name(slug)}",
                    "kind": "community",
                    "target_type": "community",
                    "target_key": slug,
                    "explanation": "This step is backed by a stored community post.",
                }
            )
        elif item.get("community_slug"):
            slug = item.get("community_slug")
            trail.append(
                {
                    "label": f"Connected to {self._community_name(slug)}",
                    "kind": "community",
                    "target_type": "community",
                    "target_key": slug,
                    "explanation": "This item carries a community slug from submission or feed context.",
                }
            )

        if item.get("cluster_label"):
            trail.append(
                {
                    "label": f"Cluster context: {str(item['cluster_label']).lower()}",
                    "kind": "cluster",
                    "target_type": "explanation",
                    "explanation": "Cluster context is a loose ML discovery aid, not proof that users recommended it.",
                }
            )
        if item.get("small_artist_score") is not None:
            trail.append(
                {
                    "label": "Kept below the mainstream threshold",
                    "kind": "small_artist",
                    "target_type": "explanation",
                    "explanation": "The recommendation system boosts smaller artists using popularity/listener proxies.",
                }
            )
        trail.append(
            {
                "label": "Shown as a quiet discovery",
                "kind": "discovery",
                "target_type": "explanation",
                "explanation": "This is editorial wording for low-mainstream discovery, not a fake trending count.",
            }
        )
        return trail[:5]

    def _community_activity(self, artist_pool: Sequence[Dict[str, Any]], posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        activity = []
        for post in posts[:4]:
            artist_key = post.get("artist_key") or normalize_key(post.get("tip_artist"))
            activity.append(
                {
                    "text": f"New post in {self._community_name(post.get('community_slug'))}",
                    "artist_key": artist_key,
                    "community_slug": post.get("community_slug"),
                }
            )
        for item in [entry for entry in artist_pool if entry.get("is_custom") or entry.get("isrc")][:2]:
            activity.append(
                {
                    "text": f"ISRC submission: {item.get('artist') or 'new artist'}",
                    "artist_key": item.get("artist_key"),
                }
            )
        return activity[:6]

    def _item_matches_community(self, item: Dict[str, Any], spec: Dict[str, Any]) -> bool:
        values = [
            item.get("genre"),
            item.get("cluster_label"),
            item.get("artist"),
            item.get("song"),
            item.get("note"),
            " ".join(item.get("top_genres") or []),
            " ".join(item.get("discovery_labels") or []),
        ]
        normalized = normalize_text(" ".join(str(value or "") for value in values))
        genres = set(normalize_genre_list([item.get("genre"), *(item.get("top_genres") or [])]))
        return bool(genres.intersection(spec.get("genres") or [])) or any(term in normalized for term in spec.get("terms") or [])

    def _community_slug_for_text(self, value: str) -> str:
        normalized = normalize_text(value)
        for spec in MICRO_COMMUNITIES:
            if any(term in normalized for term in spec["terms"]):
                return spec["slug"]
        return "late-night-discoveries"

    def _community_name(self, slug: str | None) -> str:
        for spec in self._community_specs():
            if spec["slug"] == slug:
                return spec["name"]
        return "the community"

    def _activity_label(self, post: Dict[str, Any]) -> str:
        replies = len(post.get("replies") or [])
        saved_label = "saved to profile" if post.get("saved_by_you") else "community post"
        return f"{saved_label} - {replies} repl{'y' if replies == 1 else 'ies'}"

    def _cluster_label(self, cluster_id: Any) -> str:
        try:
            numeric_id = int(cluster_id)
        except (TypeError, ValueError):
            return ""
        return f"KMeans cluster {numeric_id}" if numeric_id >= 0 else ""

    def _basic_tags(self, row: Dict[str, Any], extra_terms: Sequence[str] | None = None) -> List[str]:
        tags: List[str] = []
        genre = str(row.get("track_genre") or row.get("genre") or "").strip()
        if genre:
            tags.append(genre)
        for term in extra_terms or []:
            normalized = normalize_text(term)
            if normalized and normalized not in tags:
                tags.append(normalized)
        return tags[:8]

    # Request normalization and listener context.
    def _resolve_request_genre_values(self, request: Dict[str, Any], genre_labels: Sequence[str]) -> List[str]:
        values = set(self.dataset.map_genre_labels(genre_labels))
        values.update(normalize_genre_list(genre_labels))
        values.update(normalize_genre_list(request.get("dataset_genres", [])))
        return sorted(values)

    def _normalize_property_targets(self, targets: Dict[str, float]) -> Dict[str, float]:
        clean: Dict[str, float] = {}
        for feature in FEATURE_COLUMNS:
            if feature not in targets:
                continue
            try:
                value = float(targets[feature])
            except (TypeError, ValueError):
                continue
            if feature == "tempo":
                clean[feature] = round(max(55.0, min(190.0, value)), 3)
            else:
                clean[feature] = round(max(0.0, min(1.0, value)), 3)
        return clean

    def _property_terms(self, targets: Dict[str, float]) -> List[str]:
        terms: List[str] = []
        energy = targets.get("energy")
        valence = targets.get("valence")
        danceability = targets.get("danceability")
        acousticness = targets.get("acousticness")
        instrumentalness = targets.get("instrumentalness")
        tempo = targets.get("tempo")
        if energy is not None:
            terms.append("energetic" if energy >= 0.64 else "calm" if energy <= 0.36 else "balanced")
        if valence is not None:
            terms.append("happy" if valence >= 0.62 else "dark" if valence <= 0.36 else "neutral")
        if danceability is not None and danceability >= 0.62:
            terms.append("dance")
        if acousticness is not None and acousticness >= 0.48:
            terms.append("acoustic")
        if instrumentalness is not None and instrumentalness >= 0.32:
            terms.append("instrumental")
        if tempo is not None:
            terms.append("fast" if tempo >= 124 else "slow" if tempo <= 92 else "midtempo")
        return list(dict.fromkeys(terms))

    def _build_library_context(self, state: Dict[str, Any], custom_tracks: Sequence[Dict[str, Any]]) -> LibraryContext:
        items = self._combined_library_items(state, custom_tracks)
        preferred_genres = Counter()
        similar_artist_keys: set[str] = set()
        vectors: List[Dict[str, float]] = []
        tags = Counter()
        cluster_counter = Counter()
        seed_names: List[str] = []

        for item in items:
            if item.get("artist"):
                seed_names.append(item.get("artist"))
            preferred_genres.update(item.get("top_genres", []))
            similar_artist_keys.update(normalize_key(name) for name in item.get("similar_artists", []))
            audio_signature = item.get("audio_signature", {})
            if audio_signature:
                vectors.append(audio_signature)
            tags.update(item.get("discovery_labels", []))
            tags.update(item.get("top_genres", []))
            tags.update(item.get("tags", []))
            if item.get("cluster_id") is not None:
                cluster_counter.update([int(item.get("cluster_id", -1))])

        avg_vector = self._average_vectors(vectors)
        return LibraryContext(
            seed_names=[name for name in seed_names if name][:8],
            preferred_genres=[genre for genre, _ in preferred_genres.most_common(6)],
            similar_artist_keys=similar_artist_keys,
            avg_vector=avg_vector,
            preferred_clusters=[cluster_id for cluster_id, _ in cluster_counter.most_common(4) if cluster_id >= 0],
            preferred_tags=[tag for tag, _ in tags.most_common(8)],
        )

    # Candidate construction and ranking.
    def _build_candidate_frame(
        self,
        genre_labels: Sequence[str],
        request: Dict[str, Any],
        context: LibraryContext,
        custom_tracks: Sequence[Dict[str, Any]],
        mode: str,
    ) -> pd.DataFrame:
        genre_values = self._resolve_request_genre_values(request, genre_labels)
        if genre_values:
            dataset_frame = self.dataset.df[self.dataset.df["track_genre"].isin(genre_values)].copy()
        else:
            dataset_frame = self.dataset.rows_for_genres(genre_labels)
        if dataset_frame.empty and not genre_values:
            dataset_frame = self.dataset.df.copy()

        dataset_frame = dataset_frame.copy()
        if "cluster_id" not in dataset_frame.columns:
            dataset_frame["cluster_id"] = self.intelligence.assign_cluster_ids(dataset_frame)
        else:
            missing_mask = dataset_frame["cluster_id"].isna()
            if missing_mask.any():
                dataset_frame.loc[missing_mask, "cluster_id"] = self.intelligence.assign_cluster_ids(dataset_frame.loc[missing_mask])

        if mode == "feed" and context.preferred_clusters:
            cluster_ids = set(context.preferred_clusters)
            filtered = dataset_frame[dataset_frame["cluster_id"].isin(cluster_ids)]
            if not filtered.empty:
                dataset_frame = filtered.copy()

        if len(dataset_frame) > 16000:
            candidate_subset = dataset_frame.sort_values(
                ["local_small_artist_score", "popularity"],
                ascending=[False, True],
            ).head(12000)
            explore_subset = dataset_frame.sample(4000, random_state=len(request.get("tokens", [])) + 23)
            dataset_frame = pd.concat([candidate_subset, explore_subset], ignore_index=False).drop_duplicates(subset=["track_key"])

        dataset_frame["source"] = "dataset"
        dataset_frame["is_custom"] = False
        dataset_frame["source_weight"] = 1.0
        dataset_frame["small_artist_score"] = dataset_frame["local_small_artist_score"].fillna(0.28)
        dataset_frame["cluster_label"] = dataset_frame["cluster_id"].map(self._cluster_label)
        dataset_frame["discovery_labels"] = [[] for _ in range(len(dataset_frame))]

        custom_frame = self._build_custom_frame(custom_tracks)
        resolved_genre_values = set(self._resolve_request_genre_values(request, genre_labels))
        if resolved_genre_values and not custom_frame.empty:
            genre_values = resolved_genre_values
            genre_match = custom_frame["track_genre"].isin(genre_values)
            custom_frame = custom_frame[genre_match].copy()

        if not custom_frame.empty:
            combined = pd.concat([dataset_frame, custom_frame], ignore_index=True, sort=False)
        else:
            combined = dataset_frame

        for feature in FEATURE_COLUMNS:
            if feature not in combined.columns:
                combined[feature] = np.nan
        combined["metadata_text"] = combined["metadata_text"].fillna("")
        combined["track_key"] = combined["track_key"].fillna(combined["track_id"].fillna(""))
        combined["cluster_id"] = combined["cluster_id"].fillna(-1).astype(int)
        combined["track_genre"] = combined["track_genre"].fillna("unknown")
        combined["artist_key"] = combined["artist_key"].fillna("")
        combined["primary_artist"] = combined["primary_artist"].fillna(combined.get("artist", ""))
        combined["track_name"] = combined["track_name"].fillna(combined.get("song", ""))
        combined["album_name"] = combined["album_name"].fillna(combined.get("album", ""))
        if "audio_validated" not in combined.columns:
            combined["audio_validated"] = ~combined["is_custom"].astype(bool)
        else:
            combined["audio_validated"] = combined["audio_validated"].fillna(~combined["is_custom"].astype(bool)).astype(bool)
        if "estimated_mood_profile" not in combined.columns:
            combined["estimated_mood_profile"] = [{} for _ in range(len(combined))]
        else:
            combined["estimated_mood_profile"] = combined["estimated_mood_profile"].apply(
                lambda value: value if isinstance(value, dict) else {}
            )
        if "mood_source" not in combined.columns:
            combined["mood_source"] = np.where(combined["audio_validated"], "dataset", "")
        else:
            combined["mood_source"] = combined["mood_source"].fillna("")
        combined["small_artist_score"] = pd.to_numeric(combined["small_artist_score"], errors="coerce").fillna(0.25)
        return combined.reset_index(drop=True)

    def _build_custom_frame(self, custom_tracks: Sequence[Dict[str, Any]]) -> pd.DataFrame:
        records = [self._build_custom_candidate_row(item) for item in custom_tracks]
        if not records:
            return pd.DataFrame(columns=self.dataset.df.columns.tolist() + ["source", "is_custom"])
        return pd.DataFrame(records)

    def _build_custom_candidate_row(self, item: Dict[str, Any]) -> Dict[str, Any]:
        genre = normalize_genre(item.get("genre") or (item.get("top_genres") or ["unknown"])[0] or "unknown")
        top_genres = normalize_genre_list(item.get("top_genres", []))
        metrics = dict(item.get("metrics") or {})
        audio_is_validated = bool(item.get("audio_validated", metrics.get("audio_features_validated")))
        audio = dict(item.get("audio_signature") or {}) if audio_is_validated else {}
        metadata_text = item.get("metadata_text") or self._compose_metadata_text(
            song=item.get("song"),
            artist=item.get("artist"),
            album=item.get("album"),
            genre=genre,
            tags=item.get("tags", []),
            note=item.get("note", ""),
        )
        small_score = float(item.get("small_artist_score") or self._calculate_small_artist_score({}, metrics, is_custom=True))
        cluster_id = int(item.get("cluster_id", -1) or -1)
        if cluster_id >= 0:
            cluster_label = item.get("cluster_label") or self._cluster_label(cluster_id)
        else:
            cluster_label = item.get("cluster_label") or "Freshly added cluster"
        mood_context = {
            "genre": genre,
            "track_genre": genre,
            "metadata_text": metadata_text,
            "cluster_label": cluster_label,
        }
        if audio_is_validated:
            mood_profile = item.get("mood_profile") or {}
            estimated_mood_profile = {}
            mood_source = item.get("mood_source") or "dataset"
        else:
            mood_profile = {}
            estimated_mood_profile = {}
            mood_source = ""
        return {
            "song_key": item.get("song_key") or item.get("track_key") or item.get("isrc") or item.get("track_id"),
            "track_id": item.get("track_id") or item.get("isrc") or item.get("track_key"),
            "track_key": item.get("track_key") or item.get("isrc") or item.get("track_id"),
            "artists": item.get("artist"),
            "primary_artist": item.get("artist"),
            "artist_key": item.get("artist_key"),
            "track_name": item.get("song"),
            "album_name": item.get("album"),
            "track_genre": genre,
            "popularity": float(metrics["spotify_popularity"]) if metrics.get("spotify_popularity") is not None else np.nan,
            "danceability": float(audio["danceability"]) if "danceability" in audio else np.nan,
            "energy": float(audio["energy"]) if "energy" in audio else np.nan,
            "valence": float(audio["valence"]) if "valence" in audio else np.nan,
            "acousticness": float(audio["acousticness"]) if "acousticness" in audio else np.nan,
            "instrumentalness": float(audio["instrumentalness"]) if "instrumentalness" in audio else np.nan,
            "tempo": float(audio["tempo"]) if "tempo" in audio else np.nan,
            "search_blob": metadata_text.lower(),
            "metadata_text": metadata_text,
            "source": "custom",
            "is_custom": True,
            "source_weight": float(item.get("source_weight", 1.25)),
            "small_artist_score": small_score,
            "cluster_id": cluster_id,
            "cluster_label": cluster_label,
            "top_genres": top_genres,
            "similar_artists": item.get("similar_artists", []),
            "metrics": metrics,
            "audio_signature": audio,
            "preview": item.get("preview"),
            "image": item.get("image"),
            "deezer_link": item.get("deezer_link"),
            "lastfm_link": item.get("lastfm_link"),
            "audio_validated": audio_is_validated,
            "mood_profile": mood_profile,
            "estimated_mood_profile": estimated_mood_profile,
            "mood_source": mood_source,
            "discovery_labels": item.get("discovery_labels", []),
            "small_artist_reason": item.get("reason", ""),
            "added_at": item.get("added_at"),
            "note": item.get("note", ""),
        }

    def _score_candidate_frame(
        self,
        frame: pd.DataFrame,
        request: Dict[str, Any],
        context: LibraryContext,
        mode: str,
    ) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        working = frame.copy()
        thresholds = self._small_artist_thresholds()
        popularity_series = pd.to_numeric(working["popularity"], errors="coerce")
        if not self.small_artist_filter_paused:
            large_dataset_mask = (
                ~working["is_custom"].astype(bool)
                & (working["small_artist_score"].astype(float) < 0.34)
                & (popularity_series.fillna(0) > thresholds["spotify_avg_popularity_max"] + 5)
            )
            working = working[~large_dataset_mask].copy()
        if working.empty:
            return working

        score = pd.Series(0.0, index=working.index, dtype=float)
        history_window = max(self.settings.recent_track_window, self.settings.recent_artist_window, self.settings.cluster_count * 3)
        recent_events = self.sqlite_store.recent_feed_events(limit=history_window)
        recent_artist_events = recent_events[: self.settings.recent_artist_window]
        recent_track_events = recent_events[: self.settings.recent_track_window]
        recent_cluster_events = recent_events[: max(12, self.settings.cluster_count * 2)]
        recent_artist_counts = Counter(event.get("artist_key") for event in recent_artist_events if event.get("artist_key"))
        recent_track_counts = Counter(event.get("track_key") for event in recent_track_events if event.get("track_key"))
        recent_cluster_counts = Counter(int(event.get("cluster_id")) for event in recent_cluster_events if event.get("cluster_id") is not None)

        prompt_mode = str(request.get("prompt_mode") or "open")
        explicit_genre_terms = [
            normalize_text(term)
            for term in request.get("explicit_genre_terms", [])
            if normalize_text(term)
        ]
        audio_emphasis = float(request.get("audio_emphasis", 1.0) or 1.0)
        mood_weight_scale = 1.0
        if mode == "search" and request.get("mood_targets"):
            if prompt_mode in {"mood", "context"}:
                mood_weight_scale = max(0.7, min(1.45, audio_emphasis))
            elif prompt_mode == "mixed":
                mood_weight_scale = max(0.82, min(1.22, 1.0 + ((audio_emphasis - 1.0) * 0.55)))
        mood_context_priority = (
            mode == "search"
            and prompt_mode in {"mood", "context"}
            and not explicit_genre_terms
        )
        primary_genres = set(normalize_genre_list(request.get("primary_dataset_genres", [])))
        supporting_genres = set(normalize_genre_list(request.get("supporting_dataset_genres", []))) - primary_genres
        selected_genres = primary_genres | supporting_genres | set(self._resolve_request_genre_values(request, request.get("genres", [])))

        working["genre_match_score"] = working["track_genre"].isin(selected_genres).astype(float) if selected_genres else 0.0
        working["primary_genre_match_score"] = working["track_genre"].isin(primary_genres).astype(float) if primary_genres else 0.0
        working["supporting_genre_match_score"] = working["track_genre"].isin(supporting_genres).astype(float) if supporting_genres else 0.0

        if mode == "search":
            if mood_context_priority:
                primary_weight, supporting_weight = 1.15, 0.45
            elif prompt_mode == "genre":
                primary_weight, supporting_weight = 3.2, 1.4
            elif prompt_mode == "mixed":
                primary_weight, supporting_weight = 2.9, 1.2
            elif prompt_mode in {"mood", "context"}:
                primary_weight, supporting_weight = 2.0, 0.95
            else:
                primary_weight, supporting_weight = 2.6, 1.0
            score += working["primary_genre_match_score"] * primary_weight
            score += working["supporting_genre_match_score"] * supporting_weight
            if not primary_genres and not supporting_genres:
                score += working["genre_match_score"] * 2.2
        else:
            score += working["genre_match_score"] * 1.8

        intent_terms = [normalize_text(term) for term in request.get("intent_terms", [])[:10] if normalize_text(term)]
        if intent_terms:
            intent_text = (
                working["metadata_text"].fillna("")
                + " "
                + working["track_genre"].fillna("")
                + " "
                + working["cluster_label"].fillna("")
            )
            intent_bonus = intent_text.map(
                lambda value: min(
                    sum(0.22 for term in intent_terms if term and term in normalize_text(value)),
                    0.88,
                )
            )
            score += intent_bonus

        if context.preferred_genres:
            score += working["track_genre"].isin(set(context.preferred_genres)).astype(float) * 0.55

        if context.similar_artist_keys:
            score += working["artist_key"].isin(context.similar_artist_keys).astype(float) * 1.1

        if context.preferred_clusters:
            cluster_weight = 0.55 if mode == "search" else 1.0
            score += working["cluster_id"].isin(set(context.preferred_clusters)).astype(float) * cluster_weight

        prompt_cluster_scores = request.get("prompt_cluster_scores") or {}
        if mode == "search" and prompt_cluster_scores:
            working["prompt_cluster_score"] = working["cluster_id"].map(
                lambda cluster_id: float(prompt_cluster_scores.get(int(cluster_id), 0.0))
            )
            if prompt_mode in {"mood", "context"}:
                prompt_cluster_weight = 0.54
            elif prompt_mode == "mixed":
                prompt_cluster_weight = 0.66
            elif prompt_mode == "genre":
                prompt_cluster_weight = 0.72
            elif prompt_mode == "property":
                prompt_cluster_weight = 0.84
            else:
                prompt_cluster_weight = 0.48
            score += working["prompt_cluster_score"] * prompt_cluster_weight
        else:
            working["prompt_cluster_score"] = 0.0

        if prompt_mode == "property" and "property_group_score" in working.columns:
            score += pd.to_numeric(working["property_group_score"], errors="coerce").fillna(0.0) * 2.1

        # Only validated numeric audio should influence the high-confidence mood match.
        for feature, target in request.get("mood_targets", {}).items():
            if feature in working.columns:
                if mode == "search":
                    if mood_context_priority:
                        numeric_weight = 1.28
                    elif prompt_mode == "genre":
                        numeric_weight = 0.38
                    elif prompt_mode == "mixed":
                        numeric_weight = 0.74
                    else:
                        numeric_weight = 0.88
                else:
                    numeric_weight = 0.9
                score += self._numeric_mood_match_series(pd.to_numeric(working[feature], errors="coerce"), target, feature) * (numeric_weight * mood_weight_scale)

        if request.get("mood_targets") and mode == "search":
            if mood_context_priority:
                validated_bonus = working["audio_validated"].astype(float) * (0.55 * max(0.85, min(1.28, mood_weight_scale)))
            else:
                base_validated_bonus = 0.22 if prompt_mode in {"mood", "context", "mixed"} else 0.08
                validated_bonus = working["audio_validated"].astype(float) * (
                    base_validated_bonus * max(0.82, min(1.14, 0.95 + ((mood_weight_scale - 1.0) * 0.3)))
                )
            score += validated_bonus

        for feature, target in context.avg_vector.items():
            if feature in working.columns:
                score += self._numeric_mood_match_series(pd.to_numeric(working[feature], errors="coerce"), target, feature) * 0.24

        small_artist_weight = 0.0 if self.small_artist_filter_paused else (2.05 if mood_context_priority else 3.9)
        score += working["small_artist_score"].astype(float) * small_artist_weight
        score += working["is_custom"].astype(float) * 0.65
        if request.get("underground_focus", True) and not self.small_artist_filter_paused:
            underground_weight = 0.4 if mood_context_priority else 1.1
            score += working["small_artist_score"].astype(float) * underground_weight

        custom_recency_bonus = working["added_at"].apply(self._freshness_bonus) if "added_at" in working.columns else 0.0
        score += custom_recency_bonus
        working["custom_recency_bonus"] = custom_recency_bonus

        score -= working["artist_key"].map(lambda key: min(recent_artist_counts.get(key, 0), 4) * 0.72)
        score -= working["track_key"].map(lambda key: min(recent_track_counts.get(key, 0), 4) * 1.1)
        score -= working["cluster_id"].map(lambda key: min(recent_cluster_counts.get(int(key), 0), 4) * 0.18)

        if not self.small_artist_filter_paused:
            mainstream_penalty = (1 - working["small_artist_score"].astype(float)).clip(lower=0) * 2.5
            score -= mainstream_penalty
            score -= (popularity_series.fillna(thresholds["spotify_avg_popularity_max"]) > thresholds["spotify_avg_popularity_max"]).astype(float) * 0.85

        if request.get("disable_text_similarity"):
            token_bonus = pd.Series(0.0, index=working.index, dtype=float)
        else:
            token_bonus = working["metadata_text"].fillna("").map(
                lambda value: sum(0.16 for token in request.get("tokens", [])[:8] if token and token in normalize_text(value))
            )
        score += token_bonus

        rng = np.random.default_rng(len(recent_events) + len(request.get("tokens", [])) + (7 if mode == "feed" else 3))
        score += rng.uniform(0.0, 0.18, len(working))

        working["ranking_score"] = score
        return working.sort_values(["ranking_score", "small_artist_score"], ascending=[False, False]).reset_index(drop=True)

    # Result delivery and card/profile enrichment.
    def _prepare_ranked_frame_for_delivery(
        self,
        ranked_frame: pd.DataFrame,
        request: Dict[str, Any],
        limit: int,
        mode: str,
    ) -> tuple[pd.DataFrame, Dict[str, Any]]:
        if ranked_frame.empty or mode != "search":
            return ranked_frame, {
                "candidate_window_size": 0,
                "weighted_randomness_used": False,
            }

        prompt_mode = str(request.get("prompt_mode") or "open")
        explicit_genre_terms = [
            normalize_text(term)
            for term in request.get("explicit_genre_terms", [])
            if normalize_text(term)
        ]
        intensity_strength = float(request.get("intensity_strength", 1.0) or 1.0)

        if prompt_mode == "genre":
            base_window = max(limit * 6, 24)
        elif prompt_mode in {"mood", "context"} and not explicit_genre_terms:
            base_window = max(limit * 10, 40)
        elif prompt_mode == "mixed":
            base_window = max(limit * 8, 32)
        else:
            base_window = max(limit * 7, 28)

        if intensity_strength >= 1.25:
            base_window = int(base_window * 0.82)
        elif intensity_strength <= 0.82:
            base_window = int(base_window * 1.18)

        candidate_window_size = int(min(len(ranked_frame), max(limit * 4, min(base_window, 90))))
        if candidate_window_size <= limit + 2:
            return ranked_frame, {
                "candidate_window_size": candidate_window_size,
                "weighted_randomness_used": False,
            }

        relevant_window = ranked_frame.head(candidate_window_size).copy()
        tail = ranked_frame.iloc[candidate_window_size:].copy()

        scores = pd.to_numeric(relevant_window["ranking_score"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        shifted_scores = (scores - float(scores.min())) + 0.08
        rank_positions = np.arange(1, len(relevant_window) + 1, dtype=float)
        rank_bias_exponent = 0.33 if prompt_mode in {"mood", "context"} and not explicit_genre_terms else 0.42
        rank_bias = 1.0 / np.power(rank_positions, rank_bias_exponent)
        weights = shifted_scores * rank_bias
        weights = np.clip(weights, 1e-6, None)
        weights = weights / weights.sum()

        rng = np.random.default_rng()
        order = rng.choice(len(relevant_window), size=len(relevant_window), replace=False, p=weights)
        randomized_window = relevant_window.iloc[order].copy().reset_index(drop=True)
        prepared = pd.concat([randomized_window, tail], ignore_index=True)
        return prepared, {
            "candidate_window_size": candidate_window_size,
            "weighted_randomness_used": True,
        }

    def _assemble_results(
        self,
        ranked_frame: pd.DataFrame,
        request: Dict[str, Any],
        context: LibraryContext,
        limit: int,
        context_name: str,
    ) -> List[Dict[str, Any]]:
        if ranked_frame.empty:
            return []

        delivery_frame, delivery_meta = self._prepare_ranked_frame_for_delivery(
            ranked_frame,
            request,
            limit,
            mode=str(request.get("mode") or context_name),
        )
        request["_delivery_meta"] = delivery_meta

        results: List[Dict[str, Any]] = []
        seen_artists: set[str] = set()
        seen_tracks: set[str] = set()
        seen_clusters: Counter[int] = Counter()
        target_cluster_diversity = min(max(2, limit // 2 + 1), 4)
        use_cluster_diversity = str(request.get("prompt_mode") or "") not in {"property", "genre_only"}

        for _, row in delivery_frame.head(240).iterrows():
            track_key = str(row.get("track_key", ""))
            artist_key = str(row.get("artist_key", ""))
            cluster_id = int(row.get("cluster_id", -1))
            if not track_key or not artist_key:
                continue
            if track_key in seen_tracks or artist_key in seen_artists:
                continue
            if (
                use_cluster_diversity
                and cluster_id >= 0
                and seen_clusters[cluster_id] >= 1
                and len(results) < target_cluster_diversity
                and len(seen_clusters) < target_cluster_diversity
            ):
                continue
            if not self.small_artist_filter_paused and not row.get("is_custom") and float(row.get("small_artist_score", 0.0)) < 0.22:
                continue

            profile = self._resolve_profile_for_row(row)
            if not self.small_artist_filter_paused and not profile.get("is_small"):
                continue
            if not self._release_year_matches(profile.get("release_year"), request.get("year_filter")):
                continue

            card = self._build_card(row.to_dict(), profile, request, context, context_name)
            results.append(card)
            seen_artists.add(artist_key)
            seen_tracks.add(track_key)
            if cluster_id >= 0:
                seen_clusters[cluster_id] += 1
            if len(results) >= limit:
                break

        if results:
            return results

        fallback_results: List[Dict[str, Any]] = []
        for _, row in delivery_frame.head(40).iterrows():
            profile = self._resolve_profile_for_row(row)
            if not self.small_artist_filter_paused and not profile.get("is_small") and float(row.get("small_artist_score", 0.0)) < 0.62:
                continue
            fallback_results.append(self._build_card(row.to_dict(), profile, request, context, context_name))
            if len(fallback_results) >= limit:
                break
        return fallback_results

    def _resolve_profile_for_row(self, row: pd.Series) -> Dict[str, Any]:
        if bool(row.get("is_custom")):
            metrics = dict(row.get("metrics") or {})
            small_score = float(row.get("small_artist_score", 0.65))
            is_small, reason = self._assess_small_artist({}, metrics, small_score)
            fresh_track = self.apis.get_deezer_track(row.get("track_id"))
            audio_validated = bool(row.get("audio_validated", metrics.get("audio_features_validated")))
            if audio_validated:
                mood_profile = dict(row.get("mood_profile") or {})
                estimated_mood_profile: Dict[str, Any] = {}
                mood_source = "dataset"
            else:
                mood_profile = {}
                estimated_mood_profile = {}
                mood_source = ""
            return {
                "artist": row.get("primary_artist"),
                "top_genres": list(row.get("top_genres") or []),
                "image": fresh_track.get("image") or row.get("image"),
                "preview": self._first_usable_preview(fresh_track.get("preview"), row.get("preview")),
                "deezer_link": fresh_track.get("deezer_link") or row.get("deezer_link"),
                "lastfm_link": row.get("lastfm_link"),
                "release_year": self._extract_year_from_text(fresh_track.get("release_date") or row.get("added_at")),
                "bio": row.get("note") or "Ny inlagd upptackt som nu ar en del av plattformens vaxande bibliotek.",
                "similar_artists": list(row.get("similar_artists") or []),
                "metrics": metrics,
                "is_small": is_small,
                "smallness_reason": reason or "Eget tillskott med small web-prioritet.",
                "audio_signature": dict(row.get("audio_signature") or {}),
                "mood_profile": mood_profile,
                "estimated_mood_profile": estimated_mood_profile,
                "audio_validated": audio_validated,
                "mood_source": mood_source,
                "small_artist_score": small_score,
            }

        local = self.dataset.artist_record(row.get("artist_key"))
        return self._profile_artist(row.get("primary_artist", ""), local)

    # Artist size and card explanations.
    def _profile_artist(self, artist_name: str, local: Dict[str, Any] | None = None) -> Dict[str, Any]:
        local = local or self.dataset.artist_record(normalize_key(artist_name))
        lastfm = self.apis.get_lastfm_artist(artist_name)
        deezer = self.apis.get_deezer_artist(artist_name)
        metrics = {
            "spotify_popularity": local.get("avg_popularity") if local else None,
            "spotify_tracks": local.get("track_count") if local else None,
            "lastfm_listeners": lastfm.get("listeners"),
            "deezer_fans": deezer.get("fans"),
        }
        small_artist_score = self._calculate_small_artist_score(local, metrics, is_custom=False)
        is_small, reason = self._assess_small_artist(local, metrics, small_artist_score)

        audio_signature = {
            feature: float(local.get(f"avg_{feature}", 0))
            for feature in FEATURE_COLUMNS
            if local and local.get(f"avg_{feature}") is not None
        }
        genre_hint = (local or {}).get("top_genres", [""])[0] if local else ""
        audio_validated = bool(audio_signature)
        if audio_validated:
            mood_profile = {}
            estimated_mood_profile: Dict[str, Any] = {}
            mood_source = "dataset"
        else:
            mood_profile = {}
            estimated_mood_profile = {}
            mood_source = ""
        return {
            "artist": local.get("primary_artist") if local else artist_name,
            "top_genres": list(local.get("top_genres", [])) if local else [],
            "image": deezer.get("image"),
            "preview": self._first_usable_preview(deezer.get("preview")),
            "deezer_link": deezer.get("link"),
            "lastfm_link": lastfm.get("url"),
            "release_year": self._extract_year_from_text(deezer.get("release_date")),
            "bio": lastfm.get("bio", ""),
            "similar_artists": lastfm.get("similar_artists", []),
            "metrics": metrics,
            "is_small": is_small,
            "smallness_reason": reason,
            "audio_signature": audio_signature,
            "mood_profile": mood_profile,
            "estimated_mood_profile": estimated_mood_profile,
            "audio_validated": audio_validated,
            "mood_source": mood_source,
            "small_artist_score": small_artist_score,
        }

    def _calculate_small_artist_score(
        self,
        local_stats: Dict[str, Any] | None,
        metrics: Dict[str, Any],
        is_custom: bool,
    ) -> float:
        thresholds = self._small_artist_thresholds()
        components: List[float] = []

        spotify_popularity = metrics.get("spotify_popularity")
        if spotify_popularity is None and local_stats:
            spotify_popularity = local_stats.get("avg_popularity")
        if spotify_popularity is not None:
            cap = max(thresholds["spotify_avg_popularity_max"] * 2, 1.0)
            components.append(max(0.0, 1.0 - min(float(spotify_popularity), cap) / cap))

        lastfm_listeners = metrics.get("lastfm_listeners")
        if lastfm_listeners is not None:
            ratio = min(max(float(lastfm_listeners), 0.0) / max(thresholds["lastfm_listeners_max"], 1), 4.0)
            components.append(max(0.0, 1.0 - (math.log1p(ratio) / math.log1p(4.0))))

        deezer_fans = metrics.get("deezer_fans")
        if deezer_fans is not None:
            ratio = min(max(float(deezer_fans), 0.0) / max(thresholds["deezer_fans_max"], 1), 4.0)
            components.append(max(0.0, 1.0 - (math.log1p(ratio) / math.log1p(4.0))))

        track_count = metrics.get("spotify_tracks")
        if track_count is None and local_stats:
            track_count = local_stats.get("track_count")
        if track_count is not None:
            components.append(max(0.0, 1.0 - min(float(track_count), 40.0) / 40.0) * 0.55)

        if components:
            score = float(sum(components) / len(components))
        else:
            score = 0.58 if is_custom else 0.32

        if is_custom and not components:
            score += 0.04
        return round(max(0.0, min(score, 1.0)), 4)

    def _assess_small_artist(
        self,
        local: Dict[str, Any],
        metrics: Dict[str, Any],
        small_artist_score: float,
    ) -> tuple[bool, str]:
        if self.small_artist_filter_paused:
            return True, "Small artist-filtret ar pausat for testlage."

        thresholds = self._small_artist_thresholds()
        checks = []
        spotify_popularity = metrics.get("spotify_popularity")
        if spotify_popularity is not None:
            checks.append(("Spotify-popularitet", float(spotify_popularity) <= thresholds["spotify_avg_popularity_max"]))
        lastfm_listeners = metrics.get("lastfm_listeners")
        if lastfm_listeners is not None:
            checks.append(("Last.fm-lyssnare", float(lastfm_listeners) <= thresholds["lastfm_listeners_max"]))
        deezer_fans = metrics.get("deezer_fans")
        if deezer_fans is not None:
            checks.append(("Deezer-fans", float(deezer_fans) <= thresholds["deezer_fans_max"]))

        passed = [label for label, is_ok in checks if is_ok]
        strict_pass = bool(checks) and len(passed) == len(checks)
        soft_pass = not checks and small_artist_score >= 0.72
        is_small = strict_pass or soft_pass

        if strict_pass:
            reason = "Small artist boost via " + ", ".join(label.lower() for label in passed[:3]) + "."
        elif soft_pass:
            reason = "Boostad av datasetets small-score fallback nar externa lyssnarsiffror saknas."
        else:
            reason = "Filtreras ned eftersom lyssnar-, fan- eller popularitetssignaler pekar for langt mot mainstream."
        return is_small, reason

    def _build_card(
        self,
        row: Dict[str, Any],
        profile: Dict[str, Any],
        request: Dict[str, Any],
        context: LibraryContext,
        context_name: str,
    ) -> Dict[str, Any]:
        similarity_score = 0.0
        small_artist_score = float(profile.get("small_artist_score", row.get("small_artist_score", 0.0)) or 0.0)
        discovery_labels = self._build_discovery_labels(
            row=row,
            similarity_score=similarity_score,
            small_artist_score=small_artist_score,
            custom_recency_boost=float(row.get("custom_recency_bonus", 0.0) or 0.0),
        )

        secondary_tracks = []
        if not row.get("is_custom"):
            secondary_tracks = self.dataset.rows_for_artist_key(row["artist_key"]).sort_values(
                "popularity", ascending=False
            )["track_name"].head(3).tolist()
            secondary_tracks = [track for track in secondary_tracks if track and track != row.get("track_name")]

        audio_validated = bool(profile.get("audio_validated", row.get("audio_validated", not bool(row.get("is_custom")))))
        mood_profile = profile.get("mood_profile") or {}
        estimated_mood_profile: Dict[str, Any] = {}
        display_mood_profile = mood_profile
        cluster_id = int(row.get("cluster_id", -1))
        cluster_label = row.get("cluster_label") or self._cluster_label(cluster_id)
        mood_source = profile.get("mood_source") or row.get("mood_source") or ("dataset" if audio_validated else "")
        track_audio_signature = self._row_audio_signature(row)
        track_media = self._resolve_track_media(row)
        reason = self._build_reason_text(
            request=request,
            profile=profile,
            cluster_label=cluster_label,
            mood_profile=display_mood_profile,
            similarity_score=similarity_score,
        )

        return self._with_song_identity({
            "song_key": row.get("song_key") or row.get("track_key"),
            "track_key": row.get("track_key"),
            "track_id": row.get("track_id"),
            "artist_key": row.get("artist_key"),
            "artist": row.get("primary_artist"),
            "song": row.get("track_name"),
            "title": row.get("track_name"),
            "secondary_tracks": secondary_tracks[:2],
            "genre": row.get("track_genre"),
            "album": row.get("album_name"),
            "reason": reason,
            "bio": profile.get("bio", ""),
            "image": track_media.get("image") or profile.get("image") or row.get("image"),
            "preview": self._first_usable_preview(track_media.get("preview"), row.get("preview")),
            "deezer_link": track_media.get("deezer_link") or row.get("deezer_link") or profile.get("deezer_link"),
            "lastfm_link": profile.get("lastfm_link") or row.get("lastfm_link"),
            "metrics": profile.get("metrics", row.get("metrics", {})),
            "top_genres": profile.get("top_genres", row.get("top_genres", [])),
            "similar_artists": profile.get("similar_artists", row.get("similar_artists", [])),
            "audio_signature": track_audio_signature or profile.get("audio_signature", row.get("audio_signature", {})),
            "mood_profile": mood_profile,
            "estimated_mood_profile": estimated_mood_profile,
            "audio_validated": audio_validated,
            "mood_source": mood_source,
            "discovery_labels": discovery_labels,
            "cluster_id": cluster_id,
            "cluster_label": cluster_label,
            "small_artist_score": small_artist_score,
            "source": row.get("source", context_name),
            "is_custom": bool(row.get("is_custom")),
            "added_at": row.get("added_at"),
            "note": row.get("note", ""),
        })

    def _resolve_track_media(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if bool(row.get("is_custom")):
            return {}
        return self.apis.search_deezer_track(row.get("primary_artist"), row.get("track_name"))

    def _with_track_media(self, item: Dict[str, Any]) -> Dict[str, Any]:
        if item.get("image") and self._usable_preview_url(item.get("preview")) and item.get("deezer_link"):
            return item

        track_id = item.get("track_id")
        if track_id is not None and str(track_id).strip().isdigit():
            media = self.apis.get_deezer_track(track_id)
        else:
            media = self.apis.search_deezer_track(
                item.get("artist") or item.get("primary_artist"),
                item.get("song") or item.get("title") or item.get("track_name"),
            )
        if not media.get("image"):
            media = {
                **media,
                **self.apis.get_spotify_track_image(item.get("track_key") or item.get("song_key") or item.get("track_id")),
            }
        if not media.get("image"):
            media = {
                **media,
                "image": self.apis.get_deezer_artist(item.get("artist") or item.get("primary_artist")).get("image"),
            }
        if not any(media.get(key) for key in ("image", "preview", "deezer_link", "track_id", "isrc", "album")):
            if item.get("preview") and not self._usable_preview_url(item.get("preview")):
                payload = dict(item)
                payload["preview"] = ""
                return payload
            return item
        payload = dict(item)
        payload["preview"] = self._first_usable_preview(media.get("preview"), payload.get("preview"))
        for key in ("image", "deezer_link", "track_id", "isrc", "album"):
            payload[key] = payload.get(key) or media.get(key)
        return payload

    def _usable_preview_url(self, value: Any) -> str:
        url = str(value or "").strip()
        if not url or url.lower() in {"nan", "none", "null", "undefined"}:
            return ""
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            return ""
        expiry = re.search(r"exp=(\d+)", url)
        if expiry:
            try:
                if int(expiry.group(1)) <= int(datetime.now(timezone.utc).timestamp()) + 60:
                    return ""
            except ValueError:
                return ""
        return url

    def _first_usable_preview(self, *values: Any) -> str:
        for value in values:
            preview = self._usable_preview_url(value)
            if preview:
                return preview
        return ""

    # Track media, reasons and custom track helpers.
    def _row_audio_signature(self, row: Dict[str, Any]) -> Dict[str, float]:
        signature: Dict[str, float] = {}
        for feature in FEATURE_COLUMNS:
            value = row.get(feature)
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
                signature[feature] = float(value)
            except (TypeError, ValueError):
                continue
        return signature

    def _build_reason_text(
        self,
        request: Dict[str, Any],
        profile: Dict[str, Any],
        cluster_label: str,
        mood_profile: Dict[str, Any],
        similarity_score: float,
    ) -> str:
        fragments = [request.get("source_label", "Matchad rekommendation")]
        if cluster_label:
            fragments.append(f"Den kommer fran {cluster_label.lower()}.")
        if mood_profile.get("label"):
            fragments.append(f"Mood: {mood_profile['label'].lower()}.")
        if profile.get("smallness_reason"):
            fragments.append(profile["smallness_reason"])
        return " ".join(fragments)

    def _build_discovery_labels(
        self,
        row: Dict[str, Any],
        similarity_score: float,
        small_artist_score: float,
        custom_recency_boost: float,
    ) -> List[str]:
        labels: List[str] = []
        if bool(row.get("is_custom")):
            labels.append("Newly added")
        if small_artist_score >= 0.75:
            labels.append("Hidden gem")
        elif small_artist_score >= 0.56:
            labels.append("Small artist boost")
        if similarity_score >= 0.38:
            labels.append("Related vibe")
        if row.get("mood_profile") or row.get("energy") is not None:
            labels.append("Similar mood")
        if row.get("cluster_id", -1) >= 0:
            labels.append("Underground cluster")
        if custom_recency_boost > 0.0:
            labels.append("Niche discovery")

        deduped: List[str] = []
        for label in labels:
            if label not in deduped:
                deduped.append(label)
        return deduped[:4]

    def _resolve_custom_genre(self, track: Dict[str, Any], local: Dict[str, Any], profile: Dict[str, Any]) -> str:
        track_match = self.dataset.track_record(
            normalize_key(track.get("artist")),
            track.get("song") or "",
        )
        options = [
            track.get("genre"),
            *(track.get("album_genres") or []),
            track_match.get("track_genre"),
            *(profile.get("top_genres") or []),
            *((local or {}).get("top_genres") or []),
            "unknown",
        ]
        for value in options:
            normalized = normalize_genre(value)
            if normalized and normalized != "unknown":
                return normalized
        return "unknown"

    def _resolve_top_genres(
        self,
        track: Dict[str, Any],
        local: Dict[str, Any],
        profile: Dict[str, Any],
        primary_genre: str,
    ) -> List[str]:
        values = []
        if primary_genre and primary_genre != "unknown":
            values.append(primary_genre)
        values.extend(track.get("album_genres", []) or [])
        values.extend(profile.get("top_genres", []) or [])
        values.extend((local or {}).get("top_genres", []) or [])
        return normalize_genre_list(values)[:4]

    def _resolve_custom_audio_signature(self, track: Dict[str, Any], artist_key: str) -> tuple[Dict[str, float], bool, str]:
        track_match = self.dataset.track_record(artist_key, track.get("song") or "")
        if not track_match:
            return {}, False, "unvalidated"

        signature = {
            feature: float(track_match.get(feature))
            for feature in FEATURE_COLUMNS
            if track_match.get(feature) is not None and not pd.isna(track_match.get(feature))
        }
        if not signature:
            return {}, False, "unvalidated"
        return signature, True, "dataset_track_match"

    def _compose_metadata_text(
        self,
        song: str | None,
        artist: str | None,
        album: str | None,
        genre: str | None,
        tags: Sequence[str],
        note: str | None,
    ) -> str:
        return " ".join(
            part
            for part in [
                str(song or ""),
                str(artist or ""),
                str(album or ""),
                str(genre or ""),
                " ".join(str(tag) for tag in tags if tag),
                str(note or ""),
            ]
            if part
        )

    # Shared numeric and delivery utilities.
    def _combined_library_items(self, state: Dict[str, Any], custom_tracks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        merged: List[Dict[str, Any]] = []
        for item in list(custom_tracks) + state.get("saved_artists", []):
            key = item.get("artist_key")
            if key and key not in seen:
                merged.append(item)
                seen.add(key)
        return merged

    def _average_vectors(self, vectors: Sequence[Dict[str, float]]) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for vector in vectors:
            for key, value in vector.items():
                totals[key] = totals.get(key, 0.0) + float(value)
                counts[key] = counts.get(key, 0) + 1
        return {key: totals[key] / counts[key] for key in totals if counts[key]}

    def _numeric_mood_match_series(self, series: pd.Series, target: float, feature: str) -> pd.Series:
        match = pd.Series(0.0, index=series.index, dtype=float)
        valid_mask = series.notna()
        if not valid_mask.any():
            return match

        if feature == "tempo":
            distance = ((series.loc[valid_mask] - target).abs() / 70.0).clip(0, 1)
        else:
            distance = (series.loc[valid_mask] - target).abs().clip(0, 1)
        match.loc[valid_mask] = 1 - distance
        return match

    def _preferred_labels_from_genres(self, genres: Sequence[str]) -> List[str]:
        labels: List[str] = []
        for label, values in DISCOVER_GENRES.items():
            if any(value in values for value in genres):
                labels.append(label)
        return labels

    def _record_impressions(self, context_name: str, results: Sequence[Dict[str, Any]]) -> None:
        for item in results:
            self.sqlite_store.record_feed_event(context_name, item)

    def _fallback_feed_card(
        self,
        state: Dict[str, Any],
        custom_tracks: Sequence[Dict[str, Any]],
        exclude_artist_keys: Sequence[str],
    ) -> Dict[str, Any]:
        excluded = set(exclude_artist_keys)
        for item in custom_tracks:
            if item.get("artist_key") not in excluded:
                return item
        for item in state.get("saved_artists", []):
            if item.get("artist_key") not in excluded:
                return item
        return {}

    def _freshness_bonus(self, value: Any) -> float:
        if not value:
            return 0.0
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        days = max((datetime.now(timezone.utc) - parsed).days, 0)
        if days <= 7:
            return 0.32
        if days <= 30:
            return 0.14
        return 0.0

    def _extract_year_from_text(self, value: Any) -> int | None:
        if not value:
            return None
        match = re.match(r"(\d{4})", str(value))
        return int(match.group(1)) if match else None

    def _release_year_matches(self, release_year: int | None, year_filter: Dict[str, int] | None) -> bool:
        if not year_filter or not release_year:
            return True
        return year_filter["from"] <= release_year <= year_filter["to"]
