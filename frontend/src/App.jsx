// Nabız — Mühendislik Sağlığı Panosu.
// Varsayılan görünüm TAKIM'dır (İlke E). Bireysel sekme yalnızca yetkiliye
// içerik gösterir; leaderboard yoktur. Giriş gerçek hesapla yapılır.
import { useEffect, useState } from "react";
import { api, fetchMe, getStoredUser, getToken, logout, setCurrentDevId, setupStatus } from "./api.js";
import AdminPanel from "./components/AdminPanel.jsx";
import ForceChangePassword from "./components/ForceChangePassword.jsx";
import IndividualView from "./components/IndividualView.jsx";
import LeavesPanel from "./components/LeavesPanel.jsx";
import Login from "./components/Login.jsx";
import MetricCard from "./components/MetricCard.jsx";
import ProjectsPanel from "./components/ProjectsPanel.jsx";
import Settings from "./components/Settings.jsx";
import Setup from "./components/Setup.jsx";
import TrendChart from "./components/TrendChart.jsx";

const SERIES_KEYS = ["cycle_time", "pr_review_time", "review_latency", "deployment_frequency", "rework"];

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

export default function App() {
  const [authReady, setAuthReady] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [user, setUser] = useState(null);

  const [uiConfig, setUiConfig] = useState(null);
  const [teams, setTeams] = useState([]);
  const [teamId, setTeamId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);
  const [quality, setQuality] = useState([]);
  const [directory, setDirectory] = useState([]);
  const [viewDevId, setViewDevId] = useState(null);
  const [tab, setTab] = useState("team");
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("nabiz_theme") || "auto");

  // Tema uygula + kalıcılaştır.
  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem("nabiz_theme", theme);
  }, [theme]);

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
        if (tms.length) setTeamId((cur) => cur ?? tms[0].id);
      })
      .catch(setError);
  }, [user]);

  useEffect(() => {
    if (teamId == null) return;
    api(`/api/teams/${teamId}/summary`).then(setSummary).catch(setError);
    api(`/api/teams/${teamId}/quality`).then(setQuality).catch(() => setQuality([]));
    Promise.all(
      SERIES_KEYS.map((k) => api(`/api/teams/${teamId}/series/${k}`).catch(() => null))
    ).then((all) => setSeries(all.filter(Boolean)));
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

      {tab === "team" && summary && (
        <>
          <div className="team-toolbar">
            <button className="mini" onClick={exportCsv}>CSV indir</button>
            <button className="mini" onClick={() => window.print()}>Yazdır / PDF</button>
          </div>
          <div className="cards">
            {summary.metrics.map((m) => (
              <MetricCard key={m.key} metric={m} />
            ))}
          </div>

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
            <h2>Haftalık trend</h2>
            <div className="charts">
              {series.map((s) => (
                <TrendChart key={s.metric} series={s} />
              ))}
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
            <IndividualView devId={viewDevId ?? user.developer_id} />
          ) : (
            <p className="desc">Bu hesap bir geliştiriciye bağlı değil.</p>
          )}
        </>
      )}
    </div>
  );
}
