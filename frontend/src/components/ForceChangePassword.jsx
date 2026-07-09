import { useState } from "react";
import { changePassword } from "../api.js";

// İlk giriş / admin sıfırlaması sonrası zorunlu parola değiştirme.
// Kapatılamaz — kullanıcı yeni parola belirlemeden panoya geçemez.
export default function ForceChangePassword({ onDone, onLogout }) {
  const [current, setCurrent] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (nw.length < 6) {
      setError("Yeni parola en az 6 karakter olmalı");
      return;
    }
    if (nw !== nw2) {
      setError("Yeni parolalar eşleşmiyor");
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
          <h1 className="brand-name">Nabız</h1>
        </div>
        <p className="brand-tagline">Güvenlik adımı</p>
        <p className="brand-copy">
          Hesabına yönetici tarafından geçici bir parola atandı. Devam etmeden
          önce kendine ait yeni bir parola belirlemelisin.
        </p>
      </div>

      <div className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <h2>Yeni parola belirle</h2>
          <p className="login-sub">Bu adım zorunludur.</p>
          <label>
            Geçici (mevcut) parola
            <input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              required
              autoFocus
            />
          </label>
          <label>
            Yeni parola
            <input
              type="password"
              value={nw}
              onChange={(e) => setNw(e.target.value)}
              minLength={6}
              autoComplete="new-password"
              required
            />
          </label>
          <label>
            Yeni parola (tekrar)
            <input
              type="password"
              value={nw2}
              onChange={(e) => setNw2(e.target.value)}
              minLength={6}
              autoComplete="new-password"
              required
            />
          </label>
          {error && <div className="login-error">{error}</div>}
          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Parolayı belirle ve devam et"}
          </button>
          <button type="button" className="mini ghost" onClick={onLogout} style={{ marginTop: 8 }}>
            Çıkış yap
          </button>
        </form>
      </div>
    </div>
  );
}
