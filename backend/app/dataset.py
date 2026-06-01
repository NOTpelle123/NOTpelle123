#Spotify-CSV
#→ kontrollerar kolumner
#→ städar och normaliserar datan
#→ skapar sökbara nycklar
#→ bygger artiststatistik
#→ gör det lättare för appen att hämta låtar, artister och genrer


from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd


FEATURE_COLUMNS = [
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
    "tempo",
]

REQUIRED_COLUMNS = {
    "track_id",
    "artists",
    "album_name",
    "track_name",
    "popularity",
    "duration_ms",
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
    "tempo",
    "track_genre",
}

COLUMN_ALIASES = {
    "artist": "artists",
    "artist_name": "artists",
    "album": "album_name",
    "album_title": "album_name",
    "track": "track_name",
    "song": "track_name",
    "song_name": "track_name",
    "genre": "track_genre",
}

GENRE_ALIASES = {
    "r b": "r-n-b",
    "r and b": "r-n-b",
    "rnb": "r-n-b",
    "rhythm and blues": "r-n-b",
    "hip hop": "hip-hop",
    "hiphop": "hip-hop",
    "alt rock": "alt-rock",
    "deep house": "deep-house",
    "rock n roll": "rock-n-roll",
    "lo fi": "lo-fi",
}

DISCOVER_GENRES: Dict[str, List[str]] = {
    "Indie": ["indie"],
    "Pop": ["pop"],
    "Rock": ["rock"],
    "Jazz": ["jazz"],
    "Electronic": ["electronic"],
    "R&B": ["r-n-b"],
    "Soul": ["soul"],
    "Funk": ["funk"],
    "Hip-Hop": ["hip-hop"],
    "Dance": ["dance"],
    "Country": ["country"],
    "Folk": ["folk"],
    "Metal": ["metal"],
    "Latin": ["latin"],
    "Classical": ["classical"],
}

def normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text)
    return text


def split_artists(value: Any) -> List[str]:
    raw = str(value or "")
    parts = [part.strip() for part in re.split(r"[;,]", raw) if part.strip()]
    return parts


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_genre(value: Any) -> str:
    text = normalize_key(value).replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "unknown"

    alias_key = text.replace("-", " ")
    if alias_key in GENRE_ALIASES:
        return GENRE_ALIASES[alias_key]
    return text.replace(" ", "-")


def normalize_genre_list(values: Iterable[Any]) -> List[str]:
    cleaned: List[str] = []
    for value in values:
        genre = normalize_genre(value)
        if genre == "unknown" or genre in cleaned:
            continue
        cleaned.append(genre)
    return cleaned


def normalize_track_title(value: Any) -> str:
    text = normalize_key(value)
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass(slots=True)
class DatasetSummary:
    spotify_rows: int
    artist_count: int
    genre_count: int


