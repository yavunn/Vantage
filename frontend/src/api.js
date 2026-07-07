// Basit API istemcisi. Kimlik (demo): X-Dev-Id başlığı — şirket ortamında
// bu katman SSO/reverse-proxy başlığıyla değişir, tek nokta burasıdır.
let currentDevId = null;

export function setCurrentDevId(id) {
  currentDevId = id;
}

export async function api(path) {
  const headers = {};
  if (currentDevId != null) headers["X-Dev-Id"] = String(currentDevId);
  const resp = await fetch(path, { headers });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const err = new Error(body.detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}
