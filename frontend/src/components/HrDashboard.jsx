import { useEffect, useMemo, useState } from "react";
import { monthKey, pad, ymd } from "../dates.js";
import {
  decideLeave, leaveBalances, leaveSummary, listEmployees, listLeaves, pendingLeaves,
} from "../api.js";
import Yukleniyor from "./Yukleniyor.jsx";
import { useLang, useT } from "../i18n.jsx";

// İK Panosu — kapasite + izin + rehber. Performans/metrik YOK (etik sınır).

// Profil eksikliği listesinde varsayılan olarak gösterilen kişi sayısı.
const PROFILE_PREVIEW = 3;

const TYPE_LABEL = { annual: "Yıllık", sick: "Rapor", other: "Diğer" };


/** Isı haritası kademesi. Sürekli opaklık yerine dört adım: her adımın
 *  yazı rengi CSS'te ayrı seçilebilsin ve rakam her tonda okunsun. */
export function yogunlukSeviyesi(sayi, enYuksek) {
  if (!sayi) return "yok";
  const oran = enYuksek > 0 ? sayi / enYuksek : 0;
  if (oran < 0.34) return "az";
  if (oran < 0.67) return "orta";
  return "cok";
}

export default function HrDashboard() {
  const t = useT();
  const { lang } = useLang();
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

  // Bes istek birden: hepsi sonuclanana kadar pano "her sey sifir" gibi
  // goruntu veriyordu (bugun izinli 0, bekleyen onay 0...).
  const [yukleniyor, setYukleniyor] = useState(true);

  function load() {
    setYukleniyor(true);
    Promise.allSettled([
      listEmployees().then(setEmployees).catch((e) => setError(e.message)),
      listLeaves(month).then(setLeaves).catch(() => setLeaves([])),
      leaveSummary(month).then(setSummary).catch(() => setSummary([])),
      pendingLeaves().then(setPending).catch(() => setPending([])),
      leaveBalances(year).then((b) => setBalances(b.balances || [])).catch(() => setBalances([])),
    ]).finally(() => setYukleniyor(false));
  }
  useEffect(load, [month, year]);

  async function decide(lv, decision) {
    setError(null); setMsg(null);
    try {
      await decideLeave(lv.id, decision);
      setMsg(t("{person} izni {result}.", { person: lv.person, result: decision === "approved" ? t("onaylandı") : t("reddedildi") }));
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
    const tb = { annual: 0, sick: 0, other: 0 };
    summary.forEach((r) => { tb.annual += r.annual ?? 0; tb.sick += r.sick ?? 0; tb.other += r.other ?? 0; });
    return tb;
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

  // İzin bakiyesi tablosunda satırların çoğu "hak 14 / kullanılan 0 / kalan 14"
  // olarak birebir aynı olabiliyor; kadro büyüdükçe tablo okunmaz hale geliyor.
  // Varsayılan görünüm yalnızca HAREKETLİ satırlar: izin kullanmış, onay
  // bekleyen ya da bakiyesi bitmiş kişiler. Kalanlar tek düğmeyle açılır —
  // veri gizlenmiyor, öne çıkan şey değişiyor.
  const [allBalances, setAllBalances] = useState(false);
  const [allProfiles, setAllProfiles] = useState(false);
  const activeBalances = useMemo(
    () => balances.filter((b) => b.used > 0 || b.pending > 0 || b.remaining <= 0),
    [balances]
  );
  const untouchedCount = balances.length - activeBalances.length;
  // Herkes hareketsizse tabloyu tamamen boşaltmak yerine hepsini göster.
  const shownBalances =
    allBalances || activeBalances.length === 0 ? balances : activeBalances;

  function exportCsv() {
    const rows = [[t("Kişi"), t("Yıllık"), t("Rapor"), t("Diğer"), t("Toplam")]];
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

  const monthName = cursor.toLocaleDateString(lang === "en" ? "en-US" : "tr-TR", { month: "long", year: "numeric" });

  // Bes istek sonuclanmadan pano "her sey sifir" gibi goruntu veriyordu.
  if (yukleniyor) {
    return (
      <div className="hr-dashboard">
        <div className="hr-toolbar"><h2>{monthName}</h2></div>
        <Yukleniyor bicim="kart" adet={4} />
        <Yukleniyor adet={4} />
      </div>
    );
  }

  return (
    <div className="hr-dashboard">
      <div className="hr-toolbar">
        <h2>{monthName}</h2>
        <span style={{ flex: 1 }} />
        <button className="mini" onClick={exportCsv}>{t("İK raporu (CSV)")}</button>
        <button className="mini" onClick={() => window.print()}>{t("Yazdır / PDF")}</button>
      </div>
      {error && <div className="error-inline" role="alert">{error}</div>}
      {msg && <div className="ok-inline" role="status">{msg}</div>}

      {/* KPI kartları */}
      <div className="hr-kpis">
        <div className="hr-kpi">
          <div className="hr-kpi-val">{offToday.length}</div>
          <div className="hr-kpi-label">{t("Bugün izinli")}</div>
        </div>
        <div className="hr-kpi">
          <div className="hr-kpi-val">{activeCount}</div>
          <div className="hr-kpi-label">{t("Aktif çalışan (headcount)")}</div>
        </div>
        <div className="hr-kpi">
          <div className="hr-kpi-val">{pending.length}</div>
          <div className="hr-kpi-label">{t("Bekleyen onay")}</div>
        </div>
        <div className="hr-kpi">
          <div className="hr-kpi-val">{incompleteProfiles.length}</div>
          <div className="hr-kpi-label">{t("Eksik profil")}</div>
        </div>
      </div>

      <div className="hr-grid">
        {/* Bugün izinli kimler */}
        <section className="section">
          <h3>{t("Bugün izinli")}</h3>
          {offToday.length === 0 ? (
            <p className="desc">{t("Bugün izinli kimse yok — tam kapasite.")}</p>
          ) : (
            <ul className="hr-list">
              {offToday.map((lv) => (
                <li key={lv.id}>
                  <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                  <strong>{lv.person}</strong>
                  <span className="leave-badge">{t(TYPE_LABEL[lv.leave_type]) || lv.leave_type}</span>
                  <span className="hr-muted">→ {lv.end_date}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* İzin türü kırılımı */}
        <section className="section">
          <h3>{t("Ay içi izin türü kırılımı (gün)")}</h3>
          <div className="hr-typebar">
            {["annual", "sick", "other"].map((k) => (
              <div key={k} className="hr-type-row">
                <span className={`leave-dot ${k}`} aria-hidden="true" />
                <span className="hr-type-name">{t(TYPE_LABEL[k])}</span>
                <span className="hr-type-val">{typeBreak[k]}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Yaklaşan izinler */}
        <section className="section">
          <h3>{t("Yaklaşan izinler")}</h3>
          {upcoming.length === 0 ? (
            <p className="desc">{t("Bu ay için planlanmış yaklaşan izin yok.")}</p>
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
          <h3>{t("Profil eksikliği")}</h3>
          {incompleteProfiles.length === 0 ? (
            <p className="desc">{t("Tüm aktif profiller tam (ünvan + telefon).")}</p>
          ) : (
            /* Liste satırlarının çoğu birebir aynı ("ünvan yok · telefon yok")
               ve kadro büyüdükçe okunmaz oluyor. Varsayılan görünüm ilk birkaç
               kişi; kalanı tek düğmeyle açılır — izin bakiyesi tablosuyla aynı
               kalıp. Veri gizlenmiyor, sayfa uzamıyor. */
            <>
              <ul className="hr-list">
                {(allProfiles ? incompleteProfiles : incompleteProfiles.slice(0, PROFILE_PREVIEW)).map((u) => (
                  <li key={u.id}>
                    <strong>{u.display_name}</strong>
                    <span className="hr-muted">
                      {!u.title && t("ünvan yok")}{!u.title && !u.phone && " · "}{!u.phone && t("telefon yok")}
                    </span>
                  </li>
                ))}
              </ul>
              {incompleteProfiles.length > PROFILE_PREVIEW && (
                <button className="mini ghost" onClick={() => setAllProfiles((v) => !v)}>
                  {allProfiles
                    ? t("Daha az göster")
                    : t("{n} kişi daha — tümünü göster", { n: incompleteProfiles.length - PROFILE_PREVIEW })}
                </button>
              )}
            </>
          )}
        </section>

        {/* İş yıldönümleri */}
        <section className="section">
          <h3>{t("Bu ay iş yıldönümleri")}</h3>
          {anniversaries.length === 0 ? (
            <p className="desc">{t("Bu ay yıldönümü olan yok.")}</p>
          ) : (
            <ul className="hr-list">
              {anniversaries.map((a, i) => (
                <li key={i}>
                  <span aria-hidden="true">🎉</span>
                  <strong>{a.name}</strong>
                  <span className="hr-muted">{t("{day}. gün · {years}. yıl", { day: a.day, years: a.years })}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Kapasite ısı haritası */}
      <section className="section">
        <h3>{t("Kapasite ısı haritası ({month})", { month: monthName })}</h3>
        <p className="desc">{t("Her sütun ayın bir günü; koyuluk o gün izinli kişi sayısıdır.")}</p>
        {conflictDays.length > 0 && (
          <div className="hr-warn">
            ⚠ {t("Kapasite riski: {list} — aynı gün {min}+ kişi izinli.", {
              list: conflictDays.map((d) => t("{day}. ({n} kişi)", { day: d.day, n: d.count })).join(", "),
              min: CONFLICT_MIN,
            })}
          </div>
        )}
        <div className="hr-heat-legend" aria-hidden="true">
          <span><i className="hhl-box hhl-yok" />{t("izin yok")}</span>
          <span><i className="hhl-box hhl-az" />{t("az")}</span>
          <span><i className="hhl-box hhl-orta" />{t("orta")}</span>
          <span><i className="hhl-box hhl-cok" />{t("çok")}</span>
        </div>
        <div className="hr-heat">
          {heat.map((c, i) => (
            <div
              key={i}
              // Yoğunluk ZEMİN tonuyla verilir. Önceden hücrenin opaklığı
              // düşürülüyordu; opaklık yazıyı da solduruyor ve az izinli
              // günlerde hücredeki rakam okunmuyordu. Ayrıca izinsiz gün
              // marka rengiyle boyanınca, ay boyunca hiç izin olmasa bile
              // ekran "dolu" görünüyordu.
              className="hr-heat-cell"
              data-yogunluk={yogunlukSeviyesi(c, heatMax)}
              title={t("{day}. gün · {n} kişi izinli", { day: i + 1, n: c })}
            >
              <span className="hr-heat-day">{i + 1}</span>
              {c > 0 && <span className="hr-heat-count">{c}</span>}
            </div>
          ))}
        </div>
      </section>

      {/* Yıllık izin bakiyesi */}
      <section className="section">
        <h3>{t("Yıllık izin bakiyesi ({year})", { year })}</h3>
        {lowBalance.length > 0 && (
          <div className="hr-warn">
            ⚠ {t("{n} kişinin yıllık izin hakkı bitti (kalan ≤ 0).", { n: lowBalance.length })}
          </div>
        )}
        {balances.length === 0 ? (
          <p className="desc">{t("Kayıt yok.")}</p>
        ) : (
          <>
            <table className="quality">
              <thead>
                <tr>
                  <th>{t("Kişi")}</th><th className="num">{t("Hak")}</th><th className="num">{t("Kullanılan")}</th>
                  <th className="num">{t("Beklemede")}</th><th className="num">{t("Kalan")}</th>
                </tr>
              </thead>
              <tbody>
                {shownBalances.map((b) => (
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
            {untouchedCount > 0 && activeBalances.length > 0 && (
              <button className="mini ghost" onClick={() => setAllBalances((v) => !v)}>
                {allBalances
                  ? t("Hareketsiz satırları gizle")
                  : t("{n} kişi hiç izin kullanmadı — tümünü göster", { n: untouchedCount })}
              </button>
            )}
          </>
        )}
      </section>

      {/* Bekleyen onay kuyruğu */}
      <section className="section">
        <h3>{t("Bekleyen izin onayları ({n})", { n: pending.length })}</h3>
        {pending.length === 0 ? (
          <p className="desc">{t("Onay bekleyen izin isteği yok.")}</p>
        ) : (
          <ul className="leave-list">
            {pending.map((lv) => (
              <li key={lv.id} className="leave-list-item">
                <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                <div className="leave-list-main">
                  <div className="leave-list-top">
                    <strong>{lv.person}</strong>
                    <span className="leave-badge">{t(TYPE_LABEL[lv.leave_type]) || lv.leave_type}</span>
                  </div>
                  <div className="leave-list-dates">
                    {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                    {lv.description ? ` · ${lv.description}` : ""}
                  </div>
                </div>
                <span className="leave-decide">
                  <button className="mini" onClick={() => decide(lv, "approved")}>{t("Onayla")}</button>
                  <button className="mini danger" onClick={() => decide(lv, "rejected")}>{t("Reddet")}</button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
