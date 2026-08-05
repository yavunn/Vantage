import { useEffect, useState } from "react";
import { decidePasswordRequest, listPasswordRequests } from "../api.js";
import { useLang } from "../i18n.jsx";

// Giriş ekranından gelen "şifremi unuttum" talepleri.
//
// NEDEN E-POSTALI LİNK YOK: kurulum on-prem ve mail altyapısı yok; sıfırlama
// linki göndermek var olmayan bir SMTP'yi varmış gibi kurgulamak olurdu.
//
// TASARIM KARARI — bu liste PAROLA DEĞİŞTİRMEZ. Talebi kapatmak yalnızca
// "ilgilendim" demektir; sıfırlama, hesap satırındaki kendi akışında kalır
// (geçici parola + ilk girişte zorunlu değiştirme). İki işi tek düğmeye
// bindirmek, yönetici "listeyi temizliyorum" derken farkında olmadan parola
// sıfırlamasına yol açardı.
export default function PasswordRequests() {
  const { t, lang } = useLang();
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  function refresh() {
    listPasswordRequests("pending")
      .then(setRows)
      .catch((e) => setError(e.message));
  }
  useEffect(refresh, []);

  async function decide(id, status) {
    setBusy(id);
    setError(null);
    try {
      await decidePasswordRequest(id, status);
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="admin-block">
      <h3>
        {t("reqs.title")}
        {rows.length > 0 && <span className="role-badge">{rows.length}</span>}
      </h3>
      <p className="desc">{t("reqs.lede")}</p>
      {error && <div className="login-error">{error}</div>}

      {rows.length === 0 ? (
        <p className="desc">{t("reqs.empty")}</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>{t("reqs.email")}</th>
              <th>{t("reqs.account")}</th>
              <th>{t("reqs.note")}</th>
              <th>{t("reqs.when")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.email}</td>
                <td>
                  {/* Hesabı olmayan e-posta da bilgidir: ya adres yanlış
                      yazılmıştır ya da hesap hiç açılmamıştır. */}
                  {r.account_exists ? t("reqs.accountYes") : t("reqs.accountNo")}
                </td>
                <td>{r.note || "—"}</td>
                <td>
                  {r.created_at
                    ? new Date(r.created_at).toLocaleString(lang === "en" ? "en-GB" : "tr-TR")
                    : "—"}
                </td>
                <td>
                  <button
                    className="mini"
                    onClick={() => decide(r.id, "resolved")}
                    disabled={busy === r.id}
                  >
                    {t("reqs.resolve")}
                  </button>{" "}
                  <button
                    className="mini ghost"
                    onClick={() => decide(r.id, "dismissed")}
                    disabled={busy === r.id}
                  >
                    {t("reqs.dismiss")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
