import { useEffect, useState } from "react";
import { analyzeTask, decideTaskLink, getTeamTaskLinks } from "../api.js";
import { useT } from "../i18n.jsx";

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
  const t = useT();
  const decided = link.status !== "suggested";
  // Konvansiyon bağı tahmin DEĞİLDİR: geliştirici commit mesajına kart
  // numarasını yazmıştır. Bunu "benzerlik 0.73" ile aynı satırda, aynı dille
  // göstermek ikisini eşit güvende gösterirdi — kullanıcı hangisine
  // güveneceğini bilemezdi.
  const kesin = link.matched_by === "convention";
  return (
    <li>
      <span>
        <span className={`badge link-${link.status}`}>{t(STATUS_LABEL[link.status])}</span>
        <span className="mono"> {link.sha}</span> {link.message}
        <span className="desc">
          {kesin
            ? ` · ${t("kesin bağ: commit mesajında kart numarası yazıyor")}`
            : link.matched_by === "manual"
              ? ` · ${t("elle bağlandı")}`
              : ` · ${t("benzerlik {score} (tahmin)", { score: link.score?.toFixed(3) ?? "—" })}`}
          {link.in_window ? ` · ${t("tarih uyumlu")}` : ` · ${t("tarih uyumsuz")}`}
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
            {t("Onayla")}
          </button>
          <button
            className="mini"
            disabled={busy || link.status === "rejected"}
            onClick={() => onDecide(link.commit_id, "rejected")}
          >
            {t("Reddet")}
          </button>
          {decided && <span className="desc"> · {t("karar verildi")}</span>}
        </span>
      )}
    </li>
  );
}

function TaskCard({ teamId, task, canManage, onChanged }) {
  const t = useT();
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
        {task.title || t("(başlıksız iş)")}
        <span className="role-tag">{task.status || t("statüsüz")}</span>
      </h3>
      <p className="desc">
        {t("{n} onaylı · {m} karar bekliyor", { n: task.confirmed, m: task.pending })}
        {task.task_key && (
          <>
            {" · "}
            {/* Konvansiyonu kullanabilmek için kişinin commit'e YAZACAĞI
                değeri görmesi gerekir; ekranda yoksa özellik ölü kalır. */}
            {t("commit mesajına")} <code>[#{task.task_key}]</code> {t("yazın, bağ tahmin edilmesin")}
            {task.task_url && (
              <>
                {" "}
                (<a href={task.task_url} target="_blank" rel="noreferrer">{t("kartı aç")}</a>)
              </>
            )}
          </>
        )}
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
        {busy ? t("Çalışıyor…") : t("Süreç analizi üret")}
      </button>
      {task.confirmed === 0 && (
        <span className="desc">
          {" "}{t("Analiz için en az bir onaylı bağ gerekir — analiz tahmine dayanmaz.")}
        </span>
      )}

      {analysis && (
        <div className={`warn-box ${analysis.status === "ok" ? "info" : "warn"}`}>
          {analysis.status === "ok" ? (
            <>
              {analysis.alignment && (
                <p>
                  <span className={`align-badge ${analysis.alignment}`}>
                    {analysis.alignment_label}
                  </span>
                  {analysis.alignment === "sapma" && (
                    <span className="desc">
                      {" "}{t("Sapma bir kusur işareti değil: çoğu zaman kart güncellenmemiştir ya da iş yol boyunca değişmiştir.")}
                    </span>
                  )}
                </p>
              )}
              <p>{analysis.analysis}</p>
              <p className="desc">
                {t("Kaynak commit: {list}", { list: analysis.commits_used.join(", ") })}
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
  const t = useT();
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
      <h2>{t("İş ↔ commit bağları")}</h2>
      <p className="desc">
        {t("Trello/Jira kartı ile commit arasında kaynaklarda")} <strong>{t("bağ yoktur")}</strong>.{" "}
        {t("Motor bunu başlık benzerliğinden tahmin eder ve")} <strong>{t("her tahmini doğru değildir")}</strong> —{" "}
        {t("ölçülen ilk sıra isabeti yaklaşık yarı yarıya. Bu yüzden süreç analizi yalnızca")} <strong>{t("sizin onayladığınız")}</strong>{t(" bağlardan üretilir.")}
      </p>
      <p className="desc">
        {t("Tahminden kurtulmanın yolu var: commit mesajına kartın numarasını")}{" "}
        <code>[#42]</code> {t("biçiminde (Jira'da")} <code>PROJ-123</code>{t(") yazın. O commit'in bağı tahmin edilmez,")} <strong>{t("kesin")}</strong> {t("kurulur ve onay beklemez. Numarayı her işin başlığının yanında bulabilirsiniz. Çıplak")}{" "}
        <code>#42</code> {t("kabul edilmez — git'te o, GitHub issue numarasıdır.")}
      </p>

      {list.length > 1 && (
        <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          {list.map((tm) => (
            <option key={tm.id} value={tm.id}>{tm.name}</option>
          ))}
        </select>
      )}

      {error && <div className="login-error">{error}</div>}
      {!data && !error && <p className="desc">{t("Yükleniyor…")}</p>}

      {data && data.tasks.length === 0 && (
        <p className="desc">
          {t("Bu takımda bağ önerisi olan iş yok. Senkron çalıştı mı ve RAG açık mı kontrol edin — öneriler senkronda üretilir.")}
        </p>
      )}

      {data &&
        data.tasks.map((tk) => (
          <TaskCard
            key={tk.task_id}
            teamId={Number(teamId)}
            task={tk}
            canManage={canManage}
            onChanged={load}
          />
        ))}
    </section>
  );
}
