// Dil katmanı (TR / EN) — seçim kullanıcıya ait, kalıcı.
//
// TASARIM:
// - Türkçe ANA dildir: sözlükte karşılığı olmayan anahtar TR metne düşer,
//   asla ham anahtar ("nav.team") ekrana çıkmaz. Yarım çeviri, bozuk arayüzden
//   iyidir; ham anahtar ikisinden de kötüdür.
// - Seçim localStorage'da tutulur ve `Accept-Language` başlığıyla sunucuya da
//   gider (metrik adları, açıklamalar ve durum etiketleri API'den geliyor —
//   yalnız arayüzü çevirmek panoyu yarı Türkçe bırakırdı).
// - <html lang> güncellenir: ekran okuyucu doğru dilde okusun.
//
// KAPSAM SINIRI (bilinçli): kural motorunun ürettiği öneri metinleri, senkron
// uyarıları ve AI çıktısı üretilmiş DÜZYAZIDIR ve Türkçe kalır. Onları burada
// sözlükleştirmek mümkün değil; ayrı bir iş kalemi.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { EN } from "./i18n-en.js";

const LANG_KEY = "vantage_lang";
export const LANGS = { tr: "Türkçe", en: "English" };
export const DEFAULT_LANG = "tr";

/** Kayıtlı tercih varsa o, yoksa Türkçe.
 *
 * Tarayıcı diline (navigator.language) BİLEREK bakılmıyor: bu Türkçe bir
 * kurumsal araç ve İngilizce SEÇİME bağlı. Otomatik algılama, İngilizce
 * işletim sistemi kullanan Türk bir çalışana arayüzü sormadan İngilizce
 * gösterirdi. */
function detectLang() {
  const saved = localStorage.getItem(LANG_KEY);
  return saved && LANGS[saved] ? saved : DEFAULT_LANG;
}

// Seçili dil modül seviyesinde de okunabilir olmalı: api.js React ağacının
// dışında ve her isteğe Accept-Language koyuyor.
let currentLang = typeof localStorage !== "undefined" ? detectLang() : DEFAULT_LANG;
export function getLang() {
  return currentLang;
}

const STRINGS = {
  tr: {
    // --- ortak ---
    "common.loading": "Yükleniyor…",
    "common.save": "Kaydet",
    "common.cancel": "Vazgeç",
    "common.close": "Kapat",
    "common.back": "Geri",
    "common.search": "Ara",
    "common.retry": "Tekrar dene",
    "common.none": "yok",
    "common.error": "Bir hata oluştu",

    // --- giriş ---
    "login.title": "Giriş yap",
    "login.subtitle": "Hesabınla oturum aç.",
    "login.email": "E-posta",
    "login.password": "Parola",
    "login.submit": "Giriş yap",
    "login.busy": "Giriş yapılıyor…",
    "login.failed": "Giriş başarısız",
    "login.forgot": "Şifremi unuttum",
    "login.backToLogin": "← Girişe dön",

    // --- şifremi unuttum (3 adım) ---
    "forgot.title": "Şifremi unuttum",
    "forgot.lede":
      "Hesabının e-postasını gir; sana 6 haneli bir doğrulama kodu gönderelim.",
    "forgot.emailLabel": "Hesabınızın e-postası",
    "forgot.sendCode": "Kod gönder",
    "forgot.sending": "Gönderiliyor…",
    "forgot.codeTitle": "Kodu gir",
    "forgot.codeLede": "{email} adresine 6 haneli bir kod gönderdik.",
    "forgot.codeLabel": "Doğrulama kodu",
    "forgot.codeDigit": "Kodun {n}. hanesi",
    "forgot.expiresIn": "Kodun geçerlilik süresi: {time}",
    "forgot.expired": "Kodun süresi doldu. Yeni bir kod iste.",
    "forgot.verify": "Doğrula",
    "forgot.verifying": "Doğrulanıyor…",
    "forgot.resend": "Kodu tekrar gönder",
    "forgot.resendIn": "Tekrar göndermek için {n} sn",
    "forgot.pwTitle": "Yeni parolanı belirle",
    "forgot.pwLede": "En az {n} karakter olmalı.",
    "forgot.newPassword": "Yeni parola",
    "forgot.newPasswordAgain": "Yeni parola (tekrar)",
    "forgot.pwMismatch": "Parolalar eşleşmiyor",
    "forgot.pwTooShort": "Parola en az {n} karakter olmalı",
    "forgot.savePassword": "Parolayı kaydet",
    "forgot.saving": "Kaydediliyor…",
    "forgot.success": "Parolan değiştirildi. Yeni parolanla giriş yapabilirsin.",

    // --- gezinme ---
    "nav.aria": "Ana gezinme",
    "nav.team": "Takım görünümü",
    "nav.me": "Bireysel görünüm",
    "nav.projects": "Projelerim",
    "nav.leaves": "İzinler",
    "nav.documents": "Evraklar",
    "nav.survey": "Anket",
    "nav.admin": "Yönetici paneli",
    "nav.settings": "Ayarlar",
    "nav.hr": "İK Panosu",
    "nav.accounts": "Hesaplar",

    // --- üst çubuk ---
    "top.search": "Ara",
    "top.searchTitle": "Hızlı arama (Ctrl+K)",
    "top.themeTitle": "Açık/Koyu/Oto tema",
    "top.logout": "Çıkış",
    "top.team": "Takım",
    "top.selectTeam": "Takım seç",
    "top.langTitle": "Dil / Language",
    "top.pending": "bekliyor",
    "top.tagline":
      "Süreç sağlığı panosu — kişi performans aracı değildir. Kırmızı, " +
      "\"takım zorlanıyor, yardım gerekebilir\" demektir; ceza sinyali değildir.",
    "top.anonymized": " · Anonim mod açık (takım-agregat).",
  },

  en: {
    // --- common ---
    "common.loading": "Loading…",
    "common.save": "Save",
    "common.cancel": "Cancel",
    "common.close": "Close",
    "common.back": "Back",
    "common.search": "Search",
    "common.retry": "Try again",
    "common.none": "none",
    "common.error": "Something went wrong",

    // --- login ---
    "login.title": "Sign in",
    "login.subtitle": "Sign in with your account.",
    "login.email": "Email",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.busy": "Signing in…",
    "login.failed": "Sign-in failed",
    "login.forgot": "Forgot your password?",
    "login.backToLogin": "← Back to sign in",

    // --- forgot password (3 steps) ---
    "forgot.title": "Forgot your password?",
    "forgot.lede":
      "Enter your account's email and we'll send you a 6-digit verification code.",
    "forgot.emailLabel": "Email on your account",
    "forgot.sendCode": "Send code",
    "forgot.sending": "Sending…",
    "forgot.codeTitle": "Enter the code",
    "forgot.codeLede": "We sent a 6-digit code to {email}.",
    "forgot.codeLabel": "Verification code",
    "forgot.codeDigit": "Digit {n} of the code",
    "forgot.expiresIn": "Code expires in {time}",
    "forgot.expired": "The code has expired. Request a new one.",
    "forgot.verify": "Verify",
    "forgot.verifying": "Verifying…",
    "forgot.resend": "Resend code",
    "forgot.resendIn": "Resend in {n}s",
    "forgot.pwTitle": "Set your new password",
    "forgot.pwLede": "Must be at least {n} characters.",
    "forgot.newPassword": "New password",
    "forgot.newPasswordAgain": "New password (repeat)",
    "forgot.pwMismatch": "Passwords do not match",
    "forgot.pwTooShort": "Password must be at least {n} characters",
    "forgot.savePassword": "Save password",
    "forgot.saving": "Saving…",
    "forgot.success": "Your password has been changed. You can sign in with it now.",

    // --- navigation ---
    "nav.aria": "Main navigation",
    "nav.team": "Team view",
    "nav.me": "My view",
    "nav.projects": "My projects",
    "nav.leaves": "Time off",
    "nav.documents": "Documents",
    "nav.survey": "Survey",
    "nav.admin": "Admin panel",
    "nav.settings": "Settings",
    "nav.hr": "HR dashboard",
    "nav.accounts": "Accounts",

    // --- top bar ---
    "top.search": "Search",
    "top.searchTitle": "Quick search (Ctrl+K)",
    "top.themeTitle": "Light / Dark / Auto theme",
    "top.logout": "Sign out",
    "top.team": "Team",
    "top.selectTeam": "Select team",
    "top.langTitle": "Dil / Language",
    "top.pending": "pending",
    "top.tagline":
      "Process health dashboard — not a personal performance tool. Red means " +
      "\"the team is struggling, support may help\"; it is not a penalty signal.",
    "top.anonymized": " · Anonymous mode on (team aggregate).",
  },
};

