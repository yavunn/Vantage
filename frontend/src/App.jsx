// Nabız — Mühendislik Sağlığı Panosu.
// Varsayılan görünüm TAKIM'dır (İlke E). Bireysel sekme yalnızca yetkiliye
// içerik gösterir; leaderboard yoktur. Giriş gerçek hesapla yapılır.
import { useEffect, useState } from "react";
import { api, fetchMe, getStoredUser, getToken, logout, setCurrentDevId } from "./api.js";
import AdminPanel from "./components/AdminPanel.jsx";
import ChangePassword from "./components/ChangePassword.jsx";
import IndividualView from "./components/IndividualView.jsx";
import Login from "./components/Login.jsx";
import MetricCard from "./components/MetricCard.jsx";
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

export default function App() {
  const [authReady, setAuthReady] = useState(false);
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
  const [showPw, setShowPw] = useState(false);

  // Oturum doğrulama: token varsa /me ile tazele, yoksa giriş ekranı.
  useEffect(() => {
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
  }, []);

  // Giriş sonrası çekirdek veriyi yükle.
  useEffect(() => {
    if (!user) return;
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

  if (!authReady) return <div className="app">Yükleniyor…</div>;
  if (!user) return <Login onSuccess={(u) => setUser(u)} />;

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

        <select value={teamId ?? ""} onChange={(e) => setTeamId(Number(e.target.value))}>
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
        {isAdmin && (
          <button className={`tab ${tab === "admin" ? "active" : ""}`} onClick={() => setTab("admin")}>
            Yönetici paneli
          </button>
        )}

        <div className="topbar-user">
          <span className="user-chip">
            {user.display_name}
            {isAdmin && <span className="role-badge">admin</span>}
          </span>
          <button className="mini ghost" onClick={() => setShowPw(true)}>Parola</button>
          <button className="mini ghost" onClick={doLogout}>Çıkış</button>
        </div>

        <span className="sub">
          Süreç sağlığı panosu — kişi performans aracı değildir. Kırmızı,
          "takım zorlanıyor, yardım gerekebilir" demektir; ceza sinyali değildir.
          {uiConfig.anonymize_individuals && " · Anonim mod açık (takım-agregat)."}
        </span>
      </header>

      {showPw && <ChangePassword onClose={() => setShowPw(false)} />}

      {tab === "admin" && isAdmin && <AdminPanel teams={teams} me={user} />}

      {tab === "team" && summary && (
        <>
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
