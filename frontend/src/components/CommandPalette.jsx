import { useEffect, useMemo, useRef, useState } from "react";

// Global hızlı arama (Ctrl+K / Cmd+K): sekme, takım ve kişi tek kutudan.
// İK akışında en büyük hızlandırıcı — "kişiye bak" 1 tuş + 2 harf.
export default function CommandPalette({ open, onClose, tabs, teams, people, onGoTab, onGoTeam, onGoPerson }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);

  const items = useMemo(() => {
    const all = [
      ...tabs.map((t) => ({ kind: "Sekme", label: t.label, run: () => onGoTab(t.key) })),
      ...teams.map((t) => ({ kind: "Takım", label: t.name, run: () => onGoTeam(t.id) })),
      ...people.map((p) => ({ kind: "Kişi", label: p.display_name, run: () => onGoPerson(p.id) })),
    ];
    const q = query.trim().toLocaleLowerCase("tr");
    if (!q) return all.slice(0, 12);
    return all.filter((i) => i.label.toLocaleLowerCase("tr").includes(q)).slice(0, 20);
  }, [query, tabs, teams, people, onGoTab, onGoTeam, onGoPerson]);

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
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="Hızlı arama" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmdk-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKey}
          placeholder="Sekme, takım veya kişi ara…"
          aria-label="Hızlı arama"
        />
        {items.length === 0 ? (
          <p className="desc cmdk-empty">Sonuç yok.</p>
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
          <span>↑↓ gez</span><span>↵ git</span><span>Esc kapat</span>
        </div>
      </div>
    </div>
  );
}
