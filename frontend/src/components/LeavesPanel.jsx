import { useEffect, useMemo, useState } from "react";
import {
  createAnnotation, createLeave, decideLeave, deleteAnnotation, deleteLeave,
  leaveSummary, listAnnotations, listEmployees, listLeaves, myLeaveRequests,
  pendingLeaves,
} from "../api.js";
import Modal from "./Modal.jsx";
import { monthKey, ymd } from "../dates.js";
import { useLang, useT } from "../i18n.jsx";

const TYPE_LABEL = { annual: "Yıllık", sick: "Rapor", other: "Diğer" };
const ANNOT_LABEL = { holiday: "Tatil", incident: "Incident", release: "Sürüm", other: "Not" };
const ANNOT_ICON = { holiday: "🏖", incident: "⚠", release: "🚀", other: "📌" };
const ANNOT_KINDS = [
  { v: "holiday", t: "Tatil" },
  { v: "incident", t: "Incident" },
  { v: "release", t: "Sürüm" },
  { v: "other", t: "Diğer" },
];
const STATUS_LABEL = { pending: "Onay bekliyor", approved: "Onaylı", rejected: "Reddedildi" };
const WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];


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

export default function LeavesPanel({ user, canManage, teams = [] }) {
  const t = useT();
  const { lang } = useLang();
  const [cursor, setCursor] = useState(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1); });
  const [leaves, setLeaves] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [summary, setSummary] = useState([]);
  const [pending, setPending] = useState([]);
  const [mine, setMine] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  // Red akışı: gerekçe zorunlu. rejectFor = reddedilen izin, rejectNote = metin.
  const [rejectFor, setRejectFor] = useState(null);
  const [rejectNote, setRejectNote] = useState("");
  const [form, setForm] = useState({ start_date: ymd(new Date()), end_date: ymd(new Date()), leave_type: "annual", description: "", target_user_id: "" });
  const [personFilter, setPersonFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [onlyMine, setOnlyMine] = useState(false);
  // Takvim işaretleri (tatil/olay) — izinlerle aynı takvimde durduğu için
  // yönetimi de burada. Kapsam boş = global (tüm takımlar), ör. resmi tatil.
  const [annotForm, setAnnotForm] = useState({ date: ymd(new Date()), label: "", kind: "holiday", team_id: "" });

  const month = monthKey(cursor);
  const year = cursor.getFullYear();
  const mon = cursor.getMonth();

  function load() {
    listLeaves(month).then(setLeaves).catch((e) => setError(e.message));
    listAnnotations().then(setAnnotations).catch(() => setAnnotations([]));
    myLeaveRequests().then(setMine).catch(() => setMine([]));
    if (canManage) {
      leaveSummary(month).then(setSummary).catch(() => setSummary([]));
      pendingLeaves().then(setPending).catch(() => setPending([]));
    }
  }
  useEffect(load, [month]);
  // Çalışan listesi "Kişi" seçicisini doldurur. Sessizce boş kalırsa yönetici
  // başkasına izin ekleyemez ve sebebini göremez — hatayı görünür kıl.
  useEffect(() => {
    if (!canManage) return;
    listEmployees()
      .then(setEmployees)
      .catch((e) => setError(t("Çalışan listesi yüklenemedi: {msg}", { msg: e.message })));
  }, []);

  // Başka bir aya bakarken işaret eklenecekse tarih o aya düşsün — bugünün
  // tarihiyle yanlışlıkla görünmeyen bir güne işaret konmasın.
  useEffect(() => {
    setAnnotForm((f) => (f.date.startsWith(month) ? f : { ...f, date: `${month}-01` }));
  }, [month]);

  async function approve(lv) {
    setError(null); setMsg(null);
    try {
      await decideLeave(lv.id, "approved");
      setMsg(t("{person} izni onaylandı ve takvime işlendi.", { person: lv.person }));
      load();
    } catch (err) { setError(err.message); }
  }

  async function confirmReject() {
    if (!rejectNote.trim()) { setError(t("Red için gerekçe gerekli")); return; }
    setError(null); setMsg(null);
    try {
      await decideLeave(rejectFor.id, "rejected", rejectNote.trim());
      setMsg(t("{person} izni reddedildi. Gerekçe çalışana iletildi.", { person: rejectFor.person }));
      setRejectFor(null); setRejectNote("");
      load();
    } catch (err) { setError(err.message); }
  }

  const grid = useMemo(() => buildGrid(year, mon), [year, mon]);

  function leavesOnDay(d) {
    const s = ymd(d);
    return leaves.filter((lv) => lv.start_date <= s && lv.end_date >= s);
  }

  function annotsOnDay(d) {
    const s = ymd(d);
    return annotations.filter((a) => a.date === s);
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
      const toAll = canManage && form.target_user_id === "all";
      if (toAll && !window.confirm(
        t("{range} tarihinde TÜM aktif çalışanlara izin eklenecek. Onaylıyor musun?",
          { range: `${form.start_date}${form.end_date !== form.start_date ? ` → ${form.end_date}` : ""}` })
      )) return;
      if (toAll) payload.target_all = true;
      else if (canManage && form.target_user_id) payload.target_user_id = Number(form.target_user_id);
      const res = await createLeave(payload);
      setMsg(toAll
        ? t("Şirket tatili eklendi — {n} çalışana onaylı izin işlendi.", { n: res.count })
        : res.status === "pending"
          ? t("İzin isteğin gönderildi — yönetici onayı bekliyor. Onaylanınca takvime işlenecek.")
          : t("İzin eklendi (onaylı)."));
      setForm({ start_date: ymd(new Date()), end_date: ymd(new Date()), leave_type: "annual", description: "", target_user_id: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(lv) {
    if (!window.confirm(t("{person} · {date} izni silinsin mi?", { person: lv.person, date: lv.start_date }))) return;
    try { await deleteLeave(lv.id); load(); } catch (err) { setError(err.message); }
  }

  const updAnnot = (k, v) => setAnnotForm((f) => ({ ...f, [k]: v }));

  async function addAnnotation(e) {
    e.preventDefault();
    setError(null); setMsg(null);
    try {
      await createAnnotation({
        date: annotForm.date,
        label: annotForm.label.trim(),
        kind: annotForm.kind,
        team_id: annotForm.team_id === "" ? null : Number(annotForm.team_id),
      });
      setMsg(t("Takvim işareti eklendi."));
      setAnnotForm((f) => ({ ...f, date: ymd(new Date()), label: "" }));
      load();
    } catch (err) { setError(err.message); }
  }

  async function removeAnnotation(a) {
    if (!window.confirm(t('"{label}" işareti silinsin mi?', { label: a.label }))) return;
    setError(null); setMsg(null);
    try { await deleteAnnotation(a.id); load(); } catch (err) { setError(err.message); }
  }

  const monthName = cursor.toLocaleDateString(lang === "en" ? "en-US" : "tr-TR", { month: "long", year: "numeric" });

  // Listede tekilleştir: aynı izin birden çok güne yayıldığında bir kez göster.
  const uniqueLeaves = useMemo(() => {
    const seen = new Map();
    for (const lv of leaves) if (!seen.has(lv.id)) seen.set(lv.id, lv);
    return [...seen.values()].sort((a, b) => a.start_date.localeCompare(b.start_date));
  }, [leaves]);

  // Takvimde görünen ayın işaretleri — liste takvimle aynı bağlamı göstersin.
  const monthAnnots = useMemo(
    () => annotations.filter((a) => a.date.startsWith(month))
      .sort((a, b) => a.date.localeCompare(b.date)),
    [annotations, month]
  );
  const teamName = useMemo(
    () => Object.fromEntries(teams.map((tm) => [tm.id, tm.name])),
    [teams]
  );

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
          <h2>{t("İzin takvimi")}</h2>
          <div className="cal-nav">
            <button className="mini" onClick={() => setCursor(new Date(year, mon - 1, 1))}>‹</button>
            <span className="cal-month">{monthName}</span>
            <button className="mini" onClick={() => setCursor(new Date(year, mon + 1, 1))}>›</button>
          </div>
        </div>

        <div className="legend">
          <span className="lg annual">{t("Yıllık")}</span>
          <span className="lg sick">{t("Rapor")}</span>
          <span className="lg other">{t("Diğer")}</span>
        </div>

        <div className="calendar">
          {WEEKDAYS.map((w) => <div key={w} className="cal-head">{t(w)}</div>)}
          {grid.map((d, i) => (
            <div key={i} className={`cal-cell ${d ? "" : "empty"}`}>
              {d && (
                <>
                  <div className="cal-day">{d.getDate()}</div>
                  {annotsOnDay(d).map((a) => (
                    <div
                      key={"annot-" + a.id}
                      className={`annot-chip ${a.kind}`}
                      title={`${t(ANNOT_LABEL[a.kind]) || a.kind}: ${a.label}${a.team_id == null ? ` (${t("tüm takımlar")})` : ""}`}
                    >
                      <span aria-hidden="true">{ANNOT_ICON[a.kind] || "📌"}</span> {a.label}
                    </div>
                  ))}
                  <div className="cal-leaves">
                    {leavesOnDay(d).map((lv) => (
                      <button
                        key={lv.id + "-" + ymd(d)}
                        className={`leave-chip ${lv.leave_type} ${lv.status === "pending" ? "is-pending" : ""}`}
                        title={`${lv.person} · ${t(TYPE_LABEL[lv.leave_type]) || lv.leave_type}${lv.status === "pending" ? ` · ${t("beklemede")}` : ""}${lv.description ? " · " + lv.description : ""}${lv.can_delete ? ` (${t("silmek için tıkla")})` : ""}`}
                        onClick={() => lv.can_delete && remove(lv)}
                      >
                        {lv.status === "pending" ? "⏳ " : ""}{lv.person}
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

      {/* Takvim işaretleri: resmi tatil/incident/sürüm. Takvimde zaten burada
          görünüyorlar, yönetimleri de burada — ayrı bir sekmede değil. Aynı
          işaretler trend grafiklerinde de bağlam olarak çıkar; metrik verisini
          DEĞİŞTİRMEZLER. Yazma yetkisi admin + İK (backend de öyle zorlar). */}
      {canManage && (
        <section className="section">
          <h2>{t("Takvim işaretleri ({n})", { n: monthAnnots.length })}</h2>
          <p className="desc">
            {t("Resmi tatil, incident ya da sürüm gibi günleri işaretle. Takvimde ve trend grafiklerinde bağlam olarak görünür — bir tepe/çukur yanlış okunmasın diye. İzin hakkından düşmez, metrik verisini değiştirmez.")}
          </p>
          <form className="inline-form" onSubmit={addAnnotation}>
            <input type="date" value={annotForm.date}
                   onChange={(e) => updAnnot("date", e.target.value)} required />
            <input value={annotForm.label} onChange={(e) => updAnnot("label", e.target.value)}
                   placeholder={t("Etiket (ör. Ramazan Bayramı)")} required />
            <select value={annotForm.kind} onChange={(e) => updAnnot("kind", e.target.value)} aria-label={t("Tür")}>
              {ANNOT_KINDS.map((k) => <option key={k.v} value={k.v}>{t(k.t)}</option>)}
            </select>
            <select value={annotForm.team_id} onChange={(e) => updAnnot("team_id", e.target.value)} aria-label={t("Kapsam")}>
              <option value="">{t("Tüm takımlar")}</option>
              {teams.map((tm) => <option key={tm.id} value={tm.id}>{tm.name}</option>)}
            </select>
            <button type="submit" className="mini">{t("Ekle")}</button>
          </form>

          {monthAnnots.length === 0 ? (
            <p className="desc">{t("{month} ayında işaret yok.", { month: monthName })}</p>
          ) : (
            <ul className="leave-list">
              {monthAnnots.map((a) => (
                <li key={a.id} className="leave-list-item">
                  <span className="annot-icon" aria-hidden="true">{ANNOT_ICON[a.kind] || "📌"}</span>
                  <div className="leave-list-main">
                    <div className="leave-list-top">
                      <strong>{a.label}</strong>
                      <span className="leave-badge">{t(ANNOT_LABEL[a.kind]) || a.kind}</span>
                    </div>
                    <div className="leave-list-dates">
                      {a.date} · {a.team_id == null ? t("Tüm takımlar") : (teamName[a.team_id] || t("Takım"))}
                    </div>
                  </div>
                  <button className="mini danger leave-del" title={t("İşareti sil")}
                          onClick={() => removeAnnotation(a)}>
                    {t("Sil")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* İzin isteklerim: her çalışan kendi isteklerinin durumunu + red gerekçesini görür. */}
      <section className="section">
        <h2>{t("İzin isteklerim ({n})", { n: mine.length })}</h2>
        {mine.length === 0 ? (
          <p className="desc">{t("Henüz izin isteğin yok. Aşağıdan istek gönderebilirsin.")}</p>
        ) : (
          <ul className="leave-list">
            {mine.map((lv) => (
              <li key={lv.id} className="leave-list-item">
                <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                <div className="leave-list-main">
                  <div className="leave-list-top">
                    <span className="leave-badge">{t(TYPE_LABEL[lv.leave_type]) || lv.leave_type}</span>
                    <span className={`leave-status ${lv.status}`}>{t(STATUS_LABEL[lv.status]) || lv.status}</span>
                    {/* İzin-evrak senkronu: kanıt Evraklar sekmesinden zaten yüklendiyse
                        ikinci kez sorulmasın diye görünür kılınır. */}
                    {lv.has_document && (
                      <span className="leave-badge doc" title={t("Bu izne bağlı bir belge yüklendi")}>
                        📎 {t("belge var")}
                      </span>
                    )}
                  </div>
                  <div className="leave-list-dates">
                    {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                    {lv.description ? ` · ${lv.description}` : ""}
                  </div>
                  {lv.status === "rejected" && lv.decision_note && (
                    <div className="leave-reject-note">
                      <strong>{t("Red gerekçesi:")}</strong> {lv.decision_note}
                    </div>
                  )}
                </div>
                {lv.can_cancel && (
                  <button className="mini ghost leave-del" title={t("İsteği geri çek")}
                    onClick={() => remove({ id: lv.id, person: t("İsteğin"), start_date: lv.start_date })}>
                    {t("İptal")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Onay kuyruğu: çalışanların bekleyen izin istekleri. */}
      {canManage && (
        <section className="section">
          <h2>{t("Bekleyen izin onayları ({n})", { n: pending.length })}</h2>
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
                      <span className="leave-status pending">{t(STATUS_LABEL.pending)}</span>
                      {lv.has_document && (
                        <span className="leave-badge doc" title={t("Bu izne bağlı bir belge yüklendi — Evraklar sekmesinden de onaylanabilir")}>
                          📎 {t("belge var")}
                        </span>
                      )}
                    </div>
                    <div className="leave-list-dates">
                      {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                      {lv.description ? ` · ${lv.description}` : ""}
                    </div>
                  </div>
                  <span className="leave-decide">
                    <button className="mini" onClick={() => approve(lv)}>{t("Onayla")}</button>
                    <button className="mini danger" onClick={() => { setRejectFor(lv); setRejectNote(""); setError(null); }}>{t("Reddet")}</button>
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
          <h2>{t("Ay özeti (İK)")}</h2>
          {summary.length === 0 ? (
            <p className="desc">{t("Bu ay izin kaydı yok.")}</p>
          ) : (
            <table className="quality">
              <thead>
                <tr>
                  <th>{t("Kişi")}</th><th className="num">{t("Yıllık")}</th><th className="num">{t("Rapor")}</th>
                  <th className="num">{t("Diğer")}</th><th className="num">{t("Toplam")}</th>
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
                  <td>{t("Toplam ({n} kişi)", { n: summary.length })}</td>
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
          <h2>{t("Bu ayki izinler ({n}{total})", { n: visibleLeaves.length, total: visibleLeaves.length !== uniqueLeaves.length ? ` / ${uniqueLeaves.length}` : "" })}</h2>
        </div>
        {uniqueLeaves.length > 0 && (
          <div className="leave-filters">
            <select value={personFilter} onChange={(e) => setPersonFilter(e.target.value)} aria-label={t("Kişiye göre filtrele")}>
              <option value="">{t("Tüm kişiler")}</option>
              {people.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label={t("Türe göre filtrele")}>
              <option value="">{t("Tüm türler")}</option>
              <option value="annual">{t("Yıllık")}</option>
              <option value="sick">{t("Rapor")}</option>
              <option value="other">{t("Diğer")}</option>
            </select>
            <button
              className={`mini${onlyMine ? " active" : " ghost"}`}
              onClick={() => setOnlyMine((v) => !v)}
              title={t("Yalnızca silebildiğin (kendi/yetkili olduğun) kayıtlar")}
            >
              {t("Sadece benimkiler")}
            </button>
            {(personFilter || typeFilter || onlyMine) && (
              <button className="mini ghost" onClick={() => { setPersonFilter(""); setTypeFilter(""); setOnlyMine(false); }}>
                {t("Filtreyi temizle")}
              </button>
            )}
          </div>
        )}
        {visibleLeaves.length === 0 ? (
          <p className="desc">{uniqueLeaves.length === 0 ? t("Bu ay izin kaydı yok.") : t("Filtreye uyan kayıt yok.")}</p>
        ) : (
          <ul className="leave-list">
            {visibleLeaves.map((lv) => (
              <li key={lv.id} className="leave-list-item">
                <span className={`leave-dot ${lv.leave_type}`} aria-hidden="true" />
                <div className="leave-list-main">
                  <div className="leave-list-top">
                    <strong>{lv.person}</strong>
                    <span className="leave-badge">{t(TYPE_LABEL[lv.leave_type]) || lv.leave_type}</span>
                    {lv.status && lv.status !== "approved" && (
                      <span className={`leave-status ${lv.status}`}>{t(STATUS_LABEL[lv.status]) || lv.status}</span>
                    )}
                    {lv.has_document && (
                      <span className="leave-badge doc" title={t("Bu izne bağlı bir belge yüklendi")}>
                        📎 {t("belge var")}
                      </span>
                    )}
                  </div>
                  <div className="leave-list-dates">
                    {lv.start_date === lv.end_date ? lv.start_date : `${lv.start_date} → ${lv.end_date}`}
                    {lv.description ? ` · ${lv.description}` : ""}
                  </div>
                </div>
                {lv.can_delete && (
                  <button className="mini danger leave-del" title={t("İzni sil")} onClick={() => remove(lv)}>
                    {t("Sil")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section">
        <h2>{canManage ? t("İzin ekle") : t("İzin iste")}</h2>
        {!canManage && (
          <p className="desc">
            {t("İzni doğrudan alamazsın — gün(leri) seç, istek gönder. Yönetici onaylayınca takvime işlenir. İstersen açıklama ekle.")}
          </p>
        )}
        <form className="admin-form" onSubmit={add}>
          {canManage && (
            <label>{t("Kişi")}
              <select value={form.target_user_id} onChange={(e) => upd("target_user_id", e.target.value)}>
                <option value="">{t("Kendim ({name})", { name: user.display_name })}</option>
                <option value="all">🏢 {t("Herkes (tüm aktif çalışanlar)")}</option>
                {employees.filter((u) => u.developer_id != null).map((u) => (
                  <option key={u.id} value={u.id}>{u.display_name}</option>
                ))}
              </select>
            </label>
          )}
          <label>{t("Başlangıç")}
            <input type="date" value={form.start_date} onChange={(e) => upd("start_date", e.target.value)} required />
          </label>
          <label>{t("Bitiş")}
            <input type="date" value={form.end_date} onChange={(e) => upd("end_date", e.target.value)} required />
          </label>
          <label>{t("Tür")}
            <select value={form.leave_type} onChange={(e) => upd("leave_type", e.target.value)}>
              <option value="annual">{t("Yıllık izin")}</option>
              <option value="sick">{t("Rapor (hastalık)")}</option>
              <option value="other">{t("Diğer")}</option>
            </select>
          </label>
          <label>{t("Açıklama (opsiyonel)")}
            <input value={form.description} onChange={(e) => upd("description", e.target.value)} />
          </label>
          <button type="submit" className="login-btn">{canManage ? t("İzin ekle") : t("İstek gönder")}</button>
        </form>
      </section>

      {/* Red gerekçesi modalı: yönetici reddederken zorunlu gerekçe girer. */}
      {rejectFor && (
        <Modal title={t("İzin isteğini reddet")} onClose={() => { setRejectFor(null); setError(null); }}>
          <div className="reject-modal">
            <p className="desc">
              <strong>{rejectFor.person}</strong> · {rejectFor.start_date === rejectFor.end_date
                ? rejectFor.start_date : `${rejectFor.start_date} → ${rejectFor.end_date}`}
            </p>
            <label className="ca-block">
              {t("Red gerekçesi (zorunlu — çalışana iletilir)")}
              <textarea rows={3} value={rejectNote}
                onChange={(e) => setRejectNote(e.target.value)}
                placeholder={t("Örn. bu tarihlerde ekip kapasitesi düşük; farklı bir hafta önerilir.")} />
            </label>
            {error && <div className="login-error">{error}</div>}
            <div className="cred-actions">
              <button className="mini ghost" onClick={() => { setRejectFor(null); setError(null); }}>{t("Vazgeç")}</button>
              <button className="mini danger" disabled={!rejectNote.trim()} onClick={confirmReject}>
                {t("Reddet ve gerekçeyi gönder")}
              </button>
            </div>
          </div>
        </Modal>
      )}

    </div>
  );
}
