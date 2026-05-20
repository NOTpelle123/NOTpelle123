# Deployment Notes

## Current prototype storage

Prototype 2 currently uses two local persistence layers:

- `data/prototype2.sqlite3`
  - stores user-added tracks added through ISRC
  - stores feed history used for anti-repetition and rotation
- `data/user_state.json`
  - keeps saved artists for the current prototype
  - keeps community posts
  - remains in place for backward compatibility with the original prototype flow

For the prototype stage this is acceptable, because the app is still single-instance and local-first.

## What should move to production storage later

The following should move from local files to a hosted database before public deployment:

- saved artists
- custom ISRC-added tracks
- community posts
- feed history
- cached external metadata if cross-user reuse becomes important

Recommended production data model:

- `artists`
- `tracks`
- `user_saved_artists`
- `user_added_tracks`
- `community_posts`
- `recommendation_impressions`
- `metadata_cache`

## Suggested hosting options

Simple prototype-to-public path:

- Frontend: Vercel or Netlify
- Backend: Railway, Render, Fly.io, or a small container host
- Database: Supabase Postgres
- Object storage: Supabase Storage or Cloudflare R2 if media/assets are added later

Alternative stack:

- Frontend + API: Firebase Hosting + Cloud Run
- Database: Firestore or Supabase

## Environment variables

Current variables used by the backend:

- `LASTFM_API_KEY`
- `REQUEST_TIMEOUT_SECONDS`
- `RESULT_LIMIT`
- `MAX_LOCAL_POPULARITY`
- `MAX_LASTFM_LISTENERS`
- `MAX_DEEZER_FANS`
- `NLP_MAX_FEATURES`
- `CLUSTER_COUNT`
- `CLUSTER_SAMPLE_SIZE`
- `RECENT_ARTIST_WINDOW`
- `RECENT_TRACK_WINDOW`

For public deployment, secrets should be managed through the hosting platform secret manager, not `.env` files committed to the repo.

## Scaling considerations

Current prototype assumptions:

- one app process
- local SQLite file
- in-memory TF-IDF and clustering model built at startup
- lightweight local caching of Deezer/Last.fm responses

Before wider usage, plan for:

- replacing SQLite with Postgres for concurrent writes
- moving JSON state into the database
- separating recommendation impression logging into its own table
- rate-limiting or caching external API requests more aggressively
- optionally precomputing cluster assignments and text vectors offline

## Persistent storage requirements

The platform should preserve value between sessions. At minimum, production persistence must guarantee:

- user-added tracks survive restarts and deployments
- saved artists survive restarts and deployments
- recommendation history can be reused to reduce repetition
- cluster labels, small-artist metadata, and enriched genres are stored once and reused later

## Recommendation pipeline in production

The current startup pipeline is suitable for a prototype:

1. load dataset
2. build TF-IDF vocabulary
3. fit lightweight clustering
4. serve discovery requests

For production, consider a scheduled refresh job:

1. re-index metadata daily or when dataset changes
2. recompute centroids and cluster summaries
3. store cluster assignments in the database
4. keep API request latency focused on ranking, not rebuilding models
