import { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";
import { toast } from "../toast.js";
import CodeHealthCard from "./CodeHealthCard.jsx";
import Yukleniyor from "./Yukleniyor.jsx";
import CodeHealthDrilldown from "./CodeHealthDrilldown.jsx";
import { useT } from "../i18n.jsx";
import { durumMesaji } from "../codeStatus.js";

// Kullanıcının KENDİ kodunun AI sağlığı. Kıyas yok — kendi kodunun geri
// bildirimi. "Kodumu analiz et" ile isteğe bağlı çalıştırır.

const SINIF = { ok: "ok-inline", warn: "warn-inline", error: "error-inline" };

export default function MyCodeHealth({ user }) {
  const t = useT();
  const [health, setHealth] = useState(null);
  const [drill, setDrill] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  const linked = user?.developer_id != null;

  // `health === null` hem "yukleniyor" hem "yuklenemedi" demekti; ikisi ayri
  // sey - biri beklemeyi, oteki bir sorunu anlatir.
  const [yukleniyor, setYukleniyor] = useState(true);

  function load() {
    if (!linked) return;
    setYukleniyor(true);
    api("/api/me/code-health")
      .then(setHealth)
      .catch(() => setHealth(null))
      .finally(() => setYukleniyor(false));
  }
  useEffect(load, [linked]);

  async function runNow() {
    setBusy(true); setMsg(null); setError(null);
    toast(t("Kodun analiz ediliyor…"), "info");
    try {
      const r = await apiPost("/api/me/code-analysis/run", {});
      const { sev, text } = durumMesaji(t, r);
      setMsg({ sev, text });
      // Toast yalnız ok | error | info bilir; "warn" orada bilgi tonuna düşer.
      toast(text, sev === "warn" ? "info" : sev);
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
    <section className="section my-code-health">
      <h2>{t("Kodum — AI kod sağlığı")}</h2>
      <p className="desc">
        {t("Yalnızca sizin kodunuz (git yazarı = siz). Kıyaslama yok; kendi kodunuzun yapıcı geri bildirimi. Sonuçlar yalnızca size (ve yöneticinize) açıktır.")}
      </p>
      {error && <p className="error-inline">{error.message}</p>}
      {msg && <p className={SINIF[msg.sev]}>{msg.text}</p>}
      {yukleniyor ? (
        <Yukleniyor bicim="kart" adet={1} />
      ) : health ? (
        <div className="cards">
          <CodeHealthCard health={health} onClick={() => setDrill(true)} />
        </div>
      ) : (
        <p className="empty-note">{t("Kod sağlığı bilgisi alınamadı. Aşağıdan analizi çalıştırabilirsiniz.")}</p>
      )}
      <div className="ca-row">
        <button className="login-btn" onClick={runNow} disabled={busy}>
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
