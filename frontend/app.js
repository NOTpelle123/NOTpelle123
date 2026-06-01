import { api } from "./api.js";

const root = document.getElementById("app");

const numberFormatter = new Intl.NumberFormat("sv-SE");
const relativeFormatter = new Intl.RelativeTimeFormat("sv", { numeric: "auto" });
const LOCAL_PROFILE_USERNAME = "du";
const AUDIO_FAILURE_RETRY_MS = 30 * 1000;

const navItems = [
  { key: "search", label: "Discovery", icon: "sparkles" },
  { key: "songs", label: "Låtar", icon: "note" },
  { key: "suggest", label: "Föreslå", icon: "plus" },
  { key: "feed", label: "Flöde", icon: "radio" },
  { key: "profile", label: "Profil", icon: "user" },
];

const mixFeatures = [
  { key: "danceability", label: "Dansbarhet", low: "Stillsam", high: "Rytmisk", min: 0, max: 100 },
  { key: "energy", label: "Energi", low: "Mjuk", high: "Intensiv", min: 0, max: 100 },
  { key: "valence", label: "Känsla", low: "Mörk", high: "Ljus", min: 0, max: 100 },
  { key: "acousticness", label: "Akustik", low: "Elektrisk", high: "Organisk", min: 0, max: 100 },
  { key: "instrumentalness", label: "Instrumental", low: "Röst", high: "Instrumental", min: 0, max: 100 },
  { key: "tempo", label: "Tempo", low: "Långsamt", high: "Snabbt", min: 60, max: 180 },
];

const hiddenMixGenreChips = new Set(["randb", "hip-hop"]);

const mixPresets = {
  study: {
    label: "Study",
    genres: ["ambient", "acoustic", "piano", "new-age", "study"],
    targets: { danceability: 38, energy: 24, valence: 42, acousticness: 56, instrumentalness: 32, tempo: 86 },
  },
  rock: {
    label: "Rock",
    genres: ["rock", "alt-rock", "punk-rock", "power-pop"],
    targets: { danceability: 54, energy: 78, valence: 52, acousticness: 18, instrumentalness: 8, tempo: 126 },
  },
};

const avatarPresets = [
  { key: "violet", label: "Violet" },
  { key: "magenta", label: "Magenta" },
  { key: "blue", label: "Blue" },
  { key: "green", label: "Green" },
  { key: "amber", label: "Amber" },
];

const state = {
  boot: null,
  view: "search",
  isLoading: true,
  loadingMessage: "Laddar appen...",
  error: "",
  searchResults: [],
  searchInterpretation: null,
  searchHasRun: false,
  songSearchQuery: "",
  songSearchResults: [],
  songSearchHasRun: false,
  songSearchLoading: false,
  songSearchError: "",
  mixLabel: "Egen mix",
  mixMode: "surprise",
  mixPreset: "",
  mixGenres: [],
  mixGenreQuery: "",
  mixUseProperties: false,
  mixPropertiesOpen: false,
  mixTargets: { danceability: 52, energy: 50, valence: 50, acousticness: 28, instrumentalness: 8, tempo: 110 },
  feed: {
    card: null,
    communityPosts: [],
    trendingQuietly: [],
    microCommunities: [],
    communityActivity: [],
    discoveryTrail: [],
    seenKeys: [],
  },
  profile: {
    saved_artists: [],
    custom_artists: [],
    profile_posts: [],
    profile_replies: [],
    profile_song_comments: [],
    profile_discussions: [],
    saved_count: 0,
    custom_count: 0,
  },
  session: {
    authenticated: false,
    user: null,
  },
  profileAuthMode: "logged-out",
  authError: "",
  authStatus: "",
  authLoading: false,
  selectedAvatarPreset: "violet",
  savedKeys: new Set(),
  suggestionDraft: {
    isrc: "",
    confirm: false,
    note: "",
  },
  suggestionStatus: "",
  itemIndex: new Map(),
  songIndex: new Map(),
  communityTipOpen: false,
  communitySelectedSongKey: "",
  activeCommunitySlug: "",
  activeReplyPostId: "",
  audioFailures: new Map(),
  artistModal: {
    isOpen: false,
    isLoading: false,
    item: null,
    error: "",
    comments: [],
    commentsLoading: false,
    commentsError: "",
    communityDiscussions: [],
  },
  publicProfile: {
    isOpen: false,
    isLoading: false,
    username: "",
    payload: null,
    error: "",
  },
  createCommunity: {
    isOpen: false,
    isLoading: false,
    error: "",
  },
  explanationModal: { isOpen: false, title: "", body: "" },
};

function icon(name) {
  const common = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
  const icons = {
    note: `<svg ${common}><path d="M12 3v11.4a3.4 3.4 0 1 1-1.8-3V6.6l7-1.8V14a3.4 3.4 0 1 1-1.8-3V3.9z"/></svg>`,
    home: `<svg ${common}><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10.5V20h13V10.5"/></svg>`,
    plus: `<svg ${common}><circle cx="12" cy="12" r="8.5"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>`,
    radio: `<svg ${common}><path d="M12 12m-2.5 0a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0"/><path d="M5.5 5.5a9 9 0 0 0 0 13"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/><path d="M8.5 8.5a5 5 0 0 0 0 7"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>`,
    sparkles: `<svg ${common}><path d="m12 3 1.8 4.8L18.5 9l-4.7 1.2L12 15l-1.8-4.8L5.5 9l4.7-1.2z"/><path d="m18 2 .6 1.6L20.2 4l-1.6.4L18 6l-.6-1.6L15.8 4l1.6-.4z"/></svg>`,
    user: `<svg ${common}><path d="M12 13.5a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/></svg>`,
    bookmark: `<svg ${common}><path d="M8 4.5h8a1 1 0 0 1 1 1V20l-5-3-5 3V5.5a1 1 0 0 1 1-1Z"/></svg>`,
    bookmarkFilled: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1V20l-5-3-5 3z"/></svg>`,
    heart: `<svg ${common}><path d="M12 20s-6.5-4.35-8.2-8.25A4.9 4.9 0 0 1 12 6a4.9 4.9 0 0 1 8.2 5.75C18.5 15.65 12 20 12 20Z"/></svg>`,
    next: `<svg ${common}><path d="M8 7.5 16 12l-8 4.5z"/><path d="M18 7v10"/></svg>`,
    plane: `<svg ${common}><path d="M21 3 10 14"/><path d="m21 3-7 18-4-7-7-4z"/></svg>`,
    trash: `<svg ${common}><path d="M4.5 7h15"/><path d="M9 7V5.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1V7"/><path d="M8.5 10.5V18"/><path d="M12 10.5V18"/><path d="M15.5 10.5V18"/><path d="M6.5 7 7.4 19a1 1 0 0 0 1 .9h7.2a1 1 0 0 0 1-.9L17.5 7"/></svg>`,
    refresh: `<svg ${common}><path d="M20 6v5h-5"/><path d="M19 11a7 7 0 1 1-2-5"/></svg>`,
  };

  return icons[name] || "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") {
    return "saknas";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "saknas";
  }
  if (number >= 1000000) {
    return `${(number / 1000000).toFixed(1).replace(".0", "")}M`;
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(1).replace(".0", "")}k`;
  }
  return numberFormatter.format(Math.round(number));
}

function shortCopy(value = "", maxLength = 130) {
  const text = String(value || "").trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength).trim()}...`;
}

function formatRelativeTime(value) {
  if (!value) {
    return "nyss";
  }

  const date = new Date(value);
  const diffMs = date.getTime() - Date.now();
  const diffMinutes = Math.round(diffMs / (1000 * 60));

  if (Math.abs(diffMinutes) < 60) {
    return relativeFormatter.format(diffMinutes, "minute");
  }

  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return relativeFormatter.format(diffHours, "hour");
  }

  const diffDays = Math.round(diffHours / 24);
  return relativeFormatter.format(diffDays, "day");
}

function songKeyForItem(item = {}) {
  return item.song_key || item.track_key || item.track_id || item.isrc || "";
}

function rememberItems(items = []) {
  items.forEach((item) => {
    if (item?.artist_key) {
      state.itemIndex.set(item.artist_key, item);
    }
    const songKey = songKeyForItem(item);
    if (songKey) {
      state.songIndex.set(String(songKey), item);
    }
  });
}

function rememberFeedItems() {
  rememberItems([
    ...(state.feed.card ? [state.feed.card] : []),
    ...(state.feed.trendingQuietly || []),
    ...(state.feed.microCommunities || []).flatMap((community) => [
      ...(community.artists || []),
      ...(community.shared_artists || []),
      ...(community.related_discoveries || []),
    ]),
    ...(state.feed.communityPosts || []).map((post) => post.linked_artist).filter(Boolean),
  ]);
}

function syncProfile(profilePayload) {
  state.profile = {
    ...state.profile,
    ...profilePayload,
    saved_artists: profilePayload.saved_artists || [],
    custom_artists: profilePayload.custom_artists || [],
    profile_posts: profilePayload.profile_posts || [],
    profile_replies: profilePayload.profile_replies || [],
    profile_song_comments: profilePayload.profile_song_comments || [],
    profile_discussions: profilePayload.profile_discussions || [],
  };
  state.savedKeys = new Set(state.profile.saved_artists.map((item) => item.artist_key).filter(Boolean));
  rememberItems(state.profile.saved_artists);
  rememberItems(state.profile.custom_artists);
  if (state.boot?.stats) {
    state.boot.stats.saved_count = state.profile.saved_count;
    state.boot.stats.custom_count = state.profile.custom_count;
  }
}

function syncSession(sessionPayload = {}) {
  state.session = {
    authenticated: Boolean(sessionPayload.authenticated),
    user: sessionPayload.user || null,
  };
  if (state.session.authenticated) {
    state.profileAuthMode = "logged-in";
  } else if (state.profileAuthMode === "logged-in") {
    state.profileAuthMode = "logged-out";
  }
}

function currentProfileName() {
  return state.session.user?.display_name || state.session.user?.username || LOCAL_PROFILE_USERNAME;
}

function normalizeProfileName(value = "") {
  return String(value || "").trim().toLowerCase();
}

function publicDisplayName(item = {}) {
  if (typeof item === "string") {
    return item.trim() || "Anonym";
  }
  return String(item.profile_username || item.display_name || item.username || "Anonym").trim() || "Anonym";
}

function renderPublicAvatarButton(item = {}, className = "") {
  const name = publicDisplayName(item);
  const avatar = item?.avatar_kind === "preset" ? item.avatar_value || "violet" : "";
  const avatarClass = avatar ? ` avatar-${escapeHtml(avatar)}` : "";
  return `
    <button
      class="avatar user-profile-avatar ${escapeHtml(className)}${avatarClass}"
      type="button"
      data-action="public-profile-open"
      data-username="${escapeHtml(name)}"
      aria-label="Öppna ${escapeHtml(name)}s profil"
    >
      ${profileInitial(name)}
    </button>
  `;
}

function renderPublicNameButton(item = {}, className = "") {
  const name = publicDisplayName(item);
  return `
    <button
      class="user-profile-link ${escapeHtml(className)}"
      type="button"
      data-action="public-profile-open"
      data-username="${escapeHtml(name)}"
    >
      ${escapeHtml(name)}
    </button>
  `;
}

function setLoading(isLoading, message = "Jobbar...") {
  state.isLoading = isLoading;
  state.loadingMessage = message;
  render();
}

function setError(message = "") {
  state.error = message;
  render();
}

function activeCardPayload(artistKey) {
  const item = state.itemIndex.get(artistKey);
  if (!item) {
    return null;
  }

  const audioValidated = hasValidatedAudio(item);

  return {
    artist_key: item.artist_key,
    song_key: item.song_key || item.track_key,
    track_key: item.track_key,
    track_id: item.track_id,
    artist: item.artist,
    song: item.song,
    title: item.title || item.song,
    album: item.album,
    genre: item.genre,
    image: item.image,
    preview: item.preview,
    deezer_link: item.deezer_link,
    lastfm_link: item.lastfm_link,
    reason: item.reason,
    top_genres: item.top_genres || [],
    similar_artists: item.similar_artists || [],
    metrics: item.metrics || {},
    audio_signature: item.audio_signature || {},
    mood_profile: item.mood_profile || {},
    estimated_mood_profile: item.estimated_mood_profile || {},
    audio_validated: audioValidated,
    mood_source: item.mood_source || "",
    discovery_labels: item.discovery_labels || [],
    cluster_id: item.cluster_id,
    cluster_label: item.cluster_label,
    small_artist_score: item.small_artist_score,
    source: item.source || state.view,
    is_custom: Boolean(item.is_custom),
  };
}

function hasValidatedAudio(item = {}) {
  if (item.audio_validated !== undefined && item.audio_validated !== null) {
    return Boolean(item.audio_validated);
  }
  if (item.metrics?.audio_features_validated !== undefined) {
    return Boolean(item.metrics.audio_features_validated);
  }
  return Boolean(item.audio_signature && Object.keys(item.audio_signature).length);
}

async function initialize() {
  try {
    const [boot, profile, feed, session] = await Promise.all([
      api.bootstrap(),
      api.profile(),
      api.feed({ exclude_artist_keys: [] }),
      api.session(),
    ]);

    state.boot = boot;
    state.feed.card = feed.card;
    state.feed.communityPosts = feed.community_posts || [];
    state.feed.trendingQuietly = feed.trending_quietly || [];
    state.feed.microCommunities = feed.micro_communities || [];
    state.feed.communityActivity = feed.community_activity || [];
    state.feed.discoveryTrail = feed.discovery_trail || [];
    rememberFeedItems();
    syncSession(session);
    syncProfile(profile);
  } catch (error) {
    state.error = error.message;
  } finally {
    state.isLoading = false;
    render();
  }
}