// Noktalı anahtar mı ("nav.team") yoksa kaynak metin mi ("Yeni çalışan ekle")?
// İkisi bilinçli olarak bir arada: kabuk için okunur anahtarlar, gövdedeki
// yüzlerce dize için KAYNAK METNİN KENDİSİ anahtardır (gettext deseni).
// Böylece Türkçe yol kimlik fonksiyonudur — çeviri eklerken Türkçe arayüzü
// bozma riski yoktur ve eksik çeviri sessizce Türkçeye düşer, boşluğa değil.
const DOTTED_KEY = /^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9_]+)+$/;

/** Saf çeviri — React'e bağlı değil, sağlayıcı da gerektirmez. */
export function translate(lang, key, vars) {
  const noktali = DOTTED_KEY.test(key);
  // Sıra: dil sözlüğü → (İngilizcede) kaynak-metin sözlüğü → TR sözlüğü.
  let raw = STRINGS[lang]?.[key];
  if (raw == null && lang !== DEFAULT_LANG && !noktali) raw = EN[key];
  if (raw == null) raw = STRINGS[DEFAULT_LANG]?.[key];
  if (raw == null) {
    // Geri düşüş: noktalı anahtar BOŞ ("nav.team" ekranda görünmemeli);
    // kaynak metin ise kendisi (Türkçe kalır, kaybolmaz).
    raw = noktali ? "" : key;
  }
  if (!vars) return raw;
  return Object.entries(vars).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    raw,
  );
}

// Varsayılan bağlam da GERÇEK çeviriyi yapar. Sağlayıcı yalnızca dil
// değişiminde yeniden çizimi sağlar; sağlayıcı dışında kalan bir bileşen
// (ör. testte tek başına render edilen TopBar) ham anahtar göstermez.
const LangContext = createContext({
  lang: currentLang,
  setLang: () => {},
  t: (k, v) => translate(currentLang, k, v),
});

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => detectLang());

  useEffect(() => {
    currentLang = lang;
    localStorage.setItem(LANG_KEY, lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next) => {
    if (LANGS[next]) setLangState(next);
  }, []);

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang]);

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

/** Yalnız çeviri fonksiyonu gerektiğinde. */
export function useT() {
  return useContext(LangContext).t;
}
