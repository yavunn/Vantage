// Vantage — uygulama kabuğu.
// Varsayılan görünüm TAKIM'dır (İlke E). Bireysel sekme yalnızca yetkiliye
// içerik gösterir; leaderboard yoktur. Giriş gerçek hesapla yapılır.
import { lazy, Suspense, useEffect, useState } from "react";
import { api, fetchMe, getCurrentSurvey, getStoredUser, getToken, logout, setupStatus } from "./api.js";
import { toast } from "./toast.js";
import { applyTheme, RANGE_OPTIONS, readNav, writeNav } from "./nav.js";
import { useLang, useT } from "./i18n.jsx";
import ForceChangePassword from "./components/ForceChangePassword.jsx";
import Login from "./components/Login.jsx";
import SurveyBanner from "./components/SurveyBanner.jsx";
import TopBar from "./components/TopBar.jsx";
import CodeHealthCard from "./components/CodeHealthCard.jsx";
import CodeHealthDrilldown from "./components/CodeHealthDrilldown.jsx";
import MetricCard from "./components/MetricCard.jsx";
import CommandPalette from "./components/CommandPalette.jsx";
import PersonPicker, { pushRecent } from "./components/PersonPicker.jsx";
import MetricDrilldown from "./components/MetricDrilldown.jsx";
import Setup from "./components/Setup.jsx";
import SignalsBlock from "./components/SignalsBlock.jsx";
import ToastHost from "./components/ToastHost.jsx";
import TrendChart from "./components/TrendChart.jsx";

// Varsayılan (takım) görünümde gerekmeyen ağır panelleri tembel yükle —
// ilk açılış paketi küçülür.
const AdminPanel = lazy(() => import("./components/AdminPanel.jsx"));
const DocumentsPanel = lazy(() => import("./components/DocumentsPanel.jsx"));
const HrDashboard = lazy(() => import("./components/HrDashboard.jsx"));
const IndividualView = lazy(() => import("./components/IndividualView.jsx"));
const MyCodeHealth = lazy(() => import("./components/MyCodeHealth.jsx"));
const LeavesPanel = lazy(() => import("./components/LeavesPanel.jsx"));
const ProjectsPanel = lazy(() => import("./components/ProjectsPanel.jsx"));
const Settings = lazy(() => import("./components/Settings.jsx"));
const SurveyForm = lazy(() => import("./components/SurveyForm.jsx"));

function LazyFallback() {
  const t = useT();
  return <div className="app">{t("Yükleniyor…")}</div>;
}