function render() {
  const boot = state.boot;
  const counts = boot?.stats;

  root.innerHTML = `
      <div class="app-shell">
      <div class="ambient ambient-one"></div>
      <div class="ambient ambient-two"></div>
      <div class="content-shell view-${escapeHtml(state.view)}">
        ${state.error ? `<div class="banner error-banner">${escapeHtml(state.error)}</div>` : ""}
        <main class="screen">
          ${state.isLoading ? renderLoadingState() : renderCurrentView()}
        </main>
        <nav class="bottom-nav">
          ${navItems.map(renderNavItem).join("")}
        </nav>
      </div>
      ${counts ? `<div class="corner-badge">${counts.artist_count} artister indexerade</div>` : ""}
    </div>
    ${renderArtistModal()}
    ${renderPublicProfileModal()}
    ${renderCreateCommunityModal()}
    ${renderExplanationModal()}
  `;

  refreshActionStates();
}

function renderLoadingState() {
  return `
    <section class="hero-stack loading-state">
      <div class="hero-icon shimmer">${icon("note")}</div>
      <h1>${escapeHtml(state.loadingMessage)}</h1>
      <p>Vi kopplar ihop datasetet med Deezer och Last.fm.</p>
    </section>
  `;
}

function renderNavItem(item) {
  const activeClass = state.view === item.key ? "is-active" : "";
  return `
    <button class="nav-button ${activeClass}" data-view="${item.key}" type="button">
      <span class="nav-icon">${icon(item.icon)}</span>
      <span>${item.label}</span>
    </button>
  `;
}

function renderCurrentView() {
  switch (state.view) {
    case "suggest":
      return renderSuggestView();
    case "feed":
      return renderFeedCommunityView();
    case "songs":
      return renderSongSearchView();
    case "search":
      return renderSearchView();
    case "profile":
      return renderProfileView();
    default:
      return renderSearchView();
  }
}

function renderSuggestView() {
  const recentCustom = state.profile.custom_artists.slice(0, 2);
  rememberItems(recentCustom);

  return `
    <section class="hero-stack compact-hero">
      <div class="hero-icon">${icon("plane")}</div>
      <h1>Föreslå en Låt</h1>
      <p>Skicka in ditt musikförslag med en ISRC-kod.</p>
    </section>
    <section class="stack">
      <form class="card form-card" id="suggest-form" novalidate>
        <label class="field-label" for="isrc-input">ISRC-kod</label>
        <input
          id="isrc-input"
          name="isrc"
          class="text-input"
          type="text"
          value="${escapeHtml(state.suggestionDraft.isrc)}"
          placeholder="t.ex. USRC17607839"
          autocomplete="off"
        />
        <p class="microcopy">International Standard Recording Code (ISRC) är en unik identifierare för inspelningar.</p>
        <label class="checkbox-card">
          <input id="confirm-smaller" name="confirm" type="checkbox" ${state.suggestionDraft.confirm ? "checked" : ""} />
          <span>Jag bekräftar att det här är en mindre artist som jag vill lägga till i appen.</span>
        </label>
        <button class="primary-button wide-button" type="submit" id="suggest-submit">
          Skicka In Låt
        </button>
      </form>
      ${
        state.suggestionStatus
          ? `<div class="banner success-banner">${escapeHtml(state.suggestionStatus)}</div>`
          : ""
      }
      <section class="support-card">
        <h2>Hur hittar man ISRC-koder?</h2>
        <p>Du kan hitta ISRC-koder på musikplattformar som Spotify, Apple Music eller via musiktjänster och databaser som visar låtmetadata.</p>
      </section>
      ${
        recentCustom.length
          ? `
            <section class="stack">
              <h2 class="section-title">Senast tillagda</h2>
              ${recentCustom.map((item) => renderProfileCard(item, "custom")).join("")}
            </section>
          `
          : ""
      }
    </section>
  `;
}

function renderFeedCommunityView() {
  const communityPosts = state.feed.communityPosts || [];
  const communities = state.feed.microCommunities || [];
  const activeCommunity = communities.find((community) => community.slug === state.activeCommunitySlug);
  rememberFeedItems();

  if (activeCommunity) {
    return renderCommunitySpace(activeCommunity);
  }

  return `
    <section class="feed-ecosystem">
      ${renderMicroCommunityRail(communities)}
      <section class="community-main">
        <div class="section-kicker">
          <p class="eyebrow">Community discoveries</p>
          <h2>Vad folk hittar och delar</h2>
        </div>
        ${renderCommunityComposer()}
        <div class="post-stack">
          ${communityPosts.map(renderCommunityPost).join("")}
        </div>
      </section>
    </section>
  `;
}

function renderFeedHero(card) {
  const songKey = songKeyForItem(card);
  return `
    <section class="underground-hero">
      <div class="underground-hero-media">
        ${
          card.image
            ? `<img src="${escapeHtml(card.image)}" alt="${escapeHtml(card.artist)}" />`
            : `<div class="image-fallback">${icon("note")}</div>`
        }
      </div>
      <div class="underground-hero-content">
        <button class="feature-pill hero-pill" type="button" data-action="artist-detail" data-key="${escapeHtml(card.artist_key)}">Upptäck</button>
        <h1 data-action="artist-detail" data-key="${escapeHtml(card.artist_key)}">${escapeHtml(card.artist)}</h1>
        <p class="hero-track" ${songKey ? `data-action="song-detail" data-song-key="${escapeHtml(songKey)}" role="button" tabindex="0"` : ""}>${escapeHtml(card.song || "Community discovery")}</p>
        ${renderHeroSummaryPills(card)}
        <div class="action-row hero-actions">
          ${renderPreviewSlot(card, "hero-audio")}
          <button type="button" class="icon-button" data-action="save-toggle" data-key="${escapeHtml(card.artist_key)}">${state.savedKeys.has(card.artist_key) ? icon("bookmarkFilled") : icon("heart")}</button>
          <button type="button" class="primary-button mini-button" data-action="feed-next">${icon("next")} Byt</button>
        </div>
      </div>
    </section>
  `;
}

function renderMicroCommunityRail(communities = []) {
  if (!communities.length) {
    return "";
  }
  return `
    <section class="community-rail-section">
      <div class="section-kicker">
        <p class="eyebrow">Utforska communities</p>
        <h2>Små scener som håller musiken vid liv</h2>
      </div>
      <div class="community-rail">
        ${communities.map((community) => `
          <button class="community-pill" type="button" data-action="community-open" data-slug="${escapeHtml(community.slug)}">
            <span>${escapeHtml(community.name)}</span>
            <small>${
              community.shared_count
                ? `${formatNumber(community.shared_count)} delade`
                : community.post_count
                  ? `${formatNumber(community.post_count)} posts`
                  : community.suggested_count
                    ? `${formatNumber(community.suggested_count)} fynd`
                    : "ny scen"
            }</small>
          </button>
        `).join("")}
        <button class="community-pill community-create-pill" type="button" data-action="community-create-open">
          <span>${icon("plus")} Skapa rum</span>
          <small>${state.session.authenticated ? "ny scen" : "logga in"}</small>
        </button>
      </div>
    </section>
  `;
}

function renderTrendingQuietly(items = []) {
  // UNDER_RADAR_GRID_START
  const visibleItems = items.slice(0, 10);
  if (!visibleItems.length) {
    return "";
  }
  const underRadarGrid = `
    <section class="quiet-section">
      <div class="section-kicker centered">
        <h2 class="mix-under-radar-title">Nya tillagda låtar</h2>
        <p class="eyebrow">Trending quietly</p>
      </div>
      <div class="quiet-grid">
        ${visibleItems.map(renderQuietArtist).join("")}
      </div>
    </section>
  `;
  // UNDER_RADAR_GRID_END
  return underRadarGrid;
}

