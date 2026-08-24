import { useEffect, useMemo, useState } from "react";
import {
  MIN_PASSWORD_LENGTH,
  createEmployee,
  deleteEmployee,
  listEmployees,
  setEmployeePassword,
  setEmployment,
  updateEmployee,
} from "../api.js";
import AuditPanel from "./AuditPanel.jsx";
import Yukleniyor from "./Yukleniyor.jsx";
import CodeAnalysisPanel from "./CodeAnalysisPanel.jsx";
import IntegrationPanel from "./IntegrationPanel.jsx";
import TaskLinksPanel from "./TaskLinksPanel.jsx";
import Modal from "./Modal.jsx";
import OnboardingPanel from "./OnboardingPanel.jsx";
import SurveyAdminPanel from "./SurveyAdminPanel.jsx";
import TeamEditor from "./TeamEditor.jsx";
import TeamsPanel from "./TeamsPanel.jsx";
import VisibilitySettings from "./VisibilitySettings.jsx";
import { todayIso } from "../dates.js";
import { toast } from "../toast.js";
import { useT } from "../i18n.jsx";

// Panoya kopyala; başarısızsa (izin yok/eski tarayıcı) sessiz düşmesin.
async function copyText(t, text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t("{label} kopyalandı", { label }), "ok");
  } catch {
    toast(t("Kopyalanamadı — panoya erişim yok"), "error");
  }
}

const PAGE_SIZE = 10;

