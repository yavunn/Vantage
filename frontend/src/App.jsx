// Engineering Health Dashboard — varsayılan görünüm TAKIM'dır (İlke E).
// Bireysel sekme yalnızca yetkiliyse içerik gösterir; leaderboard yoktur.
import { useEffect, useState } from "react";
import { api, setCurrentDevId } from "./api.js";
import IndividualView from "./components/IndividualView.jsx";
import MetricCard from "./components/MetricCard.jsx";
import TrendChart from "./components/TrendChart.jsx";

const SERIES_KEYS = ["cycle_time", "pr_review_time", "review_latency", "deployment_frequency", "rework"];

export default function App() {
  const [uiConfig, setUiConfig] = useState(null);
  const [teams, setTeams] = useState([]);
  const [teamId, setTeamId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);
  const [quality, setQuality] = useState([]);
  const [directory, setDirectory] = useState([]);
  const [devId, setDevId] = useState(null);       // demo kimlik seçici
  const [viewDevId, setViewDevId] = useState(null); // bireysel sekmede bakılan kişi
  const [tab, setTab] = useState("team");
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api("/api/config/ui"), api("/api/teams"), api("/api/directory")])
      .then(([cfg, tms, dir]) => {
        setUiConfig(cfg);
        setTeams(tms);
        setDirectory(dir);
        if (tms.length) setTeamId(tms[0].id);
      })
      .catch(setError);
  }, []);

  useEffect(() => {
    if (teamId == null) return;
    api(`/api/teams/${teamId}/summary`).then(setSummary).catch(setError);
    api(`/api/teams/${teamId}/quality`).then(setQuality).catch(() => setQuality([]));
    Promise.all(
      SERIES_KEYS.map((k) => api(`/api/teams/${teamId}/series/${k}`).catch(() => null))
    ).then((all) => setSeries(all.filter(Boolean)));
  }, [teamId]);

  useEffect(() => {
    setCurrentDevId(devId);
    if (devId != null && viewDevId == null) setViewDevId(devId);
  }, [devId]);

  if (error) return <div className="error-box">Hata: {error.message}</div>;
  if (!uiConfig) return <div className="app">Yükleniyor…</div>;

  const individualAvailable = uiConfig.individual_view_enabled;

  return (
    <div className="app">
      <header className="topbar">
        <h1>Engineering Health Dashboard</h1>
        <select value={teamId ?? ""} onChange={(e) => setTeamId(Number(e.target.value))}>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        {/* Demo kimlik seçici — gerçek kurulumda SSO'dan gelir */}
        <select
          value={devId ?? ""}
          onChange={(e) => {
            const v = e.target.value ? Number(e.target.value) : null;
            setDevId(v);
            setViewDevId(v);
          }}
        >
          <option value="">Kimlik seç (demo)</option>
          {directory.map((d) => (
            <option key={d.id} value={d.id}>
              {d.display_name}
              {d.roles.some((r) => r.role === "manager") ? " (yönetici)" : ""}
            </option>
          ))}
        </select>
        <button className={`tab ${tab === "team" ? "active" : ""}`} onClick={() => setTab("team")}>
          Takım görünümü
        </button>
        {individualAvailable && (
          <button
            className={`tab ${tab === "me" ? "active" : ""}`}
            onClick={() => setTab("me")}
          >
            Bireysel görünüm
          </button>
        )}
        <span className="sub">
          Süreç sağlığı panosu — kişi performans aracı değildir. Kırmızı,
          "takım zorlanıyor, yardım gerekebilir" demektir; ceza sinyali değildir.
          {uiConfig.anonymize_individuals && " · Anonim mod açık (takım-agregat)."}
        </span>
      </header>

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

      {tab === "me" &&
        (devId == null ? (
          <p className="desc">Bireysel görünüm için yukarıdan kimlik seçin (demo).</p>
        ) : (
          <>
            {/* Yönetici, ekibindeki bir kişiye bakabilir; sunucu yetkiyi zorlar */}
            <div style={{ marginBottom: 12 }}>
              <select
                value={viewDevId ?? devId}
                onChange={(e) => setViewDevId(Number(e.target.value))}
              >
                {directory.map((d) => (
                  <option key={d.id} value={d.id}>{d.display_name}</option>
                ))}
              </select>
            </div>
            <IndividualView devId={viewDevId ?? devId} />
          </>
        ))}
    </div>
  );
}
