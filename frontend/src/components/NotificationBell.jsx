import { useEffect, useRef, useState } from "react";
import { listNotifications, markAllNotificationsRead, markNotificationRead } from "../api.js";

// Bildirim zili: okunmamış sayacı + açılır liste. Trend alarmları burada görünür.
// Etik: içerik takım sağlığı sinyali; kişi kıyası/ceza dili yok (backend garantiler).
export default function NotificationBell() {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  function refresh() {
    listNotifications()
      .then((d) => { setItems(d.items); setUnread(d.unread); })
      .catch(() => {});
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000); // dakikada bir yokla
    return () => clearInterval(t);
  }, []);

  // Dışarı tıklayınca kapat.
  useEffect(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  async function readOne(n) {
    if (n.is_read) return;
    await markNotificationRead(n.id).catch(() => {});
    refresh();
  }
  async function readAll() {
    await markAllNotificationsRead().catch(() => {});
    refresh();
  }

  return (
    <div className="notif-bell" ref={ref}>
      <button className="mini ghost notif-trigger" onClick={() => { setOpen((o) => !o); }} aria-label="Bildirimler" title="Bildirimler">
        🔔{unread > 0 && <span className="notif-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="notif-panel" role="menu">
          <div className="notif-head">
            <strong>Bildirimler</strong>
            {unread > 0 && <button className="mini ghost" onClick={readAll}>Tümünü okundu yap</button>}
          </div>
          {items.length === 0 ? (
            <p className="desc notif-empty">Bildirim yok.</p>
          ) : (
            <ul className="notif-list">
              {items.map((n) => (
                <li key={n.id} className={`notif-item ${n.is_read ? "read" : "unread"} sev-${n.severity}`} onClick={() => readOne(n)}>
                  <div className="notif-title">{n.title}</div>
                  {n.body && <div className="notif-body">{n.body}</div>}
                  <div className="notif-time">{n.created_at ? new Date(n.created_at).toLocaleString("tr-TR") : ""}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
