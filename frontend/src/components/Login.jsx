import { useState } from "react";
import { login } from "../api.js";

// Giriş ekranı. Marka: "Nabız" — süreç sağlığını nabız gibi ölçer;
// gözetim değil, ekibin iyiliği için. Çerçeve (İlke E) burada da görünür.
export default function Login({ onSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await login(email.trim(), password);
      onSuccess(user);
    } catch (err) {
      setError(err.message || "Giriş başarısız");
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
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <h1 className="brand-name">Nabız</h1>
        </div>
        <p className="brand-tagline">Mühendislik Sağlığı Panosu</p>
        <p className="brand-copy">
          Takımın süreç sağlığını nabız gibi ölçer. Kişi performans karnesi ya da
          gözetim aracı değildir — kırmızı bir metrik, "ekip zorlanıyor, destek
          gerekebilir" demektir.
        </p>
      </div>

      <div className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <h2>Giriş yap</h2>
          <p className="login-sub">Hesabınla oturum aç.</p>

          <label>
            E-posta
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ad@corp.local"
              required
              autoFocus
            />
          </label>

          <label>
            Parola
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </label>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? "Giriş yapılıyor…" : "Giriş yap"}
          </button>

          <p className="login-hint">
            Parolanı yöneticinden aldıysan, giriş sonrası profilinden
            değiştirebilirsin.
          </p>
        </form>
      </div>
    </div>
  );
}
