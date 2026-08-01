import { useEffect, useState } from "react";
import { analyzeTask, decideTaskLink, getTeamTaskLinks } from "../api.js";

// Task ↔ commit onay ekranı.
//
// Neden onay gerekiyor: kaynaklarda bu bağ YOK. Trello kart id'si commit
// mesajında geçmiyor, task'ların çoğunda atanan kişi boş. Motor bağı başlık ile
// commit mesajının anlamsal benzerliğinden TAHMİN ediyor ve ölçüldüğünde ilk
// sıra isabeti ~%50 çıktı (Türkçe kart başlığı ↔ İngilizce commit mesajı).
//
// Bu yüzden ekran skoru GİZLEMİYOR: kullanıcı neye baktığını bilmeli. Analiz
// yalnız onaylanan bağlardan üretilir — sistem tahmin üstüne yorum yazmaz.

const STATUS_LABEL = {
  suggested: "öneri",
  confirmed: "onaylı",
  rejected: "reddedildi",
};

function LinkRow({ link, canManage, busy, onDecide }) {
  const decided = link.status !== "suggested";
  return (
    <li>
      <span>
        <span className={`badge link-${link.status}`}>{STATUS_LABEL[link.status]}</span>
        <span className="mono"> {link.sha}</span> {link.message}
        <span className="desc">
          {" · "}benzerlik {link.score?.toFixed(3) ?? "—"}
          {link.in_window ? " · tarih uyumlu" : " · tarih uyumsuz"}
          {link.committed_at ? ` · ${link.committed_at.slice(0, 10)}` : ""}
        </span>
      </span>
      {canManage && (
        <span>
          <button
            className="mini"
            disabled={busy || link.status === "confirmed"}
            onClick={() => onDecide(link.commit_id, "confirmed")}
          >
            Onayla
          </button>
          <button
            className="mini"
            disabled={busy || link.status === "rejected"}
            onClick={() => onDecide(link.commit_id, "rejected")}
          >
            Reddet
          </button>
          {decided && <span className="desc"> · karar verildi</span>}
        </span>
      )}
    </li>
  );
}

function TaskCard({ teamId, task, canManage, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [error, setError] = useState(null);

  async function decide(commitId, status) {
    setBusy(true);
    setError(null);
    try {
      await decideTaskLink(teamId, task.task_id, commitId, status);
      // Bağ değişti → eski analiz artık başka bir veriye dayanıyor, göstermeyi bırak.
      setAnalysis(null);
      await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function runAnalysis() {
    setBusy(true);
    setError(null);
    try {
      setAnalysis(await analyzeTask(teamId, task.task_id));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="task-link-card">
      <h3>
        {task.title || "(başlıksız iş)"}
        <span className="role-tag">{task.status || "statüsüz"}</span>
      </h3>
      <p className="desc">
        {task.confirmed} onaylı · {task.pending} karar bekliyor
      </p>

      <ul className="team-list">
        {task.links.map((l) => (
          <LinkRow
            key={l.commit_id}
            link={l}
            canManage={canManage}
            busy={busy}
            onDecide={decide}
          />
        ))}
      </ul>

      {error && <div className="login-error">{error}</div>}

      <button className="mini" disabled={busy || task.confirmed === 0} onClick={runAnalysis}>
        {busy ? "Çalışıyor…" : "Süreç analizi üret"}
      </button>
      {task.confirmed === 0 && (
        <span className="desc">
          {" "}Analiz için en az bir onaylı bağ gerekir — analiz tahmine dayanmaz.
        </span>
      )}

      {analysis && (
        <div className={`warn-box ${analysis.status === "ok" ? "info" : "warn"}`}>
          {analysis.status === "ok" ? (
            <>
              <p>{analysis.analysis}</p>
              <p className="desc">
                Kaynak commit: {analysis.commits_used.join(", ")}
              </p>
            </>
          ) : (
            <p>{analysis.reason}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function TaskLinksPanel({ teams, canManage }) {
  const list = teams || [];
  const [teamId, setTeamId] = useState(() => (list[0] ? String(list[0].id) : ""));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    if (!teamId) return;
    try {
      setError(null);
      setData(await getTeamTaskLinks(Number(teamId)));
    } catch (e) {
      setError(e.message);
      setData(null);
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId]);

  return (
    <section className="section">
      <h2>İş ↔ commit bağları</h2>
      <p className="desc">
        Trello/Jira kartı ile commit arasında kaynaklarda <strong>bağ yoktur</strong>.
        Motor bunu başlık benzerliğinden tahmin eder ve <strong>her tahmini doğru
        değildir</strong> — ölçülen ilk sıra isabeti yaklaşık yarı yarıya. Bu yüzden
        süreç analizi yalnızca <strong>sizin onayladığınız</strong> bağlardan üretilir.
      </p>

      {list.length > 1 && (
        <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          {list.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      )}

      {error && <div className="login-error">{error}</div>}
      {!data && !error && <p className="desc">Yükleniyor…</p>}

      {data && data.tasks.length === 0 && (
        <p className="desc">
          Bu takımda bağ önerisi olan iş yok. Senkron çalıştı mı ve RAG açık mı
          kontrol edin — öneriler senkronda üretilir.
        </p>
      )}

      {data &&
        data.tasks.map((t) => (
          <TaskCard
            key={t.task_id}
            teamId={Number(teamId)}
            task={t}
            canManage={canManage}
            onChanged={load}
          />
        ))}
    </section>
  );
}
