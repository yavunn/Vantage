import { useEffect, useState } from "react";
import { api } from "../api.js";
import Modal from "./Modal.jsx";
import { useT } from "../i18n.jsx";

// Kod sağlığı drill-down: en çok dikkat isteyen dosyalar + AI önerileri.
// KİŞİ İSMİ YOK — yalnızca dosya/modül ve yapıcı öneriler.
const STATUS_COLOR = {
  green: "var(--status-good)",
  yellow: "var(--status-warning)",
  red: "var(--status-critical)",
  insufficient_data: "var(--status-neutral)",
};

// path: breakdown endpoint'i (takım / kendi / kişi). title: modal başlığı.
export default function CodeHealthDrilldown({ path, title, onClose }) {
  const t = useT();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    api(path)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, [path]);

  return (
    <Modal title={title || t("Kod Sağlığı — dikkat isteyen bölümler")} onClose={onClose}>
      <p className="desc">
        {t("Dosya/modül düzeyinde AI analizi. En düşük skorlu dosyalar üstte; öneriler yapıcı ve kişi suçlamayan dille.")}
      </p>
      {error && <p className="desc">{t("Yüklenemedi: {msg}", { msg: error.message })}</p>}
      {!data && !error && <p className="desc">{t("Yükleniyor…")}</p>}
      {data && data.rows.length === 0 && (
        <p className="desc">{t("Henüz analiz yok. Uydurma skor gösterilmez.")}</p>
      )}
      {data && data.rows.length > 0 && (
        <div className="drill-scroll">
          {data.rows.map((f, i) => (
            <div key={i} className="ch-file">
              <div className="ch-file-head">
                <span className="dot" style={{ background: STATUS_COLOR[f.status] }} aria-hidden="true" />
                <code>{f.file_path}</code>
                <span className="ch-score">{f.composite}/100</span>
              </div>
              {f.summary && <p className="desc" style={{ margin: "4px 0" }}>{f.summary}</p>}
              <div className="ch-dims">
                {Object.entries(f.dimensions).map(([label, v]) => (
                  <span key={label} className={v != null && v <= 50 ? "low" : ""}>
                    {label} {v ?? "–"}
                  </span>
                ))}
              </div>
              {f.suggestions?.length > 0 && (
                <ul className="ch-sugg">
                  {f.suggestions.map((s, j) => <li key={j}>{s}</li>)}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
