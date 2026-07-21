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

// Alan-bazlı Türkçe karşılıklar (FastAPI 422 loc son elemanı).
const FIELD_TR = {
  new_password: "Yeni parola",
  current_password: "Mevcut parola",
  password: "Parola",
  email: "E-posta",
  display_name: "Ad Soyad",
  name: "Ad",
  github_url: "GitHub adresi",
};

// FastAPI 422 doğrulama hatası: detail bir LİSTE. İnsan-okur Türkçe mesaja çevir.
function humanizeDetail(detail) {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "Geçersiz istek";
  return detail
    .map((e) => {
      const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
      const label = FIELD_TR[field] || field;
      const min = e.ctx && e.ctx.min_length;
      if (e.type === "string_too_short" || (e.type && e.type.includes("min_length"))) {
        return `${label} en az ${min ?? 6} karakter olmalı`;
      }
      if (e.type === "value_error.missing" || e.type === "missing") {
        return `${label} zorunlu`;
      }
      return `${label ? label + ": " : ""}${e.msg || "geçersiz"}`;
    })
    .join(" · ");
}

async function parseError(resp) {
  const body = await resp.json().catch(() => ({}));
  const err = new Error(humanizeDetail(body.detail) || `HTTP ${resp.status}`);
  err.status = resp.status;
  // Kimlikli bir istekte 401: oturum düştü/süresi doldu. Session temizle,
  // App'e haber ver ki login ekranına yönlensin (sayfa kırılmasın).
  if (resp.status === 401 && getToken()) {
    logout();
    window.dispatchEvent(new CustomEvent("nabiz:session-expired"));
  }
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

// Genel JSON PUT
export async function apiPut(path, body) {
  const resp = await fetch(path, {
    method: "PUT",
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

export function updateProfile(patch) {
  return apiPatch("/api/auth/me/profile", patch);
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

export function addMembership(userId, team_id, role) {
  return apiPost(`/api/auth/employees/${userId}/memberships`, { team_id, role });
}

export function removeMembership(userId, teamId) {
  return apiDelete(`/api/auth/employees/${userId}/memberships/${teamId}`);
}

// --- ilk kurulum --------------------------------------------------------------

export function setupStatus() {
  return fetch("/api/auth/setup-status").then((r) => r.json());
}

export async function setup(payload) {
  const data = await apiPost("/api/auth/setup", payload);
  saveSession(data.access_token, data.user);
  setCurrentDevId(data.user.developer_id);
  return data.user;
}

// --- projeler (GitHub) --------------------------------------------------------

export function listProjects(all = false) {
  return api(`/api/projects${all ? "?all=true" : ""}`);
}
export function createProject(name, github_url) {
  return apiPost("/api/projects", { name, github_url });
}
export function syncProject(id) {
  return apiPost(`/api/projects/${id}/sync`, {});
}
export function deleteProject(id) {
  return apiDelete(`/api/projects/${id}`);
}
export function getProjectCommits(id) {
  return api(`/api/projects/${id}/commits`);
}
export function reviewProject(id) {
  return apiPost(`/api/projects/${id}/review`, {});
}
export function getProjectReviews(id) {
  return api(`/api/projects/${id}/reviews`);
}

// --- izinler ------------------------------------------------------------------

export function listLeaves(month) {
  return api(`/api/leaves?month=${month}`);
}
export function createLeave(payload) {
  return apiPost("/api/leaves", payload);
}
export function deleteLeave(id) {
  return apiDelete(`/api/leaves/${id}`);
}
export function leaveSummary(month) {
  return api(`/api/leaves/summary?month=${month}`);
}

// --- bildirimler --------------------------------------------------------------

export function listNotifications() {
  return api("/api/me/notifications");
}
export function markNotificationRead(id) {
  return apiPost(`/api/me/notifications/${id}/read`, {});
}
export function markAllNotificationsRead() {
  return apiPost("/api/me/notifications/read-all", {});
}

// --- denetim kaydı (admin) ----------------------------------------------------

export function listAudit() {
  return api("/api/admin/audit");
}

// --- 1:1 hazırlık özeti -------------------------------------------------------

export function oneOnOne(devId) {
  return api(`/api/developers/${devId}/one-on-one`);
}

// --- CSV indirme (auth başlıklı; blob olarak indirir) -------------------------

export async function downloadCsv(path, filename) {
  const resp = await fetch(path, { headers: authHeaders() });
  if (!resp.ok) throw await parseError(resp);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// --- yönetici: entegrasyon/kaynak ---------------------------------------------

export function getSources() {
  return api("/api/admin/sources");
}

export function updateSources(patch) {
  return apiPut("/api/admin/sources", patch);
}

export function triggerSync() {
  return apiPost("/api/admin/sync", {});
}
