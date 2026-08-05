// API istemcisi + oturum yönetimi.
// Kimlik: JWT (Bearer) — TÜM uçlar (dashboard dahil) bunu ister.

import { getLang } from "./i18n.jsx";

const TOKEN_KEY = "vantage_token";
const USER_KEY = "vantage_user";

// Parola taban uzunluğu — backend'deki MIN_PASSWORD_LENGTH ile AYNI olmalı
// (app/api/auth.py). İstemcide daha düşük olursa kullanıcı formu gönderir ve
// anlamsız bir 422 ile karşılaşır; tek yerden yönetilsin diye burada.
export const MIN_PASSWORD_LENGTH = 10;

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
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // Metrik adları, açıklamaları ve durum etiketleri SUNUCUDAN geliyor. Dil
  // başlığı gönderilmezse arayüz İngilizce, kartlar Türkçe kalırdı.
  headers["Accept-Language"] = getLang();
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
  // Gövde yok ya da JSON değil (ör. 500 + HTML hata sayfası, proxy kesintisi):
  // boş dön ki çağıran HTTP kodunu göstersin. "Geçersiz istek" demek yanıltıcı
  // olurdu — istek geçersiz değil, sunucu cevap veremedi.
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "Geçersiz istek";
  return detail
    .map((e) => {
      const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
      const label = FIELD_TR[field] || field;
      const min = e.ctx && e.ctx.min_length;
      if (e.type === "string_too_short" || (e.type && e.type.includes("min_length"))) {
        return `${label} en az ${min ?? MIN_PASSWORD_LENGTH} karakter olmalı`;
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
    window.dispatchEvent(new CustomEvent("vantage:session-expired"));
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
  return data.user;
}

export async function fetchMe() {
  return api("/api/auth/me");
}

export async function changePassword(current_password, new_password) {
  const data = await apiPost("/api/auth/change-password", { current_password, new_password });
  // Backend parola değişince token_version artırır (eski token'lar düşer). Bu
  // oturumun devam etmesi için dönen YENİ token'ı sakla.
  if (data && data.access_token) localStorage.setItem(TOKEN_KEY, data.access_token);
  return data;
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

export function setEmployment(userId, patch) {
  return apiPatch(`/api/auth/employees/${userId}/employment`, patch);
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
  return data.user;
}

// --- projeler (GitHub) --------------------------------------------------------

export function listProjects(all = false) {
  return api(`/api/projects${all ? "?all=true" : ""}`);
}
/** Kendi GitHub anahtarımın DURUMU — anahtarın kendisi asla dönmez. */
export function getGithubCredential() {
  return api("/api/me/credentials/github");
}
/** Boş string gönderilirse bağlantı kaldırılır. */
export function setGithubCredential(token) {
  return apiPut("/api/me/credentials/github", { token });
}

/** source: {type:"github", url} ya da {type:"local", path} — yerel kaynak ağa çıkmaz. */
export function createProject(name, source) {
  const body = source.type === "local"
    ? { name, source_type: "local", local_path: source.path }
    : { name, source_type: "github", github_url: source.url };
  return apiPost("/api/projects", body);
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
export function leaveBalances(year) {
  return api(`/api/leaves/balances${year ? `?year=${year}` : ""}`);
}
export function pendingLeaves() {
  return api("/api/leaves/pending");
}
export function myLeaveRequests() {
  return api("/api/leaves/mine");
}
export function decideLeave(id, decision, note) {
  return apiPost(`/api/leaves/${id}/decision`, { decision, note });
}

// --- anotasyonlar (tatil/olay işaretleri) -------------------------------------
// İzin takviminin bir parçası: aynı ekranda hem izinler hem tatil/olay işaretleri
// yönetilir. Yazma/silme admin + İK (backend de öyle zorlar).
export function listAnnotations(teamId) {
  return api(`/api/annotations${teamId != null ? `?team_id=${teamId}` : ""}`);
}
export function createAnnotation(payload) {
  return apiPost("/api/annotations", payload);
}
export function deleteAnnotation(id) {
  return apiDelete(`/api/annotations/${id}`);
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

// Senkron artık ARKA PLANDA çalışır: uç hemen bir iş kimliği döner.
// (Eskiden pipeline istek içinde koşuyordu; gerçek kaynakla dakikalar sürdüğü
// için tarayıcı/proxy zaman aşımına düşüyor ve ilerleme görünmüyordu.)
export function triggerSync(full = false) {
  return apiPost(`/api/admin/sync${full ? "?full=true" : ""}`, {});
}

export function syncStatus(jobId) {
  return api(jobId ? `/api/admin/sync/${jobId}` : "/api/admin/sync/status");
}

// Kuru çalıştırma: kaynaklar okunabiliyor mu? DB'ye yazmaz.
export function testSources() {
  return apiPost("/api/admin/sources/test", {});
}

// --- yönetici: takım yönetimi ------------------------------------------------

export function listTeamsAdmin() {
  return api("/api/admin/teams");
}

export function createTeam(name) {
  return apiPost("/api/admin/teams", { name });
}

export function renameTeam(id, name) {
  return apiPatch(`/api/admin/teams/${id}`, { name });
}

export function deleteTeam(id) {
  return apiDelete(`/api/admin/teams/${id}`);
}

// --- yönetici: kimlik eşleme (git ↔ görev kaynağı) --------------------------

export function listIdentities() {
  return api("/api/admin/identities");
}

// key boş/null → bağ kaldırılır. Aynı kimliği taşıyan kopya kişi kaydı varsa
// sunucu onu hedefe birleştirir (task + üyelik taşınır, kopya silinir).
export function setTaskIdentity(devId, source, key) {
  return apiPatch(`/api/admin/developers/${devId}/task-identity`, { source, key });
}

// İki kişi kaydını elle birleştirir (hedef = devId, silinen = duplicateId).
// Aynı insan iki git e-postasıyla geldiyse otomatik ipucu yoktur; kararı insan
// verir. GERİ ALINAMAZ — çağıran onay almalı.
export function mergeDevelopers(devId, duplicateId) {
  return apiPost(`/api/admin/developers/${devId}/merge`, { duplicate_id: duplicateId });
}

// --- task ↔ commit bağı (öneri + insan onayı) -------------------------------
//
// Kaynaklarda bu bağ yok; motor anlamsal benzerlikle TAHMİN ediyor ve isabet
// ~%50. Bu yüzden analiz yalnızca ONAYLANMIŞ bağları okur — kullanıcı burada
// onaylamadan hiçbir analiz üretilmez.

export function getTeamTaskLinks(teamId) {
  return api(`/api/teams/${teamId}/task-links`);
}

// status: "confirmed" | "rejected". Karar kalıcıdır; senkron onu EZMEZ.
export function decideTaskLink(teamId, taskId, commitId, status) {
  return apiPost(`/api/teams/${teamId}/tasks/${taskId}/links/${commitId}`, { status });
}

export function analyzeTask(teamId, taskId) {
  return apiPost(`/api/teams/${teamId}/tasks/${taskId}/analysis`);
}

// --- yönetici: genel ayarlar (metrik/eşik/kural/anket/gizlilik) --------------

export function getSettings() {
  return api("/api/admin/settings");
}

export function updateSettings(patch) {
  return apiPut("/api/admin/settings", patch);
}

// --- baş yönetici (owner): AI sağlayıcı ---------------------------------------

export function getLlmProvider() {
  return api("/api/admin/llm-provider");
}

export function updateLlmProvider(patch) {
  return apiPut("/api/admin/llm-provider", patch);
}

// --- anonim memnuniyet anketi -------------------------------------------------

export function getCurrentSurvey() {
  return api("/api/survey/current");
}
export function submitSurvey(answers, texts) {
  return apiPost("/api/survey/current", { answers, texts });
}
export function getSurveyQuestions() {
  return api("/api/survey/questions");
}
export function updateSurveyQuestions(items) {
  return apiPut("/api/survey/questions", items);
}
export function getSurveyResults(cycleKey) {
  return api(`/api/survey/results${cycleKey ? `?cycle=${encodeURIComponent(cycleKey)}` : ""}`);
}
export function getSurveyCycles() {
  return api("/api/survey/cycles");
}
export function getSurveyStatus() {
  return api("/api/survey/status");
}
export function genSurveyKey() {
  return apiPost("/api/survey/genkey", {});
}
