import { useEffect, useState } from "react";
import {
  genSurveyKey, getSettings, getSurveyCycles, getSurveyQuestions, getSurveyResults,
  getSurveyStatus, updateSettings, updateSurveyQuestions,
} from "../api.js";
import { toast } from "../toast.js";
import { useT } from "../i18n.jsx";

// Anket ayarları sonuçlarla aynı sekmede durur: ayarı değiştiren kişi etkisini
// hemen aynı ekranda görür, ikinci bir kopyası başka yerde yaşamaz.
function SurveySettings({ onSaved }) {
  const t = useT();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings().then((d) => setForm(d.survey)).catch(() => setForm(null));
  }, []);

  if (!form) return null;

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await updateSettings({
        survey_enabled: form.enabled,
        survey_interval_days: Number(form.interval_days),
        survey_min_responses: Number(form.min_responses),
      });
      toast(t("Anket ayarları kaydedildi"), "ok");
      onSaved && onSaved();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <section className="section">
      <h2>{t("Anket ayarları")}</h2>
      <form className="settings-admin" onSubmit={save}>
        <label className="switch-row">
          <input type="checkbox" checked={form.enabled}
                 onChange={(e) => upd("enabled", e.target.checked)} />
          <span>
            <strong>{t("Anket açık")}</strong>
            <em>{t("Kapalıyken kimseye anket gösterilmez ve yeni döngü açılmaz.")}</em>
          </span>
        </label>
        <div className="grid-2">
          <label>
            {t("Döngü aralığı (gün)")}
            <input type="number" min={1} value={form.interval_days}
                   onChange={(e) => upd("interval_days", e.target.value)} />
          </label>
          <label>
            {t("Asgari yanıt (gizlilik eşiği)")}
            <input type="number" min={1} value={form.min_responses}
                   onChange={(e) => upd("min_responses", e.target.value)} />
            <span className="field-hint">
              {t("Bu sayının altında sonuç gösterilmez — tek yanıt ifşa olmasın.")}
            </span>
          </label>
        </div>
        <div className="settings-actions">
          <button className="login-btn" type="submit" disabled={saving}>
            {saving ? t("Kaydediliyor…") : t("Anket ayarlarını kaydet")}
          </button>
        </div>
      </form>
    </section>
  );
}

