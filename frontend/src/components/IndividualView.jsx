// Bireysel görünüm (Faz 4): yalnızca kişinin kendisi + yöneticisi erişebilir
// (sunucu tarafında zorlanır). Kıyas SADECE kişinin kendi geçmişiyle yapılır —
// başka kişiyle kıyas eden hiçbir öğe bu ekranda yoktur ve API'de de yoktur.
import { useEffect, useState } from "react";
import { api, oneOnOne } from "../api.js";
import MetricCard from "./MetricCard.jsx";
import Modal from "./Modal.jsx";
import { useT } from "../i18n.jsx";

function scoreTone(score) {
  if (score === null || score === undefined) return "insufficient_data";
  if (score >= 8.5) return "green";
  if (score >= 7) return "green";
  if (score >= 5) return "yellow";
  return "red";
}

// Genel skor: performans notu değil, kişinin kendi akış özeti (10 üzerinden).
function OverallScore({ overall }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const has = overall.score !== null && overall.score !== undefined;
  return (
    <div className={`overall-score status-${scoreTone(overall.score)}`}>
      <div className="overall-main">
        <div className="overall-value">
          {has ? overall.score.toFixed(1) : "—"}
          <span className="overall-max">/10</span>
        </div>
        <div className="overall-meta">
          <div className="overall-label">{overall.label}</div>
          <div className="desc">
            {t("{a}/{b} metrik skora girdi (veri yetersiz olanlar hariç)", { a: overall.covered, b: overall.total })}
          </div>
        </div>
        <button className="mini" onClick={() => setOpen((v) => !v)}>
          {open ? t("Kırılımı gizle") : t("Nasıl hesaplandı?")}
        </button>
      </div>
      <div className="note">{overall.note}</div>
      {open && (
        <table className="score-breakdown">
          <thead>
            <tr><th>{t("Metrik")}</th><th>{t("Puan")}</th><th>{t("Ağırlık")}</th></tr>
          </thead>
          <tbody>
            {overall.breakdown.map((b) => (
              <tr key={b.key} className={b.weight > 0 ? "" : "muted"}>
                <td>{b.name}</td>
                <td>{b.score === null ? t("veri yetersiz") : b.score.toFixed(1)}</td>
                <td>{b.weight > 0 ? b.weight.toFixed(2) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// Commit mesajı ↔ değişen kod eşleşmesi. Dürüstlük denetimi değil:
// mesajların sonradan okunabilir/aranabilir olmasını hedefler.
function CommitAlignment({ data }) {
  const t = useT();
  const has = data.score !== null && data.score !== undefined;
  return (
    <div className="alignment-card">
      <div className="alignment-head">
        <h3>{t("Commit mesajı — kod eşleşmesi")}</h3>
        <span className={`badge status-${has ? scoreTone(data.score / 10) : "insufficient_data"}`}>
          {has ? `${data.score}/100` : t("veri yetersiz")}
        </span>
      </div>
      <div className="desc">{data.summary}</div>
      {has && (
        <div className="desc">
          {t("{n} commit incelendi · %{pct} mesaj değişen kodla örtüşüyor",
            { n: data.checked, pct: Math.round((data.aligned_ratio || 0) * 100) })}
        </div>
      )}
      {data.samples && data.samples.length > 0 && (
        <ul className="alignment-samples">
          {data.samples.map((s) => (
            <li key={s.sha}>
              <code>{s.sha}</code> {t("({n} dosya, {score}/100)", { n: s.files, score: s.score })}
              <ul>{s.issues.map((i, k) => <li key={k}>{i}</li>)}</ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function IndividualView({ devId }) {
  const t = useT();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [prep, setPrep] = useState(null); // 1:1 hazırlık özeti

  useEffect(() => {
    setData(null);
    setError(null);
    setPrep(null);
    api(`/api/developers/${devId}/summary`)
      .then(setData)
      .catch((e) => setError(e));
  }, [devId]);

  if (error)
    return (
      <div className="error-box">
        {error.status === 403 || error.status === 401
          ? t("Erişim yok: {msg}", { msg: error.message })
          : t("Hata: {msg}", { msg: error.message })}
      </div>
    );
  if (!data) return <p className="desc">{t("Yükleniyor…")}</p>;

  return (
    <div>
      <div className="indiv-head">
        <button className="mini" onClick={() => oneOnOne(devId).then(setPrep).catch((e) => setError(e))}>
          {t("1:1 hazırlık özeti")}
        </button>
      </div>
      {data.overall && <OverallScore overall={data.overall} />}
      {data.commit_alignment && <CommitAlignment data={data.commit_alignment} />}
      <div className="cards">
        {data.metrics.map((m) => (
          <MetricCard key={m.key} metric={m} previous={m.previous_value} />
        ))}
      </div>
      <div className="note">{data.note}</div>

      {prep && (
        <Modal title={t("1:1 hazırlık — {name}", { name: prep.developer.display_name })} onClose={() => setPrep(null)}>
          <div className="prep-modal">
            {prep.talking_points.map((sec) => (
              <div key={sec.section} className={`prep-section tone-${sec.tone}`}>
                <h3>{sec.section}</h3>
                <ul>
                  {sec.items.map((it, i) => <li key={i}>{it}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}
