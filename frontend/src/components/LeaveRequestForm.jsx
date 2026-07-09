// Self-servis izin talebi + kişinin KENDİ talep listesi (Faz 5).
// Çalışan ani izin girer; yalnız kendi taleplerini görür (sunucu zorlar).
import { useEffect, useState } from "react";
import { api } from "../api.js";

const LEAVE_TYPES = [
  { key: "yillik", label: "Yıllık izin" },
  { key: "hastalik", label: "Hastalık" },
  { key: "rapor", label: "Rapor" },
];
const STATUS_TEXT = {
  pending: "bekliyor",
  approved: "onaylı",
  rejected: "reddedildi",
};

export default function LeaveRequestForm() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [leaveType, setLeaveType] = useState("yillik");
  const [description, setDescription] = useState("");
  const [mine, setMine] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function reload() {
    api("/api/user/leave-requests").then(setMine).catch(setError);
  }
  useEffect(reload, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/user/leave-requests", {
        method: "POST",
        body: {
          start_date: startDate,
          end_date: endDate,
          leave_type: leaveType,
          description: description || null,
        },
      });
      setStartDate("");
      setEndDate("");
      setDescription("");
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="section" onSubmit={submit} style={{ maxWidth: 480 }}>
        <h2>İzin talebi</h2>
        <p className="desc">
          İzin bir bağlamdır, ceza değildir: onaylanan günler metrik
          penceresinden düşülür — izindeki düşük aktivite anomali sayılmaz.
        </p>
        <div style={{ display: "grid", gap: 8 }}>
          <label>
            Başlangıç{" "}
            <input type="date" value={startDate}
                   onChange={(e) => setStartDate(e.target.value)} required />
          </label>
          <label>
            Bitiş{" "}
            <input type="date" value={endDate}
                   onChange={(e) => setEndDate(e.target.value)} required />
          </label>
          <select value={leaveType} onChange={(e) => setLeaveType(e.target.value)}>
            {LEAVE_TYPES.map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </select>
          <input
            placeholder="Açıklama (isteğe bağlı, yalnız siz ve onaylayanınız görür)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={1000}
          />
          <button type="submit" disabled={busy}>
            {busy ? "Gönderiliyor…" : "Talep gönder"}
          </button>
          {error && <div className="error-box">Hata: {error.message}</div>}
        </div>
      </form>

      <section className="section">
        <h2>Taleplerim</h2>
        {mine.length === 0 ? (
          <p className="desc">Henüz izin talebiniz yok.</p>
        ) : (
          <table className="quality">
            <thead>
              <tr>
                <th>Başlangıç</th><th>Bitiş</th><th>Tür</th><th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {mine.map((lv) => (
                <tr key={lv.id}>
                  <td>{lv.start_date}</td>
                  <td>{lv.end_date}</td>
                  <td>{lv.leave_type}</td>
                  <td>{STATUS_TEXT[lv.status] ?? lv.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
