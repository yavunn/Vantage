import { useState } from "react";
import { changePassword } from "../api.js";

// Profil / Ayarlar sayfası: profil bilgisi, parola değiştirme, tema, oturum.
export default function Settings({ user, theme, onCycleTheme, themeLabel, onLogout }) {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [pwError, setPwError] = useState(null);
  const [pwOk, setPwOk] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submitPw(e) {
    e.preventDefault();
    setPwError(null);
    setPwOk(false);
    if (nw.length < 6) {
      setPwError("Yeni parola en az 6 karakter olmalı");
      return;
    }
    if (nw !== nw2) {
      setPwError("Yeni parolalar eşleşmiyor");
      return;
    }
    setBusy(true);
    try {
      await changePassword(cur, nw);
      setPwOk(true);
      setCur(""); setNw(""); setNw2("");
    } catch (err) {
      setPwError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-page">
      <section className="section">
        <h2>Profil</h2>
        <div className="profile-card">
          <div className="profile-avatar" aria-hidden="true">
            {user.display_name.slice(0, 1).toUpperCase()}
          </div>
          <div className="profile-info">
            <div className="profile-name">
              {user.display_name}
              {user.role === "admin" && <span className="role-badge">admin</span>}
            </div>
            <dl className="profile-fields">
              <div><dt>E-posta</dt><dd>{user.email}</dd></div>
              <div><dt>Rol</dt><dd>{user.role === "admin" ? "Yönetici" : "Çalışan"}</dd></div>
              <div>
                <dt>Takımlar</dt>
                <dd>
                  {user.teams && user.teams.length
                    ? user.teams.map((t) => `${t.team_name}${t.role === "manager" ? " (yönetici)" : ""}`).join(", ")
                    : "—"}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Parola değiştir</h2>
        <form className="settings-form" onSubmit={submitPw}>
          <label>Mevcut parola
            <input type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" required />
          </label>
          <label>Yeni parola
            <input type="password" value={nw} onChange={(e) => setNw(e.target.value)} minLength={6} autoComplete="new-password" required />
          </label>
          <label>Yeni parola (tekrar)
            <input type="password" value={nw2} onChange={(e) => setNw2(e.target.value)} minLength={6} autoComplete="new-password" required />
          </label>
          {pwError && <div className="login-error">{pwError}</div>}
          {pwOk && <div className="admin-ok">Parola güncellendi.</div>}
          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Parolayı değiştir"}
          </button>
        </form>
      </section>

      <section className="section">
        <h2>Görünüm</h2>
        <p className="desc">Tema tercihi cihazında saklanır.</p>
        <button className="mini" onClick={onCycleTheme}>{themeLabel}</button>
      </section>

      <section className="section">
        <h2>Oturum</h2>
        <button className="mini danger" onClick={onLogout}>Oturumu kapat</button>
      </section>
    </div>
  );
}
