import { useEffect, useRef, useState } from "react";
import {
  MIN_PASSWORD_LENGTH,
  requestPasswordCode,
  resetPassword,
  verifyResetCode,
} from "../api.js";
import { useT } from "../i18n.jsx";
import PasswordField from "./PasswordField.jsx";

// "Şifremi unuttum" — tek sayfa, 3 adımlı durum makinesi:
//   email → code → password
//
// Kod kullanıcının POSTA KUTUSUNA gider, hiçbir zaman ekranda gösterilmez;
// postayı alabilmek isteğin gerçekten hesap sahibinden geldiğini doğrulayan
// tek adımdır. 2. adım sonunda alınan kısa ömürlü jeton sayesinde 3. adımda
// kod tekrar sorulmaz.
//
// Giriş ekranının kart/buton/hata sınıfları (login-card, login-btn, link-btn,
// login-error) aynen kullanılır — bu akış için yeni bir görsel dil icat
// edilmedi.

const CODE_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 60;

/** 6 kutucuklu kod girişi: otomatik ilerleme, backspace ile geri, paste desteği. */
function CodeInput({ value, onChange, disabled, onComplete }) {
  const t = useT();
  const refs = useRef([]);

  // Adım açılır açılmaz ilk kutuya odaklan — kullanıcı tıklamak zorunda kalmasın.
  useEffect(() => {
    refs.current[0]?.focus();
  }, []);

  function setChar(i, ch) {
    const next = value.split("");
    next[i] = ch;
    const birlesik = next.join("").slice(0, CODE_LENGTH);
    onChange(birlesik);
    return birlesik;
  }

  function onKeyDown(e, i) {
    if (e.key === "Backspace") {
      e.preventDefault();
      if (value[i]) {
        setChar(i, "");           // dolu kutuyu boşalt, yerinde kal
      } else if (i > 0) {
        setChar(i - 1, "");       // boşsa bir öncekini temizleyip oraya git
        refs.current[i - 1]?.focus();
      }
    } else if (e.key === "ArrowLeft" && i > 0) {
      refs.current[i - 1]?.focus();
    } else if (e.key === "ArrowRight" && i < CODE_LENGTH - 1) {
      refs.current[i + 1]?.focus();
    }
  }

  function onInput(e, i) {
    // Yalnız rakam; kullanıcı tek kutuya birden çok karakter yazarsa (mobil
    // klavye) hepsini sırayla dağıt.
    const rakamlar = e.target.value.replace(/\D/g, "");
    if (!rakamlar) return;
    const next = value.split("");
    let j = i;
    for (const ch of rakamlar) {
      if (j >= CODE_LENGTH) break;
      next[j] = ch;
      j += 1;
    }
    const birlesik = next.join("").slice(0, CODE_LENGTH);
    onChange(birlesik);
    refs.current[Math.min(j, CODE_LENGTH - 1)]?.focus();
    if (birlesik.length === CODE_LENGTH && !birlesik.includes("")) onComplete?.(birlesik);
  }

  function onPaste(e) {
    // Maildeki kodu tek seferde yapıştırmak en yaygın kullanım — kutu kutu
    // yazdırmak yerine tamamını dağıt.
    const yapistirilan = (e.clipboardData.getData("text") || "").replace(/\D/g, "");
    if (!yapistirilan) return;
    e.preventDefault();
    const birlesik = yapistirilan.slice(0, CODE_LENGTH);
    onChange(birlesik);
    refs.current[Math.min(birlesik.length, CODE_LENGTH - 1)]?.focus();
    if (birlesik.length === CODE_LENGTH) onComplete?.(birlesik);
  }

  return (
    <div className="code-input" role="group" aria-label={t("forgot.codeLabel")}>
      {Array.from({ length: CODE_LENGTH }).map((_, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          className="code-box"
          type="text"
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={1}
          value={value[i] || ""}
          disabled={disabled}
          onChange={(e) => onInput(e, i)}
          onKeyDown={(e) => onKeyDown(e, i)}
          onPaste={onPaste}
          aria-label={t("forgot.codeDigit", { n: i + 1 })}
        />
      ))}
    </div>
  );
}

function fmtSure(saniye) {
  const d = Math.floor(saniye / 60);
  const s = saniye % 60;
  return `${d}:${String(s).padStart(2, "0")}`;
}

