// Bireysel görünüm (Faz 4): yalnızca kişinin kendisi + yöneticisi erişebilir
// (sunucu tarafında zorlanır). Kıyas SADECE kişinin kendi geçmişiyle yapılır —
// başka kişiyle kıyas eden hiçbir öğe bu ekranda yoktur ve API'de de yoktur.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import MetricCard from "./MetricCard.jsx";

export default function IndividualView({ devId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
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
      <div className="cards">
        {data.metrics.map((m) => (
          <MetricCard key={m.key} metric={m} previous={m.previous_value} />
        ))}
      </div>
      <div className="note">{data.note}</div>
    </div>
  );
}
