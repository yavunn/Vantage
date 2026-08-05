import { useState } from "react";
import { submitSurvey } from "../api.js";
import { toast } from "../toast.js";
import { useLang, useT } from "../i18n.jsx";

// Anonim memnuniyet anketi — çalışan sayfası. Veri App'ten gelir (tek kaynak);
// bu bileşen yalnız gösterir + gönderir. Anonimlik her adımda hissettirilir.
const SCALE = [
  { v: 1, emoji: "😞", label: "Hiç" },
  { v: 2, emoji: "🙁", label: "Az" },
  { v: 3, emoji: "😐", label: "Orta" },
  { v: 4, emoji: "🙂", label: "İyi" },
  { v: 5, emoji: "😄", label: "Çok" },
];

// ISO tarih ("2026-07-20") → "20 Tem" (yerel, TZ kaymadan: parça parça kur).
function fmtDay(iso, lang) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString(lang === "en" ? "en-US" : "tr-TR", { day: "numeric", month: "short" });
}
// closes_at hariç (bitiş günü = closes_at - 1 gün).
function lastDay(iso, lang) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d - 1);
  return dt.toLocaleDateString(lang === "en" ? "en-US" : "tr-TR", { day: "numeric", month: "short" });
}

function TrustStrip() {
  const t = useT();
  return (
    <div className="survey-trust" role="note">
      <span>🔒</span>
      <span>{t("Kimliğin")} <b>{t("kaydedilmez")}</b> · {t("cevapların")} <b>{t("şifrelenir")}</b> · {t("yalnız")} <b>{t("toplu")}</b> {t("görülür")}</span>
    </div>
  );
}

function Shell({ children }) {
  return <div className="survey-page">{children}</div>;
}

