// Analiz sonuçları (Faz 4): durum + proje hijyen sinyalleri + commit listesi.
// Sinyaller takım/proje hijyenidir; kırmızı "yardım gerekebilir" demektir.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import CommitTable from "./CommitTable.jsx";
import MetricCard from "./MetricCard.jsx";

const STATUS_TEXT = {
  pending: "Sırada…",
  running: "Çalışıyor…",
  ok: "Tamamlandı",
  error: "Hata",
};

export default function AnalysisResults({ projectId }) {
  const [analysis, setAnalysis] = useState(null);
  const [commits, setCommits] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let timer;
    function load() {
      api(`/api/user/projects/${projectId}/analysis`)
        .then((a) => {
          setAnalysis(a);
          if (a.status === "pending" || a.status === "running") {
            timer = setTimeout(load, 3000); // bitene dek yokla
          } else {
            api(`/api/user/projects/${projectId}/commits`)
              .then(setCommits)
              .catch(() => setCommits([]));
          }
        })
        .catch(setError);
    }
    load();
    return () => clearTimeout(timer);
  }, [projectId]);

  if (error) return <div className="error-box">Hata: {error.message}</div>;
  if (!analysis) return <p className="desc">Yükleniyor…</p>;

  return (
    <section className="section">
      <h2>
        Analiz — {STATUS_TEXT[analysis.status] ?? "Henüz çalıştırılmadı"}
        {analysis.last_run_at &&
          ` (${new Date(analysis.last_run_at).toLocaleString()})`}
      </h2>
      {analysis.status === "error" && (
        <div className="error-box">{String(analysis.detail)}</div>
      )}
      {analysis.metrics.length > 0 && (
        <>
          <p className="desc">{analysis.note}</p>
          <div className="cards">
            {analysis.metrics.map((m) => (
              <MetricCard key={m.key} metric={m} />
            ))}
          </div>
        </>
      )}
      <h2>Son commit'ler</h2>
      <CommitTable commits={commits} />
    </section>
  );
}
