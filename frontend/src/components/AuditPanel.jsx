import { useEffect, useState } from "react";
import { downloadFile, listAudit } from "../api.js";
import { toast } from "../toast.js";
import { useLang, useT } from "../i18n.jsx";

const ACTION_TR = {
  create_employee: "Çalışan oluşturuldu",
  update_employee: "Hesap güncellendi",
  delete_employee: "Hesap silindi",
  reset_password: "Parola sıfırlandı",
};

// Yönetici işlemlerinin denetim kaydı. Kim, neyi, kime, ne zaman.
// Hassas içerik (parola) saklanmaz — yalnız eylem + hedef + meta.
export default function AuditPanel() {
  const t = useT();
  const { lang } = useLang();
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    listAudit().then(setRows).catch((e) => setError(e.message));
  }, []);

  const filtered = rows.filter((r) => {
    if (!q.trim()) return true;
    const s = q.trim().toLowerCase();
    return (
      (r.actor_email || "").toLowerCase().includes(s) ||
      (r.target_email || "").toLowerCase().includes(s) ||
      t(ACTION_TR[r.action] || r.action).toLowerCase().includes(s)
    );
  });

  function fmtDetail(d) {
    if (!d) return "";
    return Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(" · ");
  }

  return (
    <section className="section">
      <div className="section-head">
        <h2>{t("Denetim kaydı ({n})", { n: filtered.length })}</h2>
        <span className="input-with-btn">
          <input className="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Eylem, aktör veya hedefe göre ara…")} />
          <button className="mini" onClick={() => downloadFile("/api/admin/audit.csv", "denetim-kaydi.csv").catch((e) => toast(e.message, "error"))}>{t("CSV indir")}</button>
        </span>
      </div>
      <p className="desc">{t("Yönetici işlemleri burada kayıt altındadır (hesap verebilirlik). Parola gibi hassas içerik saklanmaz.")}</p>
      {error && <div className="login-error">{error}</div>}
      <table className="quality">
        <thead>
          <tr>
            <th>{t("Zaman")}</th>
            <th>{t("Aktör")}</th>
            <th>{t("Eylem")}</th>
            <th>{t("Hedef")}</th>
            <th>{t("Ayrıntı")}</th>
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 ? (
            <tr><td colSpan={5}><span className="na">{t("Kayıt yok")}</span></td></tr>
          ) : filtered.map((r) => (
            <tr key={r.id}>
              <td>{r.created_at ? new Date(r.created_at).toLocaleString(lang === "en" ? "en-US" : "tr-TR") : ""}</td>
              <td>{r.actor_email || "—"}</td>
              <td>{t(ACTION_TR[r.action]) || r.action}</td>
              <td>{r.target_email || "—"}</td>
              <td>{fmtDetail(r.detail) || <span className="na">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
