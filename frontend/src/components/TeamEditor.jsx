import { useState } from "react";
import { addMembership, removeMembership } from "../api.js";
import Modal from "./Modal.jsx";

// Bir çalışanın takım üyeliklerini yönetir: ekle (rol seçerek), çıkar.
export default function TeamEditor({ user, teams, onClose, onChanged }) {
  const [current, setCurrent] = useState(user.teams || []);
  const [teamId, setTeamId] = useState("");
  const [role, setRole] = useState("member");
  const [error, setError] = useState(null);

  const memberTeamIds = new Set(current.map((t) => t.team_id));
  const available = teams.filter((t) => !memberTeamIds.has(t.id));

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
    <Modal title={`Takımlar — ${user.display_name}`} onClose={onClose}>
      {user.developer_id == null ? (
        <p className="desc">Bu hesap bir geliştiriciye bağlı değil; takım atanamaz.</p>
      ) : (
        <>
          {current.length === 0 ? (
            <p className="desc">Henüz takım yok.</p>
          ) : (
            <ul className="team-list">
              {current.map((t) => (
                <li key={t.team_id}>
                  <span>
                    {t.team_name}
                    <span className="role-tag">{t.role === "manager" ? "yönetici" : "üye"}</span>
                  </span>
                  <button className="mini danger" onClick={() => remove(t.team_id)}>Çıkar</button>
                </li>
              ))}
            </ul>
          )}

          {available.length > 0 && (
            <div className="team-add">
              <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                <option value="">Takım seç…</option>
                {available.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="member">Üye</option>
                <option value="manager">Yönetici</option>
              </select>
              <button className="mini" onClick={add} disabled={!teamId}>Ekle</button>
            </div>
          )}
          {error && <div className="login-error">{error}</div>}
        </>
      )}
      <div className="modal-actions">
        <button className="login-btn" onClick={onClose}>Kapat</button>
      </div>
    </Modal>
  );
}
