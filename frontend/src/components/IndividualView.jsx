// Bireysel görünüm (Faz 4): yalnızca kişinin kendisi + yöneticisi erişebilir
// (sunucu tarafında zorlanır). Kıyas SADECE kişinin kendi geçmişiyle yapılır —
// başka kişiyle kıyas eden hiçbir öğe bu ekranda yoktur ve API'de de yoktur.
import { useEffect, useState } from "react";
import { api, oneOnOne } from "../api.js";
import MetricCard from "./MetricCard.jsx";
import Modal from "./Modal.jsx";

function scoreTone(score) {
  if (score === null || score === undefined) return "insufficient_data";
  if (score >= 8.5) return "green";
  if (score >= 7) return "green";
  if (score >= 5) return "yellow";
  return "red";
}

// Genel skor: performans notu değil, kişinin kendi akış özeti (10 üzerinden).
function OverallScore({ overall }) {
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
            {overall.covered}/{overall.total} metrik skora girdi (veri yetersiz olanlar hariç)
          </div>
        </div>
        <button className="mini" onClick={() => setOpen((v) => !v)}>
          {open ? "Kırılımı gizle" : "Nasıl hesaplandı?"}
        </button>
      </div>
      <div className="note">{overall.note}</div>
      {open && (
        <table className="score-breakdown">
          <thead>
            <tr><th>Metrik</th><th>Puan</th><th>Ağırlık</th></tr>
          </thead>
          <tbody>
            {overall.breakdown.map((b) => (
              <tr key={b.key} className={b.weight > 0 ? "" : "muted"}>
                <td>{b.name}</td>
                <td>{b.score === null ? "veri yetersiz" : b.score.toFixed(1)}</td>
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
  const has = data.score !== null && data.score !== undefined;
  return (
    <div className="alignment-card">
      <div className="alignment-head">
        <h3>Commit mesajı — kod eşleşmesi</h3>
        <span className={`badge status-${has ? scoreTone(data.score / 10) : "insufficient_data"}`}>
          {has ? `${data.score}/100` : "veri yetersiz"}
        </span>
      </div>
      <div className="desc">{data.summary}</div>
      {has && (
        <div className="desc">
          {data.checked} commit incelendi · %{Math.round((data.aligned_ratio || 0) * 100)} mesaj
          değişen kodla örtüşüyor
        </div>
      )}
      {data.samples && data.samples.length > 0 && (
        <ul className="alignment-samples">
          {data.samples.map((s) => (
            <li key={s.sha}>
              <code>{s.sha}</code> ({s.files} dosya, {s.score}/100)
              <ul>{s.issues.map((i, k) => <li key={k}>{i}</li>)}</ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function IndividualView({ devId }) {
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
          ? `Erişim yok: ${error.message}`
          : `Hata: ${error.message}`}
      </div>
    );
  if (!data) return <p className="desc">Yükleniyor…</p>;

  return (
    <div>
      <div className="indiv-head">
        <button className="mini" onClick={() => oneOnOne(devId).then(setPrep).catch((e) => setError(e))}>
          1:1 hazırlık özeti
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
        <Modal title={`1:1 hazırlık — ${prep.developer.display_name}`} onClose={() => setPrep(null)}>
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
