import { useEffect, useRef, useState } from "react";
import { listNotifications, markAllNotificationsRead, markNotificationRead } from "../api.js";
import { toast } from "../toast.js";
import { useLang, useT } from "../i18n.jsx";

// Bildirim zili: okunmamış sayacı + açılır liste. Trend alarmları burada görünür.
// Etik: içerik takım sağlığı sinyali; kişi kıyası/ceza dili yok (backend garantiler).
export default function NotificationBell({ onNavigate }) {
  const t = useT();
  const { lang } = useLang();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // Arka plan yoklaması BİLİNÇLİ olarak sessiz: dakikada bir çalışıyor, ağ
  // kesintisinde kullanıcıyı toast yağmuruna tutmanın faydası yok. Kullanıcının
  // BAŞLATTIĞI eylemler (okundu işaretleme) ise sessiz kalmamalı — aşağıda.
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

  // Bildirime tıkla → okundu işaretle + ilgili takıma git (alarm eyleme dönüşsün).
  // link formatı backend'den: "/?team=<id>"
  async function readOne(n) {
    if (!n.is_read) {
      // Sessizce yutulursa bildirim okunmuş görünür ama sunucuda okunmamış
      // kalır; kullanıcı aynı alarmı tekrar tekrar görür ve sebebini bilmez.
      try {
        await markNotificationRead(n.id);
      } catch (err) {
        toast(t("Bildirim okundu işaretlenemedi: {msg}", { msg: err.message }), "error");
      }
      refresh();
    }
    if (!onNavigate) return;
    // Anket bildirimi: doğrudan ankete git. Trend alarmı: ilgili takıma git.
    if (n.link && /survey/.test(n.link)) {
      onNavigate({ survey: true });
      setOpen(false);
      return;
    }
    const m = n.link && n.link.match(/team=(\d+)/);
    if (m) {
      onNavigate({ teamId: Number(m[1]) });
      setOpen(false);
    }
  }
  async function readAll() {
    try {
      await markAllNotificationsRead();
    } catch (err) {
      toast(t("Bildirimler okundu işaretlenemedi: {msg}", { msg: err.message }), "error");
    }
    refresh();
  }

  return (
    <div className="notif-bell" ref={ref}>
      <button className="mini ghost notif-trigger" onClick={() => { setOpen((o) => !o); }} aria-label={t("Bildirimler")} title={t("Bildirimler")}>
        🔔{unread > 0 && <span className="notif-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="notif-panel" role="menu">
          <div className="notif-head">
            <strong>{t("Bildirimler")}</strong>
            {unread > 0 && <button className="mini ghost" onClick={readAll}>{t("Tümünü okundu yap")}</button>}
          </div>
          {items.length === 0 ? (
            <p className="desc notif-empty">{t("Bildirim yok.")}</p>
          ) : (
            <ul className="notif-list">
              {items.map((n) => (
                <li key={n.id} className={`notif-item ${n.is_read ? "read" : "unread"} sev-${n.severity}`} onClick={() => readOne(n)}>
                  <div className="notif-title">{n.title}</div>
                  {n.body && <div className="notif-body">{n.body}</div>}
                  <div className="notif-time">{n.created_at ? new Date(n.created_at).toLocaleString(lang === "en" ? "en-US" : "tr-TR") : ""}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
