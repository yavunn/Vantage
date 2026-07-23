import { useEffect, useMemo, useState } from "react";
import {
  createEmployee,
  deleteEmployee,
  listEmployees,
  setEmployeePassword,
  setEmployment,
  updateEmployee,
} from "../api.js";
import AnnotationsPanel from "./AnnotationsPanel.jsx";
import AuditPanel from "./AuditPanel.jsx";
import CodeAnalysisPanel from "./CodeAnalysisPanel.jsx";
import IntegrationPanel from "./IntegrationPanel.jsx";
import Modal from "./Modal.jsx";
import OnboardingPanel from "./OnboardingPanel.jsx";
import TeamEditor from "./TeamEditor.jsx";
import { toast } from "../toast.js";

// Panoya kopyala; başarısızsa (izin yok/eski tarayıcı) sessiz düşmesin.
async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${label} kopyalandı`, "ok");
  } catch {
    toast("Kopyalanamadı — panoya erişim yok", "error");
  }
}

const PAGE_SIZE = 10;
const ROLE_LABEL = { user: "Çalışan", admin: "Yönetici", hr: "İnsan Kaynakları" };
// Yerel bugünün tarihi (YYYY-MM-DD) — TZ kaymadan.
function todayIso() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

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
export default function AdminPanel({ teams, me, onViewPerson, hrMode = false }) {
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

  function refresh() {
    listEmployees().then(setEmployees).catch((e) => setError(e.message));
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
      setMsg(`Oluşturuldu: ${created.display_name} (${created.email}). Geçici parolayı çalışana ilet — ilk girişte değiştirecek.`);
      setCred({ title: "Yeni hesap oluşturuldu", email: created.email, password: form.password });
      setForm({ display_name: "", email: "", password: "", role: "user", team_id: "", team_role: "member", hire_date: todayIso(), annual_allowance: 14 });
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function doReset(userId) {
    setError(null); setMsg(null);
    if (resetPw.length < 6) {
      setError("Yeni parola en az 6 karakter olmalı");
      return;
    }
    try {
      const target = employees.find((x) => x.id === userId);
      await setEmployeePassword(userId, resetPw);
      setMsg("Parola sıfırlandı. Çalışan ilk girişte değiştirecek.");
      setCred({ title: "Parola sıfırlandı", email: target ? target.email : "", password: resetPw });
      setResetFor(null); setResetPw("");
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function doDelete(u) {
    if (!window.confirm(`${u.display_name} (${u.email}) hesabı silinsin mi? Bu işlem geri alınamaz.`)) return;
    setError(null); setMsg(null);
    try {
      const res = await deleteEmployee(u.id);
      setEmployees((list) => list.filter((x) => x.id !== u.id));
      setSelected((s) => { const n = new Set(s); n.delete(u.id); return n; });
      setMsg(res.developer_removed ? "Hesap ve geliştirici kaydı silindi." : "Hesap silindi (geçmiş metrikler korundu).");
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
      setMsg(`${updated.display_name}: işe giriş + izin hakkı güncellendi.`);
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
    if (!window.confirm(`${ids.length} hesap pasifleştirilsin mi?`)) return;
    setError(null); setMsg(null);
    let ok = 0, fail = 0;
    for (const id of ids) {
      try { const u = await updateEmployee(id, { is_active: false }); setEmployees((l) => l.map((x) => (x.id === id ? u : x))); ok++; }
      catch { fail++; }
    }
    setSelected(new Set());
    setMsg(`Toplu pasifleştirme: ${ok} başarılı${fail ? `, ${fail} başarısız (ör. son admin)` : ""}.`);
  }

  return (
    <div className="admin-panel">
      {!hrMode && (
        <div className="subtabs">
          <button className={`tab ${subtab === "onboarding" ? "active" : ""}`} onClick={() => setSubtab("onboarding")}>Başlangıç</button>
          <button className={`tab ${subtab === "accounts" ? "active" : ""}`} onClick={() => setSubtab("accounts")}>Hesaplar</button>
          <button className={`tab ${subtab === "integration" ? "active" : ""}`} onClick={() => setSubtab("integration")}>Entegrasyon</button>
          <button className={`tab ${subtab === "annotations" ? "active" : ""}`} onClick={() => setSubtab("annotations")}>Anotasyonlar</button>
          <button className={`tab ${subtab === "code" ? "active" : ""}`} onClick={() => setSubtab("code")}>AI Kod Analizi</button>
          <button className={`tab ${subtab === "audit" ? "active" : ""}`} onClick={() => setSubtab("audit")}>Denetim</button>
        </div>
      )}

      {!hrMode && subtab === "onboarding" && <OnboardingPanel onGoto={setSubtab} />}

      {!hrMode && subtab === "integration" && <IntegrationPanel />}

      {!hrMode && subtab === "annotations" && <AnnotationsPanel teams={teams} />}

      {!hrMode && subtab === "code" && <CodeAnalysisPanel me={me} />}

      {!hrMode && subtab === "audit" && <AuditPanel />}

      {(hrMode || subtab === "accounts") && (
        <>
          <section className="section">
            <h2>Yeni çalışan ekle</h2>
            <form className="admin-form" onSubmit={submit}>
              <label>Ad Soyad
                <input value={form.display_name} onChange={(e) => upd("display_name", e.target.value)} required />
              </label>
              <label>E-posta
                <input type="email" value={form.email} onChange={(e) => upd("email", e.target.value)} placeholder="ad@corp.local" required />
              </label>
              <label>Başlangıç parolası
                <span className="input-with-btn">
                  <input value={form.password} onChange={(e) => upd("password", e.target.value)} placeholder="en az 6 karakter" minLength={6} required />
                  <button type="button" className="mini" onClick={() => upd("password", randomPassword())} title="Rastgele güçlü parola üret">Üret</button>
                  <button type="button" className="mini ghost" disabled={!form.password} onClick={() => copyText(form.password, "Parola")} title="Parolayı kopyala">Kopyala</button>
                </span>
              </label>
              <label>Rol
                <select value={hrMode ? "user" : form.role} disabled={hrMode} title={hrMode ? "İK yalnızca çalışan (user) hesabı açabilir" : ""} onChange={(e) => upd("role", e.target.value)}>
                  <option value="user">Çalışan</option>
                  {!hrMode && <option value="admin">Yönetici (admin)</option>}
                  {!hrMode && <option value="hr">İnsan Kaynakları (hr)</option>}
                </select>
              </label>
              <label>Takım (opsiyonel)
                <select value={form.team_id} onChange={(e) => upd("team_id", e.target.value)}>
                  <option value="">— seçilmedi —</option>
                  {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </label>
              <label>Takım rolü
                <select value={form.team_role} onChange={(e) => upd("team_role", e.target.value)} disabled={!form.team_id}>
                  <option value="member">Üye</option>
                  <option value="manager">Takım yöneticisi</option>
                </select>
              </label>
              <label>İşe giriş tarihi (varsayılan bugün)
                <input type="date" value={form.hire_date} onChange={(e) => upd("hire_date", e.target.value)} />
              </label>
              <label>Yıllık izin hakkı (gün)
                <input type="number" min={0} max={365} value={form.annual_allowance} onChange={(e) => upd("annual_allowance", e.target.value)} />
              </label>
              <button type="submit" className="login-btn">Çalışanı oluştur</button>
            </form>
            {msg && <div className="admin-ok">{msg}</div>}
            {error && <div className="login-error">{error}</div>}
          </section>

          <section className="section">
            <div className="section-head">
              <h2>Hesaplar ({filtered.length})</h2>
              <input className="search" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} placeholder="Ada veya e-postaya göre ara…" />
            </div>

            {!hrMode && selected.size > 0 && (
              <div className="bulk-bar">
                <span>{selected.size} seçili</span>
                <button className="mini" onClick={bulkDeactivate}>Seçilenleri pasifleştir</button>
                <button className="mini ghost" onClick={() => setSelected(new Set())}>Seçimi temizle</button>
              </div>
            )}

            <table className="quality">
              <thead>
                <tr>
                  {!hrMode && <th><input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="Tümünü seç" /></th>}
                  <th className="sortable" onClick={() => toggleSort("display_name")}>Ad{sortArrow("display_name")}</th>
                  <th className="sortable" onClick={() => toggleSort("email")}>E-posta{sortArrow("email")}</th>
                  <th>Takımlar</th>
                  <th className="sortable" onClick={() => toggleSort("role")}>Rol{sortArrow("role")}</th>
                  <th className="sortable" onClick={() => toggleSort("status")}>Durum{sortArrow("status")}</th>
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
                          <input type="checkbox" disabled={isSelf || isOwner} checked={selected.has(u.id)} onChange={() => toggleOne(u.id)} aria-label={`${u.display_name} seç`} />
                        </td>
                      )}
                      <td>
                        {/* İK akışı: hesaptan doğrudan o kişinin sağlık görünümüne geç. */}
                        {onViewPerson && u.developer_id != null ? (
                          <button
                            className="linklike"
                            title="Bu kişinin bireysel görünümünü aç"
                            onClick={() => onViewPerson(u.developer_id)}
                          >
                            {u.display_name}
                          </button>
                        ) : u.display_name}
                        {u.must_change_password && <span className="pw-flag" title="Parola değiştirme bekliyor">⟳</span>}
                        {isOwner && <span className="owner-badge" title="Baş yönetici — korumalı, en üst yetki">★ Baş Yönetici</span>}
                      </td>
                      <td>{u.email}</td>
                      <td>
                        <button className="mini ghost" onClick={() => setTeamEditFor(u)}>
                          {u.teams && u.teams.length ? u.teams.map((t) => t.team_name).join(", ") : "— ata —"}
                        </button>
                      </td>
                      <td>
                        {isOwner ? (
                          <span className="owner-role" title="Baş yönetici rolü değiştirilemez">★ Baş Yönetici</span>
                        ) : hrMode ? (
                          <span className={`role-tag role-${u.role}`}>{ROLE_LABEL[u.role] || u.role}</span>
                        ) : (
                          <select className="cell-select" value={u.role} disabled={isSelf} title={isSelf ? "Kendi rolünü değiştiremezsin" : ""} onChange={(e) => patch(u.id, { role: e.target.value })}>
                            <option value="user">Çalışan</option>
                            <option value="admin">Yönetici</option>
                            <option value="hr">İnsan Kaynakları</option>
                          </select>
                        )}
                      </td>
                      <td>
                        <button className={`mini ${u.is_active ? "" : "ghost"}`} disabled={hrMode || isSelf || isOwner} title={hrMode ? "İK aktiflik değiştiremez" : isOwner ? "Baş yönetici pasifleştirilemez" : isSelf ? "Kendi durumunu değiştiremezsin" : ""} onClick={() => patch(u.id, { is_active: !u.is_active })}>
                          {u.is_active ? "Aktif" : "Pasif"}
                        </button>
                      </td>
                      <td>
                        <button className="mini ghost" title="İşe giriş tarihi + yıllık izin hakkı" onClick={() => openEmployment(u)}>İzin hakkı</button>
                        {resetFor === u.id ? (
                          <span className="reset-row">
                            <input type="text" value={resetPw} onChange={(e) => setResetPw(e.target.value)} placeholder="yeni parola" minLength={6} />
                            <button className="mini" title="Rastgele üret" onClick={() => setResetPw(randomPassword())}>Üret</button>
                            <button className="mini" onClick={() => doReset(u.id)}>Kaydet</button>
                            <button className="mini ghost" onClick={() => setResetFor(null)}>Vazgeç</button>
                          </span>
                        ) : (
                          <button className="mini" disabled={lockedByOwner || (hrMode && u.role !== "user")} title={hrMode && u.role !== "user" ? "İK yalnızca çalışan (user) parolasını sıfırlayabilir" : lockedByOwner ? "Baş yöneticinin parolasını yalnızca kendisi değiştirebilir" : ""} onClick={() => { setResetFor(u.id); setResetPw(""); }}>Parola sıfırla</button>
                        )}
                        {!hrMode && (
                          <button className="mini danger" disabled={isSelf || isOwner} title={isOwner ? "Baş yönetici hesabı silinemez" : isSelf ? "Kendi hesabını silemezsin" : "Hesabı sil"} onClick={() => doDelete(u)}>Sil</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {pageCount > 1 && (
              <div className="pager">
                <button className="mini" disabled={clampedPage === 0} onClick={() => setPage(clampedPage - 1)}>‹ Önceki</button>
                <span>Sayfa {clampedPage + 1} / {pageCount}</span>
                <button className="mini" disabled={clampedPage >= pageCount - 1} onClick={() => setPage(clampedPage + 1)}>Sonraki ›</button>
              </div>
            )}
          </section>
        </>
      )}

      {cred && (
        <Modal title={cred.title} onClose={() => setCred(null)}>
          <div className="cred-modal">
            <p className="desc">Geçici parolayı çalışana güvenli bir kanaldan ilet. Kullanıcı ilk girişte değiştirecek.</p>
            <div className="cred-row">
              <span className="cred-label">E-posta</span>
              <code className="cred-value">{cred.email}</code>
              <button className="mini" onClick={() => copyText(cred.email, "E-posta")}>Kopyala</button>
            </div>
            <div className="cred-row">
              <span className="cred-label">Parola</span>
              <code className="cred-value">{cred.password}</code>
              <button className="mini" onClick={() => copyText(cred.password, "Parola")}>Kopyala</button>
            </div>
            <div className="cred-actions">
              <button className="mini" onClick={() => copyText(`mail:${cred.email} şifre:${cred.password}`, "E-posta ve parola")}>İkisini birden kopyala</button>
              <button className="login-btn" onClick={() => setCred(null)}>Tamam</button>
            </div>
          </div>
        </Modal>
      )}

      {employmentFor && (
        <Modal title={`İstihdam · ${employmentFor.display_name}`} onClose={() => setEmploymentFor(null)}>
          <div className="admin-form" style={{ display: "grid", gap: "12px" }}>
            <label>İşe giriş tarihi
              <input type="date" value={empForm.hire_date} onChange={(e) => setEmpForm((f) => ({ ...f, hire_date: e.target.value }))} />
            </label>
            <label>Yıllık izin hakkı (gün)
              <input type="number" min={0} max={365} value={empForm.annual_allowance} onChange={(e) => setEmpForm((f) => ({ ...f, annual_allowance: e.target.value }))} />
            </label>
            <div className="cred-actions">
              <button className="mini ghost" onClick={() => setEmploymentFor(null)}>Vazgeç</button>
              <button className="login-btn" onClick={saveEmployment}>Kaydet</button>
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
