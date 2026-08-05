import NotificationBell from "./NotificationBell.jsx";
import { LANGS, useLang } from "../i18n.jsx";

// Kabuk: kimlik satırı + gezinme. App.jsx'ten çıkarıldı — orada 100 satırlık
// JSX, veri yükleme mantığının ortasında duruyordu.
//
// ETİK SINIR BURADA GÖRÜNÜR: İK'nın sekme kümesi ayrıdır. İK'ya takım/bireysel
// performans sekmeleri GÖSTERİLMEZ (backend de bu uçlara 403 verir; ikisi
// birbirinin yedeği). Bu yüzden iki küme bilerek ayrı yazıldı, tek bir listeyi
// filtrelemekle değil — sekme eklerken hangi rolü etkilediği görünsün.
function BrandMark() {
  return (
    <span className="topbar-mark" aria-hidden="true">
      <svg viewBox="0 0 96 28" width="96" height="28">
        <polyline
          className="ecg"
          points="0,14 18,14 24,14 29,4 36,24 42,14 48,14 53,9 58,19 63,14 96,14"
          fill="none" stroke="currentColor" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

/** Dil seçici — giriş ekranındakiyle aynı bileşen davranışı, üst çubuk ölçeği. */
function LangSwitch() {
  const { lang, setLang, t } = useLang();
  return (
    <div className="lang-switch mini-switch" role="group" aria-label={t("top.langTitle")}>
      {Object.entries(LANGS).map(([code, label]) => (
        <button
          key={code}
          type="button"
          className={`lang-opt ${lang === code ? "active" : ""}`}
          aria-pressed={lang === code}
          onClick={() => setLang(code)}
          title={label}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export default function TopBar({
  user, isAdmin, isHr,
  tab, onTab,
  teams, teamId, onTeam,
  individualAvailable, surveyRespondent, surveyPending,
  anonymized,
  themeLabel, onCycleTheme, onOpenPalette, onLogout,
}) {
  const { t } = useLang();
  const Tab = ({ id, children }) => (
    <button className={`tab ${tab === id ? "active" : ""}`} onClick={() => onTab(id)}>
      {children}
    </button>
  );

  return (
    <header className="topbar">
      <div className="topbar-row topbar-row-main">
        <div className="topbar-brand">
          <BrandMark />
          <div>
            <h1>Vantage</h1>
          </div>
        </div>

        <div className="topbar-user">
          <button className="mini ghost cmdk-trigger" onClick={onOpenPalette} title={t("top.searchTitle")}>
            <span aria-hidden="true">⌕</span> {t("top.search")} <kbd>Ctrl K</kbd>
          </button>
          <NotificationBell onNavigate={({ teamId: tid, survey: goSurvey }) => {
            if (goSurvey) { onTab("survey"); return; }
            if (tid != null) { onTeam(tid); onTab("team"); }
          }} />
          <button className="mini ghost" onClick={onCycleTheme} title={t("top.themeTitle")}>{themeLabel}</button>
          <LangSwitch />
          <span className="user-chip">
            {user.display_name}
            {isAdmin && <span className="role-badge">admin</span>}
            {isHr && <span className="role-badge hr-badge">{t("İK")}</span>}
          </span>
          <button className="mini ghost" onClick={onLogout}>{t("top.logout")}</button>
        </div>
      </div>

      <div className="topbar-row topbar-row-nav">
        <nav className="topbar-tabs" aria-label={t("nav.aria")}>
          {isHr ? (
            <>
              <Tab id="hr">{t("nav.hr")}</Tab>
              <Tab id="leaves">{t("nav.leaves")}</Tab>
              <Tab id="accounts">{t("nav.accounts")}</Tab>
              {surveyRespondent && (
                <Tab id="survey">
                  {t("nav.survey")}{surveyPending && <span className="tab-dot" aria-label={t("top.pending")} />}
                </Tab>
              )}
              <Tab id="settings">{t("nav.settings")}</Tab>
            </>
          ) : (
            <>
              <Tab id="team">{t("nav.team")}</Tab>
              {individualAvailable && <Tab id="me">{t("nav.me")}</Tab>}
              <Tab id="projects">{t("nav.projects")}</Tab>
              <Tab id="leaves">{t("nav.leaves")}</Tab>
              {surveyRespondent && (
                <Tab id="survey">
                  {t("nav.survey")}{surveyPending && <span className="tab-dot" aria-label={t("top.pending")} />}
                </Tab>
              )}
              {isAdmin && <Tab id="admin">{t("nav.admin")}</Tab>}
              <Tab id="settings">{t("nav.settings")}</Tab>
            </>
          )}
        </nav>

        {/* Takım seçici yalnız takıma bağlı sekmede — bağlam kirliliği olmasın. */}
        {tab === "team" && (
          <label className="topbar-context">
            <span className="ctx-label">{t("top.team")}</span>
            <select value={teamId ?? ""} onChange={(e) => onTeam(Number(e.target.value))} aria-label={t("top.selectTeam")}>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      <span className="sub">
        {t("top.tagline")}
        {anonymized && t("top.anonymized")}
      </span>
    </header>
  );
}
