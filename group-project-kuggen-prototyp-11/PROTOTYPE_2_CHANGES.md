# Prototype 2 Changes

## What was fixed

This pass improves the existing Small Web prototype without rebuilding the app from scratch.

Main fixes:

- large artists are filtered more aggressively
- listener/follower thresholding is now applied more strictly
- small-score influences ranking more strongly
- prompt and mood search are more aligned with user wording
- custom-track genres are normalized more consistently
- unreliable generated audio features are no longer treated as trustworthy data
- user-added track playback is more resilient because Deezer preview URLs are refreshed
- dataset usage is clearer and more consistent

## Where the original issues came from

### Large artists still appeared too often

The original ranking used `small_artist_score` only as one input among many, and the final gate still let non-small artists through in some cases.

Main sources:

- `backend/app/recommendations.py`
  - `_score_candidate_frame`
  - `_assemble_results`
  - `_assess_small_artist`
  - `_resolve_profile_for_row`

Important detail:

- custom tracks were previously treated as `is_small=True` by default, even when the external listener/fan signals did not justify that

### Listener limit logic was too soft

The old defaults were too permissive:

- `MAX_LASTFM_LISTENERS=350000`
- `MAX_DEEZER_FANS=120000`

That made the “small artist” definition much broader than intended.

Main source:

- `backend/app/config.py`
- `backend/app/recommendations.py`

### Prompt/mood search felt inaccurate

The original prompt parser only used a small keyword dictionary plus TF-IDF against the raw prompt text. It did not expand common vibe phrases strongly enough.

Main source:

- `backend/app/recommendations.py`
  - `PROMPT_GENRE_HINTS`
  - `PROMPT_MOODS`
  - `_interpret_prompt`
- `backend/app/discovery_intelligence.py`
  - `cosine_against_query`

### ISRC genres were inconsistent

Genre strings from Deezer could come in different textual forms such as:

- `R&B`
- `R and B`
- `r b`
- `hip-hop`
- `hip hop`

The earlier logic normalized text but did not canonicalize equivalent genres to one stable internal label.

Main source:

- `backend/app/recommendations.py`
  - `_resolve_custom_genre`
  - `_resolve_top_genres`
- `backend/app/dataset.py`

### Audio features for ISRC tracks were unreliable

The original custom-track path fell back to inferred or averaged feature values and then stored them as if they were reliable.

Examples:

- genre centroid fallback from `DiscoveryIntelligence.infer_audio_signature_from_genre`
- artist-average fallback from the dataset

That could pollute clustering and recommendations with fake precision.

Main source:

- `backend/app/recommendations.py`
  - `_resolve_custom_audio_signature`
  - `_build_custom_candidate_row`
- `backend/app/discovery_intelligence.py`

### User-added tracks could stop playing

Deezer preview URLs are signed and can expire. The prototype stored preview URLs in cache/SQLite and reused them later.

Main source:

- `backend/app/external_services.py`
- `backend/app/recommendations.py`

### Dataset usage was unclear

The dataset was doing several jobs at once, but custom-track logic also reused dataset-derived fallbacks in ways that blurred the boundary between:

- real dataset-based signals
- inferred custom-track data

Main source:

- `backend/app/dataset.py`
- `backend/app/recommendations.py`

## How listener filtering now works

Prototype 2 now uses a stricter threshold system centered around small artists:

- Spotify popularity: capped at `<= 50` and still defaulted to `45`
- Last.fm listeners: effectively capped at `<= 50,000`
- Deezer fans/followers: effectively capped at `<= 50,000`

Implementation notes:

- `backend/app/recommendations.py`
  - `_small_artist_thresholds`
  - `_assess_small_artist`
  - `_score_candidate_frame`
  - `_assemble_results`

Behavior:

- obviously mainstream rows are filtered before ranking when dataset popularity and small-score both indicate they are too large
- non-small artists are skipped during result assembly unless the fallback path is truly empty
- the feed, discover, and search all run with the same small-artist focus

## How small-score works

`small_artist_score` is kept intentionally simple and readable.

Signals used:

- dataset popularity
- dataset track count
- Last.fm listeners
- Deezer fans

General behavior:

