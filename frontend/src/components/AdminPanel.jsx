import { useEffect, useState } from "react";
import {
  createEmployee,
  deleteEmployee,
  listEmployees,
  setEmployeePassword,
  updateEmployee,
} from "../api.js";

// Kolay okunur, güçlü geçici parola üretir (karışan karakterler hariç).
function randomPassword() {
  const chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const syms = "!@#$%*?";
  let out = "";
  for (let i = 0; i < 10; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out + syms[Math.floor(Math.random() * syms.length)];
}

// Yönetici paneli: yeni çalışan + hesap oluşturma, mevcut hesapların
// parolasını sıfırlama. Parola çalışana verilir; çalışan sonradan
// profilinden kendi parolasını değiştirebilir.
export default function AdminPanel({ teams, me }) {
  const [employees, setEmployees] = useState([]);
  const [form, setForm] = useState({
    display_name: "",
    email: "",
    password: "",
    role: "user",
    team_id: "",
    team_role: "member",
  });
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [resetFor, setResetFor] = useState(null);
  const [resetPw, setResetPw] = useState("");
  const [query, setQuery] = useState("");

  function refresh() {
    listEmployees().then(setEmployees).catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  function upd(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    try {
      const payload = {
        display_name: form.display_name.trim(),
        email: form.email.trim(),
        password: form.password,
        role: form.role,
        team_role: form.team_role,
      };
      if (form.team_id) payload.team_id = Number(form.team_id);
      const created = await createEmployee(payload);
      setMsg(
        `Oluşturuldu: ${created.display_name} (${created.email}). Parolayı çalışana ilet.`
      );
      setForm({
        display_name: "",
        email: "",
        password: "",
        role: "user",
        team_id: "",
        team_role: "member",
      });
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function doReset(userId) {
    setError(null);
    setMsg(null);
    try {
      await setEmployeePassword(userId, resetPw);
      setMsg("Parola sıfırlandı. Yeni parolayı çalışana ilet.");
      setResetFor(null);
      setResetPw("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function doDelete(u) {
    if (!window.confirm(`${u.display_name} (${u.email}) hesabı silinsin mi? Bu işlem geri alınamaz.`)) return;
    setError(null);
    setMsg(null);
    try {
      const res = await deleteEmployee(u.id);
      setEmployees((list) => list.filter((x) => x.id !== u.id));
      setMsg(
        res.developer_removed
          ? "Hesap ve geliştirici kaydı silindi."
          : "Hesap silindi (geçmiş metrikler korundu)."
      );
    } catch (err) {
      setError(err.message);
    }
  }

  async function patch(userId, changes) {
    setError(null);
    setMsg(null);
    try {
      const updated = await updateEmployee(userId, changes);
      setEmployees((list) => list.map((u) => (u.id === userId ? { ...u, ...updated } : u)));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="admin-panel">
      <section className="section">
        <h2>Yeni çalışan ekle</h2>
        <form className="admin-form" onSubmit={submit}>
          <label>
            Ad Soyad
            <input
              value={form.display_name}
              onChange={(e) => upd("display_name", e.target.value)}
              required
            />
          </label>
          <label>
            E-posta
            <input
              type="email"
              value={form.email}
              onChange={(e) => upd("email", e.target.value)}
              placeholder="ad@corp.local"
              required
            />
          </label>
          <label>
            Başlangıç parolası
            <span className="input-with-btn">
              <input
                value={form.password}
                onChange={(e) => upd("password", e.target.value)}
                placeholder="en az 6 karakter"
                minLength={6}
                required
              />
              <button
                type="button"
                className="mini"
                onClick={() => upd("password", randomPassword())}
                title="Rastgele güçlü parola üret"
              >
                Üret
              </button>
            </span>
          </label>
          <label>
            Rol
            <select value={form.role} onChange={(e) => upd("role", e.target.value)}>
              <option value="user">Çalışan</option>
              <option value="admin">Yönetici (admin)</option>
            </select>
          </label>
          <label>
            Takım (opsiyonel)
            <select value={form.team_id} onChange={(e) => upd("team_id", e.target.value)}>
              <option value="">— seçilmedi —</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
          <label>
            Takım rolü
            <select
              value={form.team_role}
              onChange={(e) => upd("team_role", e.target.value)}
              disabled={!form.team_id}
            >
              <option value="member">Üye</option>
              <option value="manager">Takım yöneticisi</option>
            </select>
          </label>
          <button type="submit" className="login-btn">Çalışanı oluştur</button>
        </form>
        {msg && <div className="admin-ok">{msg}</div>}
        {error && <div className="login-error">{error}</div>}
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Hesaplar ({employees.length})</h2>
          <input
            className="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ada veya e-postaya göre ara…"
          />
        </div>
        <table className="quality">
          <thead>
            <tr>
              <th>Ad</th><th>E-posta</th><th>Rol</th><th>Durum</th><th></th>
            </tr>
          </thead>
          <tbody>
            {employees
              .filter((u) => {
                const q = query.trim().toLowerCase();
                if (!q) return true;
                return (
                  u.display_name.toLowerCase().includes(q) ||
                  u.email.toLowerCase().includes(q)
                );
              })
              .map((u) => {
              const isSelf = me && u.id === me.id;
              return (
              <tr key={u.id} className={u.is_active ? "" : "row-inactive"}>
                <td>{u.display_name}</td>
                <td>{u.email}</td>
                <td>
                  <select
                    className="cell-select"
                    value={u.role}
                    disabled={isSelf}
                    title={isSelf ? "Kendi rolünü değiştiremezsin" : ""}
                    onChange={(e) => patch(u.id, { role: e.target.value })}
                  >
                    <option value="user">Çalışan</option>
                    <option value="admin">Yönetici</option>
                  </select>
                </td>
                <td>
                  <button
                    className={`mini ${u.is_active ? "" : "ghost"}`}
                    disabled={isSelf}
                    title={isSelf ? "Kendi durumunu değiştiremezsin" : ""}
                    onClick={() => patch(u.id, { is_active: !u.is_active })}
                  >
                    {u.is_active ? "Aktif" : "Pasif"}
                  </button>
                </td>
                <td>
                  {resetFor === u.id ? (
                    <span className="reset-row">
                      <input
                        type="text"
                        value={resetPw}
                        onChange={(e) => setResetPw(e.target.value)}
                        placeholder="yeni parola"
                        minLength={6}
                      />
                      <button className="mini" onClick={() => doReset(u.id)}>Kaydet</button>
                      <button className="mini ghost" onClick={() => setResetFor(null)}>Vazgeç</button>
                    </span>
                  ) : (
                    <button className="mini" onClick={() => { setResetFor(u.id); setResetPw(""); }}>
                      Parola sıfırla
                    </button>
                  )}
                  <button
                    className="mini danger"
                    disabled={isSelf}
                    title={isSelf ? "Kendi hesabını silemezsin" : "Hesabı sil"}
                    onClick={() => doDelete(u)}
                  >
                    Sil
                  </button>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