export default function ForgotPassword({ onBack, onDone }) {
  const t = useT();
  const [step, setStep] = useState("email"); // email | code | password
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [resetToken, setResetToken] = useState(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Kodun kalan ömrü ve "tekrar gönder" bekleme sayacı (saniye).
  const [kalan, setKalan] = useState(0);
  const [cooldown, setCooldown] = useState(0);

  // Tek zamanlayıcı iki sayacı da yürütür — ikinci bir interval açmaya gerek yok.
  useEffect(() => {
    if (kalan <= 0 && cooldown <= 0) return undefined;
    const id = setInterval(() => {
      setKalan((v) => (v > 0 ? v - 1 : 0));
      setCooldown((v) => (v > 0 ? v - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, [kalan, cooldown]);

  async function kodIste(e) {
    e?.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await requestPasswordCode(email.trim());
      setCode("");
      setKalan((res.expires_in_minutes ?? 10) * 60);
      setCooldown(RESEND_COOLDOWN_SECONDS);
      setStep("code");
    } catch (err) {
      setError(err.message || t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  async function kodDogrula(e, hazirKod) {
    e?.preventDefault();
    const girilen = (hazirKod ?? code).trim();
    if (girilen.length !== CODE_LENGTH) return;
    setError(null);
    setBusy(true);
    try {
      const res = await verifyResetCode(email.trim(), girilen);
      setResetToken(res.reset_token);
      setStep("password");
    } catch (err) {
      setError(err.message || t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  async function parolaBelirle(e) {
    e.preventDefault();
    setError(null);
    if (pw !== pw2) {
      setError(t("forgot.pwMismatch"));
      return;
    }
    setBusy(true);
    try {
      await resetPassword(resetToken, pw);
      onDone();
    } catch (err) {
      setError(err.message || t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  // --- 1. adım: e-posta -------------------------------------------------------
  if (step === "email") {
    return (
      <form className="login-card" onSubmit={kodIste}>
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
        <button type="submit" className="login-btn" disabled={busy || !email.trim()}>
          {busy ? t("forgot.sending") : t("forgot.sendCode")}
        </button>
        <button type="button" className="link-btn" onClick={onBack}>
          {t("login.backToLogin")}
        </button>
      </form>
    );
  }

  // --- 2. adım: kod -----------------------------------------------------------
  if (step === "code") {
    const suresiDoldu = kalan <= 0;
    return (
      <form className="login-card" onSubmit={kodDogrula}>
        <h2>{t("forgot.codeTitle")}</h2>
        <p className="login-sub">{t("forgot.codeLede", { email: email.trim() })}</p>

        <CodeInput
          value={code}
          onChange={setCode}
          disabled={busy || suresiDoldu}
          onComplete={(k) => kodDogrula(null, k)}
        />

        <p className={`forgot-countdown ${suresiDoldu ? "expired" : ""}`}>
          {suresiDoldu ? t("forgot.expired") : t("forgot.expiresIn", { time: fmtSure(kalan) })}
        </p>

        {error && <div className="login-error">{error}</div>}

        <button
          type="submit"
          className="login-btn"
          disabled={busy || suresiDoldu || code.length !== CODE_LENGTH}
        >
          {busy ? t("forgot.verifying") : t("forgot.verify")}
        </button>

        <button
          type="button"
          className="link-btn"
          onClick={kodIste}
          disabled={busy || cooldown > 0}
        >
          {cooldown > 0 ? t("forgot.resendIn", { n: cooldown }) : t("forgot.resend")}
        </button>
        <button type="button" className="link-btn" onClick={onBack}>
          {t("login.backToLogin")}
        </button>
      </form>
    );
  }

  // --- 3. adım: yeni parola ---------------------------------------------------
  const kisa = pw.length > 0 && pw.length < MIN_PASSWORD_LENGTH;
  const uyusmuyor = pw2.length > 0 && pw !== pw2;
  return (
    <form className="login-card" onSubmit={parolaBelirle}>
      <h2>{t("forgot.pwTitle")}</h2>
      <p className="login-sub">{t("forgot.pwLede", { n: MIN_PASSWORD_LENGTH })}</p>

      <PasswordField
        label={t("forgot.newPassword")}
        autoComplete="new-password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        minLength={MIN_PASSWORD_LENGTH}
        required
        autoFocus
      />
      <PasswordField
        label={t("forgot.newPasswordAgain")}
        autoComplete="new-password"
        value={pw2}
        onChange={(e) => setPw2(e.target.value)}
        minLength={MIN_PASSWORD_LENGTH}
        required
      />

      {/* Eşleşme/uzunluk uyarısı anlık — kullanıcı gönder'e basana kadar
          beklemesin. */}
      {kisa && <div className="login-error">{t("forgot.pwTooShort", { n: MIN_PASSWORD_LENGTH })}</div>}
      {!kisa && uyusmuyor && <div className="login-error">{t("forgot.pwMismatch")}</div>}
      {error && <div className="login-error">{error}</div>}

      <button
        type="submit"
        className="login-btn"
        disabled={busy || kisa || uyusmuyor || !pw || !pw2}
      >
        {busy ? t("forgot.saving") : t("forgot.savePassword")}
      </button>
      <button type="button" className="link-btn" onClick={onBack}>
        {t("login.backToLogin")}
      </button>
    </form>
  );
}