- lower popularity/listener/fan values increase the score
- larger catalog saturation lowers the score
- missing data falls back conservatively instead of assuming a track is small

Ranking impact:

- higher small-score gets a stronger positive weight
- lower small-score gets a stronger mainstream penalty
- explicit underground/niche requests reinforce the small-score bias further

Main logic:

- `backend/app/recommendations.py`
  - `_calculate_small_artist_score`
  - `_score_candidate_frame`

## How genre normalization works

A reusable genre-cleaning layer now lives in the dataset module.

Main helpers:

- `normalize_genre`
- `normalize_genre_list`

Examples:

- `R&B`, `r b`, `r and b`, `rnb` -> `r-n-b`
- `hip hop`, `hip-hop`, `hiphop` -> `hip-hop`
- `alt rock` -> `alt-rock`

This is now used in both:

- dataset loading
- custom-track enrichment and ranking

Main file:

- `backend/app/dataset.py`

## How ISRC enrichment works now

When a user adds a track through ISRC:

1. Deezer track metadata is fetched
2. Deezer album metadata is fetched
3. album genres are extracted when available
4. genres are normalized to internal canonical names
5. the track is saved to SQLite
6. the track becomes eligible for feed/discover/search

Main files:

- `backend/app/external_services.py`
- `backend/app/recommendations.py`
- `backend/app/sqlite_store.py`

## Audio feature policy for ISRC tracks

Important change:

- inferred audio features are no longer treated as trustworthy permanent data

Current rule:

- if there is an exact dataset track match for the same artist and track title, validated audio features can be reused
- otherwise custom tracks are stored without trusted audio-feature values

Fallback behavior when no validated audio exists:

- use genre/text-based mood logic
- allow clustering to rely more on metadata text instead of fake numeric precision

Main files:

- `backend/app/recommendations.py`
- `backend/app/discovery_intelligence.py`

## Deezer playback fix for user-added tracks

User-added tracks now refresh Deezer track metadata before being rendered into cards.

Why:

- preview URLs can expire

What changed:

- added a short-lived `get_deezer_track` refresh path
- stopped relying only on long-lived cached preview URLs
- shortened ISRC cache lifetime for Deezer track data

Main files:

- `backend/app/external_services.py`
- `backend/app/recommendations.py`

## How dataset usage was cleaned up

The intended split is now clearer:

Dataset is mainly used for:

- baseline discovery pool
- initial search/discover candidates
- TF-IDF vocabulary
- cluster fitting
- validated audio features only when there is a true dataset track match

SQLite/user-added tracks are mainly used for:

- growing long-term discovery
- evolving feed context
- user-owned additions
- persistent feed anti-repetition history

Important cleanup:

- custom-track `popularity` no longer abuses raw Deezer fan counts as if they were dataset popularity values
- the loader now validates required dataset columns and supports a few common cleaned-column aliases

## Cleaned dataset integration

The loader now:

- drops unnamed index columns
- supports common alias columns such as `genre -> track_genre`
- validates required columns before continuing
- normalizes `track_genre`
- generates a normalized `track_name_key` for exact custom-track matching

Main file:

- `backend/app/dataset.py`

## Affected files

- `backend/app/config.py`
- `backend/app/dataset.py`
- `backend/app/discovery_intelligence.py`
- `backend/app/external_services.py`
- `backend/app/recommendations.py`
- `backend/app/sqlite_store.py`
- `.env.example`

## Assumptions made

- Deezer preview URLs are treated as temporary, not permanent assets
- exact track-level audio features are only considered trustworthy when the track can be matched back to the dataset
- the current app should stay light and maintainable, so no heavy ML or new large dependencies were introduced
- the active CSV file in this prototype is still `data/spotify_tracks.csv`, so “cleaned dataset” support was implemented as compatibility logic in the loader rather than as a second separate pipeline

## Remaining limitations

- Last.fm is still optional, so listener-aware filtering is stronger when an API key is configured
- true external audio-feature APIs are not available in this prototype, so some custom tracks still rely on contextual mood inference rather than real DSP features
- saved artists still live in the compatibility JSON store and should move fully into the database later
- live runtime verification depends on the local dev server state outside this Codex sandbox
