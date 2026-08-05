import { useEffect, useState } from "react";
import {
  getSources,
  listIdentities,
  mergeDevelopers,
  setTaskIdentity,
  testSources,
  triggerSync,
  syncStatus,
  updateSources,
} from "../api.js";
import { useLang, useT } from "../i18n.jsx";
import SmtpSettings from "./SmtpSettings.jsx";

const GIT_PROVIDERS = ["fixture", "git_log", "github", "gitlab"];
const TASK_PROVIDERS = ["fixture", "jira", "trello", "none"];
const NO_TEAM = "";

function TokenBadge({ token }) {
  const t = useT();
  if (!token) return null;
  return (
    <span className={`token-badge ${token.configured ? "ok" : "missing"}`}>
      {token.env_var}: {token.configured ? t("tanımlı") : t("tanımsız")}
    </span>
  );
}

// Sessiz başarısızlık yok: okunamayan board/repo burada görünür.
function WarnBox({ items, tone = "warn", title }) {
  if (!items || items.length === 0) return null;
  return (
    <div className={`warn-box ${tone}`}>
      {title && <strong>{title}</strong>}
      <ul>
        {items.map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </div>
  );
}

// Kimlik eşleme: aynı insan git'te e-postasıyla, Trello'da üye id'siyle gelir.
// İki ayrı kayıt kalırsa takım kadrosu şişer ve WIP kişi başına bölündüğü için
// metrik olduğundan İYİ görünür — o yüzden eşleme burada görünür kılınır.
function IdentitySection({ nonce }) {
  const t = useT();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [target, setTarget] = useState({});
  const [busy, setBusy] = useState(null);
  // Elle birleştirme: aynı insan İKİ git e-postasıyla geldiyse (ör. biri
  // GitHub'ın …@users.noreply.github.com adresi) iki kayıt da "eşlenmiş"
  // görünür; otomatik ipucu yoktur, kararı insan verir.
  const [mergeInto, setMergeInto] = useState({});

  function load() {
    listIdentities().then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, [nonce]);

  async function merge(row) {
    const targetId = target[row.id];
    if (!targetId) return;
    const [source, key] = Object.entries(row.task_identities)[0] || [];
    if (!source) return;
    setError(null);
    setMsg(null);
    setBusy(row.id);
    try {
      const res = await setTaskIdentity(Number(targetId), source, key);
      setMsg(
        res.merged_developer_id
          ? t("Eşlendi — kopya kayıt birleştirildi (görevler ve takım üyelikleri taşındı).")
          : t("Eşlendi.")
      );
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function mergeManual(row) {
    const targetId = Number(mergeInto[row.id]);
    if (!targetId) return;
    const hedef = rows.find((r) => r.id === targetId);
    // Geri alınamaz: kopyanın commit/görev/izin kayıtları hedefe taşınır ve
    // kayıt SİLİNİR. Onaysız yapılmaz.
    const ok = window.confirm(
      t('"{name}" kaydı "{target}" içine birleştirilecek.\n\n{commits} commit ve {tasks} görev hedefe taşınacak, sonra bu kayıt silinecek. Bu işlem geri alınamaz.',
        { name: row.display_name, target: hedef?.display_name, commits: row.commit_count ?? 0, tasks: row.task_count ?? 0 })
    );
    if (!ok) return;
    setError(null);
    setMsg(null);
    setBusy(row.id);
    try {
      const res = await mergeDevelopers(targetId, row.id);
      const tasinan = Object.entries(res.moved || {})
        .map(([tablo, n]) => `${n} ${tablo}`).join(", ");
      setMsg(tasinan ? t("Birleştirildi — taşınan: {list}.", { list: tasinan }) : t("Birleştirildi (taşınacak kayıt yoktu)."));
      setMergeInto({});
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (error && !rows) return <div className="login-error">{error}</div>;
  if (!rows) return <p className="desc">{t("Yükleniyor…")}</p>;

  const unlinked = rows.filter((r) => r.unlinked);
  // Hedef yalnızca "gerçek" kişi olabilir: giriş hesabı ya da git kimliği olan.
  const anchors = rows.filter((r) => r.user_email || r.git_email);

  return (
    <section className="section">
      <h2>{t("Kimlik eşleme")}</h2>
      <p className="desc">
        {t("Bir kişi git'te e-postasıyla, Trello'da üye id'siyle görünür. Eşlenmezse aynı insan iki kez sayılır; takım kadrosu şişer ve")}{" "}
        <strong>{t("WIP kişi başına bölündüğü için metrik olduğundan iyi görünür")}</strong>.
      </p>

      {unlinked.length === 0 ? (
        <p className="desc">
          {t("Otomatik yakalanan eşlenmemiş kayıt yok. Aynı kişinin iki ayrı kayda bölünmüş olabileceğini düşünüyorsan aşağıdaki tam listeye bak.")}
        </p>
      ) : (
        <ul className="team-list">
          {unlinked.map((r) => (
            <li key={r.id}>
              <span>
                {r.display_name}
                <span className="role-tag">
                  {Object.entries(r.task_identities).map(([s]) => s).join(", ")}
                </span>
                <span className="desc"> · {t("{n} görev", { n: r.task_count })} · {t("{n} takım", { n: r.team_count })}</span>
              </span>
              <span>
                <select
                  value={target[r.id] ?? ""}
                  onChange={(e) => setTarget((tg) => ({ ...tg, [r.id]: e.target.value }))}
                >
                  <option value="">{t("Şu kişiyle birleştir…")}</option>
                  {anchors.filter((a) => a.id !== r.id).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.display_name}{a.user_email ? ` (${a.user_email})` : ""}
                    </option>
                  ))}
                </select>
                <button
                  className="mini"
                  onClick={() => merge(r)}
                  disabled={!target[r.id] || busy === r.id}
                >
                  {busy === r.id ? t("Birleştiriliyor…") : t("Birleştir")}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <details className="identity-all">
        <summary>{t("Tüm kimlikler ({n}) — elle birleştirme", { n: rows.length })}</summary>
        <p className="desc">
          {t("Yukarıdaki otomatik eşleme yalnız")} <strong>{t("git kimliği olmayan")}</strong>{" "}
          {t("kayıtları yakalar. Aynı insan")} <strong>{t("iki git e-postasıyla")}</strong>{" "}
          {t("gelmişse (ör. biri GitHub'ın")} <code>…@users.noreply.github.com</code> {t("adresi) iki kayıt da \"eşlenmiş\" görünür ve otomatik ipucu yoktur — commit'ler birine, görevler diğerine düşer. Böyle bir çift görüyorsan burada birleştir. Hedef,")}{" "}
          <strong>{t("ağırlığı taşıyan")}</strong> {t("kayıt olmalı.")}
        </p>
        <ul className="team-list">
          {rows.map((r) => (
            <li key={r.id}>
              <span>
                {r.display_name}
                {r.user_email && <span className="role-tag">{t("hesap")}</span>}
                <span className="desc">
                  {" "}· {t("{n} commit", { n: r.commit_count ?? 0 })} · {t("{n} görev", { n: r.task_count ?? 0 })}
                </span>
              </span>
              <span className="desc">
                {r.git_email || t("git yok")} ·{" "}
                {Object.entries(r.task_identities).map(([s, k]) => `${s}:${k.slice(0, 8)}…`).join(" ") || t("görev kimliği yok")}
              </span>
              <span>
                <select
                  value={mergeInto[r.id] ?? ""}
                  onChange={(e) => setMergeInto((tg) => ({ ...tg, [r.id]: e.target.value }))}
                >
                  <option value="">{t("Bu kaydı şuna birleştir…")}</option>
                  {rows.filter((a) => a.id !== r.id).map((a) => (
                    <option key={a.id} value={a.id}>
                      {t("{name} ({n} commit)", { name: a.display_name, n: a.commit_count ?? 0 })}
                    </option>
                  ))}
                </select>
                <button
                  className="mini danger"
                  onClick={() => mergeManual(r)}
                  disabled={!mergeInto[r.id] || busy === r.id}
                >
                  {busy === r.id ? t("Birleştiriliyor…") : t("Birleştir")}
                </button>
              </span>
            </li>
          ))}
        </ul>
      </details>

      {msg && <div className="admin-ok">{msg}</div>}
      {error && <div className="login-error">{error}</div>}
    </section>
  );
}

// Repo → takım eşlemesi. Takımsız repo'nun commitleri hiçbir takım metriğine
// giremez (metrik motoru commitleri takımın repolarından çeker), o yüzden bu
// eşleme config'i elle düzenlemeye bırakılmaz.
function RepoRow({ repo, teams, provider, onChange, onRemove }) {
  const t = useT();
  const unmapped = !repo.team;
  // git_log yerel klasör okur; github owner/repo, gitlab ise grup/proje ister.
  // Yanlış alanı doldurmak sessiz bir "0 commit"e yol açardı, o yüzden alan
  // sağlayıcıya göre değişir.
  const uzakYol = provider === "github" || provider === "gitlab";
  const yolIpucu = provider === "gitlab"
    ? t("grup/proje  ya da  https://gitlab.sirket.local/grup/proje")
    : t("owner/repo  ya da  https://github.com/owner/repo");
  return (
    <div className={`repo-row editable ${unmapped ? "unmapped" : ""}`}>
      <div className="repo-ident">
        <input
          className="repo-name-input"
          value={repo.name}
          placeholder={t("repo adı (kimlik — değiştirmek commitleri ayırır)")}
          onChange={(e) => onChange({ ...repo, name: e.target.value })}
        />
        {uzakYol ? (
          <input
            className="repo-path-input"
            value={repo.slug || ""}
            placeholder={yolIpucu}
            onChange={(e) => onChange({ ...repo, slug: e.target.value })}
          />
        ) : (
          <input
            className="repo-path-input"
            value={repo.path || ""}
            placeholder={t("C:/yol/klasor  ya da  /srv/repos/x")}
            onChange={(e) => onChange({ ...repo, path: e.target.value })}
          />
        )}
      </div>
      <div className="repo-meta">{t("{n} commit", { n: repo.commit_count ?? 0 })}</div>
      <label className="repo-team">
        <span>{t("Takım")}</span>
        <select value={repo.team || NO_TEAM}
                onChange={(e) => onChange({ ...repo, team: e.target.value })}>
          <option value={NO_TEAM}>{t("— takım yok —")}</option>
          {teams.map((tm) => <option key={tm.id} value={tm.name}>{tm.name}</option>)}
        </select>
      </label>
      <button type="button" className="mini danger" onClick={onRemove}>{t("Çıkar")}</button>
      {unmapped && (
        <p className="repo-warn">
          {t("Takımsız — bu reponun {n} commit'i hiçbir takım metriğine girmiyor.", { n: repo.commit_count ?? 0 })}
        </p>
      )}
    </div>
  );
}

function TestResult({ result }) {
  const t = useT();
  if (!result) return null;
  const rows = [
    { label: t("Git / Kod"), r: result.git, unit: t("commit") },
    { label: t("Görevler"), r: result.tasks, unit: t("kayıt") },
  ];
  return (
    <div className="test-result">
      {rows.map(({ label, r, unit }) => (
        <div key={label} className={`test-row ${r.ok ? "ok" : "fail"}`}>
          <span className="test-dot" aria-hidden="true" />
          <strong>{label}</strong>
          <span className="test-detail">
            {r.detail
              ? r.detail
              : t("{n} {unit} okundu{pr}", { n: r.count, unit, pr: r.pull_requests != null ? t(" · {n} PR", { n: r.pull_requests }) : "" })}
          </span>
        </div>
      ))}
      <WarnBox items={[...(result.git.warnings || []), ...(result.tasks.warnings || [])]} />
      <WarnBox
        items={(result.unmapped_repos || []).map(
          (n) => t("Repo '{n}' takımsız — commitleri metriklere girmiyor (aşağıdan takım seçin).", { n })
        )}
      />
      {result.ok && <p className="ok-inline">{t("Tüm kaynaklar okunabiliyor.")}</p>}
    </div>
  );
}

// Yönetici: entegrasyon/kaynak durumu, ayar ve elle senkron.
// Sır (token) config'e YAZILMAZ — .secrets.env'e ve süreç ortamına gider.
export default function IntegrationPanel() {
  const t = useT();
  const { lang } = useLang();
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [test, setTest] = useState(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [testing, setTesting] = useState(false);
  // Senkron yeni kadro üyesi getirebilir → kimlik listesi tazelensin
  const [identityNonce, setIdentityNonce] = useState(0);

  function load() {
    getSources()
      .then((d) => {
        setData(d);
        setForm({
          git_provider: d.git.provider,
          tasks_provider: d.tasks.provider,
          gitlab_base_url: d.git.gitlab_base_url || "",
          jira_base_url: d.tasks.jira_base_url || "",
          jira_projects: (d.tasks.jira_projects || []).join("\n"),
          sync_interval_minutes: d.sync_interval_minutes,
          trello_boards: (d.tasks.trello?.boards || []).join("\n"),
          trello_key: "",    // sır asla önden doldurulmaz
          trello_token: "",
          github_token: "",  // sır — önden doldurulmaz
          gitlab_token: "",
          jira_token: "",
          repos: (d.git.repos || []).map((r) => ({ ...r, team: r.team || NO_TEAM })),
        });
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  function upd(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function updRepo(index, next) {
    setForm((f) => ({ ...f, repos: f.repos.map((r, i) => (i === index ? next : r)) }));
  }

  function addRepo() {
    setForm((f) => ({
      ...f, repos: [...f.repos, { name: "", path: "", slug: "", team: NO_TEAM, commit_count: 0 }],
    }));
  }

  function removeRepo(index) {
    setForm((f) => ({ ...f, repos: f.repos.filter((_, i) => i !== index) }));
  }

  async function save(e) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    setSaving(true);
    try {
      const payload = {
        git_provider: form.git_provider,
        tasks_provider: form.tasks_provider,
        gitlab_base_url: form.gitlab_base_url,
        jira_base_url: form.jira_base_url,
        sync_interval_minutes: Number(form.sync_interval_minutes),
        trello_boards: form.trello_boards
          .split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
        jira_projects: form.jira_projects
          .split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
        // Listenin tamamı gider (ekleme/çıkarma); adsız satırlar atılır.
        repos: form.repos
          .filter((r) => r.name.trim())
          .map((r) => ({ name: r.name.trim(), path: (r.path || "").trim(),
                        slug: (r.slug || "").trim(), team: r.team || "" })),
      };
      // Sır alanları YALNIZCA doluysa gönder (boş göndermek mevcut sırrı silerdi).
      if (form.trello_key.trim()) payload.trello_key = form.trello_key.trim();
      if (form.trello_token.trim()) payload.trello_token = form.trello_token.trim();
      if (form.github_token.trim()) payload.github_token = form.github_token.trim();
      if (form.gitlab_token.trim()) payload.gitlab_token = form.gitlab_token.trim();
      if (form.jira_token.trim()) payload.jira_token = form.jira_token.trim();
      await updateSources(payload);
      setMsg(t("Ayarlar kaydedildi. Değişikliğin panoya yansıması için 'Şimdi senkronize et'."));
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setError(null);
    setMsg(null);
    setWarnings([]);
    setTesting(true);
    try {
      setTest(await testSources());
    } catch (err) {
      setError(err.message);
    } finally {
      setTesting(false);
    }
  }

  // Senkron ARKA PLANDA çalışır (uç hemen iş kimliği döner); burada durum
  // yoklanır. Eskiden istek dakikalarca açık kalıyor, gerçek kaynakla
  // tarayıcı/proxy zaman aşımına düşüyordu.
  async function sync() {
    setError(null);
    setMsg(null);
    setTest(null);
    setSyncing(true);
    try {
      const res = await triggerSync();
      setMsg(t("Senkron başladı — arka planda çalışıyor…"));
      await pollSync(res.job?.id);
    } catch (err) {
      setError(err.message);
      setSyncing(false);
    }
  }

  async function pollSync(jobId) {
    // Sunucu tarafı zaten "aynı anda tek senkron" garantisi veriyor; burada
    // yalnız durumu izliyoruz. Hata SESSİZ yutulmaz (bkz. denetim önerisi 7).
    try {
      const { job } = await syncStatus(jobId);
      if (!job || job.status === "running") {
        setTimeout(() => pollSync(jobId), 2000);
        return;
      }
      if (job.status === "error") {
        setError(t("Senkron başarısız: {msg}", { msg: job.error || t("bilinmeyen hata") }));
        setMsg(null);
      } else {
        const s = job.stats || {};
        // Ingest sayıları da gösterilir: "metrik: 68" tek başına entegrasyonun
        // çalıştığını sanmaya yol açıyordu — asıl bilgi kaç YENİ kayıt geldiği.
        setMsg(
          t("Senkron tamam · {commits} yeni commit · {prs} yeni PR · {tasks} yeni görev · {members} yeni kadro üyesi · metrik: {metrics} · öneri: {recs}", {
            commits: s.commits ?? 0, prs: s.pull_requests ?? 0, tasks: s.tasks ?? 0,
            members: s.team_members ?? 0, metrics: s.metric_results ?? 0, recs: s.recommendations ?? 0,
          })
        );
      }
      setWarnings(job.warnings || []);
      load();
      setIdentityNonce((n) => n + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  }

  if (error && !data) return <div className="login-error">{error}</div>;
  if (!data || !form) return <p className="desc">{t("Yükleniyor…")}</p>;

  const lastSync = data.last_sync
    ? new Date(data.last_sync).toLocaleString(lang === "en" ? "en-US" : "tr-TR")
    : t("henüz yok");
  const repos = data.git.repos || [];
  const teams = data.teams || [];
  // gitlab da ORTAK repo listesini kullanır: hedef projeler ve repo→takım
  // eşlemesi tek listede yaşar (bkz. adapters/gitlab.py).
  const gitReposUsed = ["git_log", "github", "gitlab"].includes(form.git_provider);
  const unmappedCount = form.repos.filter((r) => r.name.trim() && !r.team).length;

  return (
    <div className="integration-panel">
      <section className="section">
        <div className="section-head">
          <h2>{t("Kaynak durumu")}</h2>
          <div className="team-toolbar">
            <button className="mini" onClick={runTest} disabled={testing || syncing}>
              {testing ? t("Test ediliyor…") : t("Bağlantıyı test et")}
            </button>
            <button className="login-btn" onClick={sync} disabled={syncing || testing}>
              {syncing ? t("Senkronize ediliyor…") : t("Şimdi senkronize et")}
            </button>
          </div>
        </div>
        <p className="desc">
          {t("Son senkron:")} <strong>{lastSync}</strong> · {t("Otomatik aralık:")}{" "}
          <strong>{data.sync_interval_minutes > 0 ? t("{n} dk", { n: data.sync_interval_minutes }) : t("kapalı")}</strong>
        </p>
        <div className="source-grid">
          <div className="source-card">
            <h3>{t("Git / Kod")}</h3>
            <div className="src-provider">{data.git.provider}</div>
            <div className="src-meta">
              {t("{n} repo", { n: repos.length })} · {t("{n} commit", { n: repos.reduce((a, r) => a + r.commit_count, 0) })}
            </div>
            <TokenBadge token={data.git.token} />
            <TokenBadge token={data.git.github_token} />
          </div>
          <div className="source-card">
            <h3>{t("Görevler")}</h3>
            <div className="src-provider">{data.tasks.provider}</div>
            {data.tasks.provider === "trello" ? (
              <>
                <div className="src-meta">{t("Board sayısı: {n}", { n: data.tasks.trello?.boards?.length ?? 0 })}</div>
                <TokenBadge token={data.tasks.trello?.key} />
                <TokenBadge token={data.tasks.trello?.token} />
              </>
            ) : (
              <TokenBadge token={data.tasks.token} />
            )}
          </div>
        </div>
        {msg && <div className="admin-ok">{msg}</div>}
        <WarnBox items={warnings} title={t("Senkron uyarıları")} />
        <TestResult result={test} />
        {error && <div className="login-error">{error}</div>}
      </section>

      <section className="section">
        <h2>{t("Entegrasyon ayarları")}</h2>
        <p className="desc">
          {t("Sır (token) config dosyasına yazılmaz; gitignore'lu")} <code>.secrets.env</code>'{t("e ve süreç ortamına gider. Diğer değişiklikler config'e yazılır ve sonraki senkronda geçerli olur.")}
        </p>
        <form className="admin-form" onSubmit={save}>
          <label>
            {t("Git sağlayıcı")}
            <select value={form.git_provider} onChange={(e) => upd("git_provider", e.target.value)}>
              {GIT_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            {t("GitHub token (özel repo)")}
            <input type="password" autoComplete="off" value={form.github_token} onChange={(e) => upd("github_token", e.target.value)} placeholder={data.git.github_token?.configured ? t("•••• (tanımlı — değiştirmek için yaz)") : "github_pat_… (Contents: Read)"} />
            <span className="field-hint">{t('Yalnızca "Projelerim" özel GitHub repoları için PAT.')}</span>
          </label>

          {gitReposUsed && (
            <div className="span-2 repo-block">
              <div className="repo-block-head">
                <h3>{t("Repo'lar")}</h3>
                {unmappedCount > 0 && (
                  <span className="token-badge missing">{t("{n} repo takımsız", { n: unmappedCount })}</span>
                )}
                <button type="button" className="mini" onClick={addRepo}>{t("+ Repo ekle")}</button>
              </div>
              <p className="field-hint">
                {t("Metrik motoru bir takımın commitlerini o takıma bağlı repolardan çeker. Takımsız repo hiçbir metrik üretmez — pano \"veri yetersiz\" gösterir.")}
                {form.git_provider === "github" && (
                  <>
                    {" "}{t("GitHub'da repo yolu")} <code>owner/repo</code> {t("biçimindedir.")}
                    <strong> {t("PR metrikleri (review süresi, review gecikmesi, deploy sıklığı, hata oranı) yalnız bu sağlayıcıyla ölçülebilir")}</strong> —{" "}
                    {t("yerel")} <code>git log</code>'{t("da pull request kaydı yoktur. Özel repo için aşağıdaki GitHub token'ı gerekir.")}
                  </>
                )}
                {form.git_provider === "gitlab" && (
                  <>
                    {" "}{t("GitLab'da proje yolu")} <code>grup/proje</code> {t("biçimindedir")}{" "}
                    ({t("iç içe gruplarda")} <code>grup/alt/proje</code>); {t("tam URL de yapıştırabilirsiniz.")} <strong>{t("Merge request metrikleri bu sağlayıcıyla ölçülür")}</strong> —{" "}
                    {t("MR'lar PR olarak işlenir, ilk review MR notlarından çıkarılır. Aşağıdaki GitLab adresi ve token'ı gerekir.")}
                  </>
                )}
                {form.git_provider === "git_log" && ` ${t("Yol, sunucunun eriştiği bir git klonu olmalı.")}`}
              </p>
              {form.repos.length === 0 ? (
                <p className="desc">{t('Henüz repo yok — "+ Repo ekle" ile başlayın.')}</p>
              ) : (
                <div className="repo-list">
                  {form.repos.map((r, i) => (
                    <RepoRow
                      key={i}
                      repo={r}
                      teams={teams}
                      provider={form.git_provider}
                      onChange={(next) => updRepo(i, next)}
                      onRemove={() => removeRepo(i)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {form.git_provider === "gitlab" && (
            <>
              <label>
                {t("GitLab adresi")}
                <input value={form.gitlab_base_url} onChange={(e) => upd("gitlab_base_url", e.target.value)} placeholder="https://gitlab.sirket.local" />
                <span className="field-hint">
                  {t("Şirket GitLab'ının kök adresi —")} <code>/api/v4</code> {t("otomatik eklenir.")}
                </span>
              </label>
              <label>
                {t("GitLab token")}
                <input type="password" autoComplete="off" value={form.gitlab_token} onChange={(e) => upd("gitlab_token", e.target.value)} placeholder={data.git.token?.configured ? t("•••• (tanımlı — değiştirmek için yaz)") : "glpat-… (read_api)"} />
                <span className="field-hint">
                  {t("Project/Personal access token,")} <code>read_api</code> {t("kapsamı yeter. Boş bırakırsan mevcut sır korunur.")}
                </span>
              </label>
              {(data.git.gitlab_projects || []).length > 0 && (
                <p className="field-hint span-2">
                  {t("Config'te eski biçimde {n} proje tanımlı", { n: data.git.gitlab_projects.length })}
                  {" "}(<code>{data.git.gitlab_projects.join(", ")}</code>). {t("Yukarıdaki repo listesi boş kaldığı sürece hedef olarak")} <strong>{t("onlar")}</strong> {t("kullanılır, ama takım eşlemesi yapılamadığı için metrik üretmezler — projeleri repo satırı olarak ekleyip takım seçin.")}
                </p>
              )}
            </>
          )}

          <label>
            {t("Görev sağlayıcı")}
            <select value={form.tasks_provider} onChange={(e) => upd("tasks_provider", e.target.value)}>
              {TASK_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            {t("Otomatik senkron aralığı (dakika, 0 = kapalı)")}
            <input type="number" min={0} value={form.sync_interval_minutes} onChange={(e) => upd("sync_interval_minutes", e.target.value)} />
          </label>

          {form.tasks_provider === "jira" && (
            <>
              <label>
                {t("Jira adresi")}
                <input value={form.jira_base_url} onChange={(e) => upd("jira_base_url", e.target.value)} placeholder="https://jira.sirket.local" />
                <span className="field-hint">
                  {t("Kök adres —")} <code>/rest/api/2</code> {t("otomatik eklenir.")}
                </span>
              </label>
              <label>
                {t("Jira token")}
                <input type="password" autoComplete="off" value={form.jira_token} onChange={(e) => upd("jira_token", e.target.value)} placeholder={data.tasks.token?.configured ? t("•••• (tanımlı — değiştirmek için yaz)") : "Bearer token / PAT"} />
              </label>
              <label className="span-2">
                {t("Jira proje anahtarları (her satıra bir tane)")}
                <textarea rows={3} value={form.jira_projects} onChange={(e) => upd("jira_projects", e.target.value)} placeholder="ENG&#10;OPS" />
                <span className="field-hint">
                  {t("Issue anahtarının başındaki kısım:")} <code>ENG</code>-142 → <code>ENG</code>.{" "}
                  {t('Liste boşsa hiçbir görev çekilmez. Kaydettikten sonra "Bağlantıyı test et" ile doğrulayın.')}
                </span>
              </label>
            </>
          )}

          {form.tasks_provider === "trello" && (
            <>
              <label className="span-2">
                {t("Trello board id'leri (her satıra bir tane)")}
                <textarea rows={3} value={form.trello_boards} onChange={(e) => upd("trello_boards", e.target.value)} placeholder="5f2a...&#10;60b1..." />
                <span className="field-hint">
                  {t("Board URL'inden: trello.com/b/")}<b>BOARD_ID</b>{t("/isim — kaydettikten sonra")}{" "}
                  {t('"Bağlantıyı test et" ile id\'lerin okunabildiğini doğrulayın.')}
                </span>
              </label>
              <label>
                {t("Trello API Key")}
                <input type="password" autoComplete="off" value={form.trello_key} onChange={(e) => upd("trello_key", e.target.value)} placeholder={data.tasks.trello?.key?.configured ? t("•••• (tanımlı — değiştirmek için yaz)") : "trello.com/power-ups/admin"} />
              </label>
              <label>
                {t("Trello Token")}
                <input type="password" autoComplete="off" value={form.trello_token} onChange={(e) => upd("trello_token", e.target.value)} placeholder={data.tasks.trello?.token?.configured ? t("•••• (tanımlı — değiştirmek için yaz)") : t("API Key sayfasındaki Token linki")} />
              </label>
              <p className="desc span-2">
                {t("Key/Token config'e YAZILMAZ — gitignore'lu")} <code>.secrets.env</code>'{t("e ve süreç ortamına yazılır. Boş bırakırsan mevcut sır korunur.")}
              </p>
            </>
          )}

          <button type="submit" className="login-btn" disabled={saving}>
            {saving ? t("Kaydediliyor…") : t("Ayarları kaydet")}
          </button>
        </form>
        {msg && <div className="admin-ok">{msg}</div>}
        {error && <div className="login-error">{error}</div>}
      </section>

      <SmtpSettings />

      <IdentitySection nonce={identityNonce} />
    </div>
  );
}