function renderQuietArtist(item = {}) {
  const songKey = songKeyForItem(item);
  return `
    <article class="quiet-card" ${songKey ? `data-action="song-detail" data-song-key="${escapeHtml(songKey)}"` : `data-action="artist-detail" data-key="${escapeHtml(item.artist_key)}"`} role="button" tabindex="0">
      <div class="quiet-image">
        ${item.image ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist)}" />` : `<div class="image-fallback">${icon("note")}</div>`}
      </div>
      <div>
        <strong>${escapeHtml(item.song || item.artist || "Okänd låt")}</strong>
        <span>${escapeHtml(item.artist || "Okänd artist")}</span>
        ${renderPreviewSlot(item, "mini-audio", { showMissing: false })}
      </div>
    </article>
  `;
}

// MIX_PAGE_TEXT_CLEANUP_START
function renderHeroSummaryPills(item = {}) {
  const labels = [];
  if (item.genre) {
    labels.push(item.genre);
  }
  if (isNewlyUploaded(item)) {
    labels.push("Nyligen uppladdad");
  }
  const likes = heroCountValue(item, ["like_count", "likes", "saved_count", "saved_count_total"]);
  if (likes) {
    labels.push(`${formatNumber(likes)} likes`);
  }
  const comments = heroCountValue(item, ["comment_count", "comments_count", "reply_count", "discussion_count"]);
  if (comments) {
    labels.push(`${formatNumber(comments)} kommentarer`);
  }

  if (!labels.length) {
    return "";
  }

  return `
    <div class="hero-signal-row">
      ${labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}
    </div>
  `;
}

function isNewlyUploaded(item = {}) {
  const labels = item.discovery_labels || [];
  return Boolean(item.is_custom || item.isrc || item.added_at || labels.includes("Newly added"));
}

function heroCountValue(item = {}, keys = []) {
  for (const key of keys) {
    const value = Number(item[key] ?? item.metrics?.[key]);
    if (Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  return 0;
}
// MIX_PAGE_TEXT_CLEANUP_END

function renderCommunitySpace(community) {
  const sharedArtists = community.shared_artists || [];
  const relatedDiscoveries = community.related_discoveries || [];
  rememberItems([...(community.artists || []), ...sharedArtists, ...relatedDiscoveries]);
  return `
    <section class="community-space">
      <button class="ghost-button" type="button" data-action="community-close">Tillbaka till flödet</button>
      <div class="community-space-hero">
        <p class="eyebrow">${formatNumber(community.shared_count || 0)} shared here - ${formatNumber(community.post_count || 0)} community posts${community.suggested_count ? ` - ${formatNumber(community.suggested_count)} nearby finds` : ""}</p>
        <h1>${escapeHtml(community.name)}</h1>
        <p>${escapeHtml(community.description)}</p>
        ${community.motto ? `<blockquote class="community-motto">"${escapeHtml(community.motto)}"</blockquote>` : ""}
        <div class="metric-row">
          ${(community.tags || []).map((tag) => `<span class="metric-pill accent-pill">${escapeHtml(tag)}</span>`).join("")}
          ${community.tone ? `<span class="metric-pill">${escapeHtml(community.tone)}</span>` : ""}
          <span class="metric-pill">${escapeHtml(community.activity || "No posts yet")}</span>
        </div>
      </div>
      <div class="community-layout">
        <div class="community-main">
          ${community.belongs_here ? `<div class="support-card community-identity-card"><h2>Scene note</h2><p>${escapeHtml(shortCopy(community.belongs_here, 115))}</p></div>` : ""}
          <h2 class="section-title">Shared by this community</h2>
          ${
            sharedArtists.length
              ? `<div class="community-artist-grid">${sharedArtists.map(renderCommunityArtistCard).join("")}</div>`
              : renderEmptyState("Inga delade artister än", "Den här scenen har inga riktiga delningar än. Var först med ett tips.")
          }
          <h2 class="section-title">Nearby finds</h2>
          <p class="subtle-copy">Suggested context from the dataset and music metadata, separate from community shares.</p>
          <div class="community-artist-grid">
            ${relatedDiscoveries.length ? relatedDiscoveries.map(renderCommunityArtistCard).join("") : renderEmptyState("Inga närliggande fynd", "När mer data finns kan vi visa lugna, relaterade upptäckter här.")}
          </div>
          ${renderCommunityComposer(community)}
          <h2 class="section-title">Threads</h2>
          <div class="post-stack">
            ${(community.posts || []).length ? community.posts.map(renderCommunityPost).join("") : renderEmptyState("Inga trådar än", "Den här scenen väntar på sitt första tips.")}
          </div>
        </div>
        <aside class="community-sidebar">
          <div class="side-card">
            <h3>Scene notes</h3>
            <p>${formatNumber(community.shared_count || 0)} shared here.</p>
            <p>${formatNumber(community.post_count || 0)} community posts.</p>
            ${community.suggested_count ? `<p>${formatNumber(community.suggested_count)} nearby finds shown as suggested context.</p>` : ""}
            ${community.submission_prompt ? `<p>${escapeHtml(community.submission_prompt)}</p>` : ""}
          </div>
        </aside>
      </div>
    </section>
  `;
}

function renderCommunityArtistCard(item = {}) {
  return `
    <article class="community-artist-card" data-action="artist-detail" data-key="${escapeHtml(item.artist_key)}" role="button" tabindex="0">
      <div class="mini-artwork">
        ${item.image ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist)}" />` : `<div class="image-fallback">${icon("note")}</div>`}
      </div>
      <div>
        <strong>${escapeHtml(item.artist)}</strong>
        <span>${escapeHtml(item.genre || item.song || "underground find")}</span>
        ${renderReasonChips(item, { limit: 1, compact: true })}
      </div>
      <div class="community-card-actions">
        ${renderPreviewSlot(item, "mini-audio", { showMissing: false })}
        <button class="icon-button quiet-button" type="button" data-action="save-toggle" data-key="${escapeHtml(item.artist_key)}" aria-label="Spara artist">
          ${state.savedKeys.has(item.artist_key) ? icon("bookmarkFilled") : icon("bookmark")}
        </button>
      </div>
    </article>
  `;
}

function renderCommunityComposer(community = null) {
  // COMMUNITY_POST_SAVED_SONG_SELECT_START
  const savedSongs = state.profile.saved_artists || [];
  // COMMUNITY_POST_SAVED_SONG_SELECT_END
  return `
    <section class="support-card community-divider">
      <h2>Posta en upptäckt</h2>
      <form class="community-form" id="community-form">
        <input type="hidden" name="community_slug" value="${escapeHtml(community?.slug || state.activeCommunitySlug || "")}" />
        <textarea class="text-area" name="text" rows="4" placeholder="${escapeHtml(community?.submission_prompt || "Dela en känsla, en liten scen eller ett låttips...")}"></textarea>
        ${state.communityTipOpen ? renderSavedSongSelect(savedSongs) : ""}
        <div class="composer-actions">
          <button type="button" class="ghost-button" data-action="toggle-tip">+ Rekommendera sparad låt</button>
          <button type="submit" class="primary-button mini-button">${icon("plane")} Posta</button>
        </div>
      </form>
    </section>
  `;
}

// COMMUNITY_POST_SAVED_SONG_SELECT_START
function renderSavedSongSelect(savedSongs = []) {
  if (!savedSongs.length) {
    return `<p class="saved-song-empty">Spara en låt först för att kunna dela den här.</p>`;
  }
  const selectedSong = savedSongBySelectKey(state.communitySelectedSongKey);

  return `
    <div class="saved-song-picker">
      <label class="saved-song-select">
        <span>Välj sparad låt</span>
        <select class="text-input" name="saved_song_key" id="community-saved-song">
        <option value="">Välj en låt från profilen</option>
        ${savedSongs.map((item, index) => {
          const key = communitySongSelectKey(item, index);
          return `
            <option value="${escapeHtml(key)}" ${state.communitySelectedSongKey === key ? "selected" : ""}>
              ${escapeHtml(item.song || item.title || "Okänd låt")} - ${escapeHtml(item.artist || "Okänd artist")}
            </option>
          `;
        }).join("")}
        </select>
      </label>
      ${selectedSong ? renderSavedSongPreview(selectedSong) : ""}
    </div>
  `;
}

function communitySongSelectKey(item = {}, index = 0) {
  return String(index);
}

function savedSongBySelectKey(key = "") {
  const index = Number(key);
  return Number.isInteger(index) ? (state.profile.saved_artists || [])[index] || null : null;
}

function cleanCommunitySongKey(item = {}) {
  const key = songKeyForItem(item);
  return key && String(key).toLowerCase() !== "nan" ? String(key) : "";
}

function cleanCommunityString(value) {
  if (value === undefined || value === null) {
    return null;
  }
  const text = String(value).trim();
  return text && text.toLowerCase() !== "nan" ? text : null;
}

function cleanCommunityTrackId(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value === "number" && Number.isNaN(value)) {
    return null;
  }
  return value;
}

function communityPostPayload(text, selectedSong, communitySlug) {
  const payload = {
    text,
    username: currentProfileName(),
    community_slug: communitySlug || null,
  };

  if (!selectedSong) {
    return payload;
  }

  return {
    ...payload,
    tip_artist: cleanCommunityString(selectedSong.artist),
    tip_song: cleanCommunityString(selectedSong.song || selectedSong.title),
    song_key: cleanCommunitySongKey(selectedSong) || null,
    track_key: cleanCommunityString(selectedSong.track_key),
    track_id: cleanCommunityTrackId(selectedSong.track_id),
    isrc: cleanCommunityString(selectedSong.isrc),
  };
}

function communityCoverForItem(item = {}) {
  return item.image || item.cover || item.image_url || item.album_cover || item.artwork_url || item.coverUrl || item.album?.cover || "";
}

function renderSavedSongPreview(item = {}) {
  const cover = communityCoverForItem(item);
  return `
    <div class="saved-song-preview">
      <div class="saved-song-preview-art">
        ${cover ? `<img src="${escapeHtml(cover)}" alt="${escapeHtml(item.artist || item.song || "Sparad låt")}" />` : `<div class="image-fallback">${icon("note")}</div>`}
      </div>
      <div>
        <strong>${escapeHtml(item.song || item.title || "Okänd låt")}</strong>
        <span>${escapeHtml(item.artist || "Okänd artist")}</span>
        ${item.genre ? `<small>${escapeHtml(item.genre)}</small>` : ""}
      </div>
    </div>
  `;
}
// COMMUNITY_POST_SAVED_SONG_SELECT_END

function renderCommunityActivity(items = []) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="side-card">
      <h3>Händer just nu</h3>
      <div class="activity-list">
        ${items.map((item) => `
          <button
            type="button"
            data-action="${item.community_slug ? "community-open" : "artist-detail"}"
            ${item.community_slug ? `data-slug="${escapeHtml(item.community_slug)}"` : `data-key="${escapeHtml(item.artist_key || "")}"`}
          >
            ${escapeHtml(item.text)}
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function renderDiscoveryTrail(trail = []) {
  if (!trail.length) {
    return "";
  }
  const steps = trail.map((step) => normalizeInteractiveSignal(step, "Discovery trail")).filter((step) => step.label);
  return `
    <div class="side-card trail-card">
      <h3>Discovery trail</h3>
      ${steps.map((step) => `
        <button class="trail-step" type="button" ${actionAttributesForSignal(step)}>
          <span>${escapeHtml(step.label)}</span>
          ${step.explanation ? `<small>${escapeHtml(step.kind || "explanation")}</small>` : ""}
        </button>
      `).join("")}
    </div>
  `;
}

function renderSearchView() {
  if (state.searchResults.length > 0) {
    rememberItems(state.searchResults);
  }
  rememberFeedItems();
  // MIX_PAGE_TRENDING_HERO_START
  const mixTrendingHero = state.feed.card ? renderFeedHero(state.feed.card) : "";
  // MIX_PAGE_TRENDING_HERO_END
  // MIX_LAYOUT_MOVE_START
  const mixDiscoverySection = renderTrendingQuietly(state.feed.trendingQuietly || []);
  // MIX_LAYOUT_MOVE_END

  return `
    ${mixTrendingHero}
    ${mixDiscoverySection}
    <section class="hero-stack compact-hero">
      <div class="hero-icon">${icon("sparkles")}</div>
      <h1>Musikmixer</h1>
      <p>Slumpa låtar från olika genrer eller styr resultatet med musikens egenskaper</p>
      ${renderPropertyMixer()}
      ${state.searchInterpretation ? renderSearchInterpretation(state.searchInterpretation) : ""}
    </section>
    ${
      state.searchResults.length > 0
        ? `
          <section class="stack">
            <h2 class="section-title">Rekommenderade mindre artister</h2>
            ${state.searchResults.map((item) => renderArtistCard(item, { compact: true, mixResult: true })).join("")}
            <button class="secondary-button wide-button" type="button" data-action="search-reset">Ny Sökning</button>
          </section>
        `
        : state.searchHasRun
          ? `
            <section class="stack">
              ${renderEmptyState("Inga träffar", "Prova att vara lite bredare med prompten eller välj en annan stämning.")}
              <button class="secondary-button wide-button" type="button" data-action="search-reset">Ny Sökning</button>
            </section>
          `
        : `
          <section class="stack">
            <div class="feature-pill">Kluster först, värden sen</div>
            <div class="support-card">
              <p>Välj genre först. Öppna egenskaper om du vill styra känsla, tempo och energi mer exakt.</p>
            </div>
          </section>
        `
    }
  `;
}

function renderSongSearchView() {
  if (state.songSearchResults.length > 0) {
    rememberItems(state.songSearchResults);
  }

  return `
    <section class="hero-stack compact-hero">
      <div class="hero-icon">${icon("note")}</div>
      <h1>Låtsökning</h1>
      <form class="mixer-panel" id="song-search-form" novalidate>
        <label class="field-label" for="song-search-input">Sök låt</label>
        <input
          class="text-input"
          id="song-search-input"
          name="query"
          type="search"
          placeholder="Titel, artist eller album"
          value="${escapeHtml(state.songSearchQuery)}"
          autocomplete="off"
        />
        <button class="primary-button wide-button" type="submit" ${state.songSearchLoading ? "disabled" : ""}>
          ${icon("note")} ${state.songSearchLoading ? "Söker..." : "Sök"}
        </button>
      </form>
      ${state.songSearchError ? `<div class="banner error-banner">${escapeHtml(state.songSearchError)}</div>` : ""}
    </section>
    <section class="stack">
      ${
        state.songSearchLoading
          ? `<div class="support-card"><p>Hämtar låtar...</p></div>`
          : state.songSearchResults.length
            ? `
              <h2 class="section-title">Låtresultat</h2>
              ${state.songSearchResults.map((item) => renderArtistCard(item, { compact: true })).join("")}
            `
            : state.songSearchHasRun
              ? renderEmptyState("Inga träffar", "Prova en annan titel, artist eller album.")
              : renderEmptyState("Sök i datasetet", "Resultaten öppnas i samma låtmodal som resten av appen.")
      }
    </section>
  `;
}

function renderPropertyMixer() {
  const searchedGenres = getSearchedDatasetGenres();
  const isNewAddedMode = state.mixMode === "new_added";
  return `
    <div class="mixer-panel">
      <div class="preset-row">
        <button class="preset-button ${state.mixMode === "surprise" ? "is-active" : ""}" type="button" data-mix-mode="surprise">
          Överraska mig
        </button>
        <button class="preset-button ${isNewAddedMode ? "is-active" : ""}" type="button" data-mix-mode="new_added">
          Nya tillagda
        </button>
      </div>
      <div class="mixer-section-heading">
        <span>Genre</span>
        <strong>${state.mixGenres.length ? `${state.mixGenres.length} valda` : "Välj minst en"}</strong>
      </div>
      <div class="mix-genre-panel">
        ${(state.boot?.genres || [])
          .filter((genre) => !hiddenMixGenreChips.has(normalizeUiGenre(genre.label)))
          .map(
            (genre) => `
              <button
                class="genre-chip ${hasMixGenre(genre.label) ? "is-active" : ""}"
                type="button"
                data-mix-genre="${genre.label}"
              >
                ${escapeHtml(genre.label)}
              </button>
            `
          )
          .join("")}
      </div>
      <div class="genre-search-panel">
        <input
          class="genre-search-input"
          id="mix-genre-search"
          type="search"
          placeholder="Sök bland genrer"
          value="${escapeHtml(state.mixGenreQuery)}"
          autocomplete="off"
        />
        ${
          state.mixGenres.length
            ? `<div class="selected-genre-row">
                ${state.mixGenres.map((genre) => `
                  <button class="selected-genre-chip" type="button" data-mix-genre="${escapeHtml(genre)}">
                    ${escapeHtml(formatGenreLabel(genre))}
                  </button>
                `).join("")}
              </div>`
            : ""
        }
        ${
          searchedGenres.length
            ? `<div class="genre-search-results">
                ${searchedGenres.map((genre) => `
                  <button
                    class="genre-search-option ${hasMixGenre(genre.label) ? "is-active" : ""}"
                    type="button"
                    data-mix-genre="${escapeHtml(genre.label)}"
                  >
                    <span>${escapeHtml(formatGenreLabel(genre.label))}</span>
                    <small>${formatNumber(genre.count)}</small>
                  </button>
                `).join("")}
              </div>`
            : ""
        }
      </div>
      ${isNewAddedMode ? "" : `
        <button class="property-disclosure ${state.mixPropertiesOpen ? "is-open" : ""}" type="button" data-action="toggle-properties">
          <span>Egenskaper</span>
          <strong>${state.mixUseProperties ? renderPropertySummary() : "Av"}</strong>
        </button>
        ${
          state.mixPropertiesOpen
            ? `
              <div class="properties-panel">
                <label class="property-toggle">
                  <input type="checkbox" id="mix-use-properties" ${state.mixUseProperties ? "checked" : ""} />
                  <span>Använd egenskaper i sökningen</span>
                </label>
                <div class="preset-row">
                  ${Object.entries(mixPresets)
                    .map(
                      ([key, preset]) => `
                        <button class="preset-button ${state.mixPreset === key ? "is-active" : ""}" type="button" data-mix-preset="${key}">
                          ${escapeHtml(preset.label)}
                        </button>
                      `
                    )
                    .join("")}
                </div>
                <div class="slider-grid">
                  ${mixFeatures.map(renderMixSlider).join("")}
                </div>
              </div>
            `
            : ""
        }
      `}
      <button class="primary-button wide-button" type="button" data-action="mix-submit">
        ${icon("sparkles")} Generera
      </button>
    </div>
  `;
}

