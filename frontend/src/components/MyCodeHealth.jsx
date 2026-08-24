import { useEffect, useState } from "react";
import { api, apiPost } from "../api.js";
import { toast } from "../toast.js";
import CodeHealthCard from "./CodeHealthCard.jsx";
import Yukleniyor from "./Yukleniyor.jsx";
import CodeHealthDrilldown from "./CodeHealthDrilldown.jsx";
import { useT } from "../i18n.jsx";

// Kullanıcının KENDİ kodunun AI sağlığı. Kıyas yok — kendi kodunun geri
// bildirimi. "Kodumu analiz et" ile isteğe bağlı çalıştırır.

const SINIF = { ok: "ok-inline", warn: "warn-inline", error: "error-inline" };

/** Sunucunun DURUM KODUNU kullanıcıya dönük mesaja çevirir.
 *
 * Ham `note` alanı geliştiriciye bakar ("developer.external_ids['git']",
 * "sources.git.repos altında yerel 'path'…") ve arayüzde gösterilmez: kullanıcı
 * ne olduğunu ve ne yapacağını okumalı, veritabanı alan adını değil.
 *
 * `error` istisna: `classify_error` orada zaten kullanıcıya dönük NET bir sebep
 * üretiyor (bakiye yetersiz, anahtar geçersiz, hız limiti) — onu göstermek en
 * yararlısı ve durumu istemcide tahmin etmek mümkün değil.
 *
 * Tanınmayan durumda mesaj GENEL kalır; eskiden `JSON.stringify(r)` ile ham
 * yanıt ekrana dökülüyordu. */
function durumMesaji(t, r) {
  switch (r.status) {
    case "ok":
      return { sev: "ok", text: t("Analiz tamam: {n} yeni, {c} önbellek.", { n: r.analyzed, c: r.cached }) };
    case "no_identity":
      return { sev: "warn", text: t("code.noIdentity") };
    case "disabled":
      return { sev: "warn", text: t("code.disabled") };
    case "no_source":
      return { sev: "warn", text: t("code.noSource") };
    case "error":
      return { sev: "error", text: r.note || t("code.failed") };
    default:
      return { sev: "warn", text: t("code.failed") };
  }
}

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
