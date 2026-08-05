import { useEffect, useRef } from "react";
import { useT } from "../i18n.jsx";

// Erişilebilir modal: Esc ile kapanır, odak içeride tutulur (focus-trap),
// aria-modal + role=dialog + başlık ilişkilendirmesi. Backdrop tıklaması kapatır.
export default function Modal({ title, onClose, children }) {
  const t = useT();
  const ref = useRef(null);
  const titleId = "modal-title";

  useEffect(() => {
    const prevFocus = document.activeElement;
    const node = ref.current;
    // İlk odaklanabilir öğeye odak ver.
    const focusables = () =>
      node.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
    const first = focusables()[0];
    if (first) first.focus();

    function onKey(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab") {
        const items = focusables();
        if (items.length === 0) return;
        const firstEl = items[0];
        const lastEl = items[items.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (prevFocus && prevFocus.focus) prevFocus.focus();
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={ref}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id={titleId}>{title}</h2>
          <button className="mini ghost" aria-label={t("Kapat")} onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
