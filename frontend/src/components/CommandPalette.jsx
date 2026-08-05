import { useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../i18n.jsx";

// Global hızlı arama (Ctrl+K / Cmd+K): sekme, takım ve kişi tek kutudan.
// İK akışında en büyük hızlandırıcı — "kişiye bak" 1 tuş + 2 harf.
export default function CommandPalette({ open, onClose, tabs, teams, people, onGoTab, onGoTeam, onGoPerson }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);

  const items = useMemo(() => {
    const all = [
      ...tabs.map((tb) => ({ kind: t("Sekme"), label: tb.label, run: () => onGoTab(tb.key) })),
      ...teams.map((tm) => ({ kind: t("Takım"), label: tm.name, run: () => onGoTeam(tm.id) })),
      ...people.map((p) => ({ kind: t("Kişi"), label: p.display_name, run: () => onGoPerson(p.id) })),
    ];
    const q = query.trim().toLocaleLowerCase("tr");
    if (!q) return all.slice(0, 12);
    return all.filter((i) => i.label.toLocaleLowerCase("tr").includes(q)).slice(0, 20);
  }, [query, tabs, teams, people, onGoTab, onGoTeam, onGoPerson, t]);

  useEffect(() => { setCursor(0); }, [query]);
  useEffect(() => {
    if (open) { setQuery(""); setCursor(0); setTimeout(() => inputRef.current?.focus(), 0); }
  }, [open]);

  if (!open) return null;

  function run(item) {
    item.run();
    onClose();
  }

  function onKey(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[cursor]) run(items[cursor]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  return (
    <div className="cmdk-backdrop" onClick={onClose}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label={t("Hızlı arama")} onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmdk-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKey}
          placeholder={t("Sekme, takım veya kişi ara…")}
          aria-label={t("Hızlı arama")}
        />
        {items.length === 0 ? (
          <p className="desc cmdk-empty">{t("Sonuç yok.")}</p>
        ) : (
          <ul className="cmdk-list">
            {items.map((it, i) => (
              <li key={`${it.kind}-${it.label}-${i}`}>
                <button
                  type="button"
                  className={`cmdk-item ${i === cursor ? "cursor" : ""}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => run(it)}
                >
                  <span className="cmdk-kind">{it.kind}</span>
                  <span className="cmdk-label">{it.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="cmdk-foot">
          <span>{t("↑↓ gez")}</span><span>{t("↵ git")}</span><span>{t("Esc kapat")}</span>
        </div>
      </div>
    </div>
  );
}
