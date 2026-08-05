import { useMemo, useState } from "react";
import { MIN_PASSWORD_LENGTH, changePassword, updateProfile } from "../api.js";
import { toast } from "../toast.js";
import { useLang, useT } from "../i18n.jsx";

// Yaygın uygulama zaman dilimleri (kısa liste; kurum içi yeterli).
const TIMEZONES = [
  "Europe/Istanbul", "Europe/London", "Europe/Berlin", "UTC",
  "America/New_York", "America/Los_Angeles", "Asia/Dubai", "Asia/Tokyo",
];

// Parola gücü: uzunluk + çeşitlilik. 0..4 skala.
function passwordStrength(t, pw) {
  if (!pw) return { score: 0, label: "" };
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  s = Math.min(s, 4);
  const labels = [t("Çok zayıf"), t("Zayıf"), t("Orta"), t("İyi"), t("Güçlü")];
  return { score: s, label: labels[s] };
}

function fmtDate(iso, lang) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(lang === "en" ? "en-US" : "tr-TR"); } catch { return "—"; }
}

export default function Settings({ user, onCycleTheme, themeLabel, onLogout, onProfileUpdated }) {
  const t = useT();
  const { lang } = useLang();
  // --- profil formu ---
  const [profile, setProfile] = useState({
    display_name: user.display_name || "",
    title: user.title || "",
    phone: user.phone || "",
    timezone: user.timezone || "",
    bio: user.bio || "",
  });
  const [profBusy, setProfBusy] = useState(false);
  const dirty = useMemo(
    () =>
      profile.display_name !== (user.display_name || "") ||
      profile.title !== (user.title || "") ||
      profile.phone !== (user.phone || "") ||
      profile.timezone !== (user.timezone || "") ||
      profile.bio !== (user.bio || ""),
    [profile, user]
  );

  function updP(k, v) { setProfile((p) => ({ ...p, [k]: v })); }

  async function saveProfile(e) {
    e.preventDefault();
    if (!profile.display_name.trim()) { toast(t("Ad boş olamaz"), "error"); return; }
    setProfBusy(true);
    try {
      const updated = await updateProfile({
        display_name: profile.display_name.trim(),
        title: profile.title,
        phone: profile.phone,
        timezone: profile.timezone,
        bio: profile.bio,
      });
      onProfileUpdated?.(updated);
      toast(t("Profil güncellendi"), "ok");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setProfBusy(false);
    }
  }

  // --- parola formu ---
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [pwError, setPwError] = useState(null);
  const [pwOk, setPwOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const strength = passwordStrength(t, nw);

  async function submitPw(e) {
    e.preventDefault();
    setPwError(null); setPwOk(false);
    if (nw.length < MIN_PASSWORD_LENGTH) {
      setPwError(t("Yeni parola en az {n} karakter olmalı", { n: MIN_PASSWORD_LENGTH }));
      return;
    }
    if (nw !== nw2) { setPwError(t("Yeni parolalar eşleşmiyor")); return; }
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
        <h2>{t("Profil")}</h2>
        <div className="profile-card">
          <div className="profile-avatar" aria-hidden="true">
            {(profile.display_name || user.email).slice(0, 1).toUpperCase()}
          </div>
          <div className="profile-info">
            <div className="profile-name">
              {profile.display_name || user.display_name}
              {user.role === "admin" && <span className="role-badge">admin</span>}
            </div>
            {profile.title && <div className="profile-title">{profile.title}</div>}
            <dl className="profile-fields">
              <div><dt>{t("E-posta")}</dt><dd>{user.email}</dd></div>
              <div><dt>{t("Rol")}</dt><dd>{user.role === "admin" ? t("Yönetici") : t("Çalışan")}</dd></div>
              <div>
                <dt>{t("Takımlar")}</dt>
                <dd>
                  {user.teams && user.teams.length
                    ? user.teams.map((tm) => `${tm.team_name}${tm.role === "manager" ? ` (${t("yönetici")})` : ""}`).join(", ")
                    : "—"}
                </dd>
              </div>
              <div><dt>{t("Kayıt")}</dt><dd>{fmtDate(user.created_at, lang)}</dd></div>
              <div><dt>{t("Son giriş")}</dt><dd>{fmtDate(user.last_login_at, lang)}</dd></div>
            </dl>
          </div>
        </div>

        <form className="settings-form" onSubmit={saveProfile}>
          <label>{t("Ad Soyad")}
            <input value={profile.display_name} onChange={(e) => updP("display_name", e.target.value)} maxLength={200} required />
          </label>
          <label>{t("Ünvan / Pozisyon")}
            <input value={profile.title} onChange={(e) => updP("title", e.target.value)} placeholder={t("ör. Backend Geliştirici")} maxLength={120} />
          </label>
          <label>{t("Telefon")}
            <input value={profile.phone} onChange={(e) => updP("phone", e.target.value)} placeholder={t("ör. +90 5xx xxx xx xx")} maxLength={40} />
          </label>
          <label>{t("Zaman dilimi")}
            <select value={profile.timezone} onChange={(e) => updP("timezone", e.target.value)}>
              <option value="">{t("— seçilmedi —")}</option>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </label>
          <label>{t("Hakkında")}
            <textarea value={profile.bio} onChange={(e) => updP("bio", e.target.value)} rows={3} maxLength={2000} placeholder={t("Kısa bir not (opsiyonel)")} />
          </label>
          <button type="submit" className="login-btn" disabled={profBusy || !dirty}>
            {profBusy ? t("Kaydediliyor…") : dirty ? t("Profili kaydet") : t("Kaydedildi")}
          </button>
        </form>
      </section>

      <section className="section">
        <h2>{t("Parola değiştir")}</h2>
        <form className="settings-form" onSubmit={submitPw}>
          <label>{t("Mevcut parola")}
            <input type={showPw ? "text" : "password"} value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" required />
          </label>
          <label>{t("Yeni parola")}
            <input type={showPw ? "text" : "password"} value={nw} onChange={(e) => setNw(e.target.value)} minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" required />
          </label>
          {nw && (
            <div className={`pw-strength s${strength.score}`}>
              <div className="pw-bar"><span style={{ width: `${(strength.score / 4) * 100}%` }} /></div>
              <span className="pw-label">{strength.label}</span>
            </div>
          )}
          <label>{t("Yeni parola (tekrar)")}
            <input type={showPw ? "text" : "password"} value={nw2} onChange={(e) => setNw2(e.target.value)} minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" required />
          </label>
          <label className="pw-show">
            <input type="checkbox" checked={showPw} onChange={(e) => setShowPw(e.target.checked)} /> {t("Parolaları göster")}
          </label>
          {pwError && <div className="login-error">{pwError}</div>}
          {pwOk && <div className="admin-ok">{t("Parola güncellendi.")}</div>}
          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? t("Kaydediliyor…") : t("Parolayı değiştir")}
          </button>
        </form>
      </section>

      <section className="section">
        <h2>{t("Görünüm")}</h2>
        <p className="desc">{t("Tema tercihi cihazında saklanır.")}</p>
        <button className="mini" onClick={onCycleTheme}>{themeLabel}</button>
      </section>

      <section className="section">
        <h2>{t("Oturum")}</h2>
        <button className="mini danger" onClick={onLogout}>{t("Oturumu kapat")}</button>
      </section>
    </div>
  );
}
