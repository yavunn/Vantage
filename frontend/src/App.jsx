// Nabız — Mühendislik Sağlığı Panosu.
// Varsayılan görünüm TAKIM'dır (İlke E). Bireysel sekme yalnızca yetkiliye
// içerik gösterir; leaderboard yoktur. Giriş gerçek hesapla yapılır.
import { lazy, Suspense, useEffect, useState } from "react";
import { api, fetchMe, getStoredUser, getToken, logout, setCurrentDevId, setupStatus } from "./api.js";
import ForceChangePassword from "./components/ForceChangePassword.jsx";
import Login from "./components/Login.jsx";
import CodeHealthCard from "./components/CodeHealthCard.jsx";
import CodeHealthDrilldown from "./components/CodeHealthDrilldown.jsx";
import MetricCard from "./components/MetricCard.jsx";
import MetricDrilldown from "./components/MetricDrilldown.jsx";
import Setup from "./components/Setup.jsx";
import SignalsBlock from "./components/SignalsBlock.jsx";
import ToastHost from "./components/ToastHost.jsx";
import TrendChart from "./components/TrendChart.jsx";

// Varsayılan (takım) görünümde gerekmeyen ağır panelleri tembel yükle —
// ilk açılış paketi küçülür.
const AdminPanel = lazy(() => import("./components/AdminPanel.jsx"));
const IndividualView = lazy(() => import("./components/IndividualView.jsx"));
const LeavesPanel = lazy(() => import("./components/LeavesPanel.jsx"));
const ProjectsPanel = lazy(() => import("./components/ProjectsPanel.jsx"));
const Settings = lazy(() => import("./components/Settings.jsx"));

const LazyFallback = <div className="app">Yükleniyor…</div>;

const RANGE_OPTIONS = [7, 30, 90];

