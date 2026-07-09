import { useEffect, useState } from "react";
import {
  createProject, deleteProject, getProjectCommits, getProjectReviews,
  listProjects, reviewProject, syncProject,
} from "../api.js";

function scoreClass(s) {
  if (s == null) return "";
  if (s >= 75) return "good";
  if (s >= 50) return "warn";
  return "bad";
}

function ScoreBadge({ score }) {
  if (score == null) return <span className="score-badge none">skor yok</span>;
  return <span className={`score-badge ${scoreClass(score)}`}>{Math.round(score)}/100</span>;
}

// Projelerim: GitHub projesi ekle, commitleri gör, commit pratiği için
// AI/kural-tabanlı değerlendirme al. Admin "Tüm projeler" ile herkesinkini görür.
export default function ProjectsPanel({ isAdmin }) {
  const [projects, setProjects] = useState([]);
  const [showAll, setShowAll] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [commits, setCommits] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [detailBusy, setDetailBusy] = useState(false);

  function load() {
    listProjects(showAll && isAdmin).then(setProjects).catch((e) => setError(e.message));
  }
  useEffect(load, [showAll]);

  async function add(e) {
    e.preventDefault();
    setError(null); setMsg(null); setBusy(true);
    try {
      await createProject(name.trim(), url.trim());
      setMsg("Proje eklendi ve senkronize edildi.");
      setName(""); setUrl("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function doSync(p) {
    setError(null); setMsg(null);
    try {
      const res = await syncProject(p.id);
      setMsg(`${p.name}: ${res.added} yeni commit.`);
      load();
      if (openId === p.id) openDetail(p.id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function doDelete(p) {
    if (!window.confirm(`"${p.name}" projesi silinsin mi?`)) return;
    setError(null); setMsg(null);
    try {
      await deleteProject(p.id);
      if (openId === p.id) setOpenId(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function openDetail(id) {
    setOpenId(id);
    setDetailBusy(true);
    try {
      const [c, r] = await Promise.all([getProjectCommits(id), getProjectReviews(id)]);
      setCommits(c);
      setReviews(r);
    } catch (err) {
      setError(err.message);
    } finally {
      setDetailBusy(false);
    }
  }

  async function doReview(id) {
    setError(null); setMsg(null); setDetailBusy(true);
    try {
      await reviewProject(id);
      const r = await getProjectReviews(id);
      setReviews(r);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setDetailBusy(false);
    }
  }

  return (
    <div className="projects-panel">
      <section className="section">
        <div className="section-head">
          <h2>Proje ekle</h2>
          {isAdmin && (
            <label className="inline-check">
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
              Tüm kullanıcıların projeleri
            </label>
          )}
        </div>
        <form className="admin-form" onSubmit={add}>
          <label>Proje adı
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Örn. Kişisel API" required />
          </label>
          <label>GitHub adresi
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/kullanici/repo" required />
          </label>
          <button type="submit" className="login-btn" disabled={busy}>
            {busy ? "Ekleniyor…" : "Ekle ve senkronize et"}
          </button>
        </form>
        <p className="desc">Public repo tokensiz çalışır. Özel repo için sunucuda GITHUB_TOKEN gerekir.</p>
        {msg && <div className="admin-ok">{msg}</div>}
        {error && <div className="login-error">{error}</div>}
      </section>

      <section className="section">
        <h2>Projeler ({projects.length})</h2>
        {projects.length === 0 && <p className="desc">Henüz proje yok.</p>}
        <div className="project-cards">
          {projects.map((p) => (
            <div key={p.id} className="project-card">
              <div className="pc-head">
                <div>
                  <div className="pc-name">{p.name}</div>
                  {p.owner && <div className="pc-owner">{p.owner}</div>}
                  <a className="pc-url" href={p.url} target="_blank" rel="noreferrer">{p.url}</a>
                </div>
                <ScoreBadge score={p.latest_score} />
              </div>
              <div className="pc-meta">
                <span>{p.commit_count} commit</span>
                <span className={p.last_status === "error" ? "st-err" : "st-ok"}>
                  {p.last_status === "error" ? "hata" : "senkron"}
                  {p.last_run_at ? ` · ${new Date(p.last_run_at).toLocaleString("tr-TR")}` : ""}
                </span>
              </div>
              {p.last_status === "error" && p.last_detail && <div className="login-error small">{p.last_detail}</div>}
              <div className="pc-actions">
                <button className="mini" onClick={() => (openId === p.id ? setOpenId(null) : openDetail(p.id))}>
                  {openId === p.id ? "Gizle" : "Commitler & skor"}
                </button>
                <button className="mini" onClick={() => doSync(p)}>Senkronize et</button>
                <button className="mini danger" onClick={() => doDelete(p)}>Sil</button>
              </div>

              {openId === p.id && (
                <div className="pc-detail">
                  {detailBusy && <p className="desc">Yükleniyor…</p>}

                  <div className="pc-review-head">
                    <h4>Commit pratiği değerlendirmesi</h4>
                    <button className="mini" onClick={() => doReview(p.id)} disabled={detailBusy}>AI değerlendir</button>
                  </div>
                  {reviews.length === 0 ? (
                    <p className="desc">Henüz değerlendirme yok. "AI değerlendir" ile başlat.</p>
                  ) : (
                    <div className="review-latest">
                      <div className="review-top">
                        <ScoreBadge score={reviews[0].score} />
                        <span className="review-prov">
                          {reviews[0].provider === "rule" ? "kural tabanlı" : `AI (${reviews[0].provider})`}
                          {" · "}{reviews[0].commit_count} commit
                        </span>
                      </div>
                      <p className="review-summary">{reviews[0].summary}</p>
                      {reviews[0].details && (
                        <div className="review-bars">
                          {[["clarity", "Netlik"], ["length", "Uzunluk"], ["body", "Gövde"], ["convention", "Konvansiyon"], ["regularity", "Düzen"]].map(([k, lbl]) => (
                            reviews[0].details[k] != null && (
                              <div key={k} className="rbar">
                                <span className="rbar-lbl">{lbl}</span>
                                <span className="rbar-track"><span className="rbar-fill" style={{ width: `${reviews[0].details[k]}%` }} /></span>
                                <span className="rbar-val">{reviews[0].details[k]}</span>
                              </div>
                            )
                          ))}
                        </div>
                      )}
                      {reviews.length > 1 && (
                        <p className="desc">Önceki: {reviews.slice(1, 4).map((r) => `${Math.round(r.score)}`).join(", ")}</p>
                      )}
                    </div>
                  )}

                  <h4>Commitler ({commits.length})</h4>
                  <ul className="commit-list">
                    {commits.map((c) => (
                      <li key={c.sha}>
                        <code className="csha">{c.sha}</code>
                        <span className="cmsg">{c.message}</span>
                        <span className="cauthor">{c.author}{c.committed_at ? ` · ${new Date(c.committed_at).toLocaleDateString("tr-TR")}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
