import { useEffect, useState } from "react";
import {
  createProject, deleteProject, getGithubCredential, getProjectCommits,
  getProjectReviews, listProjects, reviewProject, setGithubCredential, syncProject,
} from "../api.js";
import { useLang, useT } from "../i18n.jsx";

function scoreClass(s) {
  if (s == null) return "";
  if (s >= 75) return "good";
  if (s >= 50) return "warn";
  return "bad";
}

function ScoreBadge({ score }) {
  const t = useT();
  if (score == null) return <span className="score-badge none">{t("skor yok")}</span>;
  return <span className={`score-badge ${scoreClass(score)}`}>{Math.round(score)}/100</span>;
}

// Projelerim: GitHub projesi ekle, commitleri gör, commit pratiği için
// AI/kural-tabanlı değerlendirme al. Admin "Tüm projeler" ile herkesinkini görür.
export default function ProjectsPanel({ isAdmin, localEnabled }) {
  const t = useT();
  const { lang } = useLang();
  const [projects, setProjects] = useState([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  // github | local. Yerel kaynak ağa çıkmaz — gizli/bitmemiş repo için doğru
  // seçim. Yönetici izinli kök tanımlamadıysa seçenek hiç gösterilmez.
  const [sourceType, setSourceType] = useState("github");
  const [localPath, setLocalPath] = useState("");
  // Kendi GitHub anahtarım: özel repo eklemenin yolu. Anahtarın kendisi
  // sunucudan hiç dönmez, yalnız "tanımlı mı" + son 4 karakter.
  const [cred, setCred] = useState(null);
  const [tokenInput, setTokenInput] = useState("");
  const [credBusy, setCredBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [commits, setCommits] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [detailBusy, setDetailBusy] = useState(false);

  function load() {
    // Admin backend'de zaten hepsini görür; kullanıcı yalnız kendininki.
    listProjects(isAdmin).then(setProjects).catch((e) => setError(e.message));
  }
  useEffect(load, []);
  // Admin proje eklemediği için anahtar bölümü de ona gösterilmez.
  useEffect(() => {
    if (isAdmin) return;
    getGithubCredential().then(setCred).catch(() => setCred(null));
  }, [isAdmin]);

  async function saveToken(deger) {
    setError(null); setMsg(null); setCredBusy(true);
    try {
      setCred(await setGithubCredential(deger));
      setTokenInput("");
      setMsg(deger ? t("GitHub anahtarın kaydedildi.") : t("GitHub bağlantın kaldırıldı."));
    } catch (e) {
      setError(e.message);
    } finally {
      setCredBusy(false);
    }
  }

  async function add(e) {
    e.preventDefault();
    setError(null); setMsg(null); setBusy(true);
    try {
      await createProject(
        name.trim(),
        sourceType === "local"
          ? { type: "local", path: localPath.trim() }
          : { type: "github", url: url.trim() },
      );
      setMsg(t("Proje eklendi ve senkronize edildi."));
      setName(""); setUrl(""); setLocalPath("");
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
      setMsg(t("{name}: {n} yeni commit.", { name: p.name, n: res.added }));
      load();
      if (openId === p.id) openDetail(p.id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function doDelete(p) {
    if (!window.confirm(t('"{name}" projesi silinsin mi?', { name: p.name }))) return;
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

  const locale = lang === "en" ? "en-US" : "tr-TR";

  return (
    <div className="projects-panel">
      {isAdmin ? (
        <section className="section">
          <h2>{t("Tüm projeler")}</h2>
          <p className="desc">
            {t("Tüm kullanıcıların projeleri aşağıda. Yönetici proje")} <b>{t("eklemez")}</b> —{" "}
            {t("yalnız görüntüler (senkron/değerlendirme yapabilir).")}
          </p>
          {msg && <div className="admin-ok">{msg}</div>}
          {error && <div className="login-error">{error}</div>}
        </section>
      ) : (
        <>
        <section className="section">
          <h2>{t("GitHub bağlantım")}</h2>
          <p className="desc">
            {t("Özel (private) repolarını ekleyebilmek için")} <b>{t("kendi")}</b> {t("GitHub anahtarını gir. Anahtar şifreli saklanır, kimse (yönetici dahil) göremez ve yalnız senin projelerini çekmekte kullanılır. Fine-grained token yeter —")}{" "}
            <b>{t("Contents: Read-only")}</b>, {t('ve eklemek istediğin repolar "Repository access" listesinde olsun.')}
          </p>
          <div className="cred-row">
            <span className={cred?.configured ? "st-ok" : "st-err"}>
              {cred?.configured ? t("bağlı {hint}", { hint: cred.hint || "" }) : t("bağlı değil")}
            </span>
            <input type="password" autoComplete="off" value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder={cred?.configured ? t("•••• (değiştirmek için yaz)") : "github_pat_…"} />
            <button className="mini" disabled={credBusy || !tokenInput.trim()}
              onClick={() => saveToken(tokenInput.trim())}>
              {credBusy ? "…" : t("Kaydet")}
            </button>
            {cred?.configured && (
              <button className="mini ghost" disabled={credBusy}
                onClick={() => saveToken("")}>{t("Bağlantıyı kaldır")}</button>
            )}
          </div>
        </section>

        <section className="section">
          <h2>{t("Proje ekle")}</h2>
          <form className="admin-form" onSubmit={add}>
            <label>{t("Proje adı")}
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("Örn. Kişisel API")} required />
            </label>
            {localEnabled && (
              <label>{t("Kaynak")}
                <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
                  <option value="github">{t("GitHub reposu")}</option>
                  <option value="local">{t("Yerel klasör (ağa çıkmaz)")}</option>
                </select>
              </label>
            )}
            {sourceType === "local" ? (
              <label>{t("Klasör yolu")}
                <input value={localPath} onChange={(e) => setLocalPath(e.target.value)}
                  placeholder={t("Örn. C:\\Users\\ad\\Documents\\GitHub\\projem")} required />
              </label>
            ) : (
              <label>{t("GitHub adresi")}
                <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/kullanici/repo" required />
              </label>
            )}
            <button type="submit" className="login-btn" disabled={busy}>
              {busy ? t("Ekleniyor…") : t("Ekle ve senkronize et")}
            </button>
          </form>
          {sourceType === "local" ? (
            <p className="desc">
              {t("Yerel klasör doğrudan diskten okunur — token gerekmez, kod makineden çıkmaz. Yalnız yöneticinin izin verdiği kök klasörler altındaki git depoları eklenebilir.")} <b>{t("Gizli repolar için önerilen yol budur.")}</b>
            </p>
          ) : (
            <p className="desc">
              {t("Public repo tokensiz çalışır. Özel repo için sunucuda GITHUB_TOKEN gerekir")}
              {localEnabled && <> {t("— ya da yukarıdan")} <b>{t("Yerel klasör")}</b> {t("seçin, token gerekmez")}</>}.
            </p>
          )}
          {msg && <div className="admin-ok">{msg}</div>}
          {error && <div className="login-error">{error}</div>}
        </section>
        </>
      )}

      <section className="section">
        <h2>{isAdmin ? t("Tüm kullanıcı projeleri") : t("Projelerim")} ({projects.length})</h2>
        {projects.length === 0 && <p className="desc">{t("Henüz proje yok.")}</p>}
        <div className="project-cards">
          {projects.map((p) => (
            <div key={p.id} className="project-card">
              <div className="pc-head">
                <div>
                  <div className="pc-name">{p.name}</div>
                  {p.owner && <div className="pc-owner">{p.owner}</div>}
                  {/* Yerel kaynak bir URL değil, disk yolu — link yapmak kırık
                      bağlantı üretirdi. Rozetle kaynağı da görünür kılıyoruz. */}
                  {p.source_type === "local" ? (
                    <div className="pc-url"><span className="pc-src">{t("yerel")}</span> {p.url}</div>
                  ) : (
                    <a className="pc-url" href={p.url} target="_blank" rel="noreferrer">{p.url}</a>
                  )}
                </div>
                <ScoreBadge score={p.latest_score} />
              </div>
              <div className="pc-meta">
                <span>{t("{n} commit", { n: p.commit_count })}</span>
                <span className={p.last_status === "error" ? "st-err" : "st-ok"}>
                  {p.last_status === "error" ? t("hata") : t("senkron")}
                  {p.last_run_at ? ` · ${new Date(p.last_run_at).toLocaleString(locale)}` : ""}
                </span>
              </div>
              {p.last_status === "error" && p.last_detail && <div className="login-error small">{p.last_detail}</div>}
              <div className="pc-actions">
                <button className="mini" onClick={() => (openId === p.id ? setOpenId(null) : openDetail(p.id))}>
                  {openId === p.id ? t("Gizle") : t("Commitler & skor")}
                </button>
                <button className="mini" onClick={() => doSync(p)}>{t("Senkronize et")}</button>
                <button className="mini danger" onClick={() => doDelete(p)}>{t("Sil")}</button>
              </div>

              {openId === p.id && (
                <div className="pc-detail">
                  {detailBusy && <p className="desc">{t("Yükleniyor…")}</p>}

                  <div className="pc-review-head">
                    <h4>{t("Commit pratiği değerlendirmesi")}</h4>
                    <button className="mini" onClick={() => doReview(p.id)} disabled={detailBusy}>{t("AI değerlendir")}</button>
                  </div>
                  {reviews.length === 0 ? (
                    <p className="desc">{t('Henüz değerlendirme yok. "AI değerlendir" ile başlat.')}</p>
                  ) : (
                    <div className="review-latest">
                      <div className="review-top">
                        <ScoreBadge score={reviews[0].score} />
                        <span className="review-prov">
                          {reviews[0].provider === "rule" ? t("kural tabanlı") : t("AI ({provider})", { provider: reviews[0].provider })}
                          {" · "}{t("{n} commit", { n: reviews[0].commit_count })}
                        </span>
                      </div>
                      <p className="review-summary">{reviews[0].summary}</p>
                      {reviews[0].details && (
                        <div className="review-bars">
                          {[["clarity", "Netlik"], ["length", "Uzunluk"], ["body", "Gövde"], ["convention", "Konvansiyon"], ["regularity", "Düzen"]].map(([k, lbl]) => (
                            reviews[0].details[k] != null && (
                              <div key={k} className="rbar">
                                <span className="rbar-lbl">{t(lbl)}</span>
                                <span className="rbar-track"><span className="rbar-fill" style={{ width: `${reviews[0].details[k]}%` }} /></span>
                                <span className="rbar-val">{reviews[0].details[k]}</span>
                              </div>
                            )
                          ))}
                        </div>
                      )}
                      {reviews.length > 1 && (
                        <p className="desc">{t("Önceki: {list}", { list: reviews.slice(1, 4).map((r) => `${Math.round(r.score)}`).join(", ") })}</p>
                      )}
                    </div>
                  )}

                  <h4>{t("Commitler ({n})", { n: commits.length })}</h4>
                  <ul className="commit-list">
                    {commits.map((c) => (
                      <li key={c.sha}>
                        <code className="csha">{c.sha}</code>
                        <span className="cmsg">{c.message}</span>
                        <span className="cauthor">{c.author}{c.committed_at ? ` · ${new Date(c.committed_at).toLocaleDateString(locale)}` : ""}</span>
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
