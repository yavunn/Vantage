// Yönetim paneli (Faz 2) — yalnız admin rolü görür; sunucu 403 ile zorlar.
// İstatistikler AGREGAT'tır: kişi kıyas tablosu bilinçli olarak yoktur.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";

export default function AdminDashboard() {
  const me = useAuth();
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [error, setError] = useState(null);

  function reload() {
    api("/api/admin/stats").then(setStats).catch(setError);
    // Pasifleştirilenler de gelsin — yeniden aktifleştirme için
    api("/api/admin/users?include_inactive=true").then(setUsers).catch(setError);
  }

  useEffect(reload, []);

  async function changeRole(u, role) {
    setError(null);
    try {
      await api(`/api/admin/users/${u.id}`, { method: "PUT", body: { role } });
      reload();
    } catch (err) {
      setError(err);
    }
  }

  async function softDelete(u) {
    if (!window.confirm(`${u.email} hesabı pasifleştirilsin mi? (ileride geri açılabilir)`)) return;
    try {
      await api(`/api/admin/users/${u.id}`, { method: "DELETE" });
      reload();
    } catch (err) {
      setError(err);
    }
  }

  async function reactivate(u) {
    try {
      await api(`/api/admin/users/${u.id}/reactivate`, { method: "POST" });
      reload();
    } catch (err) {
      setError(err);
    }
  }

  if (error) return <div className="error-box">Hata: {error.message}</div>;
  if (!stats) return <p className="desc">Yükleniyor…</p>;

  return (
    <>
      <div className="cards">
        <div className="card">
          <div className="name">Toplam kullanıcı</div>
          <div className="value">{stats.total_users}</div>
        </div>
        <div className="card">
          <div className="name">Bağlı repo</div>
          <div className="value">{stats.repo_count}</div>
        </div>
        <div className="card">
          <div className="name">Son 7 gün commit</div>
          <div className="value">{stats.commits_last_7d}</div>
        </div>
        <div className="card">
          <div className="name">Genel sağlık (takım metrikleri)</div>
          <div className="value">
            {stats.overall_health_pct != null ? (
              `%${stats.overall_health_pct}`
            ) : (
              <span className="na">veri yetersiz</span>
            )}
          </div>
        </div>
      </div>

      <section className="section">
        <h2>Hesaplar</h2>
        <p className="desc">
          Bu liste hesap yönetimi içindir; metrik içermez. Pasifleştirme
          (soft delete) hesabı silmez — kayıt durur, ileride yeniden
          aktifleştirilebilir. Admin kendi rolünü ve son admini düşüremez.
        </p>
        <table className="quality">
          <thead>
            <tr>
              <th>E-posta</th><th>Rol</th><th>Durum</th>
              <th>Geliştirici bağı</th><th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.email === me?.account?.email;
              return (
                <tr key={u.id} className={u.is_active ? "" : "inactive-row"}>
                  <td>{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      disabled={!u.is_active || self}
                      onChange={(e) => changeRole(u, e.target.value)}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td>{u.is_active ? "aktif" : <span className="na">pasif</span>}</td>
                  <td>{u.developer_id != null ? `#${u.developer_id}` : <span className="na">yok</span>}</td>
                  <td>
                    {!u.is_active ? (
                      <button onClick={() => reactivate(u)}>Aktifleştir</button>
                    ) : (
                      !self && <button onClick={() => softDelete(u)}>Pasifleştir</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}
