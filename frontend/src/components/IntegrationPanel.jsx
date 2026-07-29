import { useEffect, useState } from "react";
import { getSources, testSources, triggerSync, updateSources } from "../api.js";

const GIT_PROVIDERS = ["fixture", "git_log", "gitlab"];
const TASK_PROVIDERS = ["fixture", "jira", "trello", "none"];
const NO_TEAM = "";

function TokenBadge({ token }) {
  if (!token) return null;
  return (
    <span className={`token-badge ${token.configured ? "ok" : "missing"}`}>
      {token.env_var}: {token.configured ? "tanımlı" : "tanımsız"}
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

// Repo → takım eşlemesi. Takımsız repo'nun commitleri hiçbir takım metriğine
// giremez (metrik motoru commitleri takımın repolarından çeker), o yüzden bu
// eşleme config'i elle düzenlemeye bırakılmaz.
function RepoRow({ repo, teams, onChange, onRemove }) {
  const unmapped = !repo.team;
  return (
    <div className={`repo-row editable ${unmapped ? "unmapped" : ""}`}>
      <div className="repo-ident">
        <input
          className="repo-name-input"
          value={repo.name}
          placeholder="repo adı (kimlik — değiştirmek commitleri ayırır)"
          onChange={(e) => onChange({ ...repo, name: e.target.value })}
        />
        <input
          className="repo-path-input"
          value={repo.path || ""}
          placeholder="C:/yol/klasor  ya da  /srv/repos/x"
          onChange={(e) => onChange({ ...repo, path: e.target.value })}
        />
      </div>
      <div className="repo-meta">{repo.commit_count ?? 0} commit</div>
      <label className="repo-team">
        <span>Takım</span>
        <select value={repo.team || NO_TEAM}
                onChange={(e) => onChange({ ...repo, team: e.target.value })}>
          <option value={NO_TEAM}>— takım yok —</option>
          {teams.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
        </select>
      </label>
      <button type="button" className="mini danger" onClick={onRemove}>Çıkar</button>
      {unmapped && (
        <p className="repo-warn">
          Takımsız — bu reponun {repo.commit_count ?? 0} commit'i hiçbir takım metriğine girmiyor.
        </p>
      )}
    </div>
  );
}

// Kaynaktaki kolon adları serbest metindir (Trello listesi, Jira adımı).
// Eşlenmeyen kolon WIP'e "akıştaki iş" olarak girer ve takımı yok yere kırmızı
// yapar — bu yüzden görülen statüler tek tek kategoriye atanır.
const CATEGORY_LABELS = {
  backlog: "Backlog / bekleyen",
  in_progress: "Akışta (WIP)",
  done: "Bitti",
};

function StatusMapper({ observed, mapping, onChange }) {
  const lookup = {};
  for (const cat of Object.keys(CATEGORY_LABELS)) {
    for (const name of mapping[cat] || []) lookup[name.trim().toLowerCase()] = cat;
  }
  const names = [...new Set([
    ...observed,
    ...Object.values(mapping).flat(),
  ])].sort((a, b) => a.localeCompare(b, "tr"));

  function assign(name, category) {
    const next = {};
    for (const cat of Object.keys(CATEGORY_LABELS)) {
      next[cat] = (mapping[cat] || []).filter(
        (n) => n.trim().toLowerCase() !== name.trim().toLowerCase()
      );
    }
    if (category) next[category] = [...next[category], name];
    onChange(next);
  }

  if (names.length === 0) {
    return <p className="desc">Henüz statü görülmedi — önce senkronize edin.</p>;
  }
  return (
    <div className="status-map">
      {names.map((name) => {
        const cat = lookup[name.trim().toLowerCase()] || "";
        return (
          <div key={name} className={`status-map-row ${cat ? "" : "unmapped"}`}>
            <span className="status-name">{name}</span>
            <select value={cat} onChange={(e) => assign(name, e.target.value)}>
              <option value="">— eşlenmedi (varsayılana düşer) —</option>
              {Object.entries(CATEGORY_LABELS).map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
          </div>
        );
      })}
    </div>
  );
}

function TestResult({ result }) {
  if (!result) return null;
  const rows = [
    { label: "Git / Kod", r: result.git, unit: "commit" },
    { label: "Görevler", r: result.tasks, unit: "kayıt" },
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
              : `${r.count} ${unit} okundu${r.pull_requests != null ? ` · ${r.pull_requests} PR` : ""}`}
          </span>
        </div>
      ))}
      <WarnBox items={[...(result.git.warnings || []), ...(result.tasks.warnings || [])]} />
      <WarnBox
        items={(result.unmapped_repos || []).map(
          (n) => `Repo '${n}' takımsız — commitleri metriklere girmiyor (aşağıdan takım seçin).`
        )}
      />
      {result.ok && <p className="ok-inline">Tüm kaynaklar okunabiliyor.</p>}
    </div>
  );
}