function formatGenreLabel(value) {
  return String(value || "")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizeUiGenre(value) {
  return String(value || "").trim().toLowerCase().replaceAll("&", "and").replaceAll(/[^a-z0-9]+/g, "-").replaceAll(/^-|-$/g, "");
}

function hasMixGenre(genre) {
  const normalized = normalizeUiGenre(genre);
  return state.mixGenres.some((item) => normalizeUiGenre(item) === normalized);
}

function getSearchedDatasetGenres() {
  const query = normalizeUiGenre(state.mixGenreQuery);
  if (!query) {
    return [];
  }

  const quickGenreValues = new Set();
  for (const genre of state.boot?.genres || []) {
    quickGenreValues.add(normalizeUiGenre(genre.label));
    for (const datasetGenre of genre.dataset_genres || []) {
      quickGenreValues.add(normalizeUiGenre(datasetGenre));
    }
  }

  return (state.boot?.all_genres || [])
    .filter((genre) => {
      const normalized = normalizeUiGenre(genre.label);
      const searchable = normalizeUiGenre(formatGenreLabel(genre.label));
      return !quickGenreValues.has(normalized) && (normalized.includes(query) || searchable.includes(query));
    })
    .slice(0, 14);
}

function renderPropertySummary() {
  return `${Math.round(state.mixTargets.energy)} energi / ${Math.round(state.mixTargets.tempo)} bpm`;
}

function updateMixSliderDisplay(input) {
  const feature = mixFeatures.find((item) => item.key === input.dataset.mixFeature);
  if (!feature) {
    return;
  }

  const value = Number(input.value);
  const percent = feature.key === "tempo"
    ? Math.round(((value - feature.min) / (feature.max - feature.min)) * 100)
    : Math.round(value);
  const displayValue = feature.key === "tempo" ? `${Math.round(value)} bpm` : `${Math.round(value)}%`;

  input.style.setProperty("--slider-value", `${percent}%`);
  const valueLabel = input.closest(".mix-slider")?.querySelector(".slider-heading strong");
  if (valueLabel) {
    valueLabel.textContent = displayValue;
  }

  const summary = root.querySelector(".property-disclosure strong");
  if (summary && state.mixUseProperties) {
    summary.textContent = renderPropertySummary();
  }
}

function renderMixSlider(feature) {
  const value = Number(state.mixTargets[feature.key] ?? feature.min);
  const percent = feature.key === "tempo"
    ? Math.round(((value - feature.min) / (feature.max - feature.min)) * 100)
    : Math.round(value);
  const displayValue = feature.key === "tempo" ? `${Math.round(value)} bpm` : `${Math.round(value)}%`;

  return `
    <label class="mix-slider">
      <span class="slider-heading">
        <span>${escapeHtml(feature.label)}</span>
        <strong>${escapeHtml(displayValue)}</strong>
      </span>
      <input
        type="range"
        min="${feature.min}"
        max="${feature.max}"
        value="${value}"
        data-mix-feature="${feature.key}"
        ${state.mixUseProperties ? "" : "disabled"}
        style="--slider-value: ${percent}%"
      />
      <span class="slider-scale">
        <span>${escapeHtml(feature.low)}</span>
        <span>${escapeHtml(feature.high)}</span>
      </span>
    </label>
  `;
}

function renderProfileView() {
  if (!state.session.authenticated) {
    if (state.profileAuthMode === "login") {
      return renderProfileLoginView();
    }
    if (state.profileAuthMode === "create") {
      return renderProfileCreateView();
    }
    return renderLoggedOutProfileView();
  }

  return renderLoggedInProfileView();
}

function renderLoggedOutProfileView() {
  const savedCount = state.profile.saved_count || 0;
  const commentCount = (state.profile.profile_song_comments || []).length;
  const communityCount = profileCommunityCount();
  return `
    <section class="profile-auth-shell">
      <div class="profile-auth-avatar">${icon("user")}</div>
      <h1>Min Profil</h1>
      <p>Skapa en profil för att spara låtar, kommentera och dela musikrum.</p>
      ${state.authError ? `<div class="banner error-banner profile-auth-message">${escapeHtml(state.authError)}</div>` : ""}
      ${state.authStatus ? `<div class="banner success-banner profile-auth-message">${escapeHtml(state.authStatus)}</div>` : ""}
      <div class="profile-auth-actions">
        <button class="primary-button profile-auth-primary" type="button" data-action="profile-login-open">Logga in</button>
        <button class="ghost-button profile-auth-secondary" type="button" data-action="profile-create-open">Skapa konto</button>
      </div>
      <div class="profile-preview-grid">
        ${renderProfilePreviewCard("bookmark", formatNumber(savedCount), "Sparade låtar")}
        ${renderProfilePreviewCard("radio", formatNumber(commentCount), "Kommentarer")}
        ${renderProfilePreviewCard("user", formatNumber(communityCount), "Communities")}
      </div>
    </section>
  `;
}

function renderProfileLoginView() {
  return `
    <section class="profile-auth-panel card">
      <div class="profile-auth-panel-header">
        <h1>Logga in</h1>
        <button class="icon-button quiet-button profile-auth-close" type="button" data-action="profile-auth-back" aria-label="Tillbaka">×</button>
      </div>
      ${renderAuthMessage()}
      <form id="profile-login-form" class="profile-auth-form">
        <label>
          <span>Profilnamn</span>
          <input class="text-input" name="username" type="text" autocomplete="username" placeholder="ditt användarnamn" required />
        </label>
        <label>
          <span>Lösenord</span>
          <input class="text-input" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required />
        </label>
        <button class="primary-button profile-auth-primary" type="submit" ${state.authLoading ? "disabled" : ""}>Logga in</button>
        <button class="ghost-button profile-auth-secondary" type="button" data-action="profile-auth-back">Tillbaka</button>
        <p class="profile-auth-switch">Inget konto? <button type="button" data-action="profile-create-open">Skapa konto</button></p>
      </form>
    </section>
  `;
}

function renderProfileCreateView() {
  return `
    <section class="profile-auth-panel card profile-create-panel">
      <div class="profile-auth-panel-header">
        <h1>Skapa konto</h1>
        <button class="icon-button quiet-button profile-auth-close" type="button" data-action="profile-auth-back" aria-label="Tillbaka">×</button>
      </div>
      ${renderAuthMessage()}
      <form id="profile-register-form" class="profile-auth-form">
        <div class="avatar-picker">
          <div class="profile-auth-avatar avatar-${escapeHtml(state.selectedAvatarPreset)}">${icon("user")}</div>
          <div class="avatar-preset-row" role="radiogroup" aria-label="Välj avatar">
            ${avatarPresets.map((preset) => `
              <button
                class="avatar-preset avatar-${escapeHtml(preset.key)} ${state.selectedAvatarPreset === preset.key ? "selected" : ""}"
                type="button"
                data-action="avatar-preset"
                data-avatar="${escapeHtml(preset.key)}"
                aria-label="${escapeHtml(preset.label)}"
              ></button>
            `).join("")}
          </div>
        </div>
        <label>
          <span>Profilnamn</span>
          <input class="text-input" name="username" type="text" autocomplete="username" placeholder="välj ett användarnamn" required />
        </label>
        <label>
          <span>Lösenord</span>
          <input class="text-input" name="password" type="password" autocomplete="new-password" placeholder="••••••••" required />
        </label>
        <label>
          <span>Bekräfta lösenord</span>
          <input class="text-input" name="confirm_password" type="password" autocomplete="new-password" placeholder="••••••••" required />
        </label>
        <button class="primary-button profile-auth-primary" type="submit" ${state.authLoading ? "disabled" : ""}>Skapa konto</button>
        <button class="ghost-button profile-auth-secondary" type="button" data-action="profile-auth-back">Tillbaka</button>
      </form>
    </section>
  `;
}

function renderLoggedInProfileView() {
  const saved = state.profile.saved_artists || [];
  const custom = state.profile.custom_artists || [];
  const profilePosts = state.profile.profile_posts || [];
  const profileReplies = state.profile.profile_replies || [];
  const profileSongComments = state.profile.profile_song_comments || [];
  const profileDiscussions = state.profile.profile_discussions || [];
  const activityCount = profilePosts.length + profileReplies.length + profileSongComments.length;
  rememberItems(saved);
  rememberItems(custom);

  return `
    <section class="hero-stack compact-hero profile-account-hero">
      ${renderAccountAvatar(state.session.user, "profile-account-avatar")}
      <h1>${escapeHtml(currentProfileName())}</h1>
      <p>Dina sparade låtar, egna tillskott och senaste aktivitet.</p>
      <div class="metric-row centered">
        <span class="metric-pill">${state.profile.saved_count} sparade</span>
        <span class="metric-pill">${state.profile.custom_count} egna tillskott</span>
        <span class="metric-pill">${activityCount} aktiviteter</span>
      </div>
      <button class="ghost-button mini-button profile-logout-button" type="button" data-action="profile-logout">Logga ut</button>
    </section>
    <section class="stack">
      <h2 class="section-title">Sparade artister</h2>
      ${
        saved.length
          ? saved.map((item) => renderProfileCard(item, "saved")).join("")
          : renderEmptyState("Inga sparade än", "Spara favoriter från Mix, Flöde eller Sök.")
      }
      <h2 class="section-title">Egna tillskott</h2>
      ${
        custom.length
          ? custom.map((item) => renderProfileCard(item, "custom")).join("")
          : renderEmptyState("Inga egna tillskott än", "Använd Föreslå-vyn för att lägga till en artist via ISRC.")
      }
      <h2 class="section-title">Mina inlägg</h2>
      ${
        profilePosts.length
          ? profilePosts.map(renderProfilePostActivity).join("")
          : renderEmptyState("Inga inlägg än", "Skriv i flödet eller i ett musikrum så syns aktiviteten här.")
      }
      <h2 class="section-title">Mina svar</h2>
      ${
        profileReplies.length
          ? profileReplies.map(renderProfileReplyActivity).join("")
          : renderEmptyState("Inga svar än", "Svara i en tråd för att samla dina replies här.")
      }
      <h2 class="section-title">Mina kommentarer</h2>
      ${
        profileSongComments.length
          ? profileSongComments.map(renderProfileSongCommentActivity).join("")
          : renderEmptyState("Inga låtkommentarer än", "Kommentera i en låtdiskussion för att visa den här.")
      }
      <h2 class="section-title">Diskussioner kring mina låtar</h2>
      ${
        profileDiscussions.length
          ? profileDiscussions.map(renderProfileDiscussionActivity).join("")
          : renderEmptyState("Inga diskussioner än", "När någon diskuterar låtar du sparat, lagt till eller delat visas det här.")
      }
    </section>
  `;
}

function renderAuthMessage() {
  return `
    ${state.authError ? `<div class="banner error-banner profile-auth-message">${escapeHtml(state.authError)}</div>` : ""}
    ${state.authStatus ? `<div class="banner success-banner profile-auth-message">${escapeHtml(state.authStatus)}</div>` : ""}
  `;
}

function renderProfilePreviewCard(iconName, value, label) {
  return `
    <div class="profile-preview-card">
      <span>${icon(iconName)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(label)}</p>
    </div>
  `;
}

function renderAccountAvatar(account = {}, className = "") {
  const avatar = account?.avatar_kind === "preset" ? account.avatar_value || "violet" : "violet";
  return `<div class="profile-auth-avatar ${className} avatar-${escapeHtml(avatar)}">${icon("user")}</div>`;
}

function profileCommunityCount() {
  const slugs = new Set();
  [...(state.profile.profile_posts || []), ...(state.profile.profile_replies || []), ...(state.profile.profile_discussions || [])]
    .forEach((item) => {
      if (item.community_slug) {
        slugs.add(item.community_slug);
      }
    });
  return slugs.size;
}

function renderArtistCard(item, options = {}) {
  const compact = options.compact === true;
  const mixResult = options.mixResult === true;
  const songKey = songKeyForItem(item);
  const previewOptions = { showMissing: !compact };
  if (mixResult) {
    return `
      <article class="artist-card card ${compact ? "compact-card" : ""}" ${songKey ? `data-action="song-detail" data-song-key="${escapeHtml(songKey)}"` : ""} role="button" tabindex="0">
        <div class="artist-card-top">
          <div class="artwork">
            ${
              item.image
                ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist)}" />`
                : `<div class="image-fallback">${icon("note")}</div>`
            }
          </div>
          <div class="artist-meta">
            <div class="card-heading-row">
              <div>
                <h2>${escapeHtml(item.song || "Okänd låt")}</h2>
                <p class="muted-line">${escapeHtml(item.artist || "Okänd artist")}</p>
              </div>
            </div>
            ${item.genre ? `<div class="metric-row"><span class="metric-pill accent-pill">${escapeHtml(item.genre)}</span></div>` : ""}
            ${renderAudioFeaturePills(item)}
          </div>
        </div>
        <div class="card-actions ${compact ? "compact-actions" : ""}">
          ${renderPreviewSlot(item, "", previewOptions)}
        </div>
      </article>
    `;
  }

  return `
    <article class="artist-card card ${compact ? "compact-card" : ""}" ${songKey ? `data-action="song-detail" data-song-key="${escapeHtml(songKey)}"` : ""} role="button" tabindex="0">
      <div class="artist-card-top">
        <div class="artwork">
          ${
            item.image
              ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist)}" />`
              : `<div class="image-fallback">${icon("note")}</div>`
          }
        </div>
        <div class="artist-meta">
          <div class="card-heading-row">
            <div>
              <h2>${escapeHtml(item.song || "Okänd låt")}</h2>
              <p class="muted-line">${escapeHtml(item.artist || "Okänd artist")}</p>
              ${item.album ? `<p class="album-line">${escapeHtml(item.album)}</p>` : ""}
            </div>
            <button
              class="save-button"
              type="button"
              data-action="save-toggle"
              data-key="${escapeHtml(item.artist_key)}"
              aria-label="Spara artist"
            >
              ${state.savedKeys.has(item.artist_key) ? icon("bookmarkFilled") : icon("bookmark")}
            </button>
          </div>
          ${
            item.secondary_tracks?.length
              ? `<p class="secondary-track">Även känd för: ${escapeHtml(item.secondary_tracks.join(" • "))}</p>`
              : ""
          }
          ${renderDiscoveryBadges(item)}
          ${renderInsightStrip(item)}
          ${renderAudioFeaturePills(item)}
          <p class="body-copy">${escapeHtml(item.reason || "")}</p>
          <div class="metric-row">
            ${renderMetricPills(item.metrics)}
            ${item.genre ? `<span class="metric-pill accent-pill">${escapeHtml(item.genre)}</span>` : ""}
          </div>
        </div>
      </div>
      <div class="card-actions ${compact ? "compact-actions" : ""}">
        ${renderPreviewSlot(item, "", previewOptions)}
        <div class="link-row">
          ${
            item.deezer_link
              ? `<a class="link-button" href="${escapeHtml(item.deezer_link)}" target="_blank" rel="noreferrer">Öppna i Deezer</a>`
              : ""
          }
          ${
            item.lastfm_link
              ? `<a class="link-button ghost-link" href="${escapeHtml(item.lastfm_link)}" target="_blank" rel="noreferrer">Last.fm</a>`
              : ""
          }
        </div>
      </div>
    </article>
  `;
}

function renderMetricPills(metrics = {}) {
  const entries = [
    ["Spotify", metrics.spotify_popularity],
    ["Last.fm", metrics.lastfm_listeners],
    ["Deezer", metrics.deezer_fans],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "saknas");

  return entries
    .map(
      ([label, value]) => `<span class="metric-pill">${label}: ${formatNumber(value)}</span>`
    )
    .join("");
}

function renderDiscoveryBadges(item = {}) {
  const labels = item.discovery_labels || [];
  if (!labels.length) {
    return "";
  }

  return `
    <div class="badge-row">
      ${labels.map((label) => `<span class="discovery-badge">${escapeHtml(label)}</span>`).join("")}
    </div>
  `;
}

function labelFromSignal(signal) {
  if (typeof signal === "string") {
    return formatSignalLabel(signal);
  }
  return formatSignalLabel(signal?.label || signal?.text || "");
}

function formatSignalLabel(label = "") {
  if (label === "Dataset match") {
    return "From the dataset";
  }
  if (label.startsWith("Small score")) {
    return "Small artist signal";
  }
  if (label.startsWith("Underground cluster") || label.startsWith("Cluster context")) {
    return "Discovery context";
  }
  return label;
}

function reasonPriority(signal = {}) {
  const kind = signal.kind || "";
  const label = signal.raw_label || signal.label || "";
  if (kind === "community" || label.startsWith("Shared in")) {
    return 0;
  }
  if (label.includes("ISRC") || label.includes("Community submitted")) {
    return 1;
  }
  if (kind === "small_artist" || label.includes("Under 50k")) {
    return 2;
  }
  if (label === "Dataset match") {
    return 3;
  }
  if (kind === "cluster") {
    return 4;
  }
  return 5;
}

function normalizeInteractiveSignal(signal, fallbackTitle = "Discovery explanation") {
  if (typeof signal === "string") {
    return {
      label: formatSignalLabel(signal),
      raw_label: signal,
      kind: "legacy",
      target_type: "explanation",
      explanation: "Legacy explanation text from an older payload shape.",
    };
  }
  return {
    label: formatSignalLabel(signal?.label || fallbackTitle),
    raw_label: signal?.label || fallbackTitle,
    kind: signal?.kind || "explanation",
    target_type: signal?.target_type || "explanation",
    target_key: signal?.target_key || "",
    explanation: signal?.explanation || "",
  };
}

function actionAttributesForSignal(signal) {
  const targetType = signal.target_type;
  if (targetType === "community" && signal.target_key) {
    return `data-action="community-open" data-slug="${escapeHtml(signal.target_key)}"`;
  }
  if (targetType === "artist" && signal.target_key) {
    return `data-action="artist-detail" data-key="${escapeHtml(signal.target_key)}"`;
  }
  return `data-action="explanation-open" data-title="${escapeHtml(signal.label)}" data-explanation="${escapeHtml(signal.explanation || signal.label)}"`;
}

function renderReasonChips(item = {}, options = {}) {
  const limit = options.limit || Infinity;
  const compactClass = options.compact ? " compact-reasons" : "";
  const chips = (item.reason_chips?.length ? item.reason_chips : item.community_signals || [])
    .map((chip) => normalizeInteractiveSignal(chip, "Why this appears here"))
    .filter((chip) => chip.label)
    .sort((a, b) => reasonPriority(a) - reasonPriority(b))
    .slice(0, limit);

  if (!chips.length) {
    return "";
  }

  return `
    <div class="reason-chip-row${compactClass}">
      ${chips.map((chip) => `
        <button class="reason-chip" type="button" ${actionAttributesForSignal(chip)}>
          ${escapeHtml(chip.label)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderPreviewSlot(item = {}, className = "mini-audio", options = {}) {
  const previewUrl = usableMediaUrl(item.preview);
  const previewKey = audioPreviewKey(item);
  const showMissing = options.showMissing !== false;
  if (previewKey && hasRecentAudioFailure(previewKey)) {
    return renderPreviewFallback("Preview kunde inte spelas", item);
  }

  if (previewUrl) {
    return `<audio class="audio-player ${escapeHtml(className)}" controls preload="none" src="${escapeHtml(previewUrl)}" data-preview-key="${escapeHtml(previewKey)}"></audio>`;
  }

  if (!showMissing) {
    return "";
  }

  return renderPreviewFallback("Preview saknas", item);
}

function audioPreviewKey(item = {}) {
  return usableMediaUrl(item.preview);
}

function hasRecentAudioFailure(previewKey) {
  const failedAt = state.audioFailures.get(previewKey);
  if (!failedAt) {
    return false;
  }
  if (Date.now() - failedAt > AUDIO_FAILURE_RETRY_MS) {
    state.audioFailures.delete(previewKey);
    return false;
  }
  return true;
}

function renderPreviewFallback(message, item = {}) {
  const deezerLink = usableMediaUrl(item.deezer_link);
  return `
    <span class="preview-missing">${escapeHtml(message)}</span>
    ${deezerLink ? `<a class="link-button ghost-link" href="${escapeHtml(deezerLink)}" target="_blank" rel="noreferrer">Öppna i Deezer</a>` : ""}
  `;
}

function usableMediaUrl(value) {
  const url = String(value || "").trim();
  if (!url || ["nan", "none", "null", "undefined"].includes(url.toLowerCase())) {
    return "";
  }
  if (!/^https?:\/\//i.test(url)) {
    return "";
  }

  const expiryMatch = url.match(/exp=(\d+)/);
  if (expiryMatch && Number(expiryMatch[1]) <= Math.floor(Date.now() / 1000) + 60) {
    return "";
  }

  return url;
}

function renderAudioFeaturePills(item = {}) {
  const signature = item.audio_signature || {};
  const entries = [
    ["Dans", signature.danceability, "percent"],
    ["Energi", signature.energy, "percent"],
    ["Känsla", signature.valence, "percent"],
    ["Akustik", signature.acousticness, "percent"],
    ["Instr.", signature.instrumentalness, "percent"],
    ["Tempo", signature.tempo, "tempo"],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");

  if (!entries.length) {
    return "";
  }

  return `
    <div class="audio-feature-row">
      ${entries.map(([label, value, type]) => `
        <span class="audio-feature-pill">
          <span>${escapeHtml(label)}</span>
          <strong>${type === "tempo" ? `${Math.round(Number(value))} bpm` : `${Math.round(Number(value) * 100)}%`}</strong>
        </span>
      `).join("")}
    </div>
  `;
}

function renderInsightStrip(item = {}) {
  const parts = [];
  const audioValidated = hasValidatedAudio(item);
  const moodLabel = audioValidated ? item.mood_profile?.label : "";
  if (item.cluster_label) {
    parts.push(item.cluster_label);
  }
  if (moodLabel) {
    parts.push(moodLabel);
  }
  if (item.small_artist_score !== undefined && item.small_artist_score !== null) {
    parts.push(`Small score ${Math.round(Number(item.small_artist_score) * 100)}`);
  }

  if (!parts.length) {
    return "";
  }

  const moodSourceLabel = renderMoodSourceLabel(item);
  return `
    <p class="insight-strip">${escapeHtml(parts.join(" • "))}</p>
    ${moodSourceLabel ? `<p class="mood-source-line">${escapeHtml(moodSourceLabel)}</p>` : ""}
  `;
}

function renderMoodSourceLabel(item = {}) {
  if (hasValidatedAudio(item)) {
    return "Mood från validerad audio";
  }
  return "";
}

function renderSearchInterpretation(interpretation = {}) {
  const genres = interpretation.genres || [];
  const tokens = interpretation.tokens || [];
  const clusters = interpretation.top_prompt_clusters || [];
  const year = interpretation.year_filter;
  const yearLabel = year ? `${year.from}${year.to !== year.from ? `-${year.to}` : ""}` : "";

  return `
    <div class="support-card interpretation-card">
      <h2>Hur vi tolkar din mix</h2>
      <div class="metric-row">
        ${genres.map((genre) => `<span class="metric-pill">${escapeHtml(genre)}</span>`).join("")}
        ${tokens.slice(0, 4).map((token) => `<span class="metric-pill accent-pill">${escapeHtml(token)}</span>`).join("")}
        ${clusters.slice(0, 2).map((cluster) => `<span class="metric-pill">${escapeHtml(cluster.label)}</span>`).join("")}
        ${yearLabel ? `<span class="metric-pill">År: ${escapeHtml(yearLabel)}</span>` : ""}
      </div>
    </div>
  `;
}

function renderCommunityPost(post) {
  const replyCount = (post.replies || []).length;
  return `
    <article class="card post-card community-post-card">
      <div class="post-header">
        ${renderPublicAvatarButton(post)}
        <div>
          <h3>${renderPublicNameButton(post)}</h3>
          <p>${formatRelativeTime(post.created_at)}</p>
          <span class="community-post-badge">${escapeHtml(post.activity_label || "trending quietly")}</span>
        </div>
      </div>
      <p class="body-copy">${escapeHtml(post.text)}</p>
      ${renderLinkedCommunityArtist(post.linked_artist)}
      ${
        !post.linked_artist && (post.tip_artist || post.tip_song)
          ? `
            <div class="tip-card community-post-track">
              <span class="tip-tag">Låttips</span>
              <strong>${escapeHtml(post.tip_song || "Okänd låt")}</strong>
              <span>${escapeHtml(post.tip_artist || "Okänd artist")}</span>
            </div>
          `
          : ""
      }
      <div class="post-actions">
        ${post.linked_artist ? `<button type="button" class="ghost-button mini-button" data-action="save-toggle" data-key="${escapeHtml(post.linked_artist.artist_key)}">${state.savedKeys.has(post.linked_artist.artist_key) ? "Sparad" : "Spara till profil"}</button>` : ""}
        <button type="button" class="ghost-button mini-button" data-action="reply-toggle" data-post-id="${escapeHtml(post.id)}">${replyCount ? `${formatNumber(replyCount)} svar` : "Svara"}</button>
        ${post.community_name ? `<span>${escapeHtml(post.community_name)}</span>` : ""}
      </div>
      ${renderPostReplies(post)}
    </article>
  `;
}

function renderPostReplies(post = {}) {
  const replies = post.replies || [];
  const isOpen = state.activeReplyPostId === post.id;
  return `
    <div class="reply-thread">
      ${
        isOpen
          ? `
            ${replies.map((reply) => `
              <div class="reply-item">
                <strong>${renderPublicNameButton(reply)}</strong>
                <span>${formatRelativeTime(reply.created_at)}</span>
                <p>${escapeHtml(reply.text || "")}</p>
              </div>
            `).join("")}
            <form class="reply-form" data-post-id="${escapeHtml(post.id)}">
              <input class="text-input" name="text" type="text" placeholder="Skriv ett svar..." />
              <button class="ghost-button mini-button" type="button" data-action="reply-toggle" data-post-id="${escapeHtml(post.id)}">Avbryt</button>
              <button class="primary-button mini-button" type="submit">Kommentera</button>
            </form>
          `
          : ""
      }
    </div>
  `;
}

function renderLinkedCommunityArtist(item) {
  if (!item) {
    return "";
  }
  const songKey = songKeyForItem(item);
  // COMMUNITY_SONG_COVER_MAPPING_START
  const cover = communityCoverForItem(item);
  // COMMUNITY_SONG_COVER_MAPPING_END

  return `
    <div class="tip-card linked-tip community-post-track" ${songKey ? `data-action="song-detail" data-song-key="${escapeHtml(songKey)}"` : `data-action="artist-detail" data-key="${escapeHtml(item.artist_key)}"`} role="button" tabindex="0">
      <div class="mini-artwork community-post-artwork">
        ${cover ? `<img src="${escapeHtml(cover)}" alt="${escapeHtml(item.artist)}" />` : `<div class="image-fallback">${icon("note")}</div>`}
      </div>
      <div class="community-post-track-meta">
        <span class="tip-tag">${item.isrc ? "ISRC submitted" : "Community tip"}</span>
        <strong>${escapeHtml(item.song || item.artist || "Unknown track")}</strong>
        <span>${escapeHtml(item.artist || item.genre || "underground discovery")}</span>
        <div class="metric-row">
          ${(item.top_genres || [item.genre]).filter(Boolean).slice(0, 3).map((genre) => `<span class="metric-pill accent-pill">${escapeHtml(genre)}</span>`).join("")}
          ${item.metrics?.lastfm_listeners ? `<span class="metric-pill">${formatNumber(item.metrics.lastfm_listeners)} lyssnare</span>` : ""}
        </div>
        ${renderReasonChips(item, { limit: 1, compact: true })}
      </div>
      <div class="community-card-actions">
        ${renderPreviewSlot(item, "mini-audio", { showMissing: false })}
        <button class="icon-button quiet-button" type="button" data-action="save-toggle" data-key="${escapeHtml(item.artist_key)}" aria-label="Spara artist">
          ${state.savedKeys.has(item.artist_key) ? icon("bookmarkFilled") : icon("bookmark")}
        </button>
      </div>
    </div>
  `;
}

function renderProfileCard(item, mode) {
  return `
    <article class="profile-card card">
      <div class="profile-artwork">
        ${
          item.image
            ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist)}" />`
            : `<div class="image-fallback">${icon("note")}</div>`
        }
      </div>
      <div class="profile-meta">
        <h3>${escapeHtml(item.song || item.artist)}</h3>
        <p>${escapeHtml(item.artist)}</p>
        <span class="tiny-label">${mode === "custom" ? "Eget tillskott" : "Sparad rekommendation"}</span>
        ${item.cluster_label ? `<span class="profile-subtle">${escapeHtml(item.cluster_label)}</span>` : ""}
        ${renderMoodSourceLabel(item) ? `<span class="profile-subtle">${escapeHtml(renderMoodSourceLabel(item))}</span>` : ""}
      </div>
      <button class="icon-button quiet-button" type="button" data-action="remove-library" data-key="${escapeHtml(item.artist_key)}">
        ${icon("trash")}
      </button>
    </article>
  `;
}

function renderProfilePostActivity(item) {
  return `
    <article class="card post-card profile-activity-card">
      <div class="post-header">
        <div class="avatar">${profileInitial(item.username)}</div>
        <div>
          <h3>${escapeHtml(item.song_label || "Inlägg")}</h3>
          ${renderProfileActivityMeta(item)}
        </div>
      </div>
      <p class="body-copy">${escapeHtml(item.text || "")}</p>
      ${item.reply_count ? `<span class="profile-subtle">${formatNumber(item.reply_count)} svar</span>` : ""}
    </article>
  `;
}

function renderProfileReplyActivity(item) {
  return `
    <article class="card post-card profile-activity-card">
      <div class="post-header">
        <div class="avatar">${profileInitial(item.username)}</div>
        <div>
          <h3>${escapeHtml(item.song_label || "Svar i tråd")}</h3>
          ${renderProfileActivityMeta(item)}
        </div>
      </div>
      <p class="body-copy">${escapeHtml(item.text || "")}</p>
      ${item.parent_summary ? `<span class="profile-subtle">Svar på: ${escapeHtml(item.parent_summary)}</span>` : ""}
    </article>
  `;
}

function renderProfileSongCommentActivity(item) {
  return `
    <article class="card post-card profile-activity-card">
      <div class="post-header">
        <div class="avatar">${profileInitial(item.username)}</div>
        <div>
          <h3>${escapeHtml(item.song_label || "Låtkommentar")}</h3>
          ${renderProfileActivityMeta(item)}
        </div>
      </div>
      <p class="body-copy">${escapeHtml(item.text || "")}</p>
    </article>
  `;
}

function renderProfileDiscussionActivity(item) {
  const actor = item.is_local_user ? "Du" : item.username || "Anonym";
  const title = item.song_label || item.origin_label || "Diskussion";
  return `
    <article class="card post-card profile-activity-card">
      <div class="post-header">
        <div class="avatar">${profileInitial(actor)}</div>
        <div>
          <h3>${escapeHtml(title)}</h3>
          ${renderProfileActivityMeta({ ...item, username: actor })}
        </div>
      </div>
      <p class="body-copy">${escapeHtml(item.text || "")}</p>
      ${item.parent_summary ? `<span class="profile-subtle">I tråden: ${escapeHtml(item.parent_summary)}</span>` : ""}
    </article>
  `;
}

function renderProfileActivityMeta(item = {}) {
  const parts = [
    item.username,
    item.origin_label,
    item.community_name && item.community_name !== item.origin_label ? item.community_name : "",
    formatRelativeTime(item.created_at),
  ].filter(Boolean);
  return `<p class="muted-line">${parts.map(escapeHtml).join(" / ")}</p>`;
}

function profileInitial(value) {
  return escapeHtml(String(value || LOCAL_PROFILE_USERNAME).slice(0, 1).toUpperCase());
}

function renderEmptyState(title, text) {
  return `
    <div class="empty-state card">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function renderArtistModal() {
  if (!state.artistModal.isOpen) {
    return "";
  }

  const item = state.artistModal.item || {};
  const tracks = item.tracks?.length
    ? item.tracks
    : item.song
      ? [{
          song_key: item.song_key,
          track_key: item.track_key,
          track_id: item.track_id,
          title: item.title || item.song,
          song: item.song,
          artist: item.artist,
          artist_key: item.artist_key,
          preview: item.preview,
          deezer_link: item.deezer_link,
          genre: item.genre,
        }]
      : [];
  const related = item.related_artists || item.similar_artists || [];
  const relatedLinks = item.related_artist_links?.length
    ? item.related_artist_links
    : related.map((artist) => ({ artist, artist_key: "", available: false }));
  const genreLabels = (item.top_genres || [item.genre]).filter(Boolean).slice(0, 4);

  return `
    <div class="artist-detail-overlay" data-action="artist-modal-close">
      <section class="artist-detail-modal" role="dialog" aria-modal="true" aria-label="Artist detail">
        <button class="modal-close" type="button" data-action="artist-modal-close" aria-label="Stäng">×</button>
        ${
          state.artistModal.isLoading
            ? `
              <div class="modal-loading">
                <div class="hero-icon shimmer">${icon("note")}</div>
                <h2>Hämtar artist...</h2>
              </div>
            `
            : state.artistModal.error
              ? `
                <div class="modal-loading">
                  <h2>Kunde inte öppna artisten</h2>
                  <p>${escapeHtml(state.artistModal.error)}</p>
                </div>
              `
              : `
                <div class="artist-modal-grid">
                  <div class="artist-modal-media">
                    ${item.image ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist)}" />` : `<div class="image-fallback">${icon("note")}</div>`}
                  </div>
                  <div class="artist-modal-content">
                    ${genreLabels.length ? `<p class="eyebrow">${escapeHtml(genreLabels[0])}</p>` : ""}
                    <h2>${escapeHtml(item.song || item.title || "Okänd låt")}</h2>
                    <p class="modal-track">${escapeHtml(item.artist || "Okänd artist")}</p>
                    <p class="body-copy">${escapeHtml(item.bio || "En mindre artist från appens musikbibliotek.")}</p>
                    <div class="metric-row">
                      ${genreLabels.map((genre) => `<span class="metric-pill accent-pill">${escapeHtml(genre)}</span>`).join("")}
                    </div>
                    <div class="modal-action-row">
                      <button type="button" class="primary-button mini-button" data-action="save-toggle" data-key="${escapeHtml(item.artist_key)}">
                        ${state.savedKeys.has(item.artist_key) ? "Sparad" : "Spara"}
                      </button>
                      <button type="button" class="ghost-button" data-action="share-artist" data-key="${escapeHtml(item.artist_key)}">Dela</button>
                    </div>
                  </div>
                </div>
                <div class="artist-modal-sections">
                  ${tracks.length ? `
                    <section>
                      <h3>Tracks</h3>
                      <div class="detail-track-list">
                        ${tracks.map((track) => {
                          const trackSongKey = songKeyForItem(track);
                          return `
                          <div class="detail-track" ${trackSongKey ? `data-action="song-detail" data-song-key="${escapeHtml(trackSongKey)}" role="button" tabindex="0"` : ""}>
                            <div>
                              <strong>${escapeHtml(track.title || item.song || "Untitled")}</strong>
                              <span>${escapeHtml(track.genre || item.genre || "underground")}</span>
                            </div>
                            ${renderPreviewSlot(track, "")}
                          </div>
                        `;
                        }).join("")}
                      </div>
                    </section>
                  ` : ""}
                  ${renderSongComments(item)}
                  ${relatedLinks.length ? `
                    <section>
                      <h3>Related artists</h3>
                      <div class="badge-row">
                        ${relatedLinks.slice(0, 8).map((artist) => artist.available && artist.artist_key
                          ? `<button class="discovery-badge clickable-badge" type="button" data-action="artist-detail" data-key="${escapeHtml(artist.artist_key)}">${escapeHtml(artist.artist)}</button>`
                          : `<span class="discovery-badge">${escapeHtml(artist.artist || artist)}</span>`
                        ).join("")}
                      </div>
                    </section>
                  ` : ""}
                </div>
              `
        }
      </section>
    </div>
  `;
}

