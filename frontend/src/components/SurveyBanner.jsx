import { useT } from "../i18n.jsx";

// Ana ekranda davetkâr, kapatılabilir anket hatırlatması. Yalnız açık +
// doldurulmamış anket varken görünür (App karar verir). Tek tıkla forma gider.
export default function SurveyBanner({ onOpen, onDismiss }) {
  const t = useT();
  return (
    <div className="survey-banner" role="status">
      <span className="survey-banner-icon" aria-hidden="true">📝</span>
      <div className="survey-banner-text">
        <strong>{t("İki haftalık memnuniyet anketin hazır")}</strong>
        <span>{t("2 dakika · tamamen anonim · görüşün bize yol gösterir")}</span>
      </div>
      <button className="login-btn survey-banner-cta" onClick={onOpen}>{t("Doldur")}</button>
      <button className="survey-banner-x" onClick={onDismiss} aria-label={t("Kapat")} title={t("Şimdilik gizle")}>✕</button>
    </div>
  );
}
