// Proje bağlama formu (Faz 3). Token yalnız bu istekte gider; sunucu
// şifreli saklar, bir daha hiçbir response'ta dönmez. Form submit sonrası
// token alanını hemen temizler.
import { useState } from "react";
import { api } from "../api.js";

const SOURCE_TYPES = ["github", "gitlab", "jira", "trello"];

export default function AddProjectForm({ onAdded }) {
  const [projectName, setProjectName] = useState("");
  const [sourceType, setSourceType] = useState("github");
  const [sourceUrl, setSourceUrl] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/user/projects", {
        method: "POST",
        body: {
          project_name: projectName,
          source_type: sourceType,
          source_url: sourceUrl,
          token,
        },
      });
      setProjectName("");
      setSourceUrl("");
      setToken("");
      onAdded();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="section" onSubmit={submit} style={{ maxWidth: 480 }}>
      <h2>Proje bağla</h2>
      <div style={{ display: "grid", gap: 8 }}>
        <input
          placeholder="Proje adı"
          value={projectName}
          onChange={(e) => setProjectName(e.target.value)}
          required
        />
        <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
          {SOURCE_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          placeholder="Kaynak URL (örn. https://github.com/org/repo)"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Erişim token'ı (şifreli saklanır, geri gösterilmez)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          required
          autoComplete="off"
        />
        <button type="submit" disabled={busy}>
          {busy ? "Bağlanıyor…" : "Bağla"}
        </button>
        {error && <div className="error-box">Hata: {error.message}</div>}
      </div>
    </form>
  );
}