export default function SurveyForm({ survey, onSubmitted }) {
  const t = useT();
  const { lang } = useLang();
  const [answers, setAnswers] = useState({});
  const [texts, setTexts] = useState({});
  const [busy, setBusy] = useState(false);
  const [justDone, setJustDone] = useState(false);

  // --- durumlar ---
  if (!survey) {
    return <Shell><div className="survey-hero"><p className="desc">{t("Yükleniyor…")}</p></div></Shell>;
  }
  if (survey.enabled === false) {
    return (
      <Shell>
        <div className="survey-hero">
          <h2>{t("Memnuniyet Anketi")}</h2>
          <p className="desc">{t("Anket modülü şu an kapalı.")}</p>
        </div>
      </Shell>
    );
  }
  // Yönetici rolleri anketi doldurmaz — yönetici mesajı göster.
  if (survey.respondent === false) {
    return (
      <Shell>
        <div className="survey-hero">
          <h2>{t("Memnuniyet Anketi")}</h2>
          <p className="desc">
            {survey.note || t("Bu anketi sen yönetiyorsun; doldurman gerekmez.")}
          </p>
        </div>
      </Shell>
    );
  }
  if (survey.ready === false) {
    return (
      <Shell>
        <div className="survey-hero">
          <h2>{t("Memnuniyet Anketi")}</h2>
          <p className="desc">{t("Anket henüz kullanıma hazır değil. Kısa süre sonra tekrar dene.")}</p>
        </div>
      </Shell>
    );
  }

  const likert = (survey.questions || []).filter((q) => q.type === "likert");
  const textQs = (survey.questions || []).filter((q) => q.type === "text");
  const answered = likert.filter((q) => answers[q.key]).length;
  const total = likert.length;
  const allAnswered = total > 0 && answered === total;

  // Teşekkür ekranı (yeni gönderim ya da daha önce doldurulmuş).
  if (justDone || survey.already_submitted) {
    return (
      <Shell>
        <div className="survey-hero survey-thanks">
          <div className="survey-check" aria-hidden="true">✓</div>
          <h2>{t("Teşekkürler!")}</h2>
          <p className="desc">
            {t("Bu dönemin anketini doldurdun. Cevabın")} <b>{t("tamamen anonim")}</b> —{" "}
            {t("kimseye bağlanmadı, şifreli saklanıyor. Görüşün bizi iyileştirir. 💙")}
          </p>
          {survey.closes_at && (
            <p className="survey-next">{t("Yeni anket")} <b>{fmtDay(survey.closes_at, lang)}</b> {t("sonrası açılacak.")}</p>
          )}
        </div>
      </Shell>
    );
  }

  if (survey.is_open === false) {
    return (
      <Shell>
        <div className="survey-hero">
          <h2>{t("Memnuniyet Anketi")}</h2>
          <p className="desc">{t("Bu dönemin anketi kapandı. Bir sonraki dönemde görüşürüz.")}</p>
        </div>
      </Shell>
    );
  }

  function setAns(key, v) {
    setAnswers((a) => ({ ...a, [key]: v }));
  }
  // Ok tuşlarıyla skala gezinme (erişilebilirlik).
  function onScaleKey(e, key) {
    const cur = answers[key] || 0;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault(); setAns(key, Math.min(5, cur + 1 || 1));
    } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault(); setAns(key, Math.max(1, (cur || 2) - 1));
    }
  }

  function setText(key, v) {
    setTexts((tx) => ({ ...tx, [key]: v }));
  }

  async function submit() {
    if (!allAnswered) { toast(t("Tüm soruları yanıtla"), "error"); return; }
    setBusy(true);
    try {
      const cleanTexts = {};
      for (const q of textQs) {
        const v = (texts[q.key] || "").trim();
        if (v) cleanTexts[q.key] = v;
      }
      await submitSurvey(answers, cleanTexts);
      setJustDone(true);
      onSubmitted?.();
      toast(t("Anket gönderildi — anonim"), "ok");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  const pct = total ? Math.round((answered / total) * 100) : 0;

  return (
    <Shell>
      <div className="survey-hero">
        <h2>{t("Memnuniyet Anketi")}</h2>
        {survey.opens_at && survey.closes_at && (
          <span className="survey-period">{t("{start} – {end} dönemi", { start: fmtDay(survey.opens_at, lang), end: lastDay(survey.closes_at, lang) })}</span>
        )}
        <p className="desc">
          {t("İki haftada bir görüşünü soruyoruz. Yaklaşık 2 dakika. Dürüst ol —")}
          <b> {t("senin görüşün bizi iyileştirir.")}</b>
        </p>
        <TrustStrip />
      </div>

      {/* İlerleme */}
      <div className="survey-progress">
        <div className="survey-progress-track"><span style={{ width: `${pct}%` }} /></div>
        <span className="survey-progress-num">{t("{a}/{n} yanıtlandı", { a: answered, n: total })}</span>
      </div>

      <div className="survey-questions">
        {likert.map((q, i) => (
          <div key={q.key} className={`survey-q ${answers[q.key] ? "done" : ""}`}>
            <div className="survey-q-label"><span className="survey-q-no">{i + 1}</span>{q.label}</div>
            <div
              className="survey-scale"
              role="radiogroup"
              aria-label={q.label}
              tabIndex={0}
              onKeyDown={(e) => onScaleKey(e, q.key)}
            >
              {SCALE.map((s) => (
                <button
                  key={s.v}
                  type="button"
                  role="radio"
                  aria-checked={answers[q.key] === s.v}
                  className={`survey-opt ${answers[q.key] === s.v ? "active" : ""}`}
                  onClick={() => setAns(q.key, s.v)}
                  title={t(s.label)}
                >
                  <span className="survey-emoji">{s.emoji}</span>
                  <span className="survey-opt-label">{t(s.label)}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {textQs.map((q) => (
        <label key={q.key} className="survey-comment">
          {q.label} <span className="muted">({t("opsiyonel")})</span>
          <textarea
            rows={3}
            value={texts[q.key] || ""}
            maxLength={2000}
            onChange={(e) => setText(q.key, e.target.value)}
            placeholder={t("Serbest yorum — bu alan da anonimdir. Kendini tanıtan bilgi yazma.")}
          />
          <span className="survey-hint">{t("Bu alan da anonim. Seni belli edecek isim/detay yazma.")}</span>
        </label>
      ))}

      <div className="survey-submit-row">
        <button className="login-btn" onClick={submit} disabled={busy || !allAnswered}>
          {busy ? t("Gönderiliyor…") : t("Anonim gönder")}
        </button>
        <span className="survey-submit-note">{t("Geri alınamaz · dönem başına tek sefer")}</span>
      </div>
    </Shell>
  );
}
