// API istemcisi. Kimlik (Faz 1): JWT — istekler Authorization: Bearer taşır.
// 401'de bir kez refresh denenir; token'lar yalnızca localStorage'da durur,
// asla URL'ye yazılmaz. (Demo X-Dev-Id yolu backend'de config ile kalır.)
let accessToken = localStorage.getItem("eh_access");
let refreshToken = localStorage.getItem("eh_refresh");

export function isLoggedIn() {
  return accessToken != null;
}

function storeTokens(access, refresh) {
  accessToken = access;
  localStorage.setItem("eh_access", access);
  if (refresh) {
    refreshToken = refresh;
    localStorage.setItem("eh_refresh", refresh);
  }
}

export function logout() {
  accessToken = null;
  refreshToken = null;
  localStorage.removeItem("eh_access");
  localStorage.removeItem("eh_refresh");
}

export async function login(email, password) {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `HTTP ${resp.status}`);
  storeTokens(body.access_token, body.refresh_token);
}

async function tryRefresh() {
  if (!refreshToken) return false;
  const resp = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!resp.ok) return false;
  storeTokens((await resp.json()).access_token);
  return true;
}

function doFetch(path) {
  const headers = {};
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  return fetch(path, { headers });
}

export async function api(path) {
  let resp = await doFetch(path);
  if (resp.status === 401 && accessToken && (await tryRefresh())) {
    resp = await doFetch(path);
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const err = new Error(body.detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}
