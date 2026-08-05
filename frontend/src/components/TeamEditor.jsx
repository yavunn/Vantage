import { useState } from "react";
import { addMembership, removeMembership } from "../api.js";
import Modal from "./Modal.jsx";
import { useT } from "../i18n.jsx";

// Bir çalışanın takım üyeliklerini yönetir: ekle (rol seçerek), çıkar.
export default function TeamEditor({ user, teams, onClose, onChanged }) {
  const t = useT();
  const [current, setCurrent] = useState(user.teams || []);
  const [teamId, setTeamId] = useState("");
  const [role, setRole] = useState("member");
  const [error, setError] = useState(null);

  const memberTeamIds = new Set(current.map((tm) => tm.team_id));
  const available = teams.filter((tm) => !memberTeamIds.has(tm.id));

  async function add() {
    if (!teamId) return;
    setError(null);
    try {
      const updated = await addMembership(user.id, Number(teamId), role);
      setCurrent(updated.teams);
      setTeamId("");
      setRole("member");
      onChanged && onChanged(updated);
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(tid) {
    setError(null);
    try {
      const updated = await removeMembership(user.id, tid);
      setCurrent(updated.teams);
      onChanged && onChanged(updated);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Modal title={t("Takımlar — {name}", { name: user.display_name })} onClose={onClose}>
      {user.developer_id == null ? (
        <p className="desc">{t("Bu hesap bir geliştiriciye bağlı değil; takım atanamaz.")}</p>
      ) : (
        <>
          {current.length === 0 ? (
            <p className="desc">{t("Henüz takım yok.")}</p>
          ) : (
            <ul className="team-list">
              {current.map((tm) => (
                <li key={tm.team_id}>
                  <span>
                    {tm.team_name}
                    <span className="role-tag">{tm.role === "manager" ? t("yönetici") : t("üye")}</span>
                  </span>
                  <button className="mini danger" onClick={() => remove(tm.team_id)}>{t("Çıkar")}</button>
                </li>
              ))}
            </ul>
          )}

          {available.length > 0 && (
            <div className="team-add">
              <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                <option value="">{t("Takım seç…")}</option>
                {available.map((tm) => (
                  <option key={tm.id} value={tm.id}>{tm.name}</option>
                ))}
              </select>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="member">{t("Üye")}</option>
                <option value="manager">{t("Yönetici")}</option>
              </select>
              <button className="mini" onClick={add} disabled={!teamId}>{t("Ekle")}</button>
            </div>
          )}
          {error && <div className="login-error">{error}</div>}
        </>
      )}
      <div className="modal-actions">
        <button className="login-btn" onClick={onClose}>{t("Kapat")}</button>
      </div>
    </Modal>
  );
}
