// İzin onay listesi (Faz 5) — yalnız admin ya da takım yöneticisi içindir.
// Yetkisiz kullanıcıda (403) bileşen kendini gizler; sunucu tek yetki noktasıdır.
import { useEffect, useState } from "react";
import { api } from "../api.js";

const STATUS_TEXT = {
  pending: "bekliyor",
  approved: "onaylı",
  rejected: "reddedildi",
};

export default function LeaveApprovalList() {
  const [requests, setRequests] = useState([]);
  const [allowed, setAllowed] = useState(true);
  const [error, setError] = useState(null);

  function reload() {
    api("/api/admin/leave-requests")
      .then((r) => {
        setRequests(r);
        setAllowed(true);
      })
      .catch((err) => {
        if (err.status === 403) setAllowed(false); // yönetici/admin değil: gizle
        else setError(err);
      });
  }
  useEffect(reload, []);

  async function decide(lv, decision) {
    try {
      await api(`/api/admin/leave-requests/${lv.id}`, {
        method: "PUT",
        body: { decision },
      });
      reload();
    } catch (err) {
      setError(err);
    }
  }

  if (!allowed) return null;
  if (error) return <div className="error-box">Hata: {error.message}</div>;

  return (
    <section className="section">
      <h2>İzin onayları</h2>
      <p className="desc">
        Yalnız kendi takımınızın (admin iseniz tüm) taleplerini görürsünüz.
        Onaylanan izin, kişinin metrik penceresinden düşülür.
      </p>
      {requests.length === 0 ? (
        <p className="desc">Bekleyen talep yok.</p>
      ) : (
        <table className="quality">
          <thead>
            <tr>
              <th>Kişi</th><th>Başlangıç</th><th>Bitiş</th><th>Tür</th>
              <th>Açıklama</th><th>Durum</th><th></th>
            </tr>
          </thead>
          <tbody>
            {requests.map((lv) => (
              <tr key={lv.id}>
                <td>{lv.requester_email ?? `#${lv.user_id}`}</td>
                <td>{lv.start_date}</td>
                <td>{lv.end_date}</td>
                <td>{lv.leave_type}</td>
                <td>{lv.description || <span className="na">—</span>}</td>
                <td>{STATUS_TEXT[lv.status] ?? lv.status}</td>
                <td>
                  {lv.status === "pending" ? (
                    <>
                      <button onClick={() => decide(lv, "approve")}>Onayla</button>{" "}
                      <button onClick={() => decide(lv, "reject")}>Reddet</button>
                    </>
                  ) : (
                    <span className="na">karar verildi</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
