const JSON_HEADERS = {
  "Content-Type": "application/json",
};

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    throw new Error(readableApiError(payload?.detail) || "Något gick fel.");
  }

  return payload;
}

function readableApiError(detail) {
  if (!detail) {
    return "";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        const field = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        return [field, item?.msg].filter(Boolean).join(": ");
      })
      .filter(Boolean)
      .join(", ");
  }
  if (typeof detail === "object") {
    return detail.message || detail.msg || JSON.stringify(detail);
  }
  return String(detail);
}

function normalizeCommunityPostBody(body = {}) {
  const payload = { ...body };
  ["song_key", "track_key"].forEach((key) => {
    if (payload[key] !== undefined && payload[key] !== null && payload[key] !== "") {
      payload[key] = String(payload[key]);
    }
  });
  return payload;
}

export const api = {
  bootstrap() {
    return request("/api/bootstrap");
  },

  propertySearch(body) {
    return request("/api/property-search", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  feed(body) {
    return request("/api/feed", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  profile() {
    return request("/api/profile");
  },

  publicProfile(username) {
    return request(`/api/profiles/${encodeURIComponent(username)}`);
  },

  communities() {
    return request("/api/communities");
  },

  createCommunity(body) {
    return request("/api/communities", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  session() {
    return request("/api/session");
  },

  register(body) {
    return request("/api/auth/register", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  login(body) {
    return request("/api/auth/login", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  logout() {
    return request("/api/auth/logout", {
      method: "POST",
      headers: JSON_HEADERS,
    });
  },

  artistDetail(artistKey) {
    return request(`/api/artists/${encodeURIComponent(artistKey)}`);
  },

  songSearch(query, limit = 12) {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    });
    return request(`/api/songs/search?${params.toString()}`);
  },

  songComments(songKey, item = {}) {
    const params = new URLSearchParams();
    const metadata = {
      track_key: item.track_key || songKey,
      track_id: item.track_id,
      isrc: item.isrc,
      artist_key: item.artist_key,
      artist_name: item.artist,
      track_title: item.song || item.title,
    };
    Object.entries(metadata).forEach(([key, value]) => {
      if (value !== undefined && value !== null && String(value).trim()) {
        params.set(key, String(value));
      }
    });
    const query = params.toString();
    return request(`/api/songs/${encodeURIComponent(songKey)}/comments${query ? `?${query}` : ""}`);
  },

  createSongComment(songKey, body) {
    return request(`/api/songs/${encodeURIComponent(songKey)}/comments`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  save(body) {
    return request("/api/save", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  removeArtist(artistKey) {
    return request(`/api/library/${encodeURIComponent(artistKey)}`, {
      method: "DELETE",
    });
  },

  suggest(body) {
    return request("/api/suggestions", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },

  createCommunityPost(body) {
    return request("/api/community", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(normalizeCommunityPostBody(body)),
    });
  },

  createCommunityReply(postId, body) {
    return request(`/api/community/${encodeURIComponent(postId)}/replies`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    });
  },
};
