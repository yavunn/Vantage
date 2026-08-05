import { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";
import { toast } from "../toast.js";
import CodeHealthCard from "./CodeHealthCard.jsx";
import CodeHealthDrilldown from "./CodeHealthDrilldown.jsx";
import { useT } from "../i18n.jsx";

// Kullanıcının KENDİ kodunun AI sağlığı. Kıyas yok — kendi kodunun geri
// bildirimi. "Kodumu analiz et" ile isteğe bağlı çalıştırır.
export default function MyCodeHealth({ user }) {
  const t = useT();
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
    toast(t("Kodun analiz ediliyor…"), "info");
    try {
      const r = await apiPost("/api/me/code-analysis/run", {});
      const m = r.status === "ok"
        ? t("Analiz tamam: {n} yeni, {c} önbellek.", { n: r.analyzed, c: r.cached })
        : r.note || JSON.stringify(r);
      const sev = r.status === "ok" ? "ok" : (r.status === "error" ? "error" : "info");
      setMsg(m); toast(m, sev);
      load();
    } catch (e) { setError(e); toast(e.message, "error"); } finally { setBusy(false); }
  }

  if (!linked) {
    return (
      <section className="section">
        <h2>{t("Kodum")}</h2>
        <p className="desc">{t("Hesabınız bir geliştiriciye bağlı değil — kişisel kod analizi yok.")}</p>
      </section>
    );
  }

  return (
    <section className="section">
      <h2>{t("Kodum — AI kod sağlığı")}</h2>
      <p className="desc">
        {t("Yalnızca sizin kodunuz (git yazarı = siz). Kıyaslama yok; kendi kodunuzun yapıcı geri bildirimi. Sonuçlar yalnızca size (ve yöneticinize) açıktır.")}
      </p>
      {error && <p className="error-inline">{error.message}</p>}
      {msg && <p className="ok-inline">{msg}</p>}
      <div className="cards" style={{ maxWidth: 320 }}>
        <CodeHealthCard health={health} onClick={() => setDrill(true)} />
      </div>
      <div className="ca-row">
        <button className="mini" onClick={runNow} disabled={busy}>
          {busy ? t("Analiz ediliyor…") : t("Kodumu analiz et")}
        </button>
      </div>
      {drill && (
        <CodeHealthDrilldown
          path="/api/me/code-health/breakdown"
          title={t("Kodum — dikkat isteyen dosyalar")}
          onClose={() => setDrill(false)}
        />
      )}
    </section>
  );
}
