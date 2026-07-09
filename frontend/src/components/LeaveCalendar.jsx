// Takım müsaitlik takvimi (Faz 5). Kim ne zaman yok — operasyonel bilgi,
// performans kıyası DEĞİL. İzin sebebi/türü gösterilmez; anonim modda isim
// maskeli (sunucu zaten öyle döndürür).
import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function LeaveCalendar({ teamId }) {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    const q = teamId != null ? `?team_id=${teamId}` : "";
    api(`/api/leave/calendar${q}`).then(setEntries).catch(setError);
  }, [teamId]);

  if (error) return <div className="error-box">Hata: {error.message}</div>;

  return (
    <section className="section">
      <h2>İzin takvimi (müsaitlik)</h2>
      <p className="desc">
        Yalnız kimin ne zaman müsait olmadığını gösterir; izin sebebi gizlidir.
      </p>
      {entries.length === 0 ? (
        <p className="desc">Bu dönemde onaylı izin yok.</p>
      ) : (
        <table className="quality">
          <thead>
            <tr><th>Kişi</th><th>Başlangıç</th><th>Bitiş</th></tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i}>
                <td>{e.developer}</td>
                <td>{e.start_date}</td>
                <td>{e.end_date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
