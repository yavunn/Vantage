import { useState } from "react";
import { useT } from "../i18n.jsx";

// Parola alanı + "göster/gizle" düğmesi — tüm parola ekranlarının ortak parçası.
//
// TASARIM KARARLARI:
// - Görünürlük her alanın KENDİ durumudur. Formdaki tüm alanları tek anahtarla
//   açmak ("Parolaları göster" onay kutusu) omuz üstünden bakan birine mevcut
//   parolayı da gösterirdi; oysa kullanıcı çoğu zaman yalnız yeni yazdığı
//   alanı doğrulamak ister.
// - Düğme alanın İÇİNE oturur: ayrı satır, kartların dikey ritmini bozuyordu.
// - `type="button"` şart. Form içindeki tipsiz bir <button> varsayılan olarak
//   submit'tir; göz simgesine basmak yarım dolu formu göndermeye kalkardı.

// Göz simgesi. AÇIK parolada ÜSTÜ ÇİZİLİ göz gösterilir: simge, düğmeye
// basınca ne OLACAĞINI değil, alanın o anki durumunu anlatır — "şu an
// görünür, tıklarsan gizlenir". Ad etiketi (aria-label) eylemi söyler.
export function EyeIcon({ off }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1.8 12S5.4 5.5 12 5.5 22.2 12 22.2 12 18.6 18.5 12 18.5 1.8 12 1.8 12Z" />
      <circle cx="12" cy="12" r="3.2" />
      {off && <line x1="3.5" y1="20.5" x2="20.5" y2="3.5" />}
    </svg>
  );
}

/** Kalan tüm özellikler <input>'a geçer (value, onChange, minLength, autoComplete…).
 *  `type` bilerek kabul edilmez: alanın türünü bu bileşen yönetir. */
export default function PasswordField({ label, ...inputProps }) {
  const t = useT();
  const [show, setShow] = useState(false);
  const etiket = show ? t("pw.hide") : t("pw.show");

  const alan = (
    <div className="pw-field">
      <input {...inputProps} type={show ? "text" : "password"} className="pw-input" />
      <button
        type="button"
        className="pw-toggle"
        onClick={() => setShow((v) => !v)}
        aria-pressed={show}
        aria-label={etiket}
        title={etiket}
      >
        <EyeIcon off={show} />
      </button>
    </div>
  );

  // Etiket verilmezse alan çıplak döner: çağıran kendi <label>'ını kurmuştur.
  return label == null ? alan : <label>{label}{alan}</label>;
}
