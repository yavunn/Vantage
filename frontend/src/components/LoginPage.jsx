// Giriş sayfası (Faz 1). Başarılı girişte token api.js'te saklanır.
import { useState } from "react";
import { login } from "../api.js";

export default function LoginPage({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>Engineering Health Dashboard</h1>
        <span className="sub">
          Süreç sağlığı panosu — kişi performans aracı değildir.
        </span>
      </header>
      <form className="section" onSubmit={submit} style={{ maxWidth: 360 }}>
        <h2>Giriş</h2>
        <div style={{ display: "grid", gap: 8 }}>
          <input
            type="email"
            placeholder="E-posta"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Parola"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit" disabled={busy}>
            {busy ? "Giriş yapılıyor…" : "Giriş yap"}
          </button>
          {error && <div className="error-box">Hata: {error}</div>}
          <p className="desc">
            Demo hesaplar: geliştirici e-postası / demo123 · admin@corp.local / admin123
          </p>
        </div>
      </form>
    </div>
  );
}
