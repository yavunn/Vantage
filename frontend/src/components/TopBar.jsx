import NotificationBell from "./NotificationBell.jsx";

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

export default function TopBar({
  user, isAdmin, isHr,
  tab, onTab,
  teams, teamId, onTeam,
  individualAvailable, surveyRespondent, surveyPending,
  anonymized,
  themeLabel, onCycleTheme, onOpenPalette, onLogout,
}) {
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
          <button className="mini ghost cmdk-trigger" onClick={onOpenPalette} title="Hızlı arama (Ctrl+K)">
            <span aria-hidden="true">⌕</span> Ara <kbd>Ctrl K</kbd>
          </button>
          <NotificationBell onNavigate={({ teamId: tid, survey: goSurvey }) => {
            if (goSurvey) { onTab("survey"); return; }
            if (tid != null) { onTeam(tid); onTab("team"); }
          }} />
          <button className="mini ghost" onClick={onCycleTheme} title="Açık/Koyu/Oto tema">{themeLabel}</button>
          <span className="user-chip">
            {user.display_name}
            {isAdmin && <span className="role-badge">admin</span>}
            {isHr && <span className="role-badge hr-badge">İK</span>}
          </span>
          <button className="mini ghost" onClick={onLogout}>Çıkış</button>
        </div>
      </div>

      <div className="topbar-row topbar-row-nav">
        <nav className="topbar-tabs" aria-label="Ana gezinme">
          {isHr ? (
            <>
              <Tab id="hr">İK Panosu</Tab>
              <Tab id="leaves">İzinler</Tab>
              <Tab id="accounts">Hesaplar</Tab>
              {surveyRespondent && (
                <Tab id="survey">
                  Anket{surveyPending && <span className="tab-dot" aria-label="bekliyor" />}
                </Tab>
              )}
              <Tab id="settings">Ayarlar</Tab>
            </>
          ) : (
            <>
              <Tab id="team">Takım görünümü</Tab>
              {individualAvailable && <Tab id="me">Bireysel görünüm</Tab>}
              <Tab id="projects">Projelerim</Tab>
              <Tab id="leaves">İzinler</Tab>
              {surveyRespondent && (
                <Tab id="survey">
                  Anket{surveyPending && <span className="tab-dot" aria-label="bekliyor" />}
                </Tab>
              )}
              {isAdmin && <Tab id="admin">Yönetici paneli</Tab>}
              <Tab id="settings">Ayarlar</Tab>
            </>
          )}
        </nav>

        {/* Takım seçici yalnız takıma bağlı sekmede — bağlam kirliliği olmasın. */}
        {tab === "team" && (
          <label className="topbar-context">
            <span className="ctx-label">Takım</span>
            <select value={teamId ?? ""} onChange={(e) => onTeam(Number(e.target.value))} aria-label="Takım seç">
              {teams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      <span className="sub">
        Süreç sağlığı panosu — kişi performans aracı değildir. Kırmızı,
        "takım zorlanıyor, yardım gerekebilir" demektir; ceza sinyali değildir.
        {anonymized && " · Anonim mod açık (takım-agregat)."}
      </span>
    </header>
  );
}
