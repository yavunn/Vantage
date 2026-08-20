import { useState } from "react";
import { MIN_PASSWORD_LENGTH, changePassword } from "../api.js";
import Modal from "./Modal.jsx";
import PasswordField from "./PasswordField.jsx";
import { useT } from "../i18n.jsx";

// Çalışanın kendi parolasını değiştirmesi.
export default function ChangePassword({ onClose }) {
  const t = useT();
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (nw.length < MIN_PASSWORD_LENGTH) {
      setError(t("Yeni parola en az {n} karakter olmalı", { n: MIN_PASSWORD_LENGTH }));
      return;
    }
    if (nw !== nw2) {
      setError(t("Yeni parolalar eşleşmiyor"));
      return;
    }
    try {
      await changePassword(cur, nw);
      setDone(true);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Modal title={t("Parola değiştir")} onClose={onClose}>
      {done ? (
        <>
          <div className="admin-ok">{t("Parola güncellendi.")}</div>
          <button className="login-btn" onClick={onClose}>{t("Kapat")}</button>
        </>
      ) : (
        <form onSubmit={submit}>
          <PasswordField
            label={t("Mevcut parola")}
            autoComplete="current-password"
            value={cur} onChange={(e) => setCur(e.target.value)} required
          />
          <PasswordField
            label={t("Yeni parola")}
            autoComplete="new-password"
            value={nw} onChange={(e) => setNw(e.target.value)} minLength={MIN_PASSWORD_LENGTH} required
          />
          <PasswordField
            label={t("Yeni parola (tekrar)")}
            autoComplete="new-password"
            value={nw2} onChange={(e) => setNw2(e.target.value)} minLength={MIN_PASSWORD_LENGTH} required
          />
          {error && <div className="login-error">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="mini ghost" onClick={onClose}>{t("Vazgeç")}</button>
            <button type="submit" className="login-btn">{t("Kaydet")}</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
