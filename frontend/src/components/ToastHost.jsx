import { useEffect, useState } from "react";
import { dismiss, subscribe } from "../toast.js";

const ICON = { ok: "✓", error: "✕", info: "ℹ" };

export default function ToastHost() {
  const [items, setItems] = useState([]);
  useEffect(() => subscribe(setItems), []);
  if (items.length === 0) return null;
  return (
    <div className="toast-host" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.type}`} onClick={() => dismiss(t.id)}>
          <span className="toast-icon">{ICON[t.type] || ICON.info}</span>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}
