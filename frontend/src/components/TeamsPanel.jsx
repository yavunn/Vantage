import { useEffect, useState } from "react";
import { createTeam, deleteTeam, listTeamsAdmin, renameTeam } from "../api.js";
import { toast } from "../toast.js";
import { useT } from "../i18n.jsx";

// Yönetici: takım oluştur / yeniden adlandır / sil.
// Önceden takımlar YALNIZCA ingest sırasında (Trello board adı, repo eşlemesi)
// örtük doğuyordu — kurulu bir sistemde yeni takım için YAML düzenlemek gerekiyordu.
export default function TeamsPanel({ onChanged }) {
  const t = useT();
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
    if (await run(() => createTeam(name), t("'{name}' oluşturuldu.", { name }))) setNewName("");
  }

  async function saveRename() {
    const name = editing.name.trim();
    if (!name) return;
    const ok = await run(
      () => renameTeam(editing.id, name),
      (r) => r.config_updated
        ? t("Ad değişti; repo eşlemesi de güncellendi.")
        : t("Ad değişti.")
    );
    if (ok) setEditing(null);
  }

  async function remove(team) {
    const ok = await run(
      () => deleteTeam(team.id),
      (r) => r.detached_tasks
        ? t("'{name}' silindi; {n} görev takımsız kaldı (silinmedi).", { name: team.name, n: r.detached_tasks })
        : t("'{name}' silindi.", { name: team.name })
    );
    if (ok) setConfirming(null);
  }

  if (error && !teams) return <div className="login-error">{error}</div>;
  if (!teams) return <p className="desc">{t("Yükleniyor…")}</p>;

  return (
    <div className="teams-panel">
      <section className="section">
        <h2>{t("Takımlar")}</h2>
        <p className="desc">
          {t("Metrikler takım seviyesinde hesaplanır. Bir takıma repo bağlanmadan git metrikleri, görev kaynağı bağlanmadan akış metrikleri üretilemez — bağlama işi Entegrasyon sekmesinde.")}
        </p>

        <form className="team-create" onSubmit={add}>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("Yeni takım adı")}
            maxLength={200}
          />
          <button className="login-btn" type="submit" disabled={busy || !newName.trim()}>
            {t("Takım ekle")}
          </button>
        </form>

        {teams.length === 0 ? (
          <p className="desc">{t("Henüz takım yok.")}</p>
        ) : (
          <div className="team-rows">
            {teams.map((tm) => (
              <div key={tm.id} className="team-row">
                <div className="team-row-main">
                  {editing?.id === tm.id ? (
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
                      <button className="mini" onClick={saveRename} disabled={busy}>{t("Kaydet")}</button>
                      <button className="mini" onClick={() => setEditing(null)}>{t("Vazgeç")}</button>
                    </div>
                  ) : (
                    <>
                      <div className="team-name">{tm.name}</div>
                      <div className="team-usage">
                        {t("{a} üye · {b} repo · {c} görev", { a: tm.members, b: tm.repos, c: tm.tasks })}
                      </div>
                    </>
                  )}
                </div>

                {editing?.id !== tm.id && (
                  <div className="team-row-actions">
                    <button className="mini" onClick={() => setEditing({ id: tm.id, name: tm.name })}>
                      {t("Yeniden adlandır")}
                    </button>
                    {confirming === tm.id ? (
                      <>
                        <button className="mini danger" onClick={() => remove(tm)} disabled={busy}>
                          {t("Evet, sil")}
                        </button>
                        <button className="mini" onClick={() => setConfirming(null)}>{t("Vazgeç")}</button>
                      </>
                    ) : (
                      <button
                        className="mini danger"
                        onClick={() => setConfirming(tm.id)}
                        disabled={!tm.deletable}
                        title={tm.deletable
                          ? t("Takımı sil")
                          : t("Önce üyeleri ve repoları ayırın (Hesaplar / Entegrasyon)")}
                      >
                        {t("Sil")}
                      </button>
                    )}
                  </div>
                )}

                {confirming === tm.id && tm.tasks > 0 && (
                  <p className="team-warn">
                    {t("{n} görev bu takıma bağlı. Görevler", { n: tm.tasks })} <strong>{t("silinmez")}</strong>,{" "}
                    {t("takımsız kalır; metrik ve öneri kayıtları temizlenir.")}
                  </p>
                )}
                {!tm.deletable && confirming !== tm.id && (
                  <p className="team-hint">
                    {t("Silinemez:")} {tm.members > 0 && t("{n} üye", { n: tm.members })}
                    {tm.members > 0 && tm.repos > 0 && t(" ve ")}
                    {tm.repos > 0 && t("{n} repo", { n: tm.repos })} {t("bağlı.")}
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
