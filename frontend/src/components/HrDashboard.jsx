import { useEffect, useMemo, useState } from "react";
import { monthKey, pad, ymd } from "../dates.js";
import {
  decideLeave, leaveBalances, leaveSummary, listEmployees, listLeaves, pendingLeaves,
} from "../api.js";

// İK Panosu — kapasite + izin + rehber. Performans/metrik YOK (etik sınır).
const TYPE_LABEL = { annual: "Yıllık", sick: "Rapor", other: "Diğer" };


export default function HrDashboard() {
  const today = new Date();
  const [cursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [employees, setEmployees] = useState([]);
  const [leaves, setLeaves] = useState([]);
  const [summary, setSummary] = useState([]);
  const [pending, setPending] = useState([]);
  const [balances, setBalances] = useState([]);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);

  const month = monthKey(cursor);
  const year = cursor.getFullYear();
  const mon = cursor.getMonth();

  function load() {
    listEmployees().then(setEmployees).catch((e) => setError(e.message));
    listLeaves(month).then(setLeaves).catch(() => setLeaves([]));
    leaveSummary(month).then(setSummary).catch(() => setSummary([]));
    pendingLeaves().then(setPending).catch(() => setPending([]));
    leaveBalances(year).then((b) => setBalances(b.balances || [])).catch(() => setBalances([]));
  }
  useEffect(load, [month, year]);

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

  // Bugün izinli olanlar (onaylı, tarih bugünü kapsıyor).
  const todayStr = ymd(today);
  const uniqueLeaves = useMemo(() => {
    const seen = new Map();
    for (const lv of leaves) if (!seen.has(lv.id)) seen.set(lv.id, lv);
    return [...seen.values()];
  }, [leaves]);

  const offToday = useMemo(
    () => uniqueLeaves.filter((lv) => lv.start_date <= todayStr && lv.end_date >= todayStr
      && (lv.status || "approved") === "approved"),
    [uniqueLeaves, todayStr]
  );

  // Yaklaşan izinler (bugünden sonra başlayan, tarihe göre sıralı, ilk 8).
  const upcoming = useMemo(
    () => uniqueLeaves
      .filter((lv) => lv.start_date > todayStr && (lv.status || "approved") === "approved")
      .sort((a, b) => a.start_date.localeCompare(b.start_date))
      .slice(0, 8),
    [uniqueLeaves, todayStr]
  );

  // Tür kırılımı (ay).
  const typeBreak = useMemo(() => {
    const t = { annual: 0, sick: 0, other: 0 };
    summary.forEach((r) => { t.annual += r.annual ?? 0; t.sick += r.sick ?? 0; t.other += r.other ?? 0; });
    return t;
  }, [summary]);

  // Kapasite ısı haritası: ayın her günü kaç kişi izinli (onaylı).
  const daysInMonth = new Date(year, mon + 1, 0).getDate();
  const heat = useMemo(() => {
    const counts = new Array(daysInMonth).fill(0);
    for (const lv of uniqueLeaves) {
      if ((lv.status || "approved") !== "approved") continue;
      for (let d = 1; d <= daysInMonth; d++) {
        const s = `${year}-${pad(mon + 1)}-${pad(d)}`;
        if (lv.start_date <= s && lv.end_date >= s) counts[d - 1] += 1;
      }
    }
    return counts;
  }, [uniqueLeaves, daysInMonth, year, mon]);
  const heatMax = Math.max(1, ...heat);

  // Headcount + profil eksikliği (ünvan veya telefon boş olan aktif hesaplar).
  const activeCount = employees.filter((u) => u.is_active).length;
  const incompleteProfiles = employees.filter((u) => u.is_active && (!u.title || !u.phone));

  // Kapasite çakışması: aynı gün ≥2 kişi izinli (kapasite riski — şirket geneli).
  const CONFLICT_MIN = 2;
  const conflictDays = useMemo(
    () => heat.map((c, i) => ({ day: i + 1, count: c }))
      .filter((d) => d.count >= CONFLICT_MIN),
    [heat]
  );

  // Bu ay iş yıldönümü olanlar (hire_date'in ay/gün'ü bu aya düşen aktif hesaplar).
  const anniversaries = useMemo(() => {
    const out = [];
    for (const u of employees) {
      if (!u.is_active || !u.hire_date) continue;
      const [hy, hm, hd] = u.hire_date.split("-").map(Number);
      if (hm - 1 !== mon) continue;
      const years = year - hy;
      if (years <= 0) continue;
      out.push({ name: u.display_name, day: hd, years });
    }
    return out.sort((a, b) => a.day - b.day);
  }, [employees, mon, year]);

  // Bakiyesi biten/azalan kişiler (uyarı).
  const lowBalance = useMemo(
    () => balances.filter((b) => b.remaining <= 0),
    [balances]
  );

  function exportCsv() {
    const rows = [["Kişi", "Yıllık", "Rapor", "Diğer", "Toplam"]];
    summary.forEach((r) => rows.push([r.person, r.annual ?? 0, r.sick ?? 0, r.other ?? 0, r.days]));
    const csv = rows.map((r) => r.map((c) => `"${String(c).replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ik-izin-ozeti-${month}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const monthName = cursor.toLocaleDateString("tr-TR", { month: "long", year: "numeric" });

  return (
    <div className="hr-dashboard">
      <div className="hr-toolbar">
        <h2>İK Panosu · {monthName}</h2>
        <span style={{ flex: 1 }} />
        <button className="mini" onClick={exportCsv}>İK raporu (CSV)</button>
        <button className="mini" onClick={() => window.print()}>Yazdır / PDF</button>
      </div>
      {error && <div className="login-error">{error}</div>}
      {msg && <div className="admin-ok">{msg}</div>}

      {/* KPI kartları */}
      <div className="hr-kpis">
        <div className="hr-kpi">
          <div className="hr-kpi-val">{offToday.length}</div>
          <div className="hr-kpi-label">Bugün izinli</div>
        </div>
        <div className="hr-kpi">
          <div className="hr-kpi-val">{activeCount}</div>
          <div className="hr-kpi-label">Aktif çalışan (headcount)</div>
        </div>
        <div className="hr-kpi">
          <div className="hr-kpi-val">{pending.length}</div>
          <div className="hr-kpi-label">Bekleyen onay</div>
        </div>
        <div className="hr-kpi">
          <div className="hr-kpi-val">{incompleteProfiles.length}</div>
          <div className="hr-kpi-label">Eksik profil</div>
        </div>
      </div>

      <div className="hr-grid">
        {/* Bugün izinli kimler */}
        <section className="section">
          <h3>Bugün izinli</h3>
          {offToday.length === 0 ? (
            <p className="desc">Bugün izinli kimse yok — tam kapasite.</p>
          ) : (
            <ul className="hr-list">
              {offToday.map((lv) => (
                <li key={lv.id}>
                  <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                  <strong>{lv.person}</strong>
                  <span className="leave-badge">{TYPE_LABEL[lv.leave_type] || lv.leave_type}</span>
                  <span className="hr-muted">→ {lv.end_date}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* İzin türü kırılımı */}
        <section className="section">
          <h3>Ay içi izin türü kırılımı (gün)</h3>
          <div className="hr-typebar">
            {["annual", "sick", "other"].map((k) => (
              <div key={k} className="hr-type-row">
                <span className={`leave-dot ${k}`} aria-hidden="true" />
                <span className="hr-type-name">{TYPE_LABEL[k]}</span>
                <span className="hr-type-val">{typeBreak[k]}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Yaklaşan izinler */}
        <section className="section">
          <h3>Yaklaşan izinler</h3>
          {upcoming.length === 0 ? (
            <p className="desc">Bu ay için planlanmış yaklaşan izin yok.</p>
          ) : (
            <ul className="hr-list">
              {upcoming.map((lv) => (
                <li key={lv.id}>
                  <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                  <strong>{lv.person}</strong>
                  <span className="hr-muted">
                    {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Eksik profiller */}
        <section className="section">
          <h3>Profil eksikliği</h3>
          {incompleteProfiles.length === 0 ? (
            <p className="desc">Tüm aktif profiller tam (ünvan + telefon).</p>
          ) : (
            <ul className="hr-list">
              {incompleteProfiles.map((u) => (
                <li key={u.id}>
                  <strong>{u.display_name}</strong>
                  <span className="hr-muted">
                    {!u.title && "ünvan yok"}{!u.title && !u.phone && " · "}{!u.phone && "telefon yok"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* İş yıldönümleri */}
        <section className="section">
          <h3>Bu ay iş yıldönümleri</h3>
          {anniversaries.length === 0 ? (
            <p className="desc">Bu ay yıldönümü olan yok.</p>
          ) : (
            <ul className="hr-list">
              {anniversaries.map((a, i) => (
                <li key={i}>
                  <span aria-hidden="true">🎉</span>
                  <strong>{a.name}</strong>
                  <span className="hr-muted">{a.day}. gün · {a.years}. yıl</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Kapasite ısı haritası */}
      <section className="section">
        <h3>Kapasite ısı haritası ({monthName})</h3>
        <p className="desc">Her sütun ayın bir günü; koyuluk o gün izinli kişi sayısıdır.</p>
        {conflictDays.length > 0 && (
          <div className="hr-warn">
            ⚠ Kapasite riski: {conflictDays.map((d) => `${d.day}. (${d.count} kişi)`).join(", ")} —
            aynı gün {CONFLICT_MIN}+ kişi izinli.
          </div>
        )}
        <div className="hr-heat">
          {heat.map((c, i) => (
            <div
              key={i}
              className="hr-heat-cell"
              title={`${i + 1}. gün · ${c} kişi izinli`}
              style={{ opacity: c === 0 ? 0.12 : 0.25 + 0.75 * (c / heatMax) }}
            >
              <span className="hr-heat-day">{i + 1}</span>
              {c > 0 && <span className="hr-heat-count">{c}</span>}
            </div>
          ))}
        </div>
      </section>

      {/* Yıllık izin bakiyesi */}
      <section className="section">
        <h3>Yıllık izin bakiyesi ({year})</h3>
        {lowBalance.length > 0 && (
          <div className="hr-warn">
            ⚠ {lowBalance.length} kişinin yıllık izin hakkı bitti (kalan ≤ 0).
          </div>
        )}
        {balances.length === 0 ? (
          <p className="desc">Kayıt yok.</p>
        ) : (
          <table className="quality">
            <thead>
              <tr>
                <th>Kişi</th><th className="num">Hak</th><th className="num">Kullanılan</th>
                <th className="num">Beklemede</th><th className="num">Kalan</th>
              </tr>
            </thead>
            <tbody>
              {balances.map((b) => (
                <tr key={b.user_id} className={b.remaining <= 0 ? "row-warn" : ""}>
                  <td>{b.person}</td>
                  <td className="num">{b.allowance}</td>
                  <td className="num">{b.used}</td>
                  <td className="num">{b.pending > 0 ? b.pending : "—"}</td>
                  <td className="num"><strong>{b.remaining}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Bekleyen onay kuyruğu */}
      <section className="section">
        <h3>Bekleyen izin onayları ({pending.length})</h3>
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
    </div>
  );
}