export default function App() {
  const { lang, t } = useLang();
  const [authReady, setAuthReady] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [user, setUser] = useState(null);

  const [uiConfig, setUiConfig] = useState(null);
  const [teams, setTeams] = useState([]);
  const [teamId, setTeamId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);
  const [signals, setSignals] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [range, setRange] = useState(() => readNav().range);
  const [codeHealth, setCodeHealth] = useState(null);
  const [codeHealthSeries, setCodeHealthSeries] = useState(null);
  const [codeDrill, setCodeDrill] = useState(false);
  const [drill, setDrill] = useState(null); // {key, name} — açık drill-down metriği
  const [directory, setDirectory] = useState([]);
  const [viewDevId, setViewDevId] = useState(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [tab, setTab] = useState(() => readNav().tab);
  const [survey, setSurvey] = useState(null);
  const [surveyDismissed, setSurveyDismissed] = useState(false);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("vantage_theme") || "auto");

  // Tema uygula + kalıcılaştır.
  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem("vantage_theme", theme);
  }, [theme]);

  // Gezinme durumunu kalıcılaştır (reload'da kal, URL paylaşılabilir).
  useEffect(() => {
    writeNav({ tab, team: teamId, range });
  }, [tab, teamId, range]);

  // Klavye kısayolları: Ctrl/Cmd+K hızlı arama, Alt+1..6 sekme geçişi.
  // Bir metin alanına yazarken tetiklenmez (Ctrl+K hariç — o global).
  useEffect(() => {
    function onKey(e) {
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      const el = document.activeElement;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if (typing || !e.altKey) return;
      const order = user && user.role === "hr"
        ? ["hr", "leaves", "documents", "accounts", "survey", "settings"]
        : ["team", "me", "projects", "leaves", "documents", "survey", "admin", "settings"];
      const idx = Number(e.key) - 1;
      if (Number.isInteger(idx) && idx >= 0 && idx < order.length) {
        e.preventDefault();
        setTab(order[idx]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [user]);

  // Geçerli olmayan sekmeyi (ör. saklanmış 'admin' ama kullanıcı admin değil) düzelt.
  // HR ayrı bir gezinme kümesi kullanır (performans sekmeleri kapalı — etik sınır).
  useEffect(() => {
    if (!user || !uiConfig) return;
    let allowed;
    let fallback;
    if (user.role === "hr") {
      allowed = new Set(["hr", "leaves", "documents", "accounts", "survey", "settings"]);
      fallback = "hr";
    } else {
      allowed = new Set(["team", "projects", "leaves", "documents", "survey", "settings"]);
      if (uiConfig.individual_view_enabled) allowed.add("me");
      if (user.role === "admin") allowed.add("admin");
      fallback = "team";
    }
    if (!allowed.has(tab)) setTab(fallback);
  }, [user, uiConfig, tab]);

  // Açılış: önce kurulum gerekli mi, sonra token doğrula.
  //
  // Kullanıcıyı localStorage'dan İYİMSER set ETME: bu, aşağıdaki veri efektini
  // (config/teams/directory) daha token doğrulanmadan tetikliyordu. Token süresi
  // dolmuşsa (TOKEN_TTL_HOURS=12) o istekler 401 dönüp ekrana hata basıyordu.
  // Önce fetchMe ile doğrula — zaten authReady olana dek "Yükleniyor…" gösteriliyor,
  // yani iyimser set'in görsel bir faydası da yoktu.
  useEffect(() => {
    setupStatus()
      .then((s) => {
        if (s.needs_setup) {
          setNeedsSetup(true);
          setAuthReady(true);
          return;
        }
        if (getToken() && getStoredUser()) {
          fetchMe()
            .then((u) => setUser(u))
            .catch(() => { logout(); setUser(null); })
            .finally(() => setAuthReady(true));
        } else {
          setAuthReady(true);
        }
      })
      .catch(() => setAuthReady(true));
  }, []);

  // Oturum süresi dolunca (401) temiz düşür.
  useEffect(() => {
    function onExpired() {
      setUser(null);
      setUiConfig(null);
      setTeams([]);
      setTeamId(null);
      setSummary(null);
      setTab("team");
      // Hata kutusu OTURUM düşmesinin doğru cevabı değil — login ekranı öyle.
      // Temizlenmezse giriş yapıldıktan sonra bile ekranı kaplamaya devam eder.
      setError(null);
    }
    window.addEventListener("vantage:session-expired", onExpired);
    return () => window.removeEventListener("vantage:session-expired", onExpired);
  }, []);

  // Takım listesi yönetici panelinden değişebilir (ekle/sil/yeniden adlandır).
  // Seçili takım silinmişse seçim ilk takıma düşer, ekran boş kalmasın.
  function refreshTeams() {
    api("/api/teams")
      .then((tms) => {
        setTeams(tms);
        setTeamId((cur) => (tms.some((t) => t.id === cur) ? cur : (tms[0]?.id ?? null)));
      })
      // Bu çağrı takım ekleme/silme/yeniden adlandırma sonrası çalışır: sessizce
      // yutulursa yönetici işlemin başarısız olduğunu değil, listenin eski
      // kaldığını görür ve aynı takımı tekrar yaratmayı dener.
      .catch((e) => toast(t("Takım listesi yenilenemedi: {msg}", { msg: e.message }), "error"));
  }

  // Giriş sonrası çekirdek veriyi yükle (parola değiştirme beklemiyorsa).
  useEffect(() => {
    if (!user || user.must_change_password) return;
    setViewDevId(user.developer_id);
    Promise.all([api("/api/config/ui"), api("/api/teams"), api("/api/directory")])
      .then(([cfg, tms, dir]) => {
        setUiConfig(cfg);
        setTeams(tms);
        setDirectory(dir);
        // Admin'in kendi developer_id'si olmayabilir; bireysel görünüm için
        // dizindeki ilk kişiyi varsayılan seç ki ekran boş kalmasın.
        if (user.developer_id == null && dir.length) {
          setViewDevId((cur) => cur ?? dir[0].id);
        }
        if (tms.length) {
          const saved = readNav().team;
          const valid = tms.some((t) => t.id === saved);
          setTeamId((cur) => cur ?? (valid ? saved : tms[0].id));
        }
      })
      .catch(setError);
  }, [user]);

  // Anonim memnuniyet anketi — TEK KAYNAK: bir kez çek, banner+rozet+sayfa paylaşır.
  useEffect(() => {
    if (!user || user.must_change_password) return;
    getCurrentSurvey().then(setSurvey).catch(() => setSurvey({ enabled: false }));
  }, [user]);

  // Bildirimden ya da paylaşılan bağlantıdan "?survey=1" ile gelindiyse ankete git.
  useEffect(() => {
    if (!user) return;
    if (new URLSearchParams(location.search).get("survey") === "1") setTab("survey");
  }, [user]);

  // Rapor: seçilen aralığa (7/30/90) göre ANLIK hesap — metrik+trend+sinyal+delta.
  //
  // `lang` NEDEN BAĞIMLILIK: metrik adı/açıklaması ve durum etiketi sunucudan
  // ÇEVRİLMİŞ gelir (Accept-Language). Bu veri App'in kendi state'inde durur ve
  // App hiç unmount olmaz — dil değişince yeniden çekilmezse pano eski dilde
  // DONAR; sekme değiştirip geri gelmek de kurtarmaz (aşağıdaki key={lang}
  // yalnız ALT ağacı tazeler, App'in state'ini değil).
  useEffect(() => {
    if (teamId == null) return;
    // Hızlı TR↔EN geçişinde önceki isteğin cevabı sonra dönebilir; iptal
    // bayrağı olmadan eski dildeki cevap yeninin üstüne yazardı.
    let iptal = false;
    api(`/api/teams/${teamId}/report?days=${range}`)
      .then((rep) => {
        if (iptal) return;
        setSummary(rep);
        setSeries(rep.series || []);
        setSignals(rep.signals || []);
      })
      .catch((e) => { if (!iptal) setError(e); });
    return () => { iptal = true; };
  }, [teamId, range, lang]);

  // Anotasyon + kod sağlığını aralıktan bağımsız yükle (takım ya da dil değişince
  // — kod sağlığı boyut adları ve durum etiketleri de sunucudan çevrili gelir).
  useEffect(() => {
    if (teamId == null) return;
    let iptal = false;
    const ata = (setter) => (v) => { if (!iptal) setter(v); };
    api(`/api/annotations?team_id=${teamId}`).then(ata(setAnnotations)).catch(() => ata(setAnnotations)([]));
    api(`/api/teams/${teamId}/code-health`).then(ata(setCodeHealth)).catch(() => ata(setCodeHealth)(null));
    api(`/api/teams/${teamId}/code-health/series`).then(ata(setCodeHealthSeries)).catch(() => ata(setCodeHealthSeries)(null));
    return () => { iptal = true; };
  }, [teamId, lang]);

  function doLogout() {
    logout();
    setUser(null);
    setUiConfig(null);
    setTeams([]);
    setTeamId(null);
    setSummary(null);
    setTab("team");
  }

  function cycleTheme() {
    setTheme((t) => (t === "auto" ? "light" : t === "light" ? "dark" : "auto"));
  }
  const themeLabel = theme === "auto" ? t("Tema: Oto") : theme === "light" ? t("Tema: Açık") : t("Tema: Koyu");

  function exportCsv() {
    if (!summary) return;
    const teamName = teams.find((tm) => tm.id === teamId)?.name || t("takim");
    const rows = [[t("Metrik"), t("Değer"), t("Birim"), t("Durum"), t("Veri tamlığı")]];
    summary.metrics.forEach((m) => {
      rows.push([
        m.title || m.key,
        m.value ?? "",
        m.unit ?? "",
        m.status_label ?? m.status ?? "",
        m.data_completeness != null ? `%${Math.round(m.data_completeness * 100)}` : "",
      ]);
    });
    const csv = rows.map((r) => r.map((c) => `"${String(c).replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vantage-${teamName}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (!authReady) return <div className="app">{t("Yükleniyor…")}</div>;
  if (needsSetup) return <Setup onSuccess={(u) => { setNeedsSetup(false); setUser(u); }} />;
  // Yeni oturum, önceki oturumun hatasını miras almaz.
  if (!user) return <Login onSuccess={(u) => { setError(null); setUser(u); }} />;
  if (user.must_change_password) {
    return (
      <ForceChangePassword
        onDone={() => fetchMe().then(setUser).catch(doLogout)}
        onLogout={doLogout}
      />
    );
  }

  if (error) return <div className="error-box">{t("Hata: {msg}", { msg: error.message })}</div>;
  if (!uiConfig) return <div className="app">{t("Yükleniyor…")}</div>;

  const individualAvailable = uiConfig.individual_view_enabled;
  const isAdmin = user.role === "admin";
  const isHr = user.role === "hr";
  const canManageLeaves = isAdmin || isHr;
  // Yönetici rolleri anketi DOLDURMAZ (backend respondent:false döner). Yüklenmeden
  // önce admin'i varsayılan katılımcı-dışı say (sekme titremesin).
  const surveyRespondent = survey ? survey.respondent !== false : !isAdmin;
  // Açık + doldurulmamış anket varsa banner + nav rozeti gösterilir (yalnız katılımcıya).
  const surveyPending = !!(surveyRespondent && survey && survey.enabled && survey.ready && survey.is_open && !survey.already_submitted);

  return (
    // key={lang}: dil değişince BU ağaç baştan kurulur, yani her panel kendi
    // verisini yeni `Accept-Language` ile TEKRAR çeker.
    //
    // NEDEN MERKEZÎ ÇÖZÜM (her panele tek tek `lang` bağımlılığı eklemek yerine):
    // sunucudan çevrilmiş metin dönen uç sayısı çok — belge kataloğu, izin
    // türleri, kod sağlığı boyutları, İK kontrol listesi, metrik drill-down…
    // Her birine ayrı ayrı bağımlılık eklemek "yeni panelde eklemeyi unutma"
    // riskini kalıcı hâle getirirdi; backend'de aynı sorun için tek merkezden
    // ContextVar middleware'i tercih edildi (bkz. app/core/i18n.py).
    //
    // BEDELİ bilinçli: panele ait geçici arayüz durumu (açık modal, yarım
    // doldurulmuş form, kaydırma konumu) sıfırlanır. Dil değiştirmek nadir ve
    // KASITLI bir eylem; yarısı Türkçe kalan bir ekrandan iyidir.
    //
    // Giriş/kurulum ekranları bu ağacın DIŞINDA (yukarıdaki erken dönüşler):
    // dil değiştirmek yazılmakta olan e-posta/parolayı silmesin.
    <div className="app" key={lang}>
      <TopBar
        user={user}
        isAdmin={isAdmin}
        isHr={isHr}
        tab={tab}
        onTab={setTab}
        teams={teams}
        teamId={teamId}
        onTeam={setTeamId}
        individualAvailable={individualAvailable}
        surveyRespondent={surveyRespondent}
        surveyPending={surveyPending}
        anonymized={uiConfig.anonymize_individuals}
        themeLabel={themeLabel}
        onCycleTheme={cycleTheme}
        onOpenPalette={() => setPaletteOpen(true)}
        onLogout={doLogout}
      />

      {surveyPending && tab !== "survey" && !surveyDismissed && (
        <SurveyBanner
          onOpen={() => setTab("survey")}
          onDismiss={() => setSurveyDismissed(true)}
        />
      )}

      <Suspense fallback={<LazyFallback />}>
        {tab === "survey" && (
          <SurveyForm
            survey={survey}
            onSubmitted={() => setSurvey((s) => ({ ...s, already_submitted: true }))}
          />
        )}

        {tab === "settings" && (
          <Settings
            user={user}
            theme={theme}
            onCycleTheme={cycleTheme}
            themeLabel={themeLabel}
            onLogout={doLogout}
            onProfileUpdated={(u) => setUser((cur) => ({ ...cur, ...u }))}
          />
        )}

        {tab === "projects" && !isHr && (
          <ProjectsPanel isAdmin={isAdmin} localEnabled={uiConfig.projects_local_enabled} />
        )}

        {tab === "leaves" && <LeavesPanel user={user} canManage={canManageLeaves} teams={teams} />}

        {/* Bordro/özlük evrakı: herkes kendi belgesini yükler, admin+İK herkesinkini
            görür ve karara bağlar (sunucu da aynı sınırı zorlar). */}
        {tab === "documents" && <DocumentsPanel user={user} canManage={canManageLeaves} />}

        {tab === "hr" && isHr && <HrDashboard />}

        {/* İK hesap rehberi: yalnız çalışan (user) ekler/sıfırlar. Performans
            bağlantısı YOK (onViewPerson geçilmez — etik sınır). */}
        {tab === "accounts" && isHr && (
          <AdminPanel teams={teams} me={user} hrMode />
        )}

        {tab === "admin" && isAdmin && (
          <AdminPanel
            teams={teams}
            me={user}
            onTeamsChanged={refreshTeams}
            onViewPerson={individualAvailable ? (devId) => { pushRecent(devId); setViewDevId(devId); setTab("me"); } : undefined}
          />
        )}
      </Suspense>

      {tab === "team" && !summary && !error && (
        <div className="cards" aria-hidden="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="card skeleton">
              <div className="sk-line sk-title" />
              <div className="sk-line sk-value" />
              <div className="sk-line" />
              <div className="sk-line short" />
            </div>
          ))}
        </div>
      )}

      {tab === "team" && summary && (
        <>
          <div className="team-toolbar">
            <div className="range-picker" role="group" aria-label={t("Tarih aralığı")}>
              {RANGE_OPTIONS.map((d) => (
                <button
                  key={d}
                  className={`mini${range === d ? " active" : ""}`}
                  onClick={() => setRange(d)}
                >
                  {t("{n} gün", { n: d })}
                </button>
              ))}
            </div>
            <span style={{ flex: 1 }} />
            <button className="mini" onClick={exportCsv}>{t("CSV indir")}</button>
            <button className="mini" onClick={() => window.print()}>{t("Yazdır / PDF")}</button>
          </div>
          {(() => {
            const all = [...summary.metrics, ...signals, ...(codeHealth ? [codeHealth] : [])];
            const c = { red: 0, yellow: 0, green: 0 };
            all.forEach((m) => { if (c[m.status] != null) c[m.status] += 1; });
            const total = c.red + c.yellow + c.green;
            if (total === 0) return null;
            return (
              <div className="status-band" role="status">
                <strong>
                  {c.red > 0
                    ? t("{n} alan yardım istiyor", { n: c.red })
                    : c.yellow > 0
                    ? t("Takım genel olarak iyi, birkaç alan izlenmeli")
                    : t("Her şey akıyor 🎉")}
                </strong>
                <span className="sb-chips">
                  {c.red > 0 && <span className="sb red">● {t("{n} zorlanıyor", { n: c.red })}</span>}
                  {c.yellow > 0 && <span className="sb yellow">▲ {t("{n} izlenmeli", { n: c.yellow })}</span>}
                  {c.green > 0 && <span className="sb green">✓ {t("{n} akıyor", { n: c.green })}</span>}
                </span>
              </div>
            );
          })()}

          <div className="cards">
            {summary.metrics.map((m) => (
              <MetricCard
                key={m.key}
                metric={m}
                previous={m.previous_value}
                series={series.find((s) => s.metric === m.key)}
                onClick={() => setDrill({ key: m.key, name: m.name })}
              />
            ))}
            {codeHealth && (
              <CodeHealthCard health={codeHealth} onClick={() => setCodeDrill(true)} />
            )}
          </div>

          {summary.metrics.length > 0 && summary.metrics.every((m) => m.status === "insufficient_data") && (
            <div className="empty-guide">
              <h3>{t("Bu takım için henüz yeterli veri yok")}</h3>
              <p>
                {isAdmin
                  ? t("Gerçek veri için: kaynağı bağla (config.yaml) → senkron çalıştır. Yönetici paneli → Başlangıç adımlarını izle.")
                  : t("Veri toplandıkça metrikler burada görünecek. Sorun sürerse yöneticine danış.")}
              </p>
              {isAdmin && (
                <button className="mini" onClick={() => setTab("admin")}>{t("Yönetici paneli → Başlangıç")}</button>
              )}
            </div>
          )}

          <SignalsBlock signals={signals} />

          {summary.recommendations.length > 0 && (
            <section className="section">
              <h2>{t("Süreç önerileri")}</h2>
              <div className="recs">
                {summary.recommendations.map((r) => (
                  <div key={r.rule} className={`rec ${r.severity}`}>
                    <div className="rule">{r.rule.replaceAll("_", " ")}</div>
                    {r.message}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="section">
            <h2>{t("Trend ({n} gün)", { n: range })}</h2>
            <div className="charts">
              {series.map((s) => (
                <TrendChart
                  key={s.metric}
                  series={s}
                  threshold={uiConfig.metric_thresholds?.[s.metric]}
                  annotations={annotations}
                />
              ))}
              {codeHealthSeries && codeHealthSeries.points?.some((p) => p.value != null) && (
                <TrendChart series={codeHealthSeries} annotations={annotations} />
              )}
            </div>
          </section>
        </>
      )}

      {tab === "me" && (
        <>
          {/* Yönetici, ekibindeki bir kişiye bakabilir; sunucu yetkiyi zorlar.
              Aranabilir seçici: uzun listede isimle filtre + son bakılanlar. */}
          <div className="indiv-toolbar">
            <span className="ctx-label">{t("Kişi")}</span>
            <PersonPicker
              people={directory}
              value={viewDevId ?? user.developer_id ?? null}
              selfDevId={user.developer_id}
              onChange={setViewDevId}
            />
            {user.developer_id != null && (viewDevId ?? user.developer_id) !== user.developer_id && (
              <button className="mini ghost" onClick={() => setViewDevId(user.developer_id)}>
                {t("Bana dön")}
              </button>
            )}
          </div>
          {(viewDevId ?? user.developer_id) != null ? (
            <Suspense fallback={<LazyFallback />}>
              <IndividualView devId={viewDevId ?? user.developer_id} />
            </Suspense>
          ) : (
            <p className="desc">{t("Bu hesap bir geliştiriciye bağlı değil.")}</p>
          )}
          {/* "Kodum" AI kod sağlığı: yalnız KENDİNE bakarken (admin başkasına
              bakarken gizli — /api/me yalnız oturum sahibinin kodudur). */}
          {user.developer_id != null && (viewDevId ?? user.developer_id) === user.developer_id && (
            <Suspense fallback={<LazyFallback />}>
              <MyCodeHealth user={user} />
            </Suspense>
          )}
        </>
      )}

      {drill && (
        <MetricDrilldown
          teamId={teamId}
          metricKey={drill.key}
          metricName={drill.name}
          days={range}
          onClose={() => setDrill(null)}
        />
      )}

      {codeDrill && (
        <CodeHealthDrilldown
          path={`/api/teams/${teamId}/code-health/breakdown`}
          title={t("Kod Sağlığı — dikkat isteyen bölümler (takım)")}
          onClose={() => setCodeDrill(false)}
        />
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        tabs={isHr ? [
          { key: "hr", label: t("nav.hr") },
          { key: "leaves", label: t("nav.leaves") },
          { key: "documents", label: t("nav.documents") },
          { key: "accounts", label: t("nav.accounts") },
          ...(surveyRespondent ? [{ key: "survey", label: t("nav.survey") }] : []),
          { key: "settings", label: t("nav.settings") },
        ] : [
          { key: "team", label: t("nav.team") },
          ...(individualAvailable ? [{ key: "me", label: t("nav.me") }] : []),
          { key: "projects", label: t("nav.projects") },
          { key: "leaves", label: t("nav.leaves") },
          { key: "documents", label: t("nav.documents") },
          ...(surveyRespondent ? [{ key: "survey", label: t("nav.survey") }] : []),
          ...(isAdmin ? [{ key: "admin", label: t("nav.admin") }] : []),
          { key: "settings", label: t("nav.settings") },
        ]}
        teams={isHr ? [] : teams}
        people={!isHr && individualAvailable ? directory : []}
        onGoTab={setTab}
        onGoTeam={(id) => { setTeamId(id); setTab("team"); }}
        onGoPerson={(id) => { pushRecent(id); setViewDevId(id); setTab("me"); }}
      />

      <ToastHost />
    </div>
  );
}
