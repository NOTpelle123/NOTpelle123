# Discovery Flow Diagrams

## Discovery/Musikmix

```mermaid
flowchart TD
    A["Användaren väljer genre + sliders i Musikmix"] --> B["Frontend skickar request till /api/property-search"]
    B --> C["Backend normaliserar genre och slider-värden"]

    C --> D{"Är läget Nya tillagda?"}
    D -->|Ja| E["Hämta lokalt tillagda låtar från SQLite"]
    E --> F["Filtrera på vald genre"]
    F --> Z["Skicka resultat till frontend"]

    D -->|Nej| G["Bygg kandidatlista"]
    G --> G1["Hämta låtar från cleaned_dataset.csv"]
    G --> G2["Lägg till egna/lokalt tillagda låtar"]
    G1 --> H["Filtrera kandidatlistan på genre"]
    G2 --> H

    H --> I{"Finns sliders?"}
    I -->|Nej| J["Genrebaserad discovery/scoring"]
    I -->|Ja| K["Skapa målvektor från sliders"]

    K --> L["K-means väljer närmaste kluster"]
    L --> M["Behåll låtar i valt kluster"]
    M --> N["Hitta låten närmast målvektorn"]
    N --> O["Seed-låt"]

    O --> P["Hitta låtar nära seed-låten"]
    P --> Q["Behåll bara låtar nära slider-målvektorn"]
    Q --> R["Skapa kandidatfönster"]

    J --> S["Scoring"]
    R --> S

    S --> S1["Genrebonus"]
    S --> S2["K-means/slider-score"]
    S --> S3["Small artist-prioritet"]
    S --> S4["Minus för nyligen visade låtar"]
    S --> S5["Lite randomisering"]

    S1 --> T["Sluturval"]
    S2 --> T
    S3 --> T
    S4 --> T
    S5 --> T

    T --> U["Hämta/komplettera metadata"]
    U --> U1["Deezer bild/preview"]
    U --> U2["Spotify bild fallback"]
    U --> U3["Last.fm/Deezer artistdata"]

    U1 --> V["Small artist-filter"]
    U2 --> V
    U3 --> V

    V --> W["Bygg resultatkort"]
    W --> Z["Skicka resultat till frontend"]
```

## K-means/Seed Logic

```mermaid
flowchart TD
    A["Slider-värden"] --> B["Målvektor"]
    B --> C["Standardisera värden"]
    C --> D["Jämför med K-means-centroider"]
    D --> E["Välj närmaste kluster"]
    E --> F["Filtrera låtar till klustret"]
    F --> G["Räkna avstånd till målvektorn"]
    G --> H["Närmaste låt blir seed"]
    H --> I["Räkna avstånd från alla låtar till seed"]
    I --> J["Behåll låtar inom slider-threshold"]
    J --> K["Skicka vidare till scoring"]
```

## One Sentence Summary

K-means väljer musikaliskt område, seed-låten ger en konkret referenspunkt, och scoring/small-artist-filtret avgör vad som faktiskt visas.
