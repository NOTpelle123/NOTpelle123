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
        working = frame.copy()
        if working.empty or not selected_features:
            return working, None

        target = self._target_from_selected_features(selected_features)
        target_df = pd.DataFrame([target])
        target_matrix = self._build_cluster_feature_matrix(target_df)
        target_scaled = self.scaler.transform(target_matrix)
        predicted_cluster = int(self.cluster_model.predict(target_scaled)[0])

        working["cluster_id"] = self.assign_cluster_ids(working)
        same_cluster = working[working["cluster_id"] == predicted_cluster].copy()
        if same_cluster.empty:
            same_cluster = working.copy()

        song_matrix = self._build_cluster_feature_matrix(same_cluster)
        song_scaled = self.scaler.transform(song_matrix)
        distances = ((song_scaled - target_scaled[0]) ** 2).sum(axis=1)

        same_cluster["feature_distance"] = distances
        same_cluster["property_match_score"] = 1.0 / (1.0 + same_cluster["feature_distance"])
        same_cluster["property_neighbor_score"] = same_cluster["property_match_score"]
        same_cluster["property_group_score"] = same_cluster["property_match_score"]

        ranked = same_cluster.sort_values("feature_distance", ascending=True)
        ranked = ranked.drop_duplicates(subset=["track_name", "primary_artist"])
        ranked = ranked.drop_duplicates(subset=["track_key"])
        return ranked.head(max(limit * 30, 160)).copy(), predicted_cluster

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