function BrandMark() {
  return (
    <span className="topbar-mark" aria-hidden="true">
      <svg viewBox="0 0 96 28" width="96" height="28">
        <polyline
          className="ecg"
          points="0,14 18,14 24,14 29,4 36,24 42,14 48,14 53,9 58,19 63,14 96,14"
          fill="none" stroke="currentColor" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else delete root.dataset.theme;
}

// Gezinme durumu: URL hash (paylaşılabilir/yer imi) öncelikli, yoksa
// localStorage (reload'da kaldığın yer). #tab=team&team=1&range=30
function readNav() {
  const h = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  const ls = (k) => localStorage.getItem(k) || undefined;
  const rangeRaw = h.get("range") || ls("nabiz_range");
  const teamRaw = h.get("team") || ls("nabiz_team");
  return {
    tab: h.get("tab") || ls("nabiz_tab") || "team",
    range: [7, 30, 90].includes(Number(rangeRaw)) ? Number(rangeRaw) : 30,
    team: teamRaw != null ? Number(teamRaw) : null,
  };
}

function writeNav({ tab, team, range }) {
  if (tab) localStorage.setItem("nabiz_tab", tab);
  if (team != null) localStorage.setItem("nabiz_team", String(team));
  if (range) localStorage.setItem("nabiz_range", String(range));
  const p = new URLSearchParams();
  if (tab) p.set("tab", tab);
  if (team != null) p.set("team", String(team));
  if (range) p.set("range", String(range));
  const next = "#" + p.toString();
  if (location.hash !== next) history.replaceState(null, "", next);
}

export default function App() {
  const [authReady, setAuthReady] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [user, setUser] = useState(null);

  const [uiConfig, setUiConfig] = useState(null);
  const [teams, setTeams] = useState([]);
  const [teamId, setTeamId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);
  const [signals, setSignals] = useState([]);
  const [quality, setQuality] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [range, setRange] = useState(() => readNav().range);
  const [codeHealth, setCodeHealth] = useState(null);
  const [codeHealthSeries, setCodeHealthSeries] = useState(null);
  const [codeDrill, setCodeDrill] = useState(false);
  const [drill, setDrill] = useState(null); // {key, name} — açık drill-down metriği
  const [directory, setDirectory] = useState([]);
  const [viewDevId, setViewDevId] = useState(null);
  const [tab, setTab] = useState(() => readNav().tab);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("nabiz_theme") || "auto");

  // Tema uygula + kalıcılaştır.
  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem("nabiz_theme", theme);
  }, [theme]);

  // Gezinme durumunu kalıcılaştır (reload'da kal, URL paylaşılabilir).
  useEffect(() => {
    writeNav({ tab, team: teamId, range });
  }, [tab, teamId, range]);

  // Geçerli olmayan sekmeyi (ör. saklanmış 'admin' ama kullanıcı admin değil) düzelt.
  useEffect(() => {
    if (!user || !uiConfig) return;
    const allowed = new Set(["team", "projects", "leaves", "settings"]);
    if (uiConfig.individual_view_enabled) allowed.add("me");
    if (user.role === "admin") allowed.add("admin");
    if (!allowed.has(tab)) setTab("team");
  }, [user, uiConfig, tab]);

  // Açılış: önce kurulum gerekli mi, sonra token doğrula.
  useEffect(() => {
    setupStatus()
      .then((s) => {
        if (s.needs_setup) {
          setNeedsSetup(true);
          setAuthReady(true);
          return;
        }
        const stored = getStoredUser();
        if (getToken() && stored) {
          setCurrentDevId(stored.developer_id);
          setUser(stored);
          fetchMe()
            .then((u) => setUser(u))
            .catch(() => { logout(); setUser(null); })
            .finally(() => setAuthReady(true));
        } else {
          setAuthReady(true);
        }
      })
      .catch(() => setAuthReady(true));
  }, []);

  // Oturum süresi dolunca (401) temiz düşür.
  useEffect(() => {
    function onExpired() {
      setUser(null);
      setUiConfig(null);
      setTeams([]);
      setTeamId(null);
      setSummary(null);
      setTab("team");
    }
    window.addEventListener("nabiz:session-expired", onExpired);
    return () => window.removeEventListener("nabiz:session-expired", onExpired);
  }, []);

  // Giriş sonrası çekirdek veriyi yükle (parola değiştirme beklemiyorsa).
  useEffect(() => {
    if (!user || user.must_change_password) return;
    setViewDevId(user.developer_id);
    Promise.all([api("/api/config/ui"), api("/api/teams"), api("/api/directory")])
      .then(([cfg, tms, dir]) => {
        setUiConfig(cfg);
        setTeams(tms);
        setDirectory(dir);
        if (tms.length) {
          const saved = readNav().team;
          const valid = tms.some((t) => t.id === saved);
          setTeamId((cur) => cur ?? (valid ? saved : tms[0].id));
        }
      })
      .catch(setError);
  }, [user]);

  // Rapor: seçilen aralığa (7/30/90) göre ANLIK hesap — metrik+trend+sinyal+delta.
  useEffect(() => {
    if (teamId == null) return;
    api(`/api/teams/${teamId}/report?days=${range}`)
      .then((rep) => {
        setSummary(rep);
        setSeries(rep.series || []);
        setSignals(rep.signals || []);
      })
      .catch(setError);
  }, [teamId, range]);

  // Kaliteyi ve anotasyonları aralıktan bağımsız yükle (takım değişince).
  useEffect(() => {
    if (teamId == null) return;
    api(`/api/teams/${teamId}/quality`).then(setQuality).catch(() => setQuality([]));
    api(`/api/annotations?team_id=${teamId}`).then(setAnnotations).catch(() => setAnnotations([]));
    api(`/api/teams/${teamId}/code-health`).then(setCodeHealth).catch(() => setCodeHealth(null));
    api(`/api/teams/${teamId}/code-health/series`).then(setCodeHealthSeries).catch(() => setCodeHealthSeries(null));
  }, [teamId]);

  function doLogout() {
    logout();
    setUser(null);
    setUiConfig(null);
    setTeams([]);
    setTeamId(null);
    setSummary(null);
    setTab("team");
  }

  function cycleTheme() {
    setTheme((t) => (t === "auto" ? "light" : t === "light" ? "dark" : "auto"));
  }
  const themeLabel = theme === "auto" ? "Tema: Oto" : theme === "light" ? "Tema: Açık" : "Tema: Koyu";

  function exportCsv() {
    if (!summary) return;
    const teamName = teams.find((t) => t.id === teamId)?.name || "takim";
    const rows = [["Metrik", "Değer", "Birim", "Durum", "Veri tamlığı"]];
    summary.metrics.forEach((m) => {
      rows.push([
        m.title || m.key,
        m.value ?? "",
        m.unit ?? "",
        m.status_label ?? m.status ?? "",
        m.data_completeness != null ? `%${Math.round(m.data_completeness * 100)}` : "",
      ]);
    });
    const csv = rows.map((r) => r.map((c) => `"${String(c).replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `nabiz-${teamName}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (!authReady) return <div className="app">Yükleniyor…</div>;
  if (needsSetup) return <Setup onSuccess={(u) => { setNeedsSetup(false); setUser(u); }} />;
  if (!user) return <Login onSuccess={(u) => setUser(u)} />;
  if (user.must_change_password) {
    return (
      <ForceChangePassword
        onDone={() => fetchMe().then(setUser).catch(doLogout)}
        onLogout={doLogout}
      />
    );
  }

  if (error) return <div className="error-box">Hata: {error.message}</div>;
  if (!uiConfig) return <div className="app">Yükleniyor…</div>;

  const individualAvailable = uiConfig.individual_view_enabled;
  const isAdmin = user.role === "admin";

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-brand">
          <BrandMark />
          <div>
            <h1>Nabız</h1>
            <span className="topbar-suffix">Mühendislik Sağlığı Panosu</span>
          </div>
        </div>

        <select value={teamId ?? ""} onChange={(e) => setTeamId(Number(e.target.value))} aria-label="Takım seç">
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>

        <button className={`tab ${tab === "team" ? "active" : ""}`} onClick={() => setTab("team")}>
          Takım görünümü
        </button>
        {individualAvailable && (
          <button className={`tab ${tab === "me" ? "active" : ""}`} onClick={() => setTab("me")}>
            Bireysel görünüm
          </button>
        )}
        <button className={`tab ${tab === "projects" ? "active" : ""}`} onClick={() => setTab("projects")}>
          Projelerim
        </button>
        <button className={`tab ${tab === "leaves" ? "active" : ""}`} onClick={() => setTab("leaves")}>
          İzinler
        </button>
        {isAdmin && (
          <button className={`tab ${tab === "admin" ? "active" : ""}`} onClick={() => setTab("admin")}>
            Yönetici paneli
          </button>
        )}
        <button className={`tab ${tab === "settings" ? "active" : ""}`} onClick={() => setTab("settings")}>
          Ayarlar
        </button>

        <div className="topbar-user">
          <button className="mini ghost" onClick={cycleTheme} title="Açık/Koyu/Oto tema">{themeLabel}</button>
          <span className="user-chip">
            {user.display_name}
            {isAdmin && <span className="role-badge">admin</span>}
          </span>
          <button className="mini ghost" onClick={doLogout}>Çıkış</button>
        </div>

        <span className="sub">
          Süreç sağlığı panosu — kişi performans aracı değildir. Kırmızı,
          "takım zorlanıyor, yardım gerekebilir" demektir; ceza sinyali değildir.
          {uiConfig.anonymize_individuals && " · Anonim mod açık (takım-agregat)."}
        </span>
      </header>

      <Suspense fallback={LazyFallback}>
        {tab === "settings" && (
          <Settings
            user={user}
            theme={theme}
            onCycleTheme={cycleTheme}
            themeLabel={themeLabel}
            onLogout={doLogout}
          />
        )}

        {tab === "projects" && <ProjectsPanel isAdmin={isAdmin} />}

        {tab === "leaves" && <LeavesPanel user={user} isAdmin={isAdmin} />}

        {tab === "admin" && isAdmin && <AdminPanel teams={teams} me={user} />}
      </Suspense>

      {tab === "team" && !summary && !error && (
        <div className="cards" aria-hidden="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="card skeleton">
              <div className="sk-line sk-title" />
              <div className="sk-line sk-value" />
              <div className="sk-line" />
              <div className="sk-line short" />
            </div>
          ))}
        </div>
      )}

      {tab === "team" && summary && (
        <>
          <div className="team-toolbar">
            <div className="range-picker" role="group" aria-label="Tarih aralığı">
              {RANGE_OPTIONS.map((d) => (
                <button
                  key={d}
                  className={`mini${range === d ? " active" : ""}`}
                  onClick={() => setRange(d)}
                >
                  {d} gün
                </button>
              ))}
            </div>
            <span style={{ flex: 1 }} />
            <button className="mini" onClick={exportCsv}>CSV indir</button>
            <button className="mini" onClick={() => window.print()}>Yazdır / PDF</button>
          </div>
          {(() => {
            const all = [...summary.metrics, ...signals, ...(codeHealth ? [codeHealth] : [])];
            const c = { red: 0, yellow: 0, green: 0 };
            all.forEach((m) => { if (c[m.status] != null) c[m.status] += 1; });
            const total = c.red + c.yellow + c.green;
            if (total === 0) return null;
            return (
              <div className="status-band" role="status">
                <strong>
                  {c.red > 0
                    ? `${c.red} alan yardım istiyor`
                    : c.yellow > 0
                    ? "Takım genel olarak iyi, birkaç alan izlenmeli"
                    : "Her şey akıyor 🎉"}
                </strong>
                <span className="sb-chips">
                  {c.red > 0 && <span className="sb red">● {c.red} zorlanıyor</span>}
                  {c.yellow > 0 && <span className="sb yellow">▲ {c.yellow} izlenmeli</span>}
                  {c.green > 0 && <span className="sb green">✓ {c.green} akıyor</span>}
                </span>
              </div>
            );
          })()}

          <div className="cards">
            {summary.metrics.map((m) => (
              <MetricCard
                key={m.key}
                metric={m}
                previous={m.previous_value}
                onClick={() => setDrill({ key: m.key, name: m.name })}
              />
            ))}
            {codeHealth && (
              <CodeHealthCard health={codeHealth} onClick={() => setCodeDrill(true)} />
            )}
          </div>

          {summary.metrics.length > 0 && summary.metrics.every((m) => m.status === "insufficient_data") && (
            <div className="empty-guide">
              <h3>Bu takım için henüz yeterli veri yok</h3>
              <p>
                {isAdmin
                  ? "Gerçek veri için: kaynağı bağla (config.yaml) → senkron çalıştır. Yönetici paneli → Başlangıç adımlarını izle."
                  : "Veri toplandıkça metrikler burada görünecek. Sorun sürerse yöneticine danış."}
              </p>
              {isAdmin && (
                <button className="mini" onClick={() => setTab("admin")}>Yönetici paneli → Başlangıç</button>
              )}
            </div>
          )}

          <SignalsBlock signals={signals} />

          {summary.recommendations.length > 0 && (
            <section className="section">
              <h2>Süreç önerileri</h2>
              <div className="recs">
                {summary.recommendations.map((r) => (
                  <div key={r.rule} className={`rec ${r.severity}`}>
                    <div className="rule">{r.rule.replaceAll("_", " ")}</div>
                    {r.message}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="section">
            <h2>Trend ({range} gün)</h2>
            <div className="charts">
              {series.map((s) => (
                <TrendChart
                  key={s.metric}
                  series={s}
                  threshold={uiConfig.metric_thresholds?.[s.metric]}
                  annotations={annotations}
                />
              ))}
              {codeHealthSeries && codeHealthSeries.points?.some((p) => p.value != null) && (
                <TrendChart series={codeHealthSeries} annotations={annotations} />
              )}
            </div>
          </section>

          {quality.some((q) => q.snapshot) && (
            <section className="section">
              <h2>Kod kalitesi (araç ölçümü)</h2>
              <table className="quality">
                <thead>
                  <tr>
                    <th>Repo</th><th>Coverage</th><th>Complexity</th>
                    <th>Duplication</th><th>Code Smells</th>
                  </tr>
                </thead>
                <tbody>
                  {quality.map((q) => (
                    <tr key={q.repo}>
                      <td>{q.repo}</td>
                      {["coverage", "complexity", "duplication", "code_smells"].map((f) => (
                        <td key={f} className="num">
                          {q.snapshot && q.snapshot[f] != null ? (
                            f === "coverage" || f === "duplication"
                              ? `%${Number(q.snapshot[f]).toFixed(1)}`
                              : Number(q.snapshot[f]).toFixed(0)
                          ) : (
                            <span className="na">veri yok</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}

      {tab === "me" && (
        <>
          {/* Yönetici, ekibindeki bir kişiye bakabilir; sunucu yetkiyi zorlar */}
          <div style={{ marginBottom: 12 }}>
            <select
              value={viewDevId ?? user.developer_id ?? ""}
              onChange={(e) => setViewDevId(Number(e.target.value))}
              aria-label="Kişi seç"
            >
              {directory.map((d) => (
                <option key={d.id} value={d.id}>{d.display_name}</option>
              ))}
            </select>
          </div>
          {(viewDevId ?? user.developer_id) != null ? (
            <Suspense fallback={LazyFallback}>
              <IndividualView devId={viewDevId ?? user.developer_id} />
            </Suspense>
          ) : (
            <p className="desc">Bu hesap bir geliştiriciye bağlı değil.</p>
          )}
        </>
      )}

      {drill && (
        <MetricDrilldown
          teamId={teamId}
          metricKey={drill.key}
          metricName={drill.name}
          days={range}
          onClose={() => setDrill(null)}
        />
      )}

      {codeDrill && (
        <CodeHealthDrilldown
          path={`/api/teams/${teamId}/code-health/breakdown`}
          title="Kod Sağlığı — dikkat isteyen bölümler (takım)"
          onClose={() => setCodeDrill(false)}
        />
      )}

      <ToastHost />
    </div>
  );
}
