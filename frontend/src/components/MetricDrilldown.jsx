import { useEffect, useState } from "react";
import { api } from "../api.js";
import Modal from "./Modal.jsx";

// Drill-down: bir metriğin altındaki ham kayıtlar. Sayı gökten inmiyor —
// hangi iş/PR/commit bu değeri oluşturuyor şeffaf görünsün.
export default function MetricDrilldown({ teamId, metricKey, metricName, days, onClose }) {
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
    <Modal title={`${metricName} — detay (${days} gün)`} onClose={onClose}>
      {error && <p className="desc">Detay yüklenemedi: {error.message}</p>}
      {!data && !error && <p className="desc">Yükleniyor…</p>}
      {data && data.rows.length === 0 && (
        <p className="desc">
          Bu aralıkta bu metriği oluşturan kayıt yok. Metrik "veri yetersiz"
          gösteriyorsa bu beklenen durumdur — uydurma satır eklenmez.
        </p>
      )}
      {data && data.rows.length > 0 && (
        <>
          <p className="desc">{data.count} kayıt bu metriği oluşturuyor:</p>
          <div className="drill-scroll">
            <table className="drill-table">
              <thead>
                <tr><th>Kayıt</th><th>Bağlam</th><th className="num">Değer</th><th>Tarih</th></tr>
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
