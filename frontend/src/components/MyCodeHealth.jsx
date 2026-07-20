import { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";
import CodeHealthCard from "./CodeHealthCard.jsx";
import CodeHealthDrilldown from "./CodeHealthDrilldown.jsx";

// Kullanıcının KENDİ kodunun AI sağlığı. Kıyas yok — kendi kodunun geri
// bildirimi. "Kodumu analiz et" ile isteğe bağlı çalıştırır.
export default function MyCodeHealth({ user }) {
  const [health, setHealth] = useState(null);
  const [drill, setDrill] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  const linked = user?.developer_id != null;

  function load() {
    if (!linked) return;
    api("/api/me/code-health").then(setHealth).catch(() => setHealth(null));
  }
  useEffect(load, [linked]);

  async function runNow() {
    setBusy(true); setMsg(null); setError(null);
    try {
      const r = await apiPost("/api/me/code-analysis/run", {});
      setMsg(
        r.status === "ok"
          ? `Analiz tamam: ${r.analyzed} yeni, ${r.cached} önbellek.`
          : r.note || JSON.stringify(r)
      );
      load();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  if (!linked) {
    return (
      <section className="section">
        <h2>Kodum</h2>
        <p className="desc">Hesabınız bir geliştiriciye bağlı değil — kişisel kod analizi yok.</p>
      </section>
    );
  }

  return (
    <section className="section">
      <h2>Kodum — AI kod sağlığı</h2>
      <p className="desc">
        Yalnızca sizin kodunuz (git yazarı = siz). Kıyaslama yok; kendi kodunuzun
        yapıcı geri bildirimi. Sonuçlar yalnızca size (ve yöneticinize) açıktır.
      </p>
      {error && <p className="error-inline">{error.message}</p>}
      {msg && <p className="ok-inline">{msg}</p>}
      <div className="cards" style={{ maxWidth: 320 }}>
        <CodeHealthCard health={health} onClick={() => setDrill(true)} />
      </div>
      <div className="ca-row">
        <button className="mini" onClick={runNow} disabled={busy}>
          {busy ? "Analiz ediliyor…" : "Kodumu analiz et"}
        </button>
      </div>
      {drill && (
        <CodeHealthDrilldown
          path="/api/me/code-health/breakdown"
          title="Kodum — dikkat isteyen dosyalar"
          onClose={() => setDrill(false)}
        />
      )}
    </section>
  );
}
