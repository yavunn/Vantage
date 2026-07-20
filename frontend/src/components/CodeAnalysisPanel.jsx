import { useEffect, useState } from "react";
import { api, apiPatch, apiPost, apiPut } from "../api.js";
import { toast } from "../toast.js";
import CodeHealthCard from "./CodeHealthCard.jsx";
import CodeHealthDrilldown from "./CodeHealthDrilldown.jsx";

// AI kod analizi ayarları (admin). Rubrik ağırlıkları, hariç klasörler, sıklık.
// API anahtarı config'e YAZILMAZ — env'den okunur.
const DIM_LABELS = {
  readability: "Okunabilirlik",
  complexity: "Karmaşıklık",
  maintainability: "Bakım",
  test_adequacy: "Test",
  security: "Güvenlik",
  code_smells: "Kod Kokuları",
  conventions: "Konvansiyon",
};

export default function CodeAnalysisPanel() {
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [devs, setDevs] = useState([]);
  const [runningDev, setRunningDev] = useState(null);
  const [detailDev, setDetailDev] = useState(null);
  const [overview, setOverview] = useState(null);
  const [overviewDrill, setOverviewDrill] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [selectedHealth, setSelectedHealth] = useState(null);
  const [selectedDrill, setSelectedDrill] = useState(false);
  const [audit, setAudit] = useState([]);

  function load() {
    api("/api/admin/code-analysis").then(setCfg).catch(setError);
  }
  function loadDevs() {
    api("/api/admin/code-analysis/developers").then(setDevs).catch(() => setDevs([]));
  }
  function loadOverview() {
    api("/api/admin/code-analysis/overview").then(setOverview).catch(() => setOverview(null));
  }
  function loadAudit() {
    api("/api/admin/code-analysis/audit?limit=50").then(setAudit).catch(() => setAudit([]));
  }
  useEffect(() => { load(); loadDevs(); loadOverview(); loadAudit(); }, []);

  // Kişi seçilince o kişinin sonuçlarını getir
  useEffect(() => {
    if (!selectedId) { setSelectedHealth(null); return; }
    api(`/api/developers/${selectedId}/code-health`).then(setSelectedHealth).catch(() => setSelectedHealth(null));
  }, [selectedId]);

  async function analyzeDev(dev) {
    setRunningDev(dev.id); setMsg(null); setError(null);
    try {
      const r = await apiPost(`/api/admin/code-analysis/run-developer/${dev.id}`, {});
      const okmsg = `${dev.display_name}: ${r.status === "ok" ? `${r.analyzed} yeni, ${r.cached} önbellek` : (r.note || JSON.stringify(r))}`;
      setMsg(okmsg); toast(okmsg, r.status === "ok" ? "ok" : "info");
      loadDevs();
      loadOverview();
      loadAudit();
      if (String(selectedId) === String(dev.id)) {
        api(`/api/developers/${dev.id}/code-health`).then(setSelectedHealth).catch(() => {});
      }
    } catch (e) { setError(e); toast(`Analiz hatası: ${e.message}`, "error"); } finally { setRunningDev(null); }
  }

  const selectedDev = devs.find((d) => String(d.id) === String(selectedId));

  const [gitEdit, setGitEdit] = useState({}); // dev.id → düzenlenen e-posta
  async function saveGitEmail(dev) {
    const val = gitEdit[dev.id] ?? dev.git_email ?? "";
    setError(null); setMsg(null);
    try {
      await apiPatch(`/api/admin/developers/${dev.id}/git-email`, { git_email: val });
      setMsg(`${dev.display_name}: git e-postası kaydedildi.`); toast("git e-postası kaydedildi", "ok");
      setGitEdit((g) => { const n = { ...g }; delete n[dev.id]; return n; });
      loadDevs();
    } catch (e) { setError(e); toast(e.message, "error"); }
  }

  function upd(k, v) { setCfg((c) => ({ ...c, [k]: v })); }
  function updWeight(d, v) {
    setCfg((c) => ({ ...c, weights: { ...c.weights, [d]: v } }));
  }

  async function save() {
    setError(null); setMsg(null); setBusy(true);
    try {
      await apiPut("/api/admin/code-analysis", {
        enabled: cfg.enabled,
        llm_enabled: cfg.llm_enabled,
        llm_provider: cfg.llm_provider,
        weights: cfg.weights,
        exclude_globs: cfg.exclude_globs,
        max_files_per_run: Number(cfg.max_files_per_run),
        max_diff_lines: Number(cfg.max_diff_lines),
      });
      setMsg("Kaydedildi."); toast("Ayarlar kaydedildi", "ok");
      load();
    } catch (e) { setError(e); toast(e.message, "error"); } finally { setBusy(false); }
  }

  async function runNow() {
    setError(null); setMsg(null); setBusy(true);
    try {
      toast("Analiz başladı…", "info");
      const r = await apiPost("/api/admin/code-analysis/run", {});
      setMsg(`Analiz: ${JSON.stringify(r)}`);
      toast(r.status === "ok" ? `Analiz tamam: ${r.analyzed} yeni` : (r.note || "Analiz bitti"), r.status === "ok" ? "ok" : "info");
      loadAudit(); loadOverview();
    } catch (e) { setError(e); toast(e.message, "error"); } finally { setBusy(false); }
  }

  if (error && !cfg) return <p className="error-inline">{error.message}</p>;
  if (!cfg) return <p className="desc">Yükleniyor…</p>;

  return (
    <div>
      <section className="section">
        <h2>AI Kod Analizi</h2>
        <p className="desc">
          Kodun içeriğini analiz eden AI modülü. Skorlar repo/modül düzeyi —
          kişi değil. Anahtar (<code>{cfg.api_key?.env_var}</code>) config'e
          yazılmaz, ortamdan okunur: {cfg.api_key?.configured ? "tanımlı ✓" : "tanımsız ✗"}.
        </p>
        {error && <p className="error-inline">{error.message}</p>}
        {msg && <p className="ok-inline">{msg}</p>}
        {(busy || runningDev != null) && (
          <div className="progress-indeterminate" aria-label="İşlem sürüyor"><div /></div>
        )}

        <div className="ca-row">
          <label><input type="checkbox" checked={cfg.enabled} onChange={(e) => upd("enabled", e.target.checked)} /> Kod analizi açık</label>
          <label><input type="checkbox" checked={cfg.llm_enabled} onChange={(e) => upd("llm_enabled", e.target.checked)} /> LLM açık (dışarı veri gönderir)</label>
          <label>Sağlayıcı:{" "}
            <select value={cfg.llm_provider} onChange={(e) => upd("llm_provider", e.target.value)}>
              <option value="none">none</option>
              <option value="local">local (self-hosted)</option>
              <option value="claude">claude</option>
            </select>
          </label>
          <span className="desc">Model: {cfg.model}</span>
        </div>
      </section>

      <section className="section">
        <h3>Rubrik ağırlıkları</h3>
        <p className="desc">Composite skorda her boyutun ağırlığı (0 = yok say).</p>
        <div className="ca-weights">
          {Object.keys(DIM_LABELS).map((d) => (
            <label key={d} className="ca-slider">
              <span>{DIM_LABELS[d]} <b>{(cfg.weights?.[d] ?? 1).toFixed(1)}</b></span>
              <input type="range" min="0" max="3" step="0.5" value={cfg.weights?.[d] ?? 1}
                onChange={(e) => updWeight(d, Number(e.target.value))} />
            </label>
          ))}
        </div>
      </section>

      <section className="section">
        <h3>Hariç klasörler / sıklık</h3>
        <label className="ca-block">
          Analiz dışı desenler (her satır bir glob):
          <textarea rows={5} value={(cfg.exclude_globs || []).join("\n")}
            onChange={(e) => upd("exclude_globs", e.target.value.split("\n"))} />
        </label>
        <div className="ca-row">
          <label>Çalıştırma başına maks dosya:
            <input type="number" min="1" value={cfg.max_files_per_run}
              onChange={(e) => upd("max_files_per_run", e.target.value)} />
          </label>
          <label>Maks diff satırı (kırpma):
            <input type="number" min="20" value={cfg.max_diff_lines}
              onChange={(e) => upd("max_diff_lines", e.target.value)} />
          </label>
        </div>
      </section>

      <div className="ca-row">
        <button className="login-btn" onClick={save} disabled={busy}>Kaydet</button>
        <button className="mini" onClick={runNow} disabled={busy}>Şimdi analiz et (tüm yazarlar)</button>
      </div>

      <section className="section">
        <h3>Şirket geneli</h3>
        <p className="desc">Tüm repo/dosyaların genel AI kod sağlığı (tüm şirket).</p>
        <div className="cards" style={{ maxWidth: 320 }}>
          <CodeHealthCard health={overview} onClick={() => setOverviewDrill(true)} />
        </div>
      </section>

      <section className="section">
        <h3>Kişi seç ve sonuçlarını gör</h3>
        <p className="desc">
          İstediğin kişiyi seç, kendi kod sağlığını gör. Kıyaslamalı sıralama yok
          — her kişi kendi kodunun geri bildirimi.
        </p>
        <div className="ca-row">
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)} aria-label="Kişi seç">
            <option value="">— kişi seç —</option>
            {devs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.display_name}{d.composite != null ? ` (${d.composite})` : ""}
              </option>
            ))}
          </select>
          {selectedDev && (
            <button className="mini" disabled={!selectedDev.analyzable || runningDev === selectedDev.id}
              title={selectedDev.analyzable ? "" : "git e-postası yok — atıf yapılamaz"}
              onClick={() => analyzeDev(selectedDev)}>
              {runningDev === selectedDev.id ? "Analiz ediliyor…" : "Bu kişiyi analiz et"}
            </button>
          )}
        </div>
        {selectedId && (
          <div className="cards" style={{ maxWidth: 320, marginTop: 10 }}>
            <CodeHealthCard health={selectedHealth} onClick={() => setSelectedDrill(true)} />
          </div>
        )}
      </section>

      <section className="section">
        <h3>Tüm kişiler</h3>
        <p className="desc">
          Her kişiyi tek tek, isteğe bağlı analiz et. Atıf git commit yazarına
          göre. Kıyaslamalı sıralama yok — her kişi kendi kodunun geri bildirimi.
          git e-postası tanımsızsa atıf yapılamaz.
        </p>
        <p className="desc">
          <strong>git e-posta</strong> = kişinin commit e-postası. Bağlı değilse
          kişi-bazlı analiz atıf yapamaz. Buradan bağla (elle SQL gerekmez).
        </p>
        <table className="admin-table">
          <thead>
            <tr><th>Kişi</th><th>git e-posta (commit e-postası)</th><th className="num">Composite</th><th className="num">Dosya</th><th></th></tr>
          </thead>
          <tbody>
            {devs.map((d) => (
              <tr key={d.id}>
                <td>{d.display_name}</td>
                <td>
                  <input
                    className="git-email-input"
                    value={gitEdit[d.id] ?? d.git_email ?? ""}
                    placeholder="ad@company.com"
                    onChange={(e) => setGitEdit((g) => ({ ...g, [d.id]: e.target.value }))}
                  />
                  {(gitEdit[d.id] ?? d.git_email ?? "") !== (d.git_email ?? "") && (
                    <button className="mini" onClick={() => saveGitEmail(d)}>Kaydet</button>
                  )}
                </td>
                <td className="num">{d.composite ?? "–"}</td>
                <td className="num">{d.analyzed_files}</td>
                <td>
                  <button className="mini" disabled={!d.analyzable || runningDev === d.id}
                    title={d.analyzable ? "" : "git e-postası yok — atıf yapılamaz"}
                    onClick={() => analyzeDev(d)}>
                    {runningDev === d.id ? "…" : "Analiz et"}
                  </button>
                  <button className="mini ghost" disabled={!d.analyzed_files}
                    onClick={() => setDetailDev(d)}>Detay</button>
                </td>
              </tr>
            ))}
            {devs.length === 0 && (
              <tr><td colSpan={5} className="desc">Kişi yok.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="section">
        <h3>Denetim logu (gizlilik şeffaflığı)</h3>
        <p className="desc">
          LLM'e ne gitti — <strong>içerik saklanmaz</strong>, yalnızca meta: dosya,
          gönderilen karakter, maskelenen secret sayısı, sonuç.
        </p>
        {audit.length === 0 ? (
          <p className="desc">Henüz kayıt yok.</p>
        ) : (
          <div className="drill-scroll">
            <table className="admin-table">
              <thead>
                <tr><th>Tarih</th><th>Dosya</th><th className="num">Karakter</th><th className="num">Maskeli</th><th>Sonuç</th><th>Model</th></tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td className="muted">{a.sent_at ? a.sent_at.slice(0, 16).replace("T", " ") : "–"}</td>
                    <td><code>{a.file_path}</code></td>
                    <td className="num">{a.chars_sent}</td>
                    <td className="num">{a.masked_secrets > 0 ? <strong style={{ color: "var(--status-warning)" }}>{a.masked_secrets}</strong> : 0}</td>
                    <td className={a.outcome === "ok" ? "" : "muted"}>{a.outcome}</td>
                    <td className="muted">{a.model || a.provider || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detailDev && (
        <CodeHealthDrilldown
          path={`/api/developers/${detailDev.id}/code-health/breakdown`}
          title={`${detailDev.display_name} — kod analizi`}
          onClose={() => setDetailDev(null)}
        />
      )}
      {overviewDrill && (
        <CodeHealthDrilldown
          path="/api/admin/code-analysis/overview/breakdown"
          title="Şirket geneli — dikkat isteyen dosyalar"
          onClose={() => setOverviewDrill(false)}
        />
      )}
      {selectedDrill && selectedDev && (
        <CodeHealthDrilldown
          path={`/api/developers/${selectedDev.id}/code-health/breakdown`}
          title={`${selectedDev.display_name} — kod analizi`}
          onClose={() => setSelectedDrill(false)}
        />
      )}
    </div>
  );
}
