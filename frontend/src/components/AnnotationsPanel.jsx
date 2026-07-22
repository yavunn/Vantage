import { useEffect, useState } from "react";
import { api, apiDelete, apiPost } from "../api.js";

// Trend anotasyonları yönetimi (admin). Tatil/incident/sürüm işaretleri
// grafiklerde bağlam gösterir; metrik verisini DEĞİŞTİRMEZ.
const KINDS = [
  { v: "holiday", t: "Tatil" },
  { v: "incident", t: "Incident" },
  { v: "release", t: "Sürüm" },
  { v: "other", t: "Diğer" },
];

// Yerel bugün (YYYY-MM-DD) — TZ kaymadan.
function todayIso() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default function AnnotationsPanel({ teams }) {
  const [list, setList] = useState([]);
  const [teamId, setTeamId] = useState(teams?.[0]?.id ?? null);
  const [form, setForm] = useState({ date: todayIso(), label: "", kind: "holiday", scope: "team" });
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);

  function load() {
    if (teamId == null) return;
    api(`/api/annotations?team_id=${teamId}`).then(setList).catch(setError);
  }
  useEffect(load, [teamId]);

  function upd(k, v) { setForm((f) => ({ ...f, [k]: v })); }

  async function submit(e) {
    e.preventDefault();
    setError(null); setMsg(null);
    try {
      await apiPost("/api/annotations", {
        date: form.date,
        label: form.label,
        kind: form.kind,
        team_id: form.scope === "global" ? null : teamId,
      });
      setForm({ date: todayIso(), label: "", kind: "holiday", scope: form.scope });
      setMsg("Anotasyon eklendi.");
      load();
    } catch (err) { setError(err); }
  }

  async function remove(id) {
    if (!window.confirm("Anotasyon silinsin mi?")) return;
    try { await apiDelete(`/api/annotations/${id}`); load(); }
    catch (err) { setError(err); }
  }

  return (
    <div>
      <section className="section">
        <div className="section-head">
          <h2>Trend anotasyonları</h2>
          <select value={teamId ?? ""} onChange={(e) => setTeamId(Number(e.target.value))} aria-label="Takım">
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        <p className="desc">
          Tatil, incident ya da sürüm gibi olayları grafiklere işaretle — bir
          tepe/çukur yanlış okunmasın. "Tüm takımlar" seçilirse global olur
          (ör. resmi tatil). Metrik verisi değişmez.
        </p>
        {error && <p className="error-inline">{error.message}</p>}
        {msg && <p className="ok-inline">{msg}</p>}
        <form className="inline-form" onSubmit={submit}>
          <input type="date" value={form.date} onChange={(e) => upd("date", e.target.value)} required />
          <input value={form.label} onChange={(e) => upd("label", e.target.value)} placeholder="Etiket (ör. Ramazan Bayramı)" required />
          <select value={form.kind} onChange={(e) => upd("kind", e.target.value)}>
            {KINDS.map((k) => <option key={k.v} value={k.v}>{k.t}</option>)}
          </select>
          <select value={form.scope} onChange={(e) => upd("scope", e.target.value)}>
            <option value="team">Bu takım</option>
            <option value="global">Tüm takımlar</option>
          </select>
          <button type="submit" className="mini">Ekle</button>
        </form>
      </section>

      <section className="section">
        <h2>Mevcut anotasyonlar</h2>
        {list.length === 0 ? (
          <p className="desc">Henüz anotasyon yok.</p>
        ) : (
          <table className="admin-table">
            <thead>
              <tr><th>Tarih</th><th>Etiket</th><th>Tür</th><th>Kapsam</th><th></th></tr>
            </thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id}>
                  <td>{a.date}</td>
                  <td>{a.label}</td>
                  <td>{KINDS.find((k) => k.v === a.kind)?.t || a.kind}</td>
                  <td>{a.team_id == null ? "Tüm takımlar" : "Bu takım"}</td>
                  <td><button className="mini danger" onClick={() => remove(a.id)}>Sil</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