// Admin: anket sonuçları — YALNIZ agrega. Kişi/isim yok; k-eşiği altında gizli.
// Şifreleme anahtarını yalnız baş yönetici (owner) üretir.
export default function SurveyAdminPanel({ me }) {
  const t = useT();
  const isOwner = !!(me && me.is_owner);
  const [status, setStatus] = useState(null);
  const [cycles, setCycles] = useState([]);
  const [sel, setSel] = useState("");
  const [res, setRes] = useState(null);
  const [error, setError] = useState(null);

  function loadStatus() { getSurveyStatus().then(setStatus).catch(() => setStatus(null)); }
  function loadCycles() { getSurveyCycles().then(setCycles).catch(() => setCycles([])); }
  useEffect(() => { loadStatus(); loadCycles(); }, []);

  useEffect(() => {
    getSurveyResults(sel || undefined).then(setRes).catch(setError);
  }, [sel]);

  async function makeKey() {
    try {
      const r = await genSurveyKey();
      toast(r.created ? t("Şifreleme anahtarı üretildi") : t("Anahtar zaten vardı"), "ok");
      loadStatus();
    } catch (e) { toast(e.message, "error"); }
  }

  return (
    <div>
      <section className="section">
        <h2>{t("Çalışan Memnuniyeti")}</h2>
        <p className="desc">
          {t("İki haftada bir anonim anket. Sonuçlar")} <b>{t("yalnız toplu")}</b> {t("gösterilir — kim doldurdu asla belli olmaz. Gizlilik için en az")}{" "}
          <b>{status?.min_responses ?? 4}</b> {t("cevap gerekir; altındaysa sonuç gizlenir.")}
        </p>
        {status && (
          <div className="ca-status">
            <span>{t("Modül:")}{" "}
              <span className={`key-pill ${status.enabled ? "on" : "off"}`}>
                {status.enabled ? t("açık") : t("kapalı")}
              </span>
            </span>
            <span>{t("Şifreleme:")}{" "}
              <span className={`key-pill ${status.key_configured ? "on" : "off"}`}>
                {status.key_configured ? t("hazır") : t("kurulmadı")}
              </span>
            </span>
            {!status.key_configured && isOwner && (
              <button className="mini" onClick={makeKey}>{t("Şifreleme anahtarı üret")}</button>
            )}
            {!status.key_configured && !isOwner && (
              <span className="muted">· {t("anahtarı baş yönetici üretir")}</span>
            )}
          </div>
        )}
      </section>

      <SurveySettings onSaved={loadStatus} />

      <QuestionsEditor />

      <section className="section">
        <div className="ca-row">
          <label>{t("Dönem:")}{" "}
            <select value={sel} onChange={(e) => setSel(e.target.value)}>
              <option value="">{t("— güncel dönem —")}</option>
              {cycles.map((c) => (
                <option key={c.key} value={c.key}>
                  {t("{start} – {end} ({n} cevap)", { start: c.opens_at, end: c.closes_at, n: c.response_count })}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error && <p className="error-inline">{error.message}</p>}
        {!res ? (
          <p className="desc">{t("Yükleniyor…")}</p>
        ) : (
          <SurveyResult res={res} />
        )}
      </section>
    </div>
  );
}

// Admin soru editörü: sıralı liste, ekle/sil/taşı, tip + zorunlu. Kaydet → PUT.
// Değişiklik yalnız SONRAKİ döngüde geçerli (backend snapshot ile izole eder).
function QuestionsEditor() {
  const t = useT();
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { getSurveyQuestions().then(setItems).catch(() => setItems([])); }, []);

  if (items == null) {
    return <section className="section"><p className="desc">{t("Sorular yükleniyor…")}</p></section>;
  }
  const likertCount = items.filter((q) => q.type === "likert").length;

  function upd(i, patch) {
    setItems((list) => list.map((q, idx) => (idx === i ? { ...q, ...patch } : q)));
  }
  function add(type) {
    setItems((list) => [...list, { key: "", label: "", type, required: type === "likert" }]);
  }
  function remove(i) {
    setItems((list) => list.filter((_, idx) => idx !== i));
  }
  function move(i, dir) {
    setItems((list) => {
      const j = i + dir;
      if (j < 0 || j >= list.length) return list;
      const n = [...list];
      [n[i], n[j]] = [n[j], n[i]];
      return n;
    });
  }

  async function save() {
    if (!items.length) { toast(t("En az bir soru gerekli"), "error"); return; }
    if (items.some((q) => !q.label.trim())) { toast(t("Boş soru etiketi var"), "error"); return; }
    if (likertCount < 1) { toast(t("En az bir likert (puan) sorusu gerekli"), "error"); return; }
    setBusy(true);
    try {
      const payload = items.map((q) => ({
        key: q.key || undefined, label: q.label.trim(), type: q.type, required: !!q.required,
      }));
      const saved = await updateSurveyQuestions(payload);
      setItems(saved);
      toast(t("Sorular kaydedildi — sonraki dönemde geçerli"), "ok");
    } catch (e) {
      toast(e.message, "error");
    } finally { setBusy(false); }
  }

  return (
    <section className="section">
      <h2>{t("Anket Soruları")}</h2>
      <p className="desc">
        {t("Soruları sen belirlersin.")} <b>{t("1-5 puan")}</b> {t("ortalama/trend üretir (en az biri zorunlu),")} <b>{t("serbest yazı")}</b> {t("anonim yorum toplar. Değişiklikler")}{" "}
        <b>{t("bir sonraki dönemde")}</b> {t("geçerli olur; açık dönem dondurulmuş sorularını korur.")}
      </p>
      <div className="sq-editor">
        {items.map((q, i) => (
          <div key={i} className="sq-row">
            <div className="sq-move">
              <button className="mini ghost" disabled={i === 0} onClick={() => move(i, -1)} title={t("Yukarı")}>▲</button>
              <button className="mini ghost" disabled={i === items.length - 1} onClick={() => move(i, 1)} title={t("Aşağı")}>▼</button>
            </div>
            <input className="sq-label" value={q.label} placeholder={t("Soru metni")}
              onChange={(e) => upd(i, { label: e.target.value })} />
            <select value={q.type}
              onChange={(e) => upd(i, { type: e.target.value, required: e.target.value === "likert" ? q.required : false })}>
              <option value="likert">{t("1-5 puan")}</option>
              <option value="text">{t("Serbest yazı")}</option>
            </select>
            <label className="sq-req" title={t("Zorunlu yanıt")}>
              <input type="checkbox" checked={!!q.required} onChange={(e) => upd(i, { required: e.target.checked })} /> {t("zorunlu")}
            </label>
            <button className="mini danger" onClick={() => remove(i)}>{t("Sil")}</button>
          </div>
        ))}
      </div>
      <div className="sq-actions">
        <button className="mini" onClick={() => add("likert")}>{t("+ Puan sorusu")}</button>
        <button className="mini" onClick={() => add("text")}>{t("+ Yazı sorusu")}</button>
        <span style={{ flex: 1 }} />
        <button className="login-btn" disabled={busy || likertCount < 1} onClick={save}>
          {busy ? t("Kaydediliyor…") : t("Kaydet")}
        </button>
      </div>
      {likertCount < 1 && <p className="error-inline">{t("En az bir likert (puan) sorusu gerekli.")}</p>}
    </section>
  );
}

function Bar({ label, value, pct }) {
  return (
    <div className="survey-dist-row">
      <span className="survey-dist-label">{label}</span>
      <div className="survey-dist-track">
        <span className="survey-dist-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="survey-dist-num">{value}</span>
    </div>
  );
}

function SurveyResult({ res }) {
  const t = useT();
  const partPct = res.participation_rate != null ? Math.round(res.participation_rate * 100) : null;

  return (
    <div className="survey-result">
      <div className="survey-kpis">
        <div className="survey-kpi">
          <div className="survey-kpi-num">{res.response_count}</div>
          <div className="survey-kpi-label">{t("cevap")}</div>
        </div>
        <div className="survey-kpi">
          <div className="survey-kpi-num">{partPct != null ? `%${partPct}` : "–"}</div>
          <div className="survey-kpi-label">{t("katılım ({a}/{n})", { a: res.participation, n: res.active_users })}</div>
        </div>
      </div>

      {res.masked ? (
        <div className="survey-masked">
          🔒 {t("Yeterli katılım yok — gizlilik için sonuç gösterilmiyor (en az {min} cevap gerekir, şu an {cur}).",
            { min: res.min_responses, cur: res.response_count })}
        </div>
      ) : (
        <>
          <div className="survey-scores">
            {res.scores.map((s) => {
              const q = res.questions.find((x) => x.key === s.key);
              const max = Math.max(1, ...Object.values(s.distribution));
              return (
                <div key={s.key} className="survey-score-card">
                  <div className="survey-score-head">
                    <span className="survey-score-label">{q ? q.label : s.key}</span>
                    <span className="survey-score-avg">
                      {s.average != null ? s.average.toFixed(2) : "–"}<small>/5</small>
                    </span>
                  </div>
                  <div className="survey-dist">
                    {[5, 4, 3, 2, 1].map((n) => (
                      <Bar key={n} label={n} value={s.distribution[n]}
                        pct={Math.round((s.distribution[n] / max) * 100)} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Her serbest-yazı sorusu ayrı blok; karışık sıra, kimliksiz. Eski
              agrega yanıtı için res.comments'e düşülür (geriye uyum). */}
          {(res.texts || (res.comments ? [{ key: "_all", label: t("Yorumlar"), comments: res.comments }] : [])).map((blk) => (
            <div key={blk.key} className="survey-comments">
              <h3>{blk.label} {blk.comments?.length ? `(${blk.comments.length})` : ""}</h3>
              <p className="desc">{t("Karışık sırada, kimliksiz. Kişiye atfedilemez.")}</p>
              {blk.comments && blk.comments.length ? (
                <ul className="survey-comment-list">
                  {blk.comments.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              ) : (
                <p className="desc">{t("Bu dönem bu soruya yazı yok.")}</p>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