class DatasetCatalog:
    def __init__(self, csv_path: Path) -> None:
        self.df = self._load(csv_path)
        self.artist_frame = self._build_artist_frame(self.df)
        self.artist_map = {
            row["artist_key"]: row.to_dict()
            for _, row in self.artist_frame.iterrows()
        }

    def summary(self) -> DatasetSummary:
        return DatasetSummary(
            spotify_rows=int(len(self.df)),
            artist_count=int(len(self.artist_frame)),
            genre_count=int(self.df["track_genre"].nunique()),
        )

    def discover_genres(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for label, genres in DISCOVER_GENRES.items():
            count = int(self.df["track_genre"].isin(genres).sum())
            items.append({"label": label, "dataset_genres": genres, "count": count})
        return items

    def all_genres(self) -> List[Dict[str, Any]]:
        counts = self.df["track_genre"].dropna().astype(str).value_counts().sort_index()
        return [
            {"label": genre, "count": int(count)}
            for genre, count in counts.items()
        ]

    def rows_for_genres(self, labels: Sequence[str]) -> pd.DataFrame:
        genre_values = self.map_genre_labels(labels)
        if not genre_values:
            return self.df.copy()
        return self.df[self.df["track_genre"].isin(genre_values)].copy()

    def map_genre_labels(self, labels: Sequence[str]) -> List[str]:
        values: List[str] = []
        for label in labels:
            values.extend(DISCOVER_GENRES.get(label, []))
        return sorted(set(values))

    def artist_record(self, artist_key: str) -> Dict[str, Any]:
        return dict(self.artist_map.get(artist_key, {}))

    def rows_for_artist_key(self, artist_key: str) -> pd.DataFrame:
        return self.df[self.df["artist_key"] == artist_key].copy()

    def track_record(self, artist_key: str, track_name: str) -> Dict[str, Any]:
        name_key = normalize_track_title(track_name)
        if not name_key:
            return {}

        rows = self.df[
            (self.df["artist_key"] == artist_key)
            & (self.df["track_name_key"] == name_key)
        ]
        if rows.empty:
            return {}
        return rows.sort_values("popularity", ascending=False).iloc[0].to_dict()

    def _load(self, csv_path: Path) -> pd.DataFrame:
        df = pd.read_csv(csv_path)
        df = df.loc[:, ~df.columns.str.contains(r"^Unnamed")]
        df = df.rename(columns={source: target for source, target in COLUMN_ALIASES.items() if source in df.columns and target not in df.columns})

        missing_columns = REQUIRED_COLUMNS - set(df.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Dataset missing required columns: {missing}")

        df = df.drop_duplicates(subset=["track_id"]).copy()

        for column in ["popularity", "duration_ms", *FEATURE_COLUMNS]:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        df["track_genre"] = df["track_genre"].map(normalize_genre)
        df["primary_artist"] = df["artists"].map(self._first_artist)
        df["artist_key"] = df["primary_artist"].map(normalize_key)
        df["track_key"] = df["track_id"].fillna("").astype(str)
        df["track_name_key"] = df["track_name"].map(normalize_track_title)
        df["search_blob"] = (
            df["track_name"].fillna("")
            + " "
            + df["album_name"].fillna("")
            + " "
            + df["artists"].fillna("")
            + " "
            + df["track_genre"].fillna("")
        ).str.lower()
        df["metadata_text"] = (
            df["track_name"].fillna("")
            + " "
            + df["primary_artist"].fillna("")
            + " "
            + df["album_name"].fillna("")
            + " "
            + df["track_genre"].fillna("")
        )

        return df[df["artist_key"] != ""].reset_index(drop=True)

    def _build_artist_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        grouped = df.groupby(["artist_key", "primary_artist"], as_index=False).agg(
            track_count=("track_id", "count"),
            avg_popularity=("popularity", "mean"),
            max_popularity=("popularity", "max"),
            avg_danceability=("danceability", "mean"),
            avg_energy=("energy", "mean"),
            avg_valence=("valence", "mean"),
            avg_acousticness=("acousticness", "mean"),
            avg_instrumentalness=("instrumentalness", "mean"),
            avg_tempo=("tempo", "mean"),
        )

        top_genres: List[List[str]] = []
        sample_tracks: List[List[str]] = []
        for artist_key in grouped["artist_key"]:
            artist_rows = df[df["artist_key"] == artist_key]
            genres = normalize_genre_list(artist_rows["track_genre"].value_counts().head(3).index.tolist())
            tracks = artist_rows.sort_values("popularity", ascending=False)["track_name"].head(3).tolist()
            top_genres.append(genres)
            sample_tracks.append(tracks)

        grouped["top_genres"] = top_genres
        grouped["sample_tracks"] = sample_tracks
        grouped["avg_popularity"] = grouped["avg_popularity"].round(2)
        grouped["max_popularity"] = grouped["max_popularity"].round(2)

        return grouped.sort_values(["avg_popularity", "track_count"], ascending=[True, False]).reset_index(drop=True)

    def _first_artist(self, value: Any) -> str:
        artists = split_artists(value)
        return artists[0] if artists else clean_text(value)
