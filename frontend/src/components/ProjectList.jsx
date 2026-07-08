// Kullanıcının bağlı projeleri (Faz 3). Token asla gösterilmez —
// sunucu zaten döndürmez; yalnız "bağlı" durumu ve son çalıştırma görünür.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import AddProjectForm from "./AddProjectForm.jsx";

export default function ProjectList() {
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState(null);

  function reload() {
    api("/api/user/projects").then(setProjects).catch(setError);
  }

  useEffect(reload, []);

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
                <th>Durum</th><th>Son çalıştırma</th><th></th>
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
                    {p.last_run_at ? new Date(p.last_run_at).toLocaleString() : (
                      <span className="na">henüz yok</span>
                    )}
                  </td>
                  <td>
                    <button onClick={() => remove(p)}>Sil</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <AddProjectForm onAdded={reload} />
    </>
  );
}
