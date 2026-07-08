// Kullanıcı panosu (Faz 2): takım görünümü + bireysel görünüm.
// Gövde App.jsx'ten taşındı; davranış aynı — leaderboard yoktur.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import IndividualView from "./IndividualView.jsx";
import MetricCard from "./MetricCard.jsx";
import TrendChart from "./TrendChart.jsx";

const SERIES_KEYS = ["cycle_time", "pr_review_time", "review_latency", "deployment_frequency", "rework"];

export default function UserDashboard({ tab, teamId, directory }) {
  const me = useAuth();
  const devId = me?.id ?? null;
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);
  const [quality, setQuality] = useState([]);
  const [viewDevId, setViewDevId] = useState(null); // bireysel sekmede bakılan kişi
  const [error, setError] = useState(null);

  useEffect(() => {
    if (teamId == null) return;
    api(`/api/teams/${teamId}/summary`).then(setSummary).catch(setError);
    api(`/api/teams/${teamId}/quality`).then(setQuality).catch(() => setQuality([]));
    Promise.all(
      SERIES_KEYS.map((k) => api(`/api/teams/${teamId}/series/${k}`).catch(() => null))
    ).then((all) => setSeries(all.filter(Boolean)));
  }, [teamId]);

  useEffect(() => {
    if (devId != null && viewDevId == null) setViewDevId(devId);
  }, [devId]);

  if (error) return <div className="error-box">Hata: {error.message}</div>;

  return (
    <>
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
          <p className="desc">Bu hesap bir geliştirici profiline bağlı değil.</p>
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
    </>
  );
}