// Kolay okunur, güçlü geçici parola üretir (karışan karakterler hariç).
function randomPassword() {
  const chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const syms = "!@#$%*?";
  let out = "";
  for (let i = 0; i < 10; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out + syms[Math.floor(Math.random() * syms.length)];
}

// hrMode: İK yalnız hesap rehberini kullanır — çalışan (user) ekler ve user
// parolası sıfırlar. Rol değiştirme / silme / pasifleştirme / entegrasyon /
// denetim İK'ya KAPALI (backend de 403 verir; UI de göstermez).
export default function AdminPanel({ teams, me, onViewPerson, onTeamsChanged, hrMode = false }) {
  const t = useT();
  const ROLE_LABEL = { user: t("Çalışan"), admin: t("Yönetici"), hr: t("İnsan Kaynakları") };
  const [subtab, setSubtab] = useState("accounts"); // accounts | integration
  const [employees, setEmployees] = useState([]);
  const [form, setForm] = useState({
    display_name: "", email: "", password: "", role: "user", team_id: "", team_role: "member",
    hire_date: todayIso(), annual_allowance: 14,
  });
  const [employmentFor, setEmploymentFor] = useState(null); // düzenlenen hesap
  const [empForm, setEmpForm] = useState({ hire_date: "", annual_allowance: 14 });
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [resetFor, setResetFor] = useState(null);
  const [resetPw, setResetPw] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState({ key: "id", dir: "asc" });
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(new Set());
  const [teamEditFor, setTeamEditFor] = useState(null);
  // Yeni hesap / parola sıfırlama sonrası kimlik bilgisi modalı (kopyala araçları).
  const [cred, setCred] = useState(null); // { title, email, password }

  // Hesap listesi gelene kadar tablo bos duruyordu.
  const [yukleniyor, setYukleniyor] = useState(true);

  function refresh() {
    listEmployees()
      .then(setEmployees)
      .catch((e) => setError(e.message))
      .finally(() => setYukleniyor(false));
  }
  useEffect(refresh, []);

  function upd(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e) {
    e.preventDefault();
    setError(null); setMsg(null);
    try {
      const payload = {
        display_name: form.display_name.trim(),
        email: form.email.trim(),
        password: form.password,
        role: hrMode ? "user" : form.role,
        team_role: form.team_role,
        annual_allowance: Number(form.annual_allowance) || 0,
      };
      if (form.team_id) payload.team_id = Number(form.team_id);
      if (form.hire_date) payload.hire_date = form.hire_date;
      const created = await createEmployee(payload);
      setMsg(t("Oluşturuldu: {name} ({email}). Geçici parolayı çalışana ilet — ilk girişte değiştirecek.",
        { name: created.display_name, email: created.email }));
      setCred({ title: t("Yeni hesap oluşturuldu"), email: created.email, password: form.password });
      setForm({ display_name: "", email: "", password: "", role: "user", team_id: "", team_role: "member", hire_date: todayIso(), annual_allowance: 14 });
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function doReset(userId) {
    setError(null); setMsg(null);
    if (resetPw.length < MIN_PASSWORD_LENGTH) {
      setError(t("Yeni parola en az {n} karakter olmalı", { n: MIN_PASSWORD_LENGTH }));
      return;
    }
    try {
      const target = employees.find((x) => x.id === userId);
      await setEmployeePassword(userId, resetPw);
      setMsg(t("Parola sıfırlandı. Çalışan ilk girişte değiştirecek."));
      setCred({ title: t("Parola sıfırlandı"), email: target ? target.email : "", password: resetPw });
      setResetFor(null); setResetPw("");
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function doDelete(u) {
    if (!window.confirm(t("{name} ({email}) hesabı silinsin mi? Bu işlem geri alınamaz.",
      { name: u.display_name, email: u.email }))) return;
    setError(null); setMsg(null);
    try {
      const res = await deleteEmployee(u.id);
      setEmployees((list) => list.filter((x) => x.id !== u.id));
      setSelected((s) => { const n = new Set(s); n.delete(u.id); return n; });
      setMsg(res.developer_removed ? t("Hesap ve geliştirici kaydı silindi.") : t("Hesap silindi (geçmiş metrikler korundu)."));
    } catch (err) {
      setError(err.message);
    }
  }

  function openEmployment(u) {
    setEmploymentFor(u);
    setEmpForm({ hire_date: u.hire_date || todayIso(), annual_allowance: u.annual_allowance ?? 14 });
  }
  async function saveEmployment() {
    setError(null); setMsg(null);
    try {
      const patch = { annual_allowance: Number(empForm.annual_allowance) || 0 };
      if (empForm.hire_date) patch.hire_date = empForm.hire_date;
      const updated = await setEmployment(employmentFor.id, patch);
      setEmployees((list) => list.map((u) => (u.id === updated.id ? updated : u)));
      setMsg(t("{name}: işe giriş + izin hakkı güncellendi.", { name: updated.display_name }));
      setEmploymentFor(null);
    } catch (err) {
      setError(err.message);
    }
  }

  async function patch(userId, changes) {
    setError(null); setMsg(null);
    try {
      const updated = await updateEmployee(userId, changes);
      setEmployees((list) => list.map((u) => (u.id === userId ? updated : u)));
    } catch (err) {
      setError(err.message);
    }
  }

  // --- filtre + sıralama ---
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = employees.filter(
      (u) => !q || u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    );
    const { key, dir } = sort;
    rows = [...rows].sort((a, b) => {
      let av, bv;
      if (key === "status") { av = a.is_active ? 1 : 0; bv = b.is_active ? 1 : 0; }
      else { av = a[key]; bv = b[key]; }
      if (typeof av === "string") av = av.toLowerCase();
      if (typeof bv === "string") bv = bv.toLowerCase();
      if (av < bv) return dir === "asc" ? -1 : 1;
      if (av > bv) return dir === "asc" ? 1 : -1;
      return 0;
    });
    return rows;
  }, [employees, query, sort]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const clampedPage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(clampedPage * PAGE_SIZE, clampedPage * PAGE_SIZE + PAGE_SIZE);

  function toggleSort(key) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }
  function sortArrow(key) {
    if (sort.key !== key) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  // --- toplu seçim ---
  const selectableIds = pageRows.filter((u) => (!me || u.id !== me.id) && !u.is_owner).map((u) => u.id);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  function toggleAll() {
    setSelected((s) => {
      const n = new Set(s);
      if (allSelected) selectableIds.forEach((id) => n.delete(id));
      else selectableIds.forEach((id) => n.add(id));
      return n;
    });
  }
  function toggleOne(id) {
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }

  async function bulkDeactivate() {
    const ids = [...selected];
    if (ids.length === 0) return;
    if (!window.confirm(t("{n} hesap pasifleştirilsin mi?", { n: ids.length }))) return;
    setError(null); setMsg(null);
    let ok = 0, fail = 0;
    for (const id of ids) {
      try { const u = await updateEmployee(id, { is_active: false }); setEmployees((l) => l.map((x) => (x.id === id ? u : x))); ok++; }
      catch { fail++; }
    }
    setSelected(new Set());
    const failPart = fail ? t(", {n} başarısız (ör. son admin)", { n: fail }) : "";
    setMsg(t("Toplu pasifleştirme: {ok} başarılı{fail}.", { ok, fail: failPart }));
  }

  return (
    // side-panel: Ayarlar ekraniyla PAYLASILAN kenar cubugu kalibi. Ikisi
    // birebir ayni kurallari iki kez tanimliyordu; artik tek kalip.
    <div className="admin-panel side-panel">
      {!hrMode && (
        <div className="subtabs">
          <button className={`tab ${subtab === "onboarding" ? "active" : ""}`} onClick={() => setSubtab("onboarding")}>{t("Başlangıç")}</button>
          <button className={`tab ${subtab === "accounts" ? "active" : ""}`} onClick={() => setSubtab("accounts")}>{t("Hesaplar")}</button>
          <button className={`tab ${subtab === "teams" ? "active" : ""}`} onClick={() => setSubtab("teams")}>{t("Takımlar")}</button>
          <button className={`tab ${subtab === "visibility" ? "active" : ""}`} onClick={() => setSubtab("visibility")}>{t("Görünürlük")}</button>
          <button className={`tab ${subtab === "integration" ? "active" : ""}`} onClick={() => setSubtab("integration")}>{t("Entegrasyon")}</button>
          <button className={`tab ${subtab === "tasklinks" ? "active" : ""}`} onClick={() => setSubtab("tasklinks")}>{t("İş ↔ Commit")}</button>
          <button className={`tab ${subtab === "code" ? "active" : ""}`} onClick={() => setSubtab("code")}>{t("AI Kod Analizi")}</button>
          <button className={`tab ${subtab === "survey" ? "active" : ""}`} onClick={() => setSubtab("survey")}>{t("Memnuniyet")}</button>
          <button className={`tab ${subtab === "audit" ? "active" : ""}`} onClick={() => setSubtab("audit")}>{t("Denetim")}</button>
        </div>
      )}

      {/* Panel gövdesi: kenar çubuğunun yanına oturan tek sütun. Sarmalayıcı
          olmadan alt sekme listesi ve içerik kardeş kalıyordu; ikisini yan yana
          dizmek mümkün değildi. İçerik ve koşullar aynen korundu. */}
      <div className="admin-body side-body">

      {!hrMode && subtab === "onboarding" && <OnboardingPanel onGoto={setSubtab} />}

      {!hrMode && subtab === "integration" && <IntegrationPanel />}

      {!hrMode && subtab === "tasklinks" && (
        <TaskLinksPanel teams={teams} canManage={!hrMode} />
      )}

      {!hrMode && subtab === "code" && <CodeAnalysisPanel me={me} />}

      {!hrMode && subtab === "survey" && <SurveyAdminPanel me={me} />}

      {!hrMode && subtab === "audit" && <AuditPanel />}

      {(hrMode || subtab === "accounts") && (
        <>
          <section className="section">
            <h2>{t("Yeni çalışan ekle")}</h2>
            <form className="admin-form" onSubmit={submit}>
              <label>{t("Ad Soyad")}
                <input value={form.display_name} onChange={(e) => upd("display_name", e.target.value)} required />
              </label>
              <label>{t("E-posta")}
                <input type="email" value={form.email} onChange={(e) => upd("email", e.target.value)} placeholder="ad@corp.local" required />
              </label>
              <label>{t("Başlangıç parolası")}
                <span className="input-with-btn">
                  <input value={form.password} onChange={(e) => upd("password", e.target.value)} placeholder={t("en az {n} karakter", { n: MIN_PASSWORD_LENGTH })} minLength={MIN_PASSWORD_LENGTH} required />
                  <button type="button" className="mini" onClick={() => upd("password", randomPassword())} title={t("Rastgele güçlü parola üret")}>{t("Üret")}</button>
                  <button type="button" className="mini ghost" disabled={!form.password} onClick={() => copyText(t, form.password, t("Parola"))} title={t("Parolayı kopyala")}>{t("Kopyala")}</button>
                </span>
              </label>
              <label>{t("Rol")}
                <select value={hrMode ? "user" : form.role} disabled={hrMode} title={hrMode ? t("İK yalnızca çalışan (user) hesabı açabilir") : ""} onChange={(e) => upd("role", e.target.value)}>
                  <option value="user">{t("Çalışan")}</option>
                  {!hrMode && <option value="admin">{t("Yönetici (admin)")}</option>}
                  {!hrMode && <option value="hr">{t("İnsan Kaynakları (hr)")}</option>}
                </select>
              </label>
              <label>{t("Takım (opsiyonel)")}
                <select value={form.team_id} onChange={(e) => upd("team_id", e.target.value)}>
                  <option value="">{t("— seçilmedi —")}</option>
                  {teams.map((tm) => <option key={tm.id} value={tm.id}>{tm.name}</option>)}
                </select>
              </label>
              <label>{t("Takım rolü")}
                <select value={form.team_role} onChange={(e) => upd("team_role", e.target.value)} disabled={!form.team_id}>
                  <option value="member">{t("Üye")}</option>
                  <option value="manager">{t("Takım yöneticisi")}</option>
                </select>
              </label>
              <label>{t("İşe giriş tarihi (varsayılan bugün)")}
                <input type="date" value={form.hire_date} onChange={(e) => upd("hire_date", e.target.value)} />
              </label>
              <label>{t("Yıllık izin hakkı (gün)")}
                <input type="number" min={0} max={365} value={form.annual_allowance} onChange={(e) => upd("annual_allowance", e.target.value)} />
              </label>
              <button type="submit" className="login-btn">{t("Çalışanı oluştur")}</button>
            </form>
            {msg && <div className="admin-ok">{msg}</div>}
            {error && <div className="login-error">{error}</div>}
          </section>

          <section className="section">
            <div className="section-head">
              <h2>{t("Hesaplar ({n})", { n: filtered.length })}</h2>
              <input className="search" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} placeholder={t("Ada veya e-postaya göre ara…")} />
            </div>

            {!hrMode && selected.size > 0 && (
              <div className="bulk-bar">
                <span>{t("{n} seçili", { n: selected.size })}</span>
                <button className="mini" onClick={bulkDeactivate}>{t("Seçilenleri pasifleştir")}</button>
                <button className="mini ghost" onClick={() => setSelected(new Set())}>{t("Seçimi temizle")}</button>
              </div>
            )}

            {yukleniyor ? <Yukleniyor adet={6} /> : (
            <table className="quality">
              <thead>
                <tr>
                  {!hrMode && <th><input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label={t("Tümünü seç")} /></th>}
                  <th className="sortable" onClick={() => toggleSort("display_name")}>{t("Ad")}{sortArrow("display_name")}</th>
                  <th className="sortable" onClick={() => toggleSort("email")}>{t("E-posta")}{sortArrow("email")}</th>
                  <th>{t("Takımlar")}</th>
                  <th className="sortable" onClick={() => toggleSort("role")}>{t("Rol")}{sortArrow("role")}</th>
                  <th className="sortable" onClick={() => toggleSort("status")}>{t("Durum")}{sortArrow("status")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((u) => {
                  const isSelf = me && u.id === me.id;
                  const isOwner = !!u.is_owner;
                  // Baş yönetici korunur: kendisi dışında kimse rol/durum/silme/parola yapamaz.
                  const lockedByOwner = isOwner && !isSelf;
                  return (
                    <tr key={u.id} className={`${u.is_active ? "" : "row-inactive"} ${isOwner ? "row-owner" : ""}`}>
                      {!hrMode && (
                        <td>
                          <input type="checkbox" disabled={isSelf || isOwner} checked={selected.has(u.id)} onChange={() => toggleOne(u.id)} aria-label={t("{name} seç", { name: u.display_name })} />
                        </td>
                      )}
                      <td>
                        {/* İK akışı: hesaptan doğrudan o kişinin sağlık görünümüne geç. */}
                        {onViewPerson && u.developer_id != null ? (
                          <button
                            className="linklike"
                            title={t("Bu kişinin bireysel görünümünü aç")}
                            onClick={() => onViewPerson(u.developer_id)}
                          >
                            {u.display_name}
                          </button>
                        ) : u.display_name}
                        {u.must_change_password && <span className="pw-flag" title={t("Parola değiştirme bekliyor")}>⟳</span>}
                        {isOwner && <span className="owner-badge" title={t("Baş yönetici — korumalı, en üst yetki")}>★ {t("Baş Yönetici")}</span>}
                      </td>
                      <td>{u.email}</td>
                      <td>
                        <button className="mini ghost" onClick={() => setTeamEditFor(u)}>
                          {u.teams && u.teams.length ? u.teams.map((tm) => tm.team_name).join(", ") : t("— ata —")}
                        </button>
                      </td>
                      <td>
                        {isOwner ? (
                          <span className="owner-role" title={t("Baş yönetici rolü değiştirilemez")}>★ {t("Baş Yönetici")}</span>
                        ) : hrMode ? (
                          <span className={`role-tag role-${u.role}`}>{ROLE_LABEL[u.role] || u.role}</span>
                        ) : (
                          <select className="cell-select" value={u.role} disabled={isSelf} title={isSelf ? t("Kendi rolünü değiştiremezsin") : ""} onChange={(e) => patch(u.id, { role: e.target.value })}>
                            <option value="user">{t("Çalışan")}</option>
                            <option value="admin">{t("Yönetici")}</option>
                            <option value="hr">{t("İnsan Kaynakları")}</option>
                          </select>
                        )}
                      </td>
                      <td>
                        <button className={`mini ${u.is_active ? "" : "ghost"}`} disabled={hrMode || isSelf || isOwner} title={hrMode ? t("İK aktiflik değiştiremez") : isOwner ? t("Baş yönetici pasifleştirilemez") : isSelf ? t("Kendi durumunu değiştiremezsin") : ""} onClick={() => patch(u.id, { is_active: !u.is_active })}>
                          {u.is_active ? t("Aktif") : t("Pasif")}
                        </button>
                      </td>
                      {/* Satır eylemleri taşma menüsünde. Üç düğme alt alta
                          durunca satır ~106px oluyordu (9 satırda 27 düğme).
                          <details> seçildi: açılır davranışı ve klavye erişimi
                          tarayıcıdan gelir, yeni state gerekmez. Parola
                          sıfırlama satır içi form açtığı için o sırada menü
                          açık tutulur. */}
                      <td className="row-actions-cell">
                        <details className="row-actions" open={resetFor === u.id || undefined}>
                          <summary title={t("Satır eylemleri")} aria-label={t("Satır eylemleri")}>⋯</summary>
                          <div className="row-actions-menu">
                        <button className="mini ghost" title={t("İşe giriş tarihi + yıllık izin hakkı")} onClick={() => openEmployment(u)}>{t("İzin hakkı")}</button>
                        {resetFor === u.id ? (
                          <span className="reset-row">
                            <input type="text" value={resetPw} onChange={(e) => setResetPw(e.target.value)} placeholder={t("yeni parola")} minLength={MIN_PASSWORD_LENGTH} />
                            <button className="mini" title={t("Rastgele üret")} onClick={() => setResetPw(randomPassword())}>{t("Üret")}</button>
                            <button className="mini" onClick={() => doReset(u.id)}>{t("Kaydet")}</button>
                            <button className="mini ghost" onClick={() => setResetFor(null)}>{t("Vazgeç")}</button>
                          </span>
                        ) : (
                          <button className="mini" disabled={lockedByOwner || (hrMode && u.role !== "user")} title={hrMode && u.role !== "user" ? t("İK yalnızca çalışan (user) parolasını sıfırlayabilir") : lockedByOwner ? t("Baş yöneticinin parolasını yalnızca kendisi değiştirebilir") : ""} onClick={() => { setResetFor(u.id); setResetPw(""); }}>{t("Parola sıfırla")}</button>
                        )}
                        {!hrMode && (
                          <button className="mini danger" disabled={isSelf || isOwner} title={isOwner ? t("Baş yönetici hesabı silinemez") : isSelf ? t("Kendi hesabını silemezsin") : t("Hesabı sil")} onClick={() => doDelete(u)}>{t("Sil")}</button>
                        )}
                          </div>
                        </details>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            )}

            {pageCount > 1 && (
              <div className="pager">
                <button className="mini" disabled={clampedPage === 0} onClick={() => setPage(clampedPage - 1)}>{t("‹ Önceki")}</button>
                <span>{t("Sayfa {n} / {m}", { n: clampedPage + 1, m: pageCount })}</span>
                <button className="mini" disabled={clampedPage >= pageCount - 1} onClick={() => setPage(clampedPage + 1)}>{t("Sonraki ›")}</button>
              </div>
            )}
          </section>

        </>
      )}

      {/* Takımlar ve görünürlük artık Hesaplar sayfasının altına gömülü değil,
          kendi kenar çubuğu maddeleri. Hesaplar sayfası dört ayrı işi tek
          ekranda topluyordu (2393px) ve görünürlük ayarının kaydet düğmesi
          en dipte kalıyordu. İK'ya gösterilmez — bu uçlar admin ister. */}
      {!hrMode && subtab === "teams" && <TeamsPanel onChanged={onTeamsChanged} />}

      {!hrMode && subtab === "visibility" && <VisibilitySettings />}

      </div>{/* /admin-body */}

      {cred && (
        <Modal title={cred.title} onClose={() => setCred(null)}>
          <div className="cred-modal">
            <p className="desc">{t("Geçici parolayı çalışana güvenli bir kanaldan ilet. Kullanıcı ilk girişte değiştirecek.")}</p>
            <div className="cred-row">
              <span className="cred-label">{t("E-posta")}</span>
              <code className="cred-value">{cred.email}</code>
              <button className="mini" onClick={() => copyText(t, cred.email, t("E-posta"))}>{t("Kopyala")}</button>
            </div>
            <div className="cred-row">
              <span className="cred-label">{t("Parola")}</span>
              <code className="cred-value">{cred.password}</code>
              <button className="mini" onClick={() => copyText(t, cred.password, t("Parola"))}>{t("Kopyala")}</button>
            </div>
            <div className="cred-actions">
              <button className="mini" onClick={() => copyText(t, t("mail:{email} şifre:{password}", { email: cred.email, password: cred.password }), t("E-posta ve parola"))}>{t("İkisini birden kopyala")}</button>
              <button className="login-btn" onClick={() => setCred(null)}>{t("Tamam")}</button>
            </div>
          </div>
        </Modal>
      )}

      {employmentFor && (
        <Modal title={t("İstihdam · {name}", { name: employmentFor.display_name })} onClose={() => setEmploymentFor(null)}>
          <div className="admin-form" style={{ display: "grid", gap: "12px" }}>
            <label>{t("İşe giriş tarihi")}
              <input type="date" value={empForm.hire_date} onChange={(e) => setEmpForm((f) => ({ ...f, hire_date: e.target.value }))} />
            </label>
            <label>{t("Yıllık izin hakkı (gün)")}
              <input type="number" min={0} max={365} value={empForm.annual_allowance} onChange={(e) => setEmpForm((f) => ({ ...f, annual_allowance: e.target.value }))} />
            </label>
            <div className="cred-actions">
              <button className="mini ghost" onClick={() => setEmploymentFor(null)}>{t("Vazgeç")}</button>
              <button className="login-btn" onClick={saveEmployment}>{t("Kaydet")}</button>
            </div>
          </div>
        </Modal>
      )}

      {teamEditFor && (
        <TeamEditor
          user={teamEditFor}
          teams={teams}
          onClose={() => setTeamEditFor(null)}
          onChanged={(updated) => {
            setEmployees((list) => list.map((u) => (u.id === updated.id ? updated : u)));
            setTeamEditFor((cur) => (cur && cur.id === updated.id ? updated : cur));
          }}
        />
      )}
    </div>
  );
}
