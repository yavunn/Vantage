import { useT } from "../i18n.jsx";

/**
 * Bekleme göstergesi — tek kalıp.
 *
 * NEDEN BİLEŞEN: "yükleniyor" hâli beş panelde ya hiç yoktu ya da her birinde
 * farklı görünüyordu (kimi tek satır gri yazı, kimi hiçbir şey). Boş liste ile
 * "henüz gelmedi" aynı göründüğü sürece kullanıcı "tıkladım, bir şey oldu mu?"
 * diye düşünür.
 *
 * İki biçim var, çünkü iki farklı soru cevaplıyorlar:
 *   satır  → "burada bir liste olacak" (birkaç çizgi, listenin şekli)
 *   kart   → "burada kartlar olacak"   (kart ızgarasının şekli)
 *
 * Ekran okuyucu için `aria-busy` + gizli bir metin; görme engelli kullanıcı da
 * beklediğini bilir.
 */
export default function Yukleniyor({ bicim = "satir", adet = 3 }) {
  const t = useT();
  const etiket = t("Yükleniyor…");

  if (bicim === "kart") {
    return (
      <div className="cards" aria-busy="true" aria-label={etiket}>
        {Array.from({ length: adet }).map((_, i) => (
          <div key={i} className="card skeleton">
            <div className="sk-line sk-title" />
            <div className="sk-line sk-value" />
            <div className="sk-line short" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="yukleniyor-satirlar" aria-busy="true" aria-label={etiket}>
      {Array.from({ length: adet }).map((_, i) => (
        <div key={i} className="sk-line" />
      ))}
    </div>
  );
}
