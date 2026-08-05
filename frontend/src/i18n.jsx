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

    // --- şifremi unuttum ---
    "forgot.title": "Şifremi unuttum",
    "forgot.lede":
      "Bu sistem şirket içinde çalışır ve parola sıfırlama bağlantısı e-postayla gönderilmez. " +
      "Talebiniz yöneticinize iletilir; size geçici bir parola verilir ve ilk girişte kendi " +
      "parolanızı belirlersiniz.",
    "forgot.emailLabel": "Hesabınızın e-postası",
    "forgot.noteLabel": "Not (isteğe bağlı)",
    "forgot.notePlaceholder": "Yöneticinize kısa bir not bırakabilirsiniz",
    "forgot.submit": "Talep gönder",
    "forgot.busy": "Gönderiliyor…",
    "forgot.sentTitle": "Talebiniz iletildi",

    // --- gezinme ---
    "nav.aria": "Ana gezinme",
    "nav.team": "Takım görünümü",
    "nav.me": "Bireysel görünüm",
    "nav.projects": "Projelerim",
    "nav.leaves": "İzinler",
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

    // --- yönetici: parola talepleri ---
    "reqs.title": "Parola sıfırlama talepleri",
    "reqs.empty": "Bekleyen talep yok.",
    "reqs.lede":
      "Kullanıcı giriş ekranından talep bıraktı. Parolayı sıfırlamak ayrı ve " +
      "bilinçli bir adımdır — bu listeden talebi kapatmak parolayı DEĞİŞTİRMEZ.",
    "reqs.email": "E-posta",
    "reqs.note": "Not",
    "reqs.when": "Tarih",
    "reqs.account": "Hesap",
    "reqs.accountYes": "var",
    "reqs.accountNo": "bu e-postayla hesap yok",
    "reqs.resolve": "Kapat (çözüldü)",
    "reqs.dismiss": "Yok say",
    "reqs.pending": "bekliyor",
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

    // --- forgot password ---
    "forgot.title": "Forgot your password?",
    "forgot.lede":
      "This system runs inside your company and does not email reset links. " +
      "Your request goes to an administrator; you will be given a temporary " +
      "password and set your own on first sign-in.",
    "forgot.emailLabel": "Email on your account",
    "forgot.noteLabel": "Note (optional)",
    "forgot.notePlaceholder": "Leave a short note for your administrator",
    "forgot.submit": "Send request",
    "forgot.busy": "Sending…",
    "forgot.sentTitle": "Request sent",

    // --- navigation ---
    "nav.aria": "Main navigation",
    "nav.team": "Team view",
    "nav.me": "My view",
    "nav.projects": "My projects",
    "nav.leaves": "Time off",
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

    // --- admin: password requests ---
    "reqs.title": "Password reset requests",
    "reqs.empty": "No pending requests.",
    "reqs.lede":
      "The user submitted this from the sign-in screen. Resetting the password " +
      "is a separate, deliberate step — closing a request here does NOT change it.",
    "reqs.email": "Email",
    "reqs.note": "Note",
    "reqs.when": "Date",
    "reqs.account": "Account",
    "reqs.accountYes": "exists",
    "reqs.accountNo": "no account with this email",
    "reqs.resolve": "Close (resolved)",
    "reqs.dismiss": "Dismiss",
    "reqs.pending": "pending",
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