// Yönetici: entegrasyon/kaynak durumu, ayar ve elle senkron.
// Sır (token) config'e YAZILMAZ — .secrets.env'e ve süreç ortamına gider.
export default function IntegrationPanel() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [test, setTest] = useState(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [testing, setTesting] = useState(false);

  function load() {
    getSources()
      .then((d) => {
        setData(d);
        setForm({
          git_provider: d.git.provider,
          tasks_provider: d.tasks.provider,
          gitlab_base_url: d.git.gitlab_base_url || "",
          jira_base_url: d.tasks.jira_base_url || "",
          sync_interval_minutes: d.sync_interval_minutes,
          trello_boards: (d.tasks.trello?.boards || []).join("\n"),
          trello_key: "",    // sır asla önden doldurulmaz
          trello_token: "",
          github_token: "",  // sır — önden doldurulmaz
          repos: (d.git.repos || []).map((r) => ({ ...r, team: r.team || NO_TEAM })),
          status_mapping: d.tasks.status_mapping || { backlog: [], in_progress: [], done: [] },
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
      ...f, repos: [...f.repos, { name: "", path: "", team: NO_TEAM, commit_count: 0 }],
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
        // Listenin tamamı gider (ekleme/çıkarma); adsız satırlar atılır.
        repos: form.repos
          .filter((r) => r.name.trim())
          .map((r) => ({ name: r.name.trim(), path: (r.path || "").trim(), team: r.team || "" })),
        status_mapping: form.status_mapping,
      };
      // Sır alanları YALNIZCA doluysa gönder (boş göndermek mevcut sırrı silerdi).
      if (form.trello_key.trim()) payload.trello_key = form.trello_key.trim();
      if (form.trello_token.trim()) payload.trello_token = form.trello_token.trim();
      if (form.github_token.trim()) payload.github_token = form.github_token.trim();
      await updateSources(payload);
      setMsg("Ayarlar kaydedildi. Değişikliğin panoya yansıması için 'Şimdi senkronize et'.");
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

  async function sync() {
    setError(null);
    setMsg(null);
    setTest(null);
    setSyncing(true);
    try {
      const res = await triggerSync();
      const s = res.stats || {};
      // Ingest sayıları da gösterilir: "metrik: 68" tek başına entegrasyonun
      // çalıştığını sanmaya yol açıyordu — asıl bilgi kaç YENİ kayıt geldiği.
      setMsg(
        `Senkron tamam · ${s.commits ?? 0} yeni commit · ${s.pull_requests ?? 0} yeni PR · ` +
        `${s.tasks ?? 0} yeni görev · metrik: ${s.metric_results ?? 0} · öneri: ${s.recommendations ?? 0}`
      );
      setWarnings(s.warnings || []);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  }

  if (error && !data) return <div className="login-error">{error}</div>;
  if (!data || !form) return <p className="desc">Yükleniyor…</p>;

  const lastSync = data.last_sync
    ? new Date(data.last_sync).toLocaleString("tr-TR")
    : "henüz yok";
  const repos = data.git.repos || [];
  const teams = data.teams || [];
  const gitReposUsed = form.git_provider === "git_log";
  const unmappedCount = form.repos.filter((r) => r.name.trim() && !r.team).length;

  return (
    <div className="integration-panel">
      <section className="section">
        <div className="section-head">
          <h2>Kaynak durumu</h2>
          <div className="team-toolbar">
            <button className="mini" onClick={runTest} disabled={testing || syncing}>
              {testing ? "Test ediliyor…" : "Bağlantıyı test et"}
            </button>
            <button className="login-btn" onClick={sync} disabled={syncing || testing}>
              {syncing ? "Senkronize ediliyor…" : "Şimdi senkronize et"}
            </button>
          </div>
        </div>
        <p className="desc">
          Son senkron: <strong>{lastSync}</strong> · Otomatik aralık:{" "}
          <strong>{data.sync_interval_minutes > 0 ? `${data.sync_interval_minutes} dk` : "kapalı"}</strong>
        </p>
        <div className="source-grid">
          <div className="source-card">
            <h3>Git / Kod</h3>
            <div className="src-provider">{data.git.provider}</div>
            <div className="src-meta">
              {repos.length} repo · {repos.reduce((a, r) => a + r.commit_count, 0)} commit
            </div>
            <TokenBadge token={data.git.token} />
            <TokenBadge token={data.git.github_token} />
          </div>
          <div className="source-card">
            <h3>Görevler</h3>
            <div className="src-provider">{data.tasks.provider}</div>
            {data.tasks.provider === "trello" ? (
              <>
                <div className="src-meta">Board sayısı: {data.tasks.trello?.boards?.length ?? 0}</div>
                <TokenBadge token={data.tasks.trello?.key} />
                <TokenBadge token={data.tasks.trello?.token} />
              </>
            ) : (
              <TokenBadge token={data.tasks.token} />
            )}
          </div>
        </div>
        {msg && <div className="admin-ok">{msg}</div>}
        <WarnBox items={warnings} title="Senkron uyarıları" />
        <TestResult result={test} />
        {error && <div className="login-error">{error}</div>}
      </section>

      <section className="section">
        <h2>Entegrasyon ayarları</h2>
        <p className="desc">
          Sır (token) config dosyasına yazılmaz; gitignore'lu <code>.secrets.env</code>'e
          ve süreç ortamına gider. Diğer değişiklikler config'e yazılır ve sonraki
          senkronda geçerli olur.
        </p>
        <form className="admin-form" onSubmit={save}>
          <label>
            Git sağlayıcı
            <select value={form.git_provider} onChange={(e) => upd("git_provider", e.target.value)}>
              {GIT_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            GitHub token (özel repo)
            <input type="password" autoComplete="off" value={form.github_token} onChange={(e) => upd("github_token", e.target.value)} placeholder={data.git.github_token?.configured ? "•••• (tanımlı — değiştirmek için yaz)" : "github_pat_… (Contents: Read)"} />
            <span className="field-hint">Yalnızca "Projelerim" özel GitHub repoları için PAT.</span>
          </label>

          {gitReposUsed && (
            <div className="span-2 repo-block">
              <div className="repo-block-head">
                <h3>Repo'lar</h3>
                {unmappedCount > 0 && (
                  <span className="token-badge missing">{unmappedCount} repo takımsız</span>
                )}
                <button type="button" className="mini" onClick={addRepo}>+ Repo ekle</button>
              </div>
              <p className="field-hint">
                Metrik motoru bir takımın commitlerini o takıma bağlı repolardan çeker.
                Takımsız repo hiçbir metrik üretmez — pano "veri yetersiz" gösterir.
                Yol, sunucunun eriştiği bir git klonu olmalı.
              </p>
              {form.repos.length === 0 ? (
                <p className="desc">Henüz repo yok — "+ Repo ekle" ile başlayın.</p>
              ) : (
                <div className="repo-list">
                  {form.repos.map((r, i) => (
                    <RepoRow
                      key={i}
                      repo={r}
                      teams={teams}
                      onChange={(next) => updRepo(i, next)}
                      onRemove={() => removeRepo(i)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {form.git_provider === "gitlab" && (
            <label className="span-2">
              GitLab base URL
              <input value={form.gitlab_base_url} onChange={(e) => upd("gitlab_base_url", e.target.value)} placeholder="https://gitlab.sirket.local" />
            </label>
          )}

          <label>
            Görev sağlayıcı
            <select value={form.tasks_provider} onChange={(e) => upd("tasks_provider", e.target.value)}>
              {TASK_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>
            Otomatik senkron aralığı (dakika, 0 = kapalı)
            <input type="number" min={0} value={form.sync_interval_minutes} onChange={(e) => upd("sync_interval_minutes", e.target.value)} />
          </label>

          {form.tasks_provider === "jira" && (
            <label className="span-2">
              Jira base URL
              <input value={form.jira_base_url} onChange={(e) => upd("jira_base_url", e.target.value)} placeholder="https://jira.sirket.local" />
            </label>
          )}

          {form.tasks_provider === "trello" && (
            <>
              <label className="span-2">
                Trello board id'leri (her satıra bir tane)
                <textarea rows={3} value={form.trello_boards} onChange={(e) => upd("trello_boards", e.target.value)} placeholder="5f2a...&#10;60b1..." />
                <span className="field-hint">
                  Board URL'inden: trello.com/b/<b>BOARD_ID</b>/isim — kaydettikten sonra
                  "Bağlantıyı test et" ile id'lerin okunabildiğini doğrulayın.
                </span>
              </label>
              <label>
                Trello API Key
                <input type="password" autoComplete="off" value={form.trello_key} onChange={(e) => upd("trello_key", e.target.value)} placeholder={data.tasks.trello?.key?.configured ? "•••• (tanımlı — değiştirmek için yaz)" : "trello.com/power-ups/admin"} />
              </label>
              <label>
                Trello Token
                <input type="password" autoComplete="off" value={form.trello_token} onChange={(e) => upd("trello_token", e.target.value)} placeholder={data.tasks.trello?.token?.configured ? "•••• (tanımlı — değiştirmek için yaz)" : "API Key sayfasındaki Token linki"} />
              </label>
              <p className="desc span-2">
                Key/Token config'e YAZILMAZ — gitignore'lu <code>.secrets.env</code>'e
                ve süreç ortamına yazılır. Boş bırakırsan mevcut sır korunur.
              </p>
            </>
          )}

          {form.tasks_provider !== "none" && (
            <div className="span-2 repo-block">
              <div className="repo-block-head">
                <h3>Statü eşlemesi</h3>
              </div>
              <p className="field-hint">
                Kaynaktaki kolon adları serbest metindir ("Araştırma Konuları",
                "DEVELOPMENT"). Eşlenmeyen kolon <strong>akıştaki iş</strong> sayılır ve
                WIP'i şişirir; cycle time da yanlış noktadan başlar. Aşağıdaki liste
                senkronda gerçekten görülen statülerden üretilir.
              </p>
              <StatusMapper
                observed={data.tasks.observed_statuses || []}
                mapping={form.status_mapping}
                onChange={(next) => upd("status_mapping", next)}
              />
            </div>
          )}

          <button type="submit" className="login-btn" disabled={saving}>
            {saving ? "Kaydediliyor…" : "Ayarları kaydet"}
          </button>
        </form>
        {msg && <div className="admin-ok">{msg}</div>}
        {error && <div className="login-error">{error}</div>}
      </section>
    </div>
  );
}
