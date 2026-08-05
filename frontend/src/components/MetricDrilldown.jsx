import { useEffect, useState } from "react";
import { api } from "../api.js";
import Modal from "./Modal.jsx";
import { useT } from "../i18n.jsx";

// Drill-down: bir metriğin altındaki ham kayıtlar. Sayı gökten inmiyor —
// hangi iş/PR/commit bu değeri oluşturuyor şeffaf görünsün.
export default function MetricDrilldown({ teamId, metricKey, metricName, days, onClose }) {
  const t = useT();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    api(`/api/teams/${teamId}/metric/${metricKey}/breakdown?days=${days}`)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, [teamId, metricKey, days]);

  return (
    <Modal title={t("{name} — detay ({n} gün)", { name: metricName, n: days })} onClose={onClose}>
      {error && <p className="desc">{t("Detay yüklenemedi: {msg}", { msg: error.message })}</p>}
      {!data && !error && <p className="desc">{t("Yükleniyor…")}</p>}
      {data && data.rows.length === 0 && (
        <p className="desc">
          {t('Bu aralıkta bu metriği oluşturan kayıt yok. Metrik "veri yetersiz" gösteriyorsa bu beklenen durumdur — uydurma satır eklenmez.')}
        </p>
      )}
      {data && data.rows.length > 0 && (
        <>
          <p className="desc">{t("{n} kayıt bu metriği oluşturuyor:", { n: data.count })}</p>
          <div className="drill-scroll">
            <table className="drill-table">
              <thead>
                <tr><th>{t("Kayıt")}</th><th>{t("Bağlam")}</th><th className="num">{t("Değer")}</th><th>{t("Tarih")}</th></tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.label}</td>
                    <td className="muted">{r.detail}</td>
                    <td className="num">
                      {r.value == null ? "–" : `${r.value}${r.unit ? " " + r.unit : ""}`}
                    </td>
                    <td className="muted">{r.date || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  );
}
