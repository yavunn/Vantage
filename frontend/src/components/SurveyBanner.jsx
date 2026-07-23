// Ana ekranda davetkâr, kapatılabilir anket hatırlatması. Yalnız açık +
// doldurulmamış anket varken görünür (App karar verir). Tek tıkla forma gider.
export default function SurveyBanner({ onOpen, onDismiss }) {
  return (
    <div className="survey-banner" role="status">
      <span className="survey-banner-icon" aria-hidden="true">📝</span>
      <div className="survey-banner-text">
        <strong>İki haftalık memnuniyet anketin hazır</strong>
        <span>2 dakika · tamamen anonim · görüşün bize yol gösterir</span>
      </div>
      <button className="login-btn survey-banner-cta" onClick={onOpen}>Doldur</button>
      <button className="survey-banner-x" onClick={onDismiss} aria-label="Kapat" title="Şimdilik gizle">✕</button>
    </div>
  );
}
