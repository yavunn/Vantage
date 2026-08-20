import { useState } from "react";
import { MIN_PASSWORD_LENGTH, changePassword } from "../api.js";
import { useT } from "../i18n.jsx";
import PasswordField from "./PasswordField.jsx";

// İlk giriş / admin sıfırlaması sonrası zorunlu parola değiştirme.
// Kapatılamaz — kullanıcı yeni parola belirlemeden panoya geçemez.
export default function ForceChangePassword({ onDone, onLogout }) {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

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
    setBusy(true);
    try {
      // Backend doğrulaması için geçici (mevcut) parolayı isteriz.
      await changePassword(current, nw);
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-aside">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 120 40" width="120" height="40">
              <polyline
                className="ecg"
                points="0,20 22,20 30,20 36,6 44,34 52,20 60,20 66,14 72,26 78,20 120,20"
                fill="none" stroke="currentColor" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
          </span>
          <h1 className="brand-name">Vantage</h1>
        </div>
        <p className="brand-tagline">{t("Güvenlik adımı")}</p>
        <p className="brand-copy">
          {t("Hesabına yönetici tarafından geçici bir parola atandı. Devam etmeden önce kendine ait yeni bir parola belirlemelisin.")}
        </p>
      </div>

      <div className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <h2>{t("Yeni parola belirle")}</h2>
          <p className="login-sub">{t("Bu adım zorunludur.")}</p>
          <PasswordField
            label={t("Geçici (mevcut) parola")}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
            autoFocus
          />
          <PasswordField
            label={t("Yeni parola")}
            value={nw}
            onChange={(e) => setNw(e.target.value)}
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            required
          />
          <PasswordField
            label={t("Yeni parola (tekrar)")}
            value={nw2}
            onChange={(e) => setNw2(e.target.value)}
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            required
          />
          {error && <div className="login-error">{error}</div>}
          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? t("Kaydediliyor…") : t("Parolayı belirle ve devam et")}
          </button>
          <button type="button" className="mini ghost" onClick={onLogout} style={{ marginTop: 8 }}>
            {t("Çıkış yap")}
          </button>
        </form>
      </div>
    </div>
  );
}