function renderSongComments(item = {}) {
  const songKey = songKeyForItem(item);
  if (!songKey) {
    return `
      <section>
        <h3>Låtkommentarer</h3>
        <p class="muted-line">Kommentarer kan visas när låten har en stabil låtnyckel.</p>
      </section>
    `;
  }

  const comments = state.artistModal.comments || [];
  return `
    <section>
      <h3>Låtkommentarer</h3>
      ${
        state.artistModal.commentsLoading
          ? `<p class="muted-line">Hämtar kommentarer...</p>`
          : ""
      }
      ${
        state.artistModal.commentsError
          ? `<p class="error-text">${escapeHtml(state.artistModal.commentsError)}</p>`
          : ""
      }
      <div class="song-comment-list">
        ${
          comments.length
            ? comments.map((comment) => `
              <div class="reply-item">
                <strong>${renderPublicNameButton(comment)}</strong>
                <span>${formatRelativeTime(comment.created_at)}</span>
                <p>${escapeHtml(comment.text || "")}</p>
              </div>
            `).join("")
            : `<p class="muted-line">Inga kommentarer än.</p>`
        }
      </div>
      <form class="song-comment-form" data-song-key="${escapeHtml(songKey)}">
        <input class="text-input" name="text" type="text" placeholder="Skriv en kommentar om låten..." />
        <button class="primary-button mini-button" type="submit">Kommentera</button>
      </form>
    </section>
    ${renderCommunitySongDiscussions(state.artistModal.communityDiscussions || [])}
  `;
}

