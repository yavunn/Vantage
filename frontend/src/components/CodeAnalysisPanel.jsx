import { useEffect, useState } from "react";
import { api, apiPatch, apiPost, apiPut, getLlmProvider, updateLlmProvider } from "../api.js";
import { toast } from "../toast.js";
import CodeHealthCard from "./CodeHealthCard.jsx";
import CodeHealthDrilldown from "./CodeHealthDrilldown.jsx";

// AI kod analizi ayarları (admin). Rubrik ağırlıkları + analiz limitleri.
// Hariç klasörler (node_modules, dist, vendor…) burada YOK: ayar değil, arka
// planda sabit (backend BUILTIN_EXCLUDES).
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

// Baş yöneticinin seçebileceği AI sağlayıcılar (kart etiketleri).
const PROVIDER_META = {
  none: { label: "Kapalı", hint: "AI analizi yapılmaz" },
  claude: { label: "Claude", hint: "Anthropic API · kendi anahtarın" },
  local: { label: "Yerel / OpenAI-uyumlu", hint: "Ollama · LM Studio · vLLM · OpenAI · OpenRouter" },
};

export default function CodeAnalysisPanel({ me }) {
  const isOwner = !!(me && me.is_owner);
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
  // AI sağlayıcı (yalnız baş yönetici düzenler). prov: sunucu durumu;
  // keys: yeni girilen (write-only) API anahtarları — boşsa dokunulmaz.
  const [prov, setProv] = useState(null);
  const [keys, setKeys] = useState({ claude: "", local: "" });
  const [provBusy, setProvBusy] = useState(false);

  function load() {
    api("/api/admin/code-analysis").then(setCfg).catch(setError);
  }
  function loadProvider() {
    getLlmProvider().then(setProv).catch(() => setProv(null));
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
  useEffect(() => {
    load(); loadDevs(); loadOverview(); loadAudit();
    if (isOwner) loadProvider();
  }, [isOwner]);

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
        api(`/api/developers/${dev.id}/code-health`)
          .then(setSelectedHealth)
          .catch((err) => toast(`Kod sağlığı yenilenemedi: ${err.message}`, "error"));
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

  // --- AI sağlayıcı (owner) ---
  function updProv(k, v) { setProv((p) => ({ ...p, [k]: v })); }
  function updProvNested(section, k, v) {
    setProv((p) => ({ ...p, [section]: { ...p[section], [k]: v } }));
  }

  async function saveProvider() {
    setError(null); setMsg(null); setProvBusy(true);
    try {
      const payload = {
        provider: prov.provider,
        claude_model: prov.claude?.model,
        local_base_url: prov.local?.base_url,
        local_model: prov.local?.model,
      };
      // Anahtarlar write-only: yalnız yeni girildiyse gönder (boş = dokunma).
      if (keys.claude) payload.claude_api_key = keys.claude;
      if (keys.local) payload.local_api_key = keys.local;
      await updateLlmProvider(payload);
      setKeys({ claude: "", local: "" });
      setMsg("AI sağlayıcı kaydedildi."); toast("AI sağlayıcı kaydedildi", "ok");
      loadProvider();
      load(); // genel bölüm aktif model/anahtar durumunu tazelesin
      return true;
    } catch (e) { setError(e); toast(e.message, "error"); return false; }
    finally { setProvBusy(false); }
  }

  async function save() {
    setError(null); setMsg(null); setBusy(true);
    try {
      // Yalnız rubrik/limit ayarları. Aç/kapa provider seçimiyle yönetilir.
      await apiPut("/api/admin/code-analysis", {
        weights: cfg.weights,
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
      const m = r.status === "ok"
        ? `Analiz tamam: ${r.analyzed} yeni, ${r.cached ?? 0} önbellek.`
        : (r.note || "Analiz bitti");
      setMsg(m);
      toast(m, r.status === "ok" ? "ok" : (r.status === "error" ? "error" : "info"));
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
          Kodun içeriğini analiz eden AI modülü. Skorlar repo/modül düzeyi — kişi değil.
          Açma/kapama tek yerden: <b>AI Sağlayıcı</b> seçimi (Kapalı = modül kapalı).
        </p>
        <p className="desc">
          ⓘ Kod analizi şu an yalnızca <b>yerel git repolarında</b> (kaynak
          <code> git_log</code>, config'teki <code>repos[].path</code>) çalışır.
          GitLab/GitHub diff API'lerinden çekme henüz yok — uzak-repo diff'i
          analiz edilmez.
        </p>
        {error && <p className="error-inline">{error.message}</p>}
        {msg && <p className="ok-inline">{msg}</p>}
        {(busy || runningDev != null) && (
          <div className="progress-indeterminate" aria-label="İşlem sürüyor"><div /></div>
        )}

        <div className="ca-status">
          <span>Aktif sağlayıcı:{" "}
            <b>{PROVIDER_META[cfg.llm_provider]?.label || cfg.llm_provider}</b>
          </span>
          {cfg.llm_provider !== "none" && <span className="muted">· Model: {cfg.model || "–"}</span>}
          <span className={`key-pill ${cfg.llm_provider !== "none" ? "on" : "off"}`}>
            {cfg.llm_provider !== "none" ? "açık" : "kapalı"}
          </span>
          {!isOwner && <span className="muted">· yalnız Baş Yönetici değiştirir</span>}
        </div>
        <div className="ca-row">
          <button className="login-btn" onClick={runNow} disabled={busy || cfg.llm_provider === "none"}
            title={cfg.llm_provider === "none" ? "Önce bir AI sağlayıcı seç" : "Tüm repoları analiz et"}>
            Şimdi analiz et (tüm repolar)
          </button>
        </div>
      </section>

      {isOwner && (
        <section className="section">
          <h3>AI Sağlayıcı <span className="owner-badge" title="Yalnız baş yönetici">★ Baş Yönetici</span></h3>
          <p className="desc">
            Hangi AI kullanılacağını sen seçersin — Claude zorunlu değil. Anahtarlar
            config dosyasına <b>yazılmaz</b>, yalnız <code>.secrets.env</code>'e işlenir.
          </p>
          {!prov ? (
            <p className="desc">Yükleniyor…</p>
          ) : (
            <div className="prov-box">
              <div className="prov-cards">
                {(prov.providers || ["none", "claude", "local"]).map((p) => (
                  <button key={p} type="button"
                    className={`prov-card ${prov.provider === p ? "active" : ""}`}
                    onClick={() => updProv("provider", p)}>
                    <span className="prov-card-title">{PROVIDER_META[p]?.label || p}</span>
                    <span className="prov-card-hint">{PROVIDER_META[p]?.hint || ""}</span>
                  </button>
                ))}
              </div>

              {prov.provider === "claude" && (
                <div className="prov-fields">
                  <label className="ca-block">
                    Model
                    <input value={prov.claude?.model || ""}
                      onChange={(e) => updProvNested("claude", "model", e.target.value)}
                      placeholder="claude-sonnet-5" />
                  </label>
                  <label className="ca-block">
                    <span>API anahtarı
                      <span className={`key-pill ${prov.claude?.api_key?.configured ? "on" : "off"}`}>
                        {prov.claude?.api_key?.configured ? "tanımlı" : "tanımsız"}
                      </span>
                    </span>
                    <input type="password" autoComplete="off" value={keys.claude}
                      onChange={(e) => setKeys((k) => ({ ...k, claude: e.target.value }))}
                      placeholder="değiştirmek için gir · boş = dokunma" />
                  </label>
                </div>
              )}

              {prov.provider === "local" && (
                <div className="prov-fields">
                  <label className="ca-block">
                    Sunucu adresi
                    <input value={prov.local?.base_url || ""}
                      onChange={(e) => updProvNested("local", "base_url", e.target.value)}
                      placeholder="http://localhost:11434" />
                  </label>
                  <label className="ca-block">
                    Model
                    <input value={prov.local?.model || ""}
                      onChange={(e) => updProvNested("local", "model", e.target.value)}
                      placeholder="llama3.1" />
                  </label>
                  <label className="ca-block">
                    <span>API anahtarı <span className="muted">(opsiyonel)</span>
                      <span className={`key-pill ${prov.local?.api_key?.configured ? "on" : "off"}`}>
                        {prov.local?.api_key?.configured ? "tanımlı" : "tanımsız"}
                      </span>
                    </span>
                    <input type="password" autoComplete="off" value={keys.local}
                      onChange={(e) => setKeys((k) => ({ ...k, local: e.target.value }))}
                      placeholder="anahtarsız uçlar (Ollama) için boş bırak" />
                  </label>
                </div>
              )}

              <div className="prov-actions">
                <button className="login-btn" onClick={saveProvider} disabled={provBusy}>
                  {provBusy ? "Kaydediliyor…" : "Kaydet"}
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="section">
        <h3>Rubrik ağırlıkları</h3>
        <p className="desc">
          Her boyutun ağırlığı (0 = yok say). Bu değerler hem composite skoru hem
          <b> AI'a giden prompt'u</b> etkiler — ağırlığı yüksek boyutu (okunabilirlik,
          karmaşıklık, temizlik…) AI daha çok önemser. Kod taraması dış araca değil,
          bu prompt'a bağlıdır.
        </p>
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
        <h3>Analiz limitleri</h3>
        <p className="desc">
          Maliyet freni. Analiz her seferinde tüm projeyi okumaz: yalnız değişen
          dosyanın diff'ini ve commit mesajını görür, gerekirse birkaç ilgili
          dosyaya bakar.
        </p>
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
        <div className="ca-row">
          <button className="login-btn" onClick={save} disabled={busy}>Ayarları kaydet</button>
        </div>
      </section>

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
          git e-postası eşlemesi + composite/Detay. Analiz için: üstte
          <strong> Kişi seç → "Bu kişiyi analiz et"</strong> ya da en üstteki
          <strong> "Şimdi analiz et (tüm repolar)"</strong> (herkesi kapsar,
          commit yazarına atar). Kıyaslamalı sıralama yok.
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
          gönderilen karakter, maskelenen secret sayısı, sonuç. "Ek okuma" =
          diff yetmediği için ayrıca okunan dosya sayısı (en fazla 3).
        </p>
        {audit.length === 0 ? (
          <p className="desc">Henüz kayıt yok.</p>
        ) : (
          <div className="drill-scroll">
            <table className="admin-table">
              <thead>
                <tr><th>Tarih</th><th>Dosya</th><th className="num">Karakter</th><th className="num">Maskeli</th><th className="num">Ek okuma</th><th>Sonuç</th><th>Model</th></tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td className="muted">{a.sent_at ? a.sent_at.slice(0, 16).replace("T", " ") : "–"}</td>
                    <td><code>{a.file_path}</code></td>
                    <td className="num">{a.chars_sent}</td>
                    <td className="num">{a.masked_secrets > 0 ? <strong style={{ color: "var(--status-warning)" }}>{a.masked_secrets}</strong> : 0}</td>
                    <td className="num">{a.extra_reads ?? 0}</td>
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
