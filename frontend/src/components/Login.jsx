import { useState } from "react";
import { login, requestPasswordReset } from "../api.js";
import { LANGS, useLang } from "../i18n.jsx";

// Giriş ekranı. Marka: "Vantage" — sürece tek bir bakış noktasından bakar;
// gözetim değil, ekibin iyiliği için. Çerçeve (İlke E) burada da görünür.
//
// Dil seçici GİRİŞTEN ÖNCE de var: dil tercihi hesaba değil cihaza aittir ve
// giriş yapamayan biri de ekranı kendi dilinde okuyabilmeli.
function LangSwitch() {
  const { lang, setLang, t } = useLang();
  return (
    <div className="lang-switch" role="group" aria-label={t("top.langTitle")}>
      {Object.entries(LANGS).map(([code, label]) => (
        <button
          key={code}
          type="button"
          className={`lang-opt ${lang === code ? "active" : ""}`}
          aria-pressed={lang === code}
          onClick={() => setLang(code)}
          title={label}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function BrandArt() {
  return (
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
      <h1 className="brand-name">Vantage</h1>
    </div>
  );
}

/** Kendi kendine parola sıfırlama formu.
 *
 * Yeni geçici parola sunucu tarafından kullanıcının KENDİ adresine e-postayla
 * gönderilir; bu ekranda ASLA gösterilmez. Parolayı ekranda göstermek,
 * e-posta adresini bilen herkese hesabı açardı — postayı alabilmek, isteği
 * gerçekten hesap sahibinin yaptığını doğrulayan tek adımdır.
 *
 * GİZLİLİK: sunucu, e-posta kayıtlı olsun ya da olmasın AYNI yanıtı döner;
 * bu ekran da "böyle bir hesap yok" demez (hesap numaralandırma). */
function ForgotForm({ onBack }) {
  const { t } = useLang();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await requestPasswordReset(email.trim());
      setSent(res.message || t("forgot.sentLede"));
    } catch (err) {
      setError(err.message || t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="login-card">
        <h2>{t("forgot.sentTitle")}</h2>
        <p className="login-sub">{sent}</p>
        <button type="button" className="login-btn" onClick={onBack}>
          {t("login.backToLogin")}
        </button>
      </div>
    );
  }

  return (
    <form className="login-card" onSubmit={submit}>
      <h2>{t("forgot.title")}</h2>
      <p className="login-sub">{t("forgot.lede")}</p>

      <label>
        {t("forgot.emailLabel")}
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

      {error && <div className="login-error">{error}</div>}

      <button type="submit" className="login-btn" disabled={busy}>
        {busy ? t("forgot.busy") : t("forgot.submit")}
      </button>

      <button type="button" className="link-btn" onClick={onBack}>
        {t("login.backToLogin")}
      </button>
    </form>
  );
}

export default function Login({ onSuccess }) {
  const { t } = useLang();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("login"); // login | forgot

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await login(email.trim(), password);
      onSuccess(user);
    } catch (err) {
      setError(err.message || t("login.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-aside">
        <BrandArt />
        <p className="brand-copy">{t("top.tagline")}</p>
      </div>

      <div className="login-panel">
        {/* Seçici ve kart aynı sütunda: panel satır yerleşimli olduğu için
            doğrudan çocuk yapıldığında kartın SOLUNA düşüp yetim görünüyordu. */}
        <div className="login-stack">
          <LangSwitch />
          {mode === "forgot" ? (
          <ForgotForm onBack={() => setMode("login")} />
        ) : (
          <form className="login-card" onSubmit={submit}>
            <h2>{t("login.title")}</h2>
            <p className="login-sub">{t("login.subtitle")}</p>

            <label>
              {t("login.email")}
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
              {t("login.password")}
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
              {busy ? t("login.busy") : t("login.submit")}
            </button>

            <button type="button" className="link-btn" onClick={() => setMode("forgot")}>
              {t("login.forgot")}
            </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