function renderCommunitySongDiscussions(discussions = []) {
  if (!discussions.length) {
    return "";
  }

  return `
    <section>
      <h3>Communitydiskussioner om denna lÃ¥t</h3>
      <div class="song-comment-list">
        ${discussions.map((discussion) => `
          <div class="reply-item">
            <strong>${renderPublicNameButton(discussion)}</strong>
            <span>${formatRelativeTime(discussion.created_at)} Â· ${escapeHtml(discussion.origin_label || "Community")}</span>
            <p>${escapeHtml(discussion.text || "")}</p>
            ${
              discussion.parent_summary && discussion.parent_summary !== discussion.text
                ? `<small>${escapeHtml(`Svar pÃ¥: ${discussion.parent_summary}`)}</small>`
                : ""
            }
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderCreateCommunityModal() {
  if (!state.createCommunity.isOpen) {
    return "";
  }

  return `
    <div class="artist-detail-overlay create-community-overlay" data-action="community-create-close">
      <section class="artist-detail-modal create-community-modal" role="dialog" aria-modal="true">
        <button class="modal-close" type="button" data-action="community-create-close" aria-label="Stäng">×</button>
        <div class="create-community-header">
          <div class="hero-icon">${icon("radio")}</div>
          <p class="eyebrow">Nytt musikrum</p>
          <h2>Skapa en liten scen</h2>
          <p>Välj ett namn och en kort känsla. Sluggen skapas automatiskt.</p>
        </div>
        ${state.createCommunity.error ? `<div class="banner error-banner">${escapeHtml(state.createCommunity.error)}</div>` : ""}
        <form id="community-create-form" class="profile-auth-form create-community-form">
          <label>
            <span>Rumsnamn</span>
            <input class="text-input" name="name" type="text" maxlength="48" placeholder="t.ex. Göteborg indie" required />
          </label>
          <label>
            <span>Kort beskrivning</span>
            <textarea class="text-area" name="description" rows="4" maxlength="180" placeholder="Vad hör hemma här?"></textarea>
          </label>
          <div class="profile-auth-actions">
            <button class="primary-button profile-auth-primary" type="submit" ${state.createCommunity.isLoading ? "disabled" : ""}>Skapa rum</button>
            <button class="ghost-button profile-auth-secondary" type="button" data-action="community-create-close">Avbryt</button>
          </div>
        </form>
      </section>
    </div>
  `;
}

function renderPublicProfileModal() {
  if (!state.publicProfile.isOpen) {
    return "";
  }

  const payload = state.publicProfile.payload || {};
  const profile = payload.profile || { display_name: state.publicProfile.username };
  const saved = payload.saved_artists || [];
  const custom = payload.custom_artists || [];
  const posts = payload.profile_posts || [];
  const replies = payload.profile_replies || [];
  const comments = payload.profile_song_comments || [];
  const communities = payload.communities || [];
  const activityCount = posts.length + replies.length + comments.length;

  return `
    <div class="artist-detail-overlay public-profile-overlay" data-action="public-profile-close">
      <section class="artist-detail-modal public-profile-modal" role="dialog" aria-modal="true">
        <button class="modal-close" type="button" data-action="public-profile-close" aria-label="Stäng">×</button>
        ${
          state.publicProfile.isLoading
            ? `<div class="modal-loading"><p>Hämtar profil...</p></div>`
            : state.publicProfile.error
              ? `
                <div class="modal-loading">
                  <h2>Profilen kunde inte visas</h2>
                  <p class="error-text">${escapeHtml(state.publicProfile.error)}</p>
                </div>
              `
              : `
                <div class="public-profile-header">
                  ${renderAccountAvatar(profile, "profile-account-avatar public-profile-avatar")}
                  <div>
                    <p class="eyebrow">Musikprofil</p>
                    <h2>${escapeHtml(profile.display_name || profile.username || "Anonym")}</h2>
                    <div class="metric-row">
                      <span class="metric-pill">${formatNumber(saved.length + custom.length)} sparade</span>
                      <span class="metric-pill">${formatNumber(activityCount)} aktiviteter</span>
                      <span class="metric-pill">${formatNumber(communities.length)} communities</span>
                    </div>
                  </div>
                </div>
                <div class="artist-modal-sections public-profile-sections">
                  <section>
                    <h3>Sparad musik</h3>
                    ${
                      payload.library_public
                        ? (
                          saved.length || custom.length
                            ? [...saved.map((item) => renderPublicMusicCard(item, "Sparad")), ...custom.map((item) => renderPublicMusicCard(item, "Eget tillskott"))].join("")
                            : `<p class="muted-line">Inga offentliga sparade låtar än.</p>`
                        )
                        : `<p class="muted-line">Biblioteket är privat.</p>`
                    }
                  </section>
                  <section>
                    <h3>Communities</h3>
                    ${
                      communities.length
                        ? `<div class="metric-row">${communities.map((community) => `<span class="metric-pill accent-pill">${escapeHtml(community.name || community.slug)}</span>`).join("")}</div>`
                        : `<p class="muted-line">Inga synliga community-spår än.</p>`
                    }
                  </section>
                  <section>
                    <h3>Inlägg</h3>
                    ${posts.length ? posts.map(renderProfilePostActivity).join("") : `<p class="muted-line">Inga offentliga inlägg än.</p>`}
                  </section>
                  <section>
                    <h3>Svar</h3>
                    ${replies.length ? replies.map(renderProfileReplyActivity).join("") : `<p class="muted-line">Inga offentliga svar än.</p>`}
                  </section>
                  <section>
                    <h3>Kommentarer</h3>
                    ${comments.length ? comments.map(renderProfileSongCommentActivity).join("") : `<p class="muted-line">Inga offentliga kommentarer än.</p>`}
                  </section>
                </div>
              `
        }
      </section>
    </div>
  `;
}

function renderPublicMusicCard(item = {}, label = "Sparad") {
  return `
    <article class="profile-card public-music-card">
      <div class="profile-artwork">
        ${
          item.image
            ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.artist || item.song || "Musik")}" />`
            : `<div class="image-fallback">${icon("note")}</div>`
        }
      </div>
      <div class="profile-meta">
        <h3>${escapeHtml(item.song || item.title || item.artist || "Okänd låt")}</h3>
        <p>${escapeHtml(item.artist || "Okänd artist")}</p>
        <span class="tiny-label">${escapeHtml(label)}</span>
      </div>
    </article>
  `;
}

function renderExplanationModal() {
  if (!state.explanationModal.isOpen) {
    return "";
  }

  return `
    <div class="explanation-overlay" data-action="explanation-close">
      <section class="explanation-modal" role="dialog" aria-modal="true">
        <button class="modal-close" type="button" data-action="explanation-close" aria-label="Stäng">×</button>
        <h2>${escapeHtml(state.explanationModal.title || "Förklaring")}</h2>
        <p>${escapeHtml(state.explanationModal.body || "")}</p>
      </section>
    </div>
  `;
}

function refreshActionStates() {
  const suggestButton = document.getElementById("suggest-submit");
  if (suggestButton) {
    suggestButton.disabled = !(state.suggestionDraft.isrc.trim() && state.suggestionDraft.confirm);
  }
}

async function runSongSearch(query = state.songSearchQuery) {
  const cleanQuery = String(query || "").trim();
  state.songSearchQuery = cleanQuery;
  state.songSearchHasRun = true;
  state.songSearchError = "";
  state.songSearchResults = [];

  if (!cleanQuery) {
    state.songSearchError = "Skriv en titel, artist eller album.";
    render();
    return;
  }

  state.songSearchLoading = true;
  render();

  try {
    const payload = await api.songSearch(cleanQuery, 12);
    state.songSearchResults = payload.results || [];
    rememberItems(state.songSearchResults);
  } catch (error) {
    state.songSearchError = error.message || "Kunde inte söka låtar.";
  } finally {
    state.songSearchLoading = false;
    render();
  }
}

async function runPropertySearch() {
  state.error = "";
  state.audioFailures.clear();
  state.isLoading = true;
  state.loadingMessage = state.mixMode === "new_added" ? "Hämtar nya tillagda låtar..." : "Väljer kluster och matchar egenskaper...";
  render();

  try {
    const targets = state.mixMode === "surprise" && state.mixUseProperties
      ? Object.fromEntries(
          Object.entries(state.mixTargets).map(([key, value]) => [
            key,
            key === "tempo" ? Number(value) : Number(value) / 100,
          ])
        )
      : {};
    const payload = await api.propertySearch({
      targets,
      genres: state.mixGenres,
      label: state.mixLabel,
      mode: state.mixMode,
      limit: 6,
    });
    state.searchResults = payload.results || [];
    state.searchInterpretation = payload.interpretation || null;
    state.searchHasRun = true;
    rememberItems(state.searchResults);
  } catch (error) {
    state.error = error.message;
  } finally {
    state.isLoading = false;
    render();
  }
}

async function loadFeed() {
  state.error = "";
  state.isLoading = true;
  state.loadingMessage = "Bygger ditt flöde...";
  render();

  try {
    const payload = await api.feed({ exclude_artist_keys: state.feed.seenKeys });
    state.feed.card = payload.card || null;
    state.feed.communityPosts = payload.community_posts || [];
    state.feed.trendingQuietly = payload.trending_quietly || [];
    state.feed.microCommunities = payload.micro_communities || [];
    state.feed.communityActivity = payload.community_activity || [];
    state.feed.discoveryTrail = payload.discovery_trail || [];
    if (state.feed.card?.artist_key) {
      rememberFeedItems();
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.isLoading = false;
    render();
  }
}

async function refreshProfile() {
  const profile = await api.profile();
  syncSession({ authenticated: profile.authenticated, user: profile.account });
  syncProfile(profile);
}

async function openPublicProfile(username) {
  const cleanUsername = String(username || "").trim();
  if (!cleanUsername) {
    return;
  }

  if (state.session.authenticated && normalizeProfileName(cleanUsername) === normalizeProfileName(currentProfileName())) {
    state.publicProfile = { isOpen: false, isLoading: false, username: "", payload: null, error: "" };
    state.artistModal.isOpen = false;
    state.explanationModal = { isOpen: false, title: "", body: "" };
    state.view = "profile";
    await refreshProfile();
    render();
    return;
  }

  state.publicProfile = {
    isOpen: true,
    isLoading: true,
    username: cleanUsername,
    payload: null,
    error: "",
  };
  render();

  try {
    const payload = await api.publicProfile(cleanUsername);
    state.publicProfile = {
      isOpen: true,
      isLoading: false,
      username: cleanUsername,
      payload,
      error: "",
    };
  } catch (error) {
    state.publicProfile = {
      isOpen: true,
      isLoading: false,
      username: cleanUsername,
      payload: null,
      error: error.message || "Kunde inte hämta profilen.",
    };
  }

  render();
}

function closePublicProfile() {
  state.publicProfile = { isOpen: false, isLoading: false, username: "", payload: null, error: "" };
  render();
}

async function submitLogin(form) {
  const formData = new FormData(form);
  state.authLoading = true;
  state.authError = "";
  state.authStatus = "";
  render();

  try {
    const session = await api.login({
      username: String(formData.get("username") || "").trim(),
      password: String(formData.get("password") || ""),
    });
    syncSession(session);
    await refreshProfile();
    state.profileAuthMode = "logged-in";
    state.authStatus = "";
  } catch (error) {
    state.authError = error.message || "Kunde inte logga in.";
  } finally {
    state.authLoading = false;
    render();
  }
}

async function submitRegister(form) {
  const formData = new FormData(form);
  state.authLoading = true;
  state.authError = "";
  state.authStatus = "";
  render();

  try {
    const session = await api.register({
      username: String(formData.get("username") || "").trim(),
      password: String(formData.get("password") || ""),
      confirm_password: String(formData.get("confirm_password") || ""),
      avatar_kind: "preset",
      avatar_value: state.selectedAvatarPreset,
    });
    syncSession(session);
    await refreshProfile();
    state.profileAuthMode = "logged-in";
    state.authStatus = "";
  } catch (error) {
    state.authError = error.message || "Kunde inte skapa konto.";
  } finally {
    state.authLoading = false;
    render();
  }
}

async function submitCreateCommunity(form) {
  const formData = new FormData(form);
  const name = String(formData.get("name") || "").trim();
  const description = String(formData.get("description") || "").trim();

  if (!name) {
    state.createCommunity.error = "Skriv ett namn pÃ¥ musikrummet.";
    render();
    return;
  }

  state.createCommunity = { ...state.createCommunity, isLoading: true, error: "" };
  render();

  try {
    const payload = await api.createCommunity({ name, description });
    const slug = payload.community?.slug || "";
    state.createCommunity = { isOpen: false, isLoading: false, error: "" };
    if (slug) {
      state.activeCommunitySlug = slug;
    }
    await loadFeed();
    if (slug) {
      state.activeCommunitySlug = slug;
    }
    form.reset();
  } catch (error) {
    state.createCommunity = {
      ...state.createCommunity,
      isLoading: false,
      error: error.message || "Kunde inte skapa musikrummet.",
    };
  }

  render();
}

async function logoutProfile() {
  state.authLoading = true;
  state.authError = "";
  state.authStatus = "";
  render();

  try {
    const session = await api.logout();
    syncSession(session);
    state.profileAuthMode = "logged-out";
    state.authStatus = "Du är utloggad.";
    await refreshProfile();
  } catch (error) {
    state.authError = error.message || "Kunde inte logga ut.";
  } finally {
    state.authLoading = false;
    render();
  }
}

async function toggleSave(artistKey) {
  const payload = activeCardPayload(artistKey);
  if (!payload) {
    return;
  }

  try {
    await api.save(payload);
    await refreshProfile();
  } catch (error) {
    state.error = error.message;
  }

  render();
}

async function removeLibraryArtist(artistKey) {
  try {
    await api.removeArtist(artistKey);
    await refreshProfile();
    if (state.feed.card?.artist_key === artistKey) {
      state.feed.card = null;
    }
  } catch (error) {
    state.error = error.message;
  }

  render();
}

async function openArtistDetail(artistKey) {
  if (!artistKey) {
    return;
  }

  state.explanationModal = { isOpen: false, title: "", body: "" };
  const cached = state.itemIndex.get(artistKey) || null;
  state.artistModal = {
    isOpen: true,
    isLoading: true,
    item: cached,
    error: "",
    comments: [],
    commentsLoading: Boolean(songKeyForItem(cached || {})),
    commentsError: "",
    communityDiscussions: [],
  };
  render();

  try {
    const payload = await api.artistDetail(artistKey);
    state.artistModal = {
      isOpen: true,
      isLoading: false,
      item: payload.item,
      error: "",
      comments: [],
      commentsLoading: Boolean(songKeyForItem(payload.item || {})),
      commentsError: "",
      communityDiscussions: [],
    };
    rememberItems([payload.item, ...(payload.item?.tracks || [])]);
    await loadSongCommentsForModal(payload.item);
  } catch (error) {
    state.artistModal = {
      isOpen: true,
      isLoading: false,
      item: cached,
      error: error.message,
      comments: [],
      commentsLoading: false,
      commentsError: "",
      communityDiscussions: [],
    };
  }

  render();
}

async function openSongDetail(songKey) {
  const item = state.songIndex.get(String(songKey));
  if (!item) {
    return;
  }

  state.explanationModal = { isOpen: false, title: "", body: "" };
  state.artistModal = {
    isOpen: true,
    isLoading: false,
    item,
    error: "",
    comments: [],
    commentsLoading: Boolean(songKeyForItem(item)),
    commentsError: "",
    communityDiscussions: [],
  };
  render();
  await loadSongCommentsForModal(item);
  render();
}

async function loadSongCommentsForModal(item = state.artistModal.item) {
  const songKey = songKeyForItem(item || {});
  if (!songKey) {
    state.artistModal.comments = [];
    state.artistModal.communityDiscussions = [];
    state.artistModal.commentsLoading = false;
    state.artistModal.commentsError = "";
    return;
  }

  try {
    const payload = await api.songComments(songKey, item || {});
    state.artistModal.comments = payload.comments || [];
    state.artistModal.communityDiscussions = payload.community_discussions || [];
    state.artistModal.commentsError = "";
  } catch (error) {
    state.artistModal.comments = [];
    state.artistModal.communityDiscussions = [];
    state.artistModal.commentsError = error.message || "Kunde inte hämta kommentarer.";
  } finally {
    state.artistModal.commentsLoading = false;
  }
}

function closeArtistDetail() {
  state.artistModal = {
    isOpen: false,
    isLoading: false,
    item: null,
    error: "",
    comments: [],
    commentsLoading: false,
    commentsError: "",
    communityDiscussions: [],
  };
  render();
}

async function shareArtist(artistKey) {
  const item = state.itemIndex.get(artistKey) || state.artistModal.item;
  if (!item) {
    return;
  }

  const shareText = `${item.artist} - ${item.song || "Small Web discovery"}`;
  try {
    if (navigator.share) {
      await navigator.share({ title: item.artist, text: shareText });
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(shareText);
      state.suggestionStatus = "Artistinfo kopierad.";
    }
  } catch {
    // Delning är frivillig; vissa browsers blockerar den utan att appen ska stänga modalen.
  }
  render();
}

root.addEventListener("click", async (event) => {
  const navTarget = event.target.closest("[data-view]");
  if (navTarget) {
    state.view = navTarget.dataset.view;
    state.error = "";
    if (state.view === "feed" && !state.feed.card) {
      await loadFeed();
      return;
    }
    if (state.view === "profile") {
      await refreshProfile();
    }
    render();
    return;
  }

  const presetTarget = event.target.closest("[data-mix-preset]");
  if (presetTarget) {
    const presetKey = presetTarget.dataset.mixPreset;
    const preset = mixPresets[presetKey];
    if (preset) {
      state.mixPreset = presetKey;
      state.mixLabel = preset.label;
      state.mixGenres = preset.genres;
      state.mixUseProperties = true;
      state.mixPropertiesOpen = true;
      state.mixTargets = { ...preset.targets };
      render();
    }
    return;
  }

  const mixModeTarget = event.target.closest("[data-mix-mode]");
  if (mixModeTarget) {
    state.mixMode = mixModeTarget.dataset.mixMode === "new_added" ? "new_added" : "surprise";
    if (state.mixMode === "new_added") {
      state.mixUseProperties = false;
      state.mixPropertiesOpen = false;
      state.mixPreset = "";
      state.mixLabel = "Nya tillagda";
    } else if (state.mixLabel === "Nya tillagda") {
      state.mixLabel = "Egen mix";
    }
    render();
    return;
  }

  const mixGenreTarget = event.target.closest("[data-mix-genre]");
  if (mixGenreTarget) {
    const genre = mixGenreTarget.dataset.mixGenre;
    state.mixPreset = "";
    state.mixLabel = state.mixMode === "new_added" ? "Nya tillagda" : "Egen mix";
    state.mixGenres = hasMixGenre(genre)
      ? state.mixGenres.filter((item) => normalizeUiGenre(item) !== normalizeUiGenre(genre))
      : [...state.mixGenres, genre];
    render();
    return;
  }

  const actionTarget = event.target.closest("[data-action]");
  if (!actionTarget) {
    return;
  }

  const { action, key, songKey } = actionTarget.dataset;

  switch (action) {
    case "profile-login-open":
      state.profileAuthMode = "login";
      state.authError = "";
      state.authStatus = "";
      render();
      break;
    case "profile-create-open":
      state.profileAuthMode = "create";
      state.authError = "";
      state.authStatus = "";
      render();
      break;
    case "profile-auth-back":
      state.profileAuthMode = "logged-out";
      state.authError = "";
      render();
      break;
    case "avatar-preset":
      state.selectedAvatarPreset = actionTarget.dataset.avatar || "violet";
      render();
      break;
    case "profile-logout":
      await logoutProfile();
      break;
    case "public-profile-open":
      event.stopPropagation();
      await openPublicProfile(actionTarget.dataset.username || "");
      break;
    case "public-profile-close":
      if (actionTarget.classList.contains("public-profile-overlay") && event.target !== actionTarget) {
        return;
      }
      closePublicProfile();
      break;
    case "save-toggle":
      await toggleSave(key);
      break;
    case "artist-detail":
      await openArtistDetail(key);
      break;
    case "song-detail":
      if (event.target.closest("audio, a")) {
        return;
      }
      await openSongDetail(songKey);
      break;
    case "artist-modal-close":
      if (actionTarget.classList.contains("artist-detail-overlay") && event.target !== actionTarget) {
        return;
      }
      closeArtistDetail();
      break;
    case "explanation-open":
      state.explanationModal = {
        isOpen: true,
        title: actionTarget.dataset.title || "Why this appears",
        body: actionTarget.dataset.explanation || "",
      };
      render();
      break;
    case "explanation-close":
      state.explanationModal = { isOpen: false, title: "", body: "" };
      render();
      break;
    case "community-open":
      state.view = "feed";
      state.activeCommunitySlug = actionTarget.dataset.slug || "";
      state.artistModal.isOpen = false;
      state.explanationModal = { isOpen: false, title: "", body: "" };
      render();
      break;
    case "community-close":
      state.activeCommunitySlug = "";
      render();
      break;
    case "community-create-open":
      if (!state.session.authenticated) {
        state.view = "profile";
        state.profileAuthMode = "login";
        state.authError = "Logga in fÃ¶r att skapa ett musikrum.";
        state.artistModal.isOpen = false;
        state.publicProfile.isOpen = false;
        render();
        return;
      }
      state.createCommunity = { isOpen: true, isLoading: false, error: "" };
      render();
      break;
    case "community-create-close":
      if (actionTarget.classList.contains("create-community-overlay") && event.target !== actionTarget) {
        return;
      }
      state.createCommunity = { isOpen: false, isLoading: false, error: "" };
      render();
      break;
    case "share-artist":
      await shareArtist(key);
      break;
    case "reply-toggle":
      state.activeReplyPostId = state.activeReplyPostId === actionTarget.dataset.postId ? "" : actionTarget.dataset.postId || "";
      render();
      break;
    case "feed-next":
      if (state.feed.card?.artist_key) {
        state.feed.seenKeys = [...new Set([...state.feed.seenKeys, state.feed.card.artist_key])];
      }
      await loadFeed();
      break;
    case "toggle-tip":
      state.communityTipOpen = !state.communityTipOpen;
      render();
      break;
    case "search-reset":
      state.searchResults = [];
      state.searchInterpretation = null;
      state.searchHasRun = false;
      render();
      break;
    case "mix-submit":
      await runPropertySearch();
      break;
    case "toggle-properties":
      state.mixPropertiesOpen = !state.mixPropertiesOpen;
      if (state.mixPropertiesOpen) {
        state.mixUseProperties = true;
      } else {
        state.mixUseProperties = false;
      }
      render();
      break;
    case "remove-library":
      await removeLibraryArtist(key);
      break;
    default:
      break;
  }
});

root.addEventListener("error", (event) => {
  const audio = event.target;
  if (!(audio instanceof HTMLAudioElement)) {
    return;
  }

  const previewKey = audio.dataset.previewKey;
  if (!previewKey || hasRecentAudioFailure(previewKey)) {
    return;
  }

  state.audioFailures.set(previewKey, Date.now());
  render();
}, true);

root.addEventListener("canplay", (event) => {
  const audio = event.target;
  if (!(audio instanceof HTMLAudioElement)) {
    return;
  }
  if (audio.dataset.previewKey) {
    state.audioFailures.delete(audio.dataset.previewKey);
  }
}, true);

root.addEventListener("input", (event) => {
  if (event.target.id === "isrc-input") {
    state.suggestionDraft.isrc = event.target.value.toUpperCase();
    refreshActionStates();
  }

  if (event.target.id === "song-search-input") {
    state.songSearchQuery = event.target.value;
  }

  if (event.target.id === "mix-genre-search") {
    const query = event.target.value;
    state.mixGenreQuery = query;
    render();
    const input = root.querySelector("#mix-genre-search");
    if (input) {
      input.focus();
      input.setSelectionRange(query.length, query.length);
    }
    return;
  }

  if (event.target.dataset.mixFeature) {
    state.mixPreset = "";
    state.mixLabel = "Egen mix";
    state.mixUseProperties = true;
    state.mixTargets = {
      ...state.mixTargets,
      [event.target.dataset.mixFeature]: Number(event.target.value),
    };
    root.querySelectorAll(".preset-button.is-active").forEach((button) => button.classList.remove("is-active"));
    updateMixSliderDisplay(event.target);
  }
});

root.addEventListener("change", (event) => {
  if (event.target.id === "confirm-smaller") {
    state.suggestionDraft.confirm = event.target.checked;
    refreshActionStates();
  }

  if (event.target.id === "mix-use-properties") {
    state.mixUseProperties = event.target.checked;
    state.mixPreset = "";
    state.mixLabel = state.mixUseProperties ? "Egen mix" : "Genre only";
    render();
  }

  // COMMUNITY_SAVED_SONG_PICKER_UI_START
  if (event.target.id === "community-saved-song") {
    state.communitySelectedSongKey = event.target.value;
    render();
  }
  // COMMUNITY_SAVED_SONG_PICKER_UI_END
});

root.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (event.target.id === "profile-login-form") {
    await submitLogin(event.target);
    return;
  }

  if (event.target.id === "profile-register-form") {
    await submitRegister(event.target);
    return;
  }

  if (event.target.id === "community-create-form") {
    await submitCreateCommunity(event.target);
    return;
  }

  if (event.target.id === "song-search-form") {
    const formData = new FormData(event.target);
    await runSongSearch(formData.get("query"));
    return;
  }

  if (event.target.id === "suggest-form") {
    state.error = "";
    state.isLoading = true;
    state.loadingMessage = "Hämtar artistinformation från Deezer...";
    render();

    try {
      const payload = await api.suggest({
        isrc: state.suggestionDraft.isrc.trim(),
        confirm_smaller_artist: state.suggestionDraft.confirm,
        note: state.suggestionDraft.note,
      });
      state.suggestionStatus = `${payload.item.artist} lades till och kan nu dyka upp i flödet och rekommendationerna.`;
      state.suggestionDraft = { isrc: "", confirm: false, note: "" };
      await refreshProfile();
      state.feed.card = null;
    } catch (error) {
      state.error = error.message;
    } finally {
      state.isLoading = false;
      render();
    }
    return;
  }

  if (event.target.id === "community-form") {
    const formData = new FormData(event.target);
    const text = String(formData.get("text") || "").trim();
    // COMMUNITY_POST_SAVED_SONG_SELECT_START
    const selectedSong = state.communityTipOpen
      ? savedSongBySelectKey(String(formData.get("saved_song_key") || "").trim())
      : null;
    // COMMUNITY_POST_SAVED_SONG_SELECT_END
    const communitySlug = String(formData.get("community_slug") || "").trim();

    if (!text) {
      state.error = "Skriv något innan du postar.";
      render();
      return;
    }

    try {
      // COMMUNITY_POST_PAYLOAD_FIX_START
      await api.createCommunityPost(communityPostPayload(text, selectedSong, communitySlug));
      // COMMUNITY_POST_PAYLOAD_FIX_END
      state.communityTipOpen = false;
      state.communitySelectedSongKey = "";
      state.error = "";
      await loadFeed();
      event.target.reset();
    } catch (error) {
      state.error = error.message;
    }

    render();
  }

  if (event.target.classList.contains("song-comment-form")) {
    const formData = new FormData(event.target);
    const text = String(formData.get("text") || "").trim();
    const songKey = event.target.dataset.songKey || songKeyForItem(state.artistModal.item || {});
    const item = state.artistModal.item || {};

    if (!text || !songKey) {
      state.artistModal.commentsError = songKey ? "Skriv något innan du kommenterar." : "Låtnyckel saknas.";
      render();
      return;
    }

    try {
      await api.createSongComment(songKey, {
        text,
        username: currentProfileName(),
        track_key: item.track_key || songKey,
        track_id: item.track_id || null,
        artist_key: item.artist_key || null,
        artist_name: item.artist || null,
        track_title: item.song || item.title || null,
      });
      event.target.reset();
      state.artistModal.commentsLoading = true;
      state.artistModal.commentsError = "";
      render();
      await loadSongCommentsForModal(item);
    } catch (error) {
      state.artistModal.commentsError = error.message || "Kunde inte spara kommentaren.";
    }

    render();
  }

  if (event.target.classList.contains("reply-form")) {
    const formData = new FormData(event.target);
    const text = String(formData.get("text") || "").trim();
    const postId = event.target.dataset.postId || "";

    if (!text || !postId) {
      state.error = "Skriv något innan du svarar.";
      render();
      return;
    }

    try {
      await api.createCommunityReply(postId, { text, username: currentProfileName() });
      state.activeReplyPostId = postId;
      state.error = "";
      await loadFeed();
    } catch (error) {
      state.error = error.message;
    }

    render();
  }
});

initialize();
