import { useEffect, useState } from "react";
import { genSurveyKey, getSurveyCycles, getSurveyResults, getSurveyStatus } from "../api.js";
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

          <div className="survey-comments">
            <h3>Yorumlar {res.comments?.length ? `(${res.comments.length})` : ""}</h3>
            <p className="desc">Karışık sırada, kimliksiz. Kişiye atfedilemez.</p>
            {res.comments && res.comments.length ? (
              <ul className="survey-comment-list">
                {res.comments.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            ) : (
              <p className="desc">Bu dönem yorum yok.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
