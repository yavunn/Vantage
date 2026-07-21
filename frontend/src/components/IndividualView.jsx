// Bireysel görünüm (Faz 4): yalnızca kişinin kendisi + yöneticisi erişebilir
// (sunucu tarafında zorlanır). Kıyas SADECE kişinin kendi geçmişiyle yapılır —
// başka kişiyle kıyas eden hiçbir öğe bu ekranda yoktur ve API'de de yoktur.
import { useEffect, useState } from "react";
import { api, oneOnOne } from "../api.js";
import MetricCard from "./MetricCard.jsx";
import Modal from "./Modal.jsx";

export default function IndividualView({ devId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [prep, setPrep] = useState(null); // 1:1 hazırlık özeti

  useEffect(() => {
    setData(null);
    setError(null);
    setPrep(null);
    api(`/api/developers/${devId}/summary`)
      .then(setData)
      .catch((e) => setError(e));
  }, [devId]);

  if (error)
    return (
      <div className="error-box">
        {error.status === 403 || error.status === 401
          ? `Erişim yok: ${error.message}`
          : `Hata: ${error.message}`}
      </div>
    );
  if (!data) return <p className="desc">Yükleniyor…</p>;

  return (
    <div>
      <div className="indiv-head">
        <button className="mini" onClick={() => oneOnOne(devId).then(setPrep).catch((e) => setError(e))}>
          1:1 hazırlık özeti
        </button>
      </div>
      <div className="cards">
        {data.metrics.map((m) => (
          <MetricCard key={m.key} metric={m} previous={m.previous_value} />
        ))}
      </div>
      <div className="note">{data.note}</div>

      {prep && (
        <Modal title={`1:1 hazırlık — ${prep.developer.display_name}`} onClose={() => setPrep(null)}>
          <div className="prep-modal">
            {prep.talking_points.map((sec) => (
              <div key={sec.section} className={`prep-section tone-${sec.tone}`}>
                <h3>{sec.section}</h3>
                <ul>
                  {sec.items.map((it, i) => <li key={i}>{it}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}
