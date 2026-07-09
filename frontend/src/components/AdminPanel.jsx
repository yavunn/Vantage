import { useEffect, useState } from "react";
import { createEmployee, listEmployees, setEmployeePassword } from "../api.js";

// Yönetici paneli: yeni çalışan + hesap oluşturma, mevcut hesapların
// parolasını sıfırlama. Parola çalışana verilir; çalışan sonradan
// profilinden kendi parolasını değiştirebilir.
export default function AdminPanel({ teams }) {
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
            <input
              value={form.password}
              onChange={(e) => upd("password", e.target.value)}
              placeholder="en az 6 karakter"
              minLength={6}
              required
            />
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
        <h2>Hesaplar</h2>
        <table className="quality">
          <thead>
            <tr>
              <th>Ad</th><th>E-posta</th><th>Rol</th><th>Durum</th><th></th>
            </tr>
          </thead>
          <tbody>
            {employees.map((u) => (
              <tr key={u.id}>
                <td>{u.display_name}</td>
                <td>{u.email}</td>
                <td>{u.role === "admin" ? "Yönetici" : "Çalışan"}</td>
                <td>{u.is_active ? "Aktif" : "Pasif"}</td>
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
