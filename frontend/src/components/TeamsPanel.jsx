import { useEffect, useState } from "react";
import { createTeam, deleteTeam, listTeamsAdmin, renameTeam } from "../api.js";
import { toast } from "../toast.js";

// Yönetici: takım oluştur / yeniden adlandır / sil.
// Önceden takımlar YALNIZCA ingest sırasında (Trello board adı, repo eşlemesi)
// örtük doğuyordu — kurulu bir sistemde yeni takım için YAML düzenlemek gerekiyordu.
export default function TeamsPanel({ onChanged }) {
  const [teams, setTeams] = useState(null);
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState(null);   // {id, name}
  const [confirming, setConfirming] = useState(null); // silme onayı bekleyen id
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function load() {
    listTeamsAdmin().then(setTeams).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function run(fn, okMsg) {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      toast(typeof okMsg === "function" ? okMsg(res) : okMsg, "ok");
      load();
      // Üstteki takım listeleri (çalışan ataması, pano seçici) bayat kalmasın.
      onChanged && onChanged();
      return true;
    } catch (e) {
      setError(e.message);
      toast(e.message, "error");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(e) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    if (await run(() => createTeam(name), `'${name}' oluşturuldu.`)) setNewName("");
  }

  async function saveRename() {
    const name = editing.name.trim();
    if (!name) return;
    const ok = await run(
      () => renameTeam(editing.id, name),
      (r) => r.config_updated
        ? `Ad değişti; repo eşlemesi de güncellendi.`
        : `Ad değişti.`
    );
    if (ok) setEditing(null);
  }

  async function remove(team) {
    const ok = await run(
      () => deleteTeam(team.id),
      (r) => r.detached_tasks
        ? `'${team.name}' silindi; ${r.detached_tasks} görev takımsız kaldı (silinmedi).`
        : `'${team.name}' silindi.`
    );
    if (ok) setConfirming(null);
  }

  if (error && !teams) return <div className="login-error">{error}</div>;
  if (!teams) return <p className="desc">Yükleniyor…</p>;

  return (
    <div className="teams-panel">
      <section className="section">
        <h2>Takımlar</h2>
        <p className="desc">
          Metrikler takım seviyesinde hesaplanır. Bir takıma repo bağlanmadan git
          metrikleri, görev kaynağı bağlanmadan akış metrikleri üretilemez —
          bağlama işi Entegrasyon sekmesinde.
        </p>

        <form className="team-create" onSubmit={add}>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Yeni takım adı"
            maxLength={200}
          />
          <button className="login-btn" type="submit" disabled={busy || !newName.trim()}>
            Takım ekle
          </button>
        </form>

        {teams.length === 0 ? (
          <p className="desc">Henüz takım yok.</p>
        ) : (
          <div className="team-rows">
            {teams.map((t) => (
              <div key={t.id} className="team-row">
                <div className="team-row-main">
                  {editing?.id === t.id ? (
                    <div className="team-rename">
                      <input
                        value={editing.name}
                        autoFocus
                        maxLength={200}
                        onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") saveRename();
                          if (e.key === "Escape") setEditing(null);
                        }}
                      />
                      <button className="mini" onClick={saveRename} disabled={busy}>Kaydet</button>
                      <button className="mini" onClick={() => setEditing(null)}>Vazgeç</button>
                    </div>
                  ) : (
                    <>
                      <div className="team-name">{t.name}</div>
                      <div className="team-usage">
                        {t.members} üye · {t.repos} repo · {t.tasks} görev
                      </div>
                    </>
                  )}
                </div>

                {editing?.id !== t.id && (
                  <div className="team-row-actions">
                    <button className="mini" onClick={() => setEditing({ id: t.id, name: t.name })}>
                      Yeniden adlandır
                    </button>
                    {confirming === t.id ? (
                      <>
                        <button className="mini danger" onClick={() => remove(t)} disabled={busy}>
                          Evet, sil
                        </button>
                        <button className="mini" onClick={() => setConfirming(null)}>Vazgeç</button>
                      </>
                    ) : (
                      <button
                        className="mini danger"
                        onClick={() => setConfirming(t.id)}
                        disabled={!t.deletable}
                        title={t.deletable
                          ? "Takımı sil"
                          : "Önce üyeleri ve repoları ayırın (Hesaplar / Entegrasyon)"}
                      >
                        Sil
                      </button>
                    )}
                  </div>
                )}

                {confirming === t.id && t.tasks > 0 && (
                  <p className="team-warn">
                    {t.tasks} görev bu takıma bağlı. Görevler <strong>silinmez</strong>,
                    takımsız kalır; metrik ve öneri kayıtları temizlenir.
                  </p>
                )}
                {!t.deletable && confirming !== t.id && (
                  <p className="team-hint">
                    Silinemez: {t.members > 0 && `${t.members} üye`}
                    {t.members > 0 && t.repos > 0 && " ve "}
                    {t.repos > 0 && `${t.repos} repo`} bağlı.
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
        {error && <div className="login-error">{error}</div>}
      </section>
    </div>
  );
}
