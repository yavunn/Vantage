import { useState } from "react";
import { MIN_PASSWORD_LENGTH, setup } from "../api.js";

// İlk kurulum: sistemde hiç aktif yönetici yoksa gösterilir. İlk admin
// hesabını oluşturur ve doğrudan oturum açar (CLI gerektirmez).
export default function Setup({ onSuccess }) {
  const [form, setForm] = useState({ display_name: "", email: "", password: "", password2: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function upd(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (form.password !== form.password2) {
      setError("Parolalar eşleşmiyor");
      return;
    }
    setBusy(true);
    try {
      const user = await setup({
        display_name: form.display_name.trim(),
        email: form.email.trim(),
        password: form.password,
      });
      onSuccess(user);
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
        <p className="brand-tagline">İlk kurulum</p>
        <p className="brand-copy">
          Sisteme hoş geldin. Henüz bir yönetici hesabı yok. Başlamak için ilk
          yönetici (admin) hesabını oluştur. Bu adım yalnızca bir kez gösterilir.
        </p>
      </div>

      <div className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <h2>Yönetici hesabı oluştur</h2>
          <p className="login-sub">Bu hesapla giriş yapıp diğerlerini ekleyeceksin.</p>
          <label>
            Ad Soyad
            <input value={form.display_name} onChange={(e) => upd("display_name", e.target.value)} required autoFocus />
          </label>
          <label>
            E-posta
            <input type="email" value={form.email} onChange={(e) => upd("email", e.target.value)} placeholder="ad@corp.local" required />
          </label>
          <label>
            Parola
            <input type="password" value={form.password} onChange={(e) => upd("password", e.target.value)} minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" required />
          </label>
          <label>
            Parola (tekrar)
            <input type="password" value={form.password2} onChange={(e) => upd("password2", e.target.value)} minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" required />
          </label>
          {error && <div className="login-error">{error}</div>}
          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? "Oluşturuluyor…" : "Yöneticiyi oluştur ve başla"}
          </button>
        </form>
      </div>
    </div>
  );
}
