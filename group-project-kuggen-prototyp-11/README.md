# Small Web Prototype 2

Prototype 2 bygger vidare pa den befintliga prototypen i stallet for att skriva om allt fran grunden. Fokus ligger pa battre discovery, mindre repetition, starkare small-artist-prioritering och att egeninlagda artister faktiskt blir en vaxande del av systemet.

Det som driver appen nu:

- `spotify_tracks.csv` ar fortfarande huvudbasen for discovery, filtrering och intern rekommendationslogik
- Deezer anvands for ISRC-uppslag, albummetadata, genrer, lankar, bilder och previews
- Last.fm anvands for lyssnarsiffror, artistinfo och liknande artister
- SQLite anvands for att spara egeninlagda artister och feedhistorik mellan sessioner
- TF-IDF, cosine similarity och latta K-means-kluster anvands for att forbattra variation och vibe-matchning

## Struktur

- `backend/app/main.py`: FastAPI-app och API-endpoints
- `backend/app/recommendations.py`: huvudlogik for feed, discover, promptsearch och ranking
- `backend/app/discovery_intelligence.py`: textpreprocessning, TF-IDF, cosine similarity och klustring
- `backend/app/sqlite_store.py`: SQLite-lager for custom tracks och feedhistorik
- `backend/app/dataset.py`: datasetinlasning, artistaggregering och metadatafalt
- `backend/app/external_services.py`: Deezer- och Last.fm-integration med cache
- `backend/app/storage.py`: JSON-kompatibilitetslager for sparade artister och community-posts
- `frontend/app.js`: SPA-rendering, feedkort, sokforklaringar och interaktioner
- `frontend/styles.css`: visuell styling och badges for discovery-signaler
- `data/prototype2.sqlite3`: skapas automatiskt och lagrar anvandartillskott/feedhistorik

## Kor lokalt

```powershell
cd C:\Users\pelle\Documents\Codex\2026-04-28\files-mentioned-by-the-user-namnl\smallweb-smaller-artists-app
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
copy .env.example .env
uvicorn backend.app.main:app --reload
```

Oppna sedan [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Miljovariabler

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

## Viktiga dokument

- `PROTOTYPE_2_CHANGES.md`: vad som andrats och hur Prototype 2 fungerar
- `DEPLOYMENT_NOTES.md`: vad som behover andras infor publik drift

## Antaganden

- Deezer anvands utan separat hemlig API-nyckel i denna prototyp
- om Last.fm saknas fungerar discovery fortfarande, men small-artist-score och likhetslogik blir svagare
- klustring och TF-IDF ar medvetet latta for att halla prototypen snabb och begriplig
