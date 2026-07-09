// Engineering Health Dashboard — varsayılan görünüm TAKIM'dır (İlke E).
// Bireysel sekme yalnızca yetkiliyse içerik gösterir; leaderboard yoktur.
// Faz 2: rol bazlı görünüm — admin'e Yönetim sekmesi, kimlik AuthContext'te.
import { useEffect, useState } from "react";
import { api, isLoggedIn, logout } from "./api.js";
import { AuthContext } from "./AuthContext.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";
import LeaveApprovalList from "./components/LeaveApprovalList.jsx";
import LeaveCalendar from "./components/LeaveCalendar.jsx";
import LeaveRequestForm from "./components/LeaveRequestForm.jsx";
import LoginPage from "./components/LoginPage.jsx";
import ProjectList from "./components/ProjectList.jsx";
import UserDashboard from "./components/UserDashboard.jsx";

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn());
  const [me, setMe] = useState(null);             // /api/me — hesap + geliştirici profili
  const [uiConfig, setUiConfig] = useState(null);
  const [teams, setTeams] = useState([]);
  const [teamId, setTeamId] = useState(null);
  const [directory, setDirectory] = useState([]);
  const [tab, setTab] = useState("team");
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!authed) return;
    Promise.all([
      api("/api/config/ui"),
      api("/api/teams"),
      api("/api/directory"),
      api("/api/me"),
    ])
      .then(([cfg, tms, dir, who]) => {
        setUiConfig(cfg);
        setTeams(tms);
        setDirectory(dir);
        setMe(who);
        if (tms.length) setTeamId(tms[0].id);
      })
      .catch(setError);
  }, [authed]);

  if (!authed) return <LoginPage onLogin={() => setAuthed(true)} />;
  if (error) return <div className="error-box">Hata: {error.message}</div>;
  if (!uiConfig || !me) return <div className="app">Yükleniyor…</div>;

  const individualAvailable = uiConfig.individual_view_enabled;
  const isAdmin = me.account?.role === "admin";

  return (
    <AuthContext.Provider value={me}>
      <div className="app">
        <header className="topbar">
          <h1>Engineering Health Dashboard</h1>
          <select value={teamId ?? ""} onChange={(e) => setTeamId(Number(e.target.value))}>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <button className={`tab ${tab === "team" ? "active" : ""}`} onClick={() => setTab("team")}>
            Takım görünümü
          </button>
          {individualAvailable && (
            <button
              className={`tab ${tab === "me" ? "active" : ""}`}
              onClick={() => setTab("me")}
            >
              Bireysel görünüm
            </button>
          )}
          <button
            className={`tab ${tab === "projects" ? "active" : ""}`}
            onClick={() => setTab("projects")}
          >
            Projelerim
          </button>
          <button
            className={`tab ${tab === "leave" ? "active" : ""}`}
            onClick={() => setTab("leave")}
          >
            İzinler
          </button>
          {isAdmin && (
            <button
              className={`tab ${tab === "admin" ? "active" : ""}`}
              onClick={() => setTab("admin")}
            >
              Yönetim
            </button>
          )}
          <span className="sub">
            Süreç sağlığı panosu — kişi performans aracı değildir. Kırmızı,
            "takım zorlanıyor, yardım gerekebilir" demektir; ceza sinyali değildir.
            {uiConfig.anonymize_individuals && " · Anonim mod açık (takım-agregat)."}
          </span>
          <span className="sub">
            {me.display_name ?? me.account?.email ?? ""}
          </span>
          <button
            className="tab"
            onClick={() => {
              logout();
              setAuthed(false);
              setMe(null);
              setTab("team");
            }}
          >
            Çıkış
          </button>
        </header>

        {tab === "admin" && isAdmin ? (
          <AdminDashboard />
        ) : tab === "projects" ? (
          <ProjectList />
        ) : tab === "leave" ? (
          <>
            <LeaveApprovalList />
            <LeaveRequestForm />
            <LeaveCalendar teamId={teamId} />
          </>
        ) : (
          <UserDashboard tab={tab} teamId={teamId} directory={directory} />
        )}
      </div>
    </AuthContext.Provider>
  );
}
