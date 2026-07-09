// API istemcisi + oturum yönetimi.
// Kimlik iki katmanlı: (1) auth uçları için JWT (Bearer), (2) dashboard
// uçları için X-Dev-Id başlığı — giriş yapan kullanıcının developer_id'si.
// Şirket ortamında X-Dev-Id katmanı SSO/reverse-proxy ile değişebilir.

const TOKEN_KEY = "nabiz_token";
const USER_KEY = "nabiz_user";

let currentDevId = null;

export function setCurrentDevId(id) {
  currentDevId = id;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY));
  } catch {
    return null;
  }
}

function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  currentDevId = null;
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (currentDevId != null) headers["X-Dev-Id"] = String(currentDevId);
  return headers;
}

async function parseError(resp) {
  const body = await resp.json().catch(() => ({}));
  const err = new Error(body.detail || `HTTP ${resp.status}`);
  err.status = resp.status;
  return err;
}

// GET dashboard/API uçları
export async function api(path) {
  const resp = await fetch(path, { headers: authHeaders() });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

// Genel JSON POST (auth uçları dahil)
export async function apiPost(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body ?? {}),
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

// Genel JSON PATCH
export async function apiPatch(path, body) {
  const resp = await fetch(path, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body ?? {}),
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

// Genel DELETE
export async function apiDelete(path) {
  const resp = await fetch(path, { method: "DELETE", headers: authHeaders() });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

// --- oturum uçları ------------------------------------------------------------

export async function login(email, password) {
  const data = await apiPost("/api/auth/login", { email, password });
  saveSession(data.access_token, data.user);
  setCurrentDevId(data.user.developer_id);
  return data.user;
}

export async function fetchMe() {
  const user = await api("/api/auth/me");
  setCurrentDevId(user.developer_id);
  return user;
}

export function changePassword(current_password, new_password) {
  return apiPost("/api/auth/change-password", { current_password, new_password });
}

export function listEmployees() {
  return api("/api/auth/employees");
}

export function createEmployee(payload) {
  return apiPost("/api/auth/employees", payload);
}

export function setEmployeePassword(userId, new_password) {
  return apiPost(`/api/auth/employees/${userId}/password`, { new_password });
}

export function updateEmployee(userId, patch) {
  return apiPatch(`/api/auth/employees/${userId}`, patch);
}

export function deleteEmployee(userId) {
  return apiDelete(`/api/auth/employees/${userId}`);
}
