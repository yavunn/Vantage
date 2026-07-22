import { useEffect, useMemo, useState } from "react";
import {
  createLeave, decideLeave, deleteLeave, leaveSummary,
  listEmployees, listLeaves, pendingLeaves,
} from "../api.js";

const TYPE_LABEL = { annual: "Yıllık", sick: "Rapor", other: "Diğer" };
const STATUS_LABEL = { pending: "Onay bekliyor", approved: "Onaylı", rejected: "Reddedildi" };
const WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

// Yerel tarih formatı (UTC'ye çevirmeden — TZ kayması olmasın).
function pad(n) { return String(n).padStart(2, "0"); }
function ymd(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function monthKey(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`; }

// Aylık takvim ızgarası (Pazartesi başlangıç, CSS grid — kütüphane yok).
function buildGrid(year, month) {
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7; // Pzt=0
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < startOffset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

export default function LeavesPanel({ user, canManage }) {
  const [cursor, setCursor] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1); });
  const [leaves, setLeaves] = useState([]);
  const [summary, setSummary] = useState([]);
  const [pending, setPending] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [form, setForm] = useState({ start_date: ymd(new Date()), end_date: ymd(new Date()), leave_type: "annual", description: "", target_user_id: "" });
  const [personFilter, setPersonFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [onlyMine, setOnlyMine] = useState(false);

  const month = monthKey(cursor);
  const year = cursor.getFullYear();
  const mon = cursor.getMonth();

  function load() {
    listLeaves(month).then(setLeaves).catch((e) => setError(e.message));
    if (canManage) {
      leaveSummary(month).then(setSummary).catch(() => setSummary([]));
      pendingLeaves().then(setPending).catch(() => setPending([]));
    }
  }
  useEffect(load, [month]);
  useEffect(() => { if (canManage) listEmployees().then(setEmployees).catch(() => {}); }, []);

  async function decide(lv, decision) {
    setError(null); setMsg(null);
    try {
      await decideLeave(lv.id, decision);
      setMsg(`${lv.person} izni ${decision === "approved" ? "onaylandı" : "reddedildi"}.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const grid = useMemo(() => buildGrid(year, mon), [year, mon]);

  function leavesOnDay(d) {
    const s = ymd(d);
    return leaves.filter((lv) => lv.start_date <= s && lv.end_date >= s);
  }

  function upd(k, v) { setForm((f) => ({ ...f, [k]: v })); }

  async function add(e) {
    e.preventDefault();
    setError(null); setMsg(null);
    try {
      const payload = {
        start_date: form.start_date, end_date: form.end_date,
        leave_type: form.leave_type, description: form.description || null,
      };
      if (canManage && form.target_user_id) payload.target_user_id = Number(form.target_user_id);
      const res = await createLeave(payload);
      setMsg(res.status === "pending"
        ? "İzin isteği alındı — İK onayı bekliyor."
        : "İzin eklendi (onaylı).");
      setForm({ start_date: ymd(new Date()), end_date: ymd(new Date()), leave_type: "annual", description: "", target_user_id: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(lv) {
    if (!window.confirm(`${lv.person} · ${lv.start_date} izni silinsin mi?`)) return;
    try { await deleteLeave(lv.id); load(); } catch (err) { setError(err.message); }
  }

  const monthName = cursor.toLocaleDateString("tr-TR", { month: "long", year: "numeric" });

  // Listede tekilleştir: aynı izin birden çok güne yayıldığında bir kez göster.
  const uniqueLeaves = useMemo(() => {
    const seen = new Map();
    for (const lv of leaves) if (!seen.has(lv.id)) seen.set(lv.id, lv);
    return [...seen.values()].sort((a, b) => a.start_date.localeCompare(b.start_date));
  }, [leaves]);

  // Kişi + tür filtresi: İK uzun listede aradığını hızlı bulsun.
  const people = useMemo(
    () => [...new Set(uniqueLeaves.map((lv) => lv.person))].sort((a, b) => a.localeCompare(b, "tr")),
    [uniqueLeaves]
  );
  const visibleLeaves = useMemo(
    () => uniqueLeaves.filter(
      (lv) => (!personFilter || lv.person === personFilter)
        && (!typeFilter || lv.leave_type === typeFilter)
        && (!onlyMine || lv.can_delete)
    ),
    [uniqueLeaves, personFilter, typeFilter, onlyMine]
  );

  return (
    <div className="leaves-panel">
      <section className="section">
        <div className="section-head">
          <h2>İzin takvimi</h2>
          <div className="cal-nav">
            <button className="mini" onClick={() => setCursor(new Date(year, mon - 1, 1))}>‹</button>
            <span className="cal-month">{monthName}</span>
            <button className="mini" onClick={() => setCursor(new Date(year, mon + 1, 1))}>›</button>
          </div>
        </div>

        <div className="legend">
          <span className="lg annual">Yıllık</span>
          <span className="lg sick">Rapor</span>
          <span className="lg other">Diğer</span>
        </div>

        <div className="calendar">
          {WEEKDAYS.map((w) => <div key={w} className="cal-head">{w}</div>)}
          {grid.map((d, i) => (
            <div key={i} className={`cal-cell ${d ? "" : "empty"}`}>
              {d && (
                <>
                  <div className="cal-day">{d.getDate()}</div>
                  <div className="cal-leaves">
                    {leavesOnDay(d).map((lv) => (
                      <button
                        key={lv.id + "-" + ymd(d)}
                        className={`leave-chip ${lv.leave_type}`}
                        title={`${lv.person} · ${TYPE_LABEL[lv.leave_type] || lv.leave_type}${lv.description ? " · " + lv.description : ""}${lv.can_delete ? " (silmek için tıkla)" : ""}`}
                        onClick={() => lv.can_delete && remove(lv)}
                      >
                        {lv.person}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
        {error && <div className="login-error">{error}</div>}
        {msg && <div className="admin-ok">{msg}</div>}
      </section>

      {/* Onay kuyruğu: çalışanların bekleyen izin istekleri. */}
      {canManage && (
        <section className="section">
          <h2>Bekleyen izin onayları ({pending.length})</h2>
          {pending.length === 0 ? (
            <p className="desc">Onay bekleyen izin isteği yok.</p>
          ) : (
            <ul className="leave-list">
              {pending.map((lv) => (
                <li key={lv.id} className="leave-list-item">
                  <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                  <div className="leave-list-main">
                    <div className="leave-list-top">
                      <strong>{lv.person}</strong>
                      <span className="leave-badge">{TYPE_LABEL[lv.leave_type] || lv.leave_type}</span>
                      <span className="leave-status pending">{STATUS_LABEL.pending}</span>
                    </div>
                    <div className="leave-list-dates">
                      {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                      {lv.description ? ` · ${lv.description}` : ""}
                    </div>
                  </div>
                  <span className="leave-decide">
                    <button className="mini" onClick={() => decide(lv, "approved")}>Onayla</button>
                    <button className="mini danger" onClick={() => decide(lv, "rejected")}>Reddet</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* İK için en değerli tablo: takvimin hemen ardında, dipte değil. */}
      {canManage && (
        <section className="section">
          <h2>Ay özeti (İK)</h2>
          {summary.length === 0 ? (
            <p className="desc">Bu ay izin kaydı yok.</p>
          ) : (
            <table className="quality">
              <thead>
                <tr>
                  <th>Kişi</th><th className="num">Yıllık</th><th className="num">Rapor</th>
                  <th className="num">Diğer</th><th className="num">Toplam</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((r) => (
                  <tr key={r.person}>
                    <td>{r.person}</td>
                    <td className="num">{r.annual ?? 0}</td>
                    <td className="num">{r.sick ?? 0}</td>
                    <td className="num">{r.other ?? 0}</td>
                    <td className="num"><strong>{r.days}</strong></td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="sum-row">
                  <td>Toplam ({summary.length} kişi)</td>
                  <td className="num">{summary.reduce((a, r) => a + (r.annual ?? 0), 0)}</td>
                  <td className="num">{summary.reduce((a, r) => a + (r.sick ?? 0), 0)}</td>
                  <td className="num">{summary.reduce((a, r) => a + (r.other ?? 0), 0)}</td>
                  <td className="num"><strong>{summary.reduce((a, r) => a + r.days, 0)}</strong></td>
                </tr>
              </tfoot>
            </table>
          )}
        </section>
      )}

      <section className="section">
        <div className="section-head">
          <h2>Bu ayki izinler ({visibleLeaves.length}{visibleLeaves.length !== uniqueLeaves.length ? ` / ${uniqueLeaves.length}` : ""})</h2>
        </div>
        {uniqueLeaves.length > 0 && (
          <div className="leave-filters">
            <select value={personFilter} onChange={(e) => setPersonFilter(e.target.value)} aria-label="Kişiye göre filtrele">
              <option value="">Tüm kişiler</option>
              {people.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Türe göre filtrele">
              <option value="">Tüm türler</option>
              <option value="annual">Yıllık</option>
              <option value="sick">Rapor</option>
              <option value="other">Diğer</option>
            </select>
            <button
              className={`mini${onlyMine ? " active" : " ghost"}`}
              onClick={() => setOnlyMine((v) => !v)}
              title="Yalnızca silebildiğin (kendi/yetkili olduğun) kayıtlar"
            >
              Sadece benimkiler
            </button>
            {(personFilter || typeFilter || onlyMine) && (
              <button className="mini ghost" onClick={() => { setPersonFilter(""); setTypeFilter(""); setOnlyMine(false); }}>
                Filtreyi temizle
              </button>
            )}
          </div>
        )}
        {visibleLeaves.length === 0 ? (
          <p className="desc">{uniqueLeaves.length === 0 ? "Bu ay izin kaydı yok." : "Filtreye uyan kayıt yok."}</p>
        ) : (
          <ul className="leave-list">
            {visibleLeaves.map((lv) => (
              <li key={lv.id} className="leave-list-item">
                <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                <div className="leave-list-main">
                  <div className="leave-list-top">
                    <strong>{lv.person}</strong>
                    <span className="leave-badge">{TYPE_LABEL[lv.leave_type] || lv.leave_type}</span>
                    {lv.status && lv.status !== "approved" && (
                      <span className={`leave-status ${lv.status}`}>{STATUS_LABEL[lv.status] || lv.status}</span>
                    )}
                  </div>
                  <div className="leave-list-dates">
                    {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                    {lv.description ? ` · ${lv.description}` : ""}
                  </div>
                </div>
                {lv.can_delete && (
                  <button className="mini danger leave-del" title="İzni sil" onClick={() => remove(lv)}>
                    Sil
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section">
        <h2>İzin ekle</h2>
        <form className="admin-form" onSubmit={add}>
          {canManage && (
            <label>Kişi
              <select value={form.target_user_id} onChange={(e) => upd("target_user_id", e.target.value)}>
                <option value="">Kendim ({user.display_name})</option>
                {employees.filter((u) => u.developer_id != null).map((u) => (
                  <option key={u.id} value={u.id}>{u.display_name}</option>
                ))}
              </select>
            </label>
          )}
          <label>Başlangıç
            <input type="date" value={form.start_date} onChange={(e) => upd("start_date", e.target.value)} required />
          </label>
          <label>Bitiş
            <input type="date" value={form.end_date} onChange={(e) => upd("end_date", e.target.value)} required />
          </label>
          <label>Tür
            <select value={form.leave_type} onChange={(e) => upd("leave_type", e.target.value)}>
              <option value="annual">Yıllık izin</option>
              <option value="sick">Rapor (hastalık)</option>
              <option value="other">Diğer</option>
            </select>
          </label>
          <label>Açıklama (opsiyonel)
            <input value={form.description} onChange={(e) => upd("description", e.target.value)} />
          </label>
          <button type="submit" className="login-btn">İzin ekle</button>
        </form>
      </section>

    </div>
  );
}
