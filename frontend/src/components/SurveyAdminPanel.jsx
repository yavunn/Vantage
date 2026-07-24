import { useEffect, useState } from "react";
import {
  genSurveyKey, getSurveyCycles, getSurveyQuestions, getSurveyResults,
  getSurveyStatus, updateSurveyQuestions,
} from "../api.js";
import { toast } from "../toast.js";

// Admin: anket sonuçları — YALNIZ agrega. Kişi/isim yok; k-eşiği altında gizli.
// Şifreleme anahtarını yalnız baş yönetici (owner) üretir.
export default function SurveyAdminPanel({ me }) {
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
      toast(r.created ? "Şifreleme anahtarı üretildi" : "Anahtar zaten vardı", "ok");
      loadStatus();
    } catch (e) { toast(e.message, "error"); }
  }

  return (
    <div>
      <section className="section">
        <h2>Çalışan Memnuniyeti</h2>
        <p className="desc">
          İki haftada bir anonim anket. Sonuçlar <b>yalnız toplu</b> gösterilir —
          kim doldurdu asla belli olmaz. Gizlilik için en az{" "}
          <b>{status?.min_responses ?? 4}</b> cevap gerekir; altındaysa sonuç gizlenir.
        </p>
        {status && (
          <div className="ca-status">
            <span>Modül:{" "}
              <span className={`key-pill ${status.enabled ? "on" : "off"}`}>
                {status.enabled ? "açık" : "kapalı"}
              </span>
            </span>
            <span>Şifreleme:{" "}
              <span className={`key-pill ${status.key_configured ? "on" : "off"}`}>
                {status.key_configured ? "hazır" : "kurulmadı"}
              </span>
            </span>
            {!status.key_configured && isOwner && (
              <button className="mini" onClick={makeKey}>Şifreleme anahtarı üret</button>
            )}
            {!status.key_configured && !isOwner && (
              <span className="muted">· anahtarı baş yönetici üretir</span>
            )}
          </div>
        )}
      </section>

      <QuestionsEditor />

      <section className="section">
        <div className="ca-row">
          <label>Dönem:{" "}
            <select value={sel} onChange={(e) => setSel(e.target.value)}>
              <option value="">— güncel dönem —</option>
              {cycles.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.opens_at} – {c.closes_at} ({c.response_count} cevap)
                </option>
              ))}
            </select>
          </label>
        </div>
        {error && <p className="error-inline">{error.message}</p>}
        {!res ? (
          <p className="desc">Yükleniyor…</p>
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
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { getSurveyQuestions().then(setItems).catch(() => setItems([])); }, []);

  if (items == null) {
    return <section className="section"><p className="desc">Sorular yükleniyor…</p></section>;
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
    if (!items.length) { toast("En az bir soru gerekli", "error"); return; }
    if (items.some((q) => !q.label.trim())) { toast("Boş soru etiketi var", "error"); return; }
    if (likertCount < 1) { toast("En az bir likert (puan) sorusu gerekli", "error"); return; }
    setBusy(true);
    try {
      const payload = items.map((q) => ({
        key: q.key || undefined, label: q.label.trim(), type: q.type, required: !!q.required,
      }));
      const saved = await updateSurveyQuestions(payload);
      setItems(saved);
      toast("Sorular kaydedildi — sonraki dönemde geçerli", "ok");
    } catch (e) {
      toast(e.message, "error");
    } finally { setBusy(false); }
  }

  return (
    <section className="section">
      <h2>Anket Soruları</h2>
      <p className="desc">
        Soruları sen belirlersin. <b>1-5 puan</b> ortalama/trend üretir (en az biri
        zorunlu), <b>serbest yazı</b> anonim yorum toplar. Değişiklikler{" "}
        <b>bir sonraki dönemde</b> geçerli olur; açık dönem dondurulmuş sorularını korur.
      </p>
      <div className="sq-editor">
        {items.map((q, i) => (
          <div key={i} className="sq-row">
            <div className="sq-move">
              <button className="mini ghost" disabled={i === 0} onClick={() => move(i, -1)} title="Yukarı">▲</button>
              <button className="mini ghost" disabled={i === items.length - 1} onClick={() => move(i, 1)} title="Aşağı">▼</button>
            </div>
            <input className="sq-label" value={q.label} placeholder="Soru metni"
              onChange={(e) => upd(i, { label: e.target.value })} />
            <select value={q.type}
              onChange={(e) => upd(i, { type: e.target.value, required: e.target.value === "likert" ? q.required : false })}>
              <option value="likert">1-5 puan</option>
              <option value="text">Serbest yazı</option>
            </select>
            <label className="sq-req" title="Zorunlu yanıt">
              <input type="checkbox" checked={!!q.required} onChange={(e) => upd(i, { required: e.target.checked })} /> zorunlu
            </label>
            <button className="mini danger" onClick={() => remove(i)}>Sil</button>
          </div>
        ))}
      </div>
      <div className="sq-actions">
        <button className="mini" onClick={() => add("likert")}>+ Puan sorusu</button>
        <button className="mini" onClick={() => add("text")}>+ Yazı sorusu</button>
        <span style={{ flex: 1 }} />
        <button className="login-btn" disabled={busy || likertCount < 1} onClick={save}>
          {busy ? "Kaydediliyor…" : "Kaydet"}
        </button>
      </div>
      {likertCount < 1 && <p className="error-inline">En az bir likert (puan) sorusu gerekli.</p>}
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
  const partPct = res.participation_rate != null ? Math.round(res.participation_rate * 100) : null;

  return (
    <div className="survey-result">
      <div className="survey-kpis">
        <div className="survey-kpi">
          <div className="survey-kpi-num">{res.response_count}</div>
          <div className="survey-kpi-label">cevap</div>
        </div>
        <div className="survey-kpi">
          <div className="survey-kpi-num">{partPct != null ? `%${partPct}` : "–"}</div>
          <div className="survey-kpi-label">katılım ({res.participation}/{res.active_users})</div>
        </div>
      </div>

      {res.masked ? (
        <div className="survey-masked">
          🔒 Yeterli katılım yok — gizlilik için sonuç gösterilmiyor
          (en az {res.min_responses} cevap gerekir, şu an {res.response_count}).
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
          {(res.texts || (res.comments ? [{ key: "_all", label: "Yorumlar", comments: res.comments }] : [])).map((t) => (
            <div key={t.key} className="survey-comments">
              <h3>{t.label} {t.comments?.length ? `(${t.comments.length})` : ""}</h3>
              <p className="desc">Karışık sırada, kimliksiz. Kişiye atfedilemez.</p>
              {t.comments && t.comments.length ? (
                <ul className="survey-comment-list">
                  {t.comments.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              ) : (
                <p className="desc">Bu dönem bu soruya yazı yok.</p>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
