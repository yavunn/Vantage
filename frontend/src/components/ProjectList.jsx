// Kullanıcının bağlı projeleri (Faz 3). Token asla gösterilmez —
// sunucu zaten döndürmez; yalnız "bağlı" durumu ve son çalıştırma görünür.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import AddProjectForm from "./AddProjectForm.jsx";
import AnalysisResults from "./AnalysisResults.jsx";

const STATUS_TEXT = {
  pending: "sırada",
  running: "çalışıyor",
  ok: "tamam",
  error: "hata",
};

export default function ProjectList() {
  const [projects, setProjects] = useState([]);
  const [openId, setOpenId] = useState(null); // sonuçları açık proje
  const [error, setError] = useState(null);

  function reload() {
    api("/api/user/projects").then(setProjects).catch(setError);
  }

  useEffect(reload, []);

  async function analyze(p) {
    try {
      await api(`/api/user/projects/${p.id}/analyze`, { method: "POST" });
      setOpenId(p.id);
      reload();
    } catch (err) {
      setError(err);
    }
  }

  async function remove(p) {
    if (!window.confirm(`${p.project_name} bağlantısı silinsin mi?`)) return;
    try {
      await api(`/api/user/projects/${p.id}`, { method: "DELETE" });
      reload();
    } catch (err) {
      setError(err);
    }
  }

  if (error) return <div className="error-box">Hata: {error.message}</div>;

  return (
    <>
      <section className="section">
        <h2>Bağlı projelerim</h2>
        {projects.length === 0 ? (
          <p className="desc">Henüz bağlı proje yok. Aşağıdan ekleyebilirsiniz.</p>
        ) : (
          <table className="quality">
            <thead>
              <tr>
                <th>Proje</th><th>Kaynak</th><th>URL</th>
                <th>Durum</th><th>Analiz</th><th>Son çalıştırma</th><th></th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>{p.project_name}</td>
                  <td>{p.source_type}</td>
                  <td>{p.source_url}</td>
                  <td>{p.connected ? "bağlı" : <span className="na">token yok</span>}</td>
                  <td>
                    {p.last_status ? STATUS_TEXT[p.last_status] : <span className="na">yok</span>}
                  </td>
                  <td>
                    {p.last_run_at ? new Date(p.last_run_at).toLocaleString() : (
                      <span className="na">henüz yok</span>
                    )}
                  </td>
                  <td>
                    <button onClick={() => analyze(p)}>Analiz et</button>{" "}
                    <button onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                      {openId === p.id ? "Sonuçları gizle" : "Sonuçlar"}
                    </button>{" "}
                    <button onClick={() => remove(p)}>Sil</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {openId != null && <AnalysisResults projectId={openId} />}
      <AddProjectForm onAdded={reload} />
    </>
  );
}
