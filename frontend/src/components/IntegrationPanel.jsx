import { useEffect, useState } from "react";
import { getSources, triggerSync, updateSources } from "../api.js";

const GIT_PROVIDERS = ["fixture", "git_log", "gitlab"];
const TASK_PROVIDERS = ["fixture", "jira", "trello", "none"];
const QUALITY_PROVIDERS = ["fixture", "sonarqube", "linter", "none"];

function TokenBadge({ token }) {
  if (!token) return null;
  return (
    <span className={`token-badge ${token.configured ? "ok" : "missing"}`}>
      {token.env_var}: {token.configured ? "tanımlı" : "tanımsız"}
    </span>
  );
}

// Yönetici: entegrasyon/kaynak durumu, ayar ve elle senkron.
// Sır (token) burada YAZILMAZ — yalnızca ortam değişkeni durumu gösterilir.
export default function IntegrationPanel() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);

  function load() {
    getSources()
      .then((d) => {
        setData(d);
        setForm({
          git_provider: d.git.provider,
          tasks_provider: d.tasks.provider,
          quality_provider: d.quality.provider,
          gitlab_base_url: d.git.gitlab_base_url || "",
          jira_base_url: d.tasks.jira_base_url || "",
          sonarqube_base_url: d.quality.sonarqube_base_url || "",
          sync_interval_minutes: d.sync_interval_minutes,
        });
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  function upd(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function save(e) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    setSaving(true);
    try {
      await updateSources({
        ...form,
        sync_interval_minutes: Number(form.sync_interval_minutes),
      });
      setMsg("Ayarlar kaydedildi. Yeni ayarlar sonraki senkronda geçerli olur.");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function sync() {
    setError(null);
    setMsg(null);
    setSyncing(true);
    try {
      const res = await triggerSync();
      const s = res.stats || {};
      setMsg(
        `Senkron tamam · metrik: ${s.metric_results ?? 0}, öneri: ${s.recommendations ?? 0}, kalite: ${s.quality_snapshots ?? 0}`
      );
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  }

  if (error && !data) return <div className="login-error">{error}</div>;
  if (!data || !form) return <p className="desc">Yükleniyor…</p>;

  const lastSync = data.last_sync
    ? new Date(data.last_sync).toLocaleString("tr-TR")
    : "henüz yok";

  return (
    <div className="integration-panel">
      <section className="section">
        <div className="section-head">
          <h2>Kaynak durumu</h2>
          <button className="login-btn" onClick={sync} disabled={syncing}>
            {syncing ? "Senkronize ediliyor…" : "Şimdi senkronize et"}
          </button>
        </div>
        <p className="desc">Son senkron: <strong>{lastSync}</strong></p>
        <div className="source-grid">
          <div className="source-card">
            <h3>Git / Kod</h3>
            <div className="src-provider">{data.git.provider}</div>
            <div className="src-meta">Repo sayısı: {data.git.repo_count}</div>
            <TokenBadge token={data.git.token} />
          </div>
          <div className="source-card">
            <h3>Görevler</h3>
            <div className="src-provider">{data.tasks.provider}</div>
            <TokenBadge token={data.tasks.token} />
          </div>
          <div className="source-card">
            <h3>Kod Kalitesi</h3>
            <div className="src-provider">{data.quality.provider}</div>
            <TokenBadge token={data.quality.token} />
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Entegrasyon ayarları</h2>
        <p className="desc">
          Sır (token) buradan girilmez; ortam değişkeniyle verilir. Değişiklikler
          config dosyasına yazılır ve sonraki senkronda geçerli olur.
        </p>
        <form className="admin-form" onSubmit={save}>
          <label>
            Git sağlayıcı
            <select value={form.git_provider} onChange={(e) => upd("git_provider", e.target.value)}>
              {GIT_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            GitLab base URL
            <input value={form.gitlab_base_url} onChange={(e) => upd("gitlab_base_url", e.target.value)} placeholder="https://gitlab.sirket.local" />
          </label>
          <label>
            Görev sağlayıcı
            <select value={form.tasks_provider} onChange={(e) => upd("tasks_provider", e.target.value)}>
              {TASK_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            Jira base URL
            <input value={form.jira_base_url} onChange={(e) => upd("jira_base_url", e.target.value)} placeholder="https://jira.sirket.local" />
          </label>
          <label>
            Kalite sağlayıcı
            <select value={form.quality_provider} onChange={(e) => upd("quality_provider", e.target.value)}>
              {QUALITY_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            SonarQube base URL
            <input value={form.sonarqube_base_url} onChange={(e) => upd("sonarqube_base_url", e.target.value)} placeholder="https://sonar.sirket.local" />
          </label>
          <label>
            Otomatik senkron aralığı (dakika, 0 = kapalı)
            <input type="number" min={0} value={form.sync_interval_minutes} onChange={(e) => upd("sync_interval_minutes", e.target.value)} />
          </label>
          <button type="submit" className="login-btn" disabled={saving}>
            {saving ? "Kaydediliyor…" : "Ayarları kaydet"}
          </button>
        </form>
        {msg && <div className="admin-ok">{msg}</div>}
        {error && <div className="login-error">{error}</div>}
      </section>
    </div>
  );
}
