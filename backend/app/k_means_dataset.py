from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from .config import Settings


CLUSTER_FEATURE_COLUMNS = [
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
    "tempo",
]


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


class KMeansDataset:
    def __init__(self, settings: Settings, dataset_df: pd.DataFrame) -> None:
        self.settings = settings
        self.scaler = StandardScaler()
        self.cluster_model = KMeans(
            n_clusters=settings.cluster_count,
            random_state=42,
            n_init=10,
        )
        self.numeric_means_: Dict[str, float] = {}

        self._fit_numeric_stats(dataset_df)
        self._fit_clusters(dataset_df)

    def assign_cluster_ids(self, frame: pd.DataFrame) -> np.ndarray:
        feature_matrix = self._build_cluster_feature_matrix(frame)
        if len(feature_matrix) == 0:
            return np.zeros(0, dtype=np.int32)
        scaled_matrix = self.scaler.transform(feature_matrix)
        return self.cluster_model.predict(scaled_matrix).astype(np.int32)

    def rank_frame_by_selected_features(
        self,
        frame: pd.DataFrame,
        selected_features: Dict[str, float],
        limit: int,
    ) -> tuple[pd.DataFrame, int | None]:
        """Rank a candidate frame from the user's slider values.

        Discovery flow in plain language:
        1. Treat the slider values as a target audio vector.
        2. Let K-means pick the cluster nearest to that target vector.
        3. Inside that cluster, find the best direct slider match. This is the seed track.
        4. Prefer songs close to the seed track, but only while they stay close enough
           to the original slider target.
        5. Return a wider candidate window for the recommendation scorer to finish.
        """
        working = frame.copy()
        if working.empty or not selected_features:
            return working, None

        # The target is the user's desired sound profile. Values are scaled with the
        # same scaler as the dataset so tempo does not dominate 0-1 audio features.
        target = self._target_from_selected_features(selected_features)
        target_df = pd.DataFrame([target])
        target_matrix = self._build_cluster_feature_matrix(target_df)
        target_scaled = self.scaler.transform(target_matrix)
        predicted_cluster = int(self.cluster_model.predict(target_scaled)[0])

        # First K-means step: keep songs from the cluster nearest to the target.
        # If the filtered input has no songs in that cluster, fall back to all candidates.
        working["cluster_id"] = self.assign_cluster_ids(working)
        same_cluster = working[working["cluster_id"] == predicted_cluster].copy()
        if same_cluster.empty:
            same_cluster = working.copy()

        # Measure direct distance from each song to the slider target.
        # Lower feature_distance means a closer slider match.
        song_matrix = self._build_cluster_feature_matrix(same_cluster)
        song_scaled = self.scaler.transform(song_matrix)
        distances = ((song_scaled - target_scaled[0]) ** 2).sum(axis=1)

        same_cluster["feature_distance"] = distances
        same_cluster["property_match_score"] = 1.0 / (1.0 + same_cluster["feature_distance"])

        # The closest song to the target becomes the seed track.
        # It is an anchor for the rest of the discovery list, not a guaranteed final result.
        target_ranked = same_cluster.sort_values("feature_distance", ascending=True)
        target_ranked = target_ranked.drop_duplicates(subset=["track_name", "primary_artist"])
        target_ranked = target_ranked.drop_duplicates(subset=["track_key"])
        if target_ranked.empty:
            return target_ranked.copy(), predicted_cluster

        # Second distance step: compare every candidate in the cluster to the seed track.
        # This makes the list more coherent than pure slider sorting.
        seed_row = target_ranked.iloc[[0]]
        seed_matrix = self._build_cluster_feature_matrix(seed_row)
        seed_scaled = self.scaler.transform(seed_matrix)
        seed_distances = ((song_scaled - seed_scaled[0]) ** 2).sum(axis=1)

        same_cluster["seed_neighbor_distance"] = seed_distances
        same_cluster["property_neighbor_score"] = 1.0 / (1.0 + same_cluster["seed_neighbor_distance"])
        target_ranked = same_cluster.loc[target_ranked.index].copy()

        # Quality threshold: do not let seed-neighbor similarity pull in songs that are
        # too far from the sliders. The threshold is based on the strongest target matches.
        quality_window = target_ranked.head(max(limit * 2, 10))
        quality_threshold = float(quality_window["feature_distance"].quantile(0.75)) * 1.25
        neighbor_ranked = same_cluster[same_cluster["feature_distance"] <= quality_threshold].sort_values(
            ["seed_neighbor_distance", "feature_distance"],
            ascending=[True, True],
        )
        neighbor_ranked = neighbor_ranked.drop_duplicates(subset=["track_name", "primary_artist"])
        neighbor_ranked = neighbor_ranked.drop_duplicates(subset=["track_key"])

        window_size = max(limit * 30, 160)
        if len(neighbor_ranked) < window_size:
            # If the quality threshold is too strict, fill the candidate window with the
            # best direct slider matches so the later scorer still has enough options.
            existing_keys = set(neighbor_ranked["track_key"].fillna("").astype(str))
            fallback = target_ranked[
                ~target_ranked["track_key"].fillna("").astype(str).isin(existing_keys)
            ]
            neighbor_ranked = pd.concat([neighbor_ranked, fallback], ignore_index=True, sort=False)

        # Final K-means candidate score: mostly direct slider match, partly seed-neighbor
        # similarity. The recommendation engine will combine this with other app scores.
        neighbor_ranked["property_group_score"] = (
            pd.to_numeric(neighbor_ranked["property_match_score"], errors="coerce").fillna(0.0) * 0.72
            + pd.to_numeric(neighbor_ranked["property_neighbor_score"], errors="coerce").fillna(0.0) * 0.28
        )
        return neighbor_ranked.head(window_size).copy(), predicted_cluster

    def recommend_from_selected_features(
        self,
        frame: pd.DataFrame,
        selected_features: Dict[str, float],
        genres: Sequence[str] | None = None,
        limit: int = 6,
    ) -> Dict[str, Any]:
        working = frame.copy()
        genre_values = [normalize_text(genre) for genre in genres or [] if normalize_text(genre)]

        if genre_values:
            working = working[working["track_genre"].fillna("").map(normalize_text).isin(genre_values)]

        if working.empty:
            return {
                "view": "feature_kmeans",
                "genre": genre_values[0] if genre_values else None,
                "genres": genre_values,
                "selected_features": selected_features,
                "results": [],
            }

        if selected_features:
            ranked, predicted_cluster = self.rank_frame_by_selected_features(working, selected_features, limit)
        else:
            working["cluster_id"] = self.assign_cluster_ids(working)
            ranked = working.sample(n=min(len(working), limit), random_state=None)
            predicted_cluster = None

        results: List[Dict[str, Any]] = []
        for _, row in ranked.head(limit).iterrows():
            cluster_id = int(row.get("cluster_id", predicted_cluster if predicted_cluster is not None else -1))
            results.append(
                {
                    "artist_key": row.get("artist_key"),
                    "track_key": row.get("track_key"),
                    "artist": row.get("primary_artist"),
                    "song": row.get("track_name"),
                    "album": row.get("album_name"),
                    "genre": row.get("track_genre"),
                    "cluster_id": cluster_id,
                    "distance": float(row.get("feature_distance", 0.0) or 0.0),
                    "reason": (
                        f"Matchar dina valda egenskaper inom {', '.join(genre_values) or 'vald genre'}. "
                        f"Avstand: {float(row.get('feature_distance', 0.0) or 0.0):.2f}."
                    ),
                    "audio_signature": self.audio_signature_from_row(row),
                    "features": self.audio_signature_from_row(row),
                    "source": "feature_kmeans",
                    "is_custom": bool(row.get("is_custom", False)),
                }
            )

        return {
            "view": "feature_kmeans",
            "genre": genre_values[0] if genre_values else None,
            "genres": genre_values,
            "selected_features": self._target_from_selected_features(selected_features) if selected_features else {},
            "predicted_cluster": predicted_cluster,
            "results": results,
        }

    def audio_signature_from_row(self, row: pd.Series | Dict[str, Any]) -> Dict[str, float]:
        signature: Dict[str, float] = {}
        for column in CLUSTER_FEATURE_COLUMNS:
            value = row.get(column)
            if value is None or pd.isna(value):
                continue
            signature[column] = float(value)
        return signature

    def _target_from_selected_features(self, selected_features: Dict[str, float]) -> Dict[str, float]:
        target: Dict[str, float] = {}
        for column in CLUSTER_FEATURE_COLUMNS:
            if column in selected_features:
                target[column] = float(selected_features[column])
            else:
                target[column] = self.numeric_means_[column]
        return target

    def _fit_numeric_stats(self, frame: pd.DataFrame) -> None:
        for column in CLUSTER_FEATURE_COLUMNS:
            series = pd.to_numeric(frame[column], errors="coerce").fillna(frame[column].median())
            self.numeric_means_[column] = float(series.mean())

    def _fit_clusters(self, frame: pd.DataFrame) -> None:
        sample_size = min(len(frame), self.settings.cluster_sample_size)
        sample = frame.sample(sample_size, random_state=17) if sample_size < len(frame) else frame

        working_sample = sample.copy()
        feature_matrix = self._build_cluster_feature_matrix(working_sample)
        scaled_matrix = self.scaler.fit_transform(feature_matrix)
        self.cluster_model.fit_predict(scaled_matrix)

    def _build_cluster_feature_matrix(self, frame: pd.DataFrame) -> np.ndarray:
        numeric_parts: List[np.ndarray] = []
        for column in CLUSTER_FEATURE_COLUMNS:
            series = pd.to_numeric(frame[column], errors="coerce").fillna(self.numeric_means_[column])
            values = series.to_numpy(dtype=np.float32).reshape(-1, 1)
            numeric_parts.append(values)

        return np.hstack(numeric_parts).astype(np.float32)
