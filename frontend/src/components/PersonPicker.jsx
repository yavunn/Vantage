import { useEffect, useMemo, useRef, useState } from "react";

// Aranabilir kişi seçici (combobox) + son bakılanlar.
// İK akışında en sık işlem "kişiye bak" — düz <select> uzun listede yavaş.
// Klavye: ok tuşları gez, Enter seç, Esc kapat.
const RECENT_KEY = "nabiz_recent_devs";
const RECENT_MAX = 5;

function readRecent() {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY));
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function pushRecent(devId) {
  if (devId == null) return;
  const cur = readRecent().filter((id) => id !== devId);
  cur.unshift(devId);
  localStorage.setItem(RECENT_KEY, JSON.stringify(cur.slice(0, RECENT_MAX)));
}

export default function PersonPicker({ people, value, onChange, selfDevId }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  const selected = people.find((p) => p.id === value) || null;
  const recentIds = readRecent().filter((id) => people.some((p) => p.id === id));

  const matches = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("tr");
    if (!q) {
      // Arama yokken: kendisi + son bakılanlar önce, sonra alfabetik kalanlar.
      const priority = [];
      if (selfDevId != null) {
        const me = people.find((p) => p.id === selfDevId);
        if (me) priority.push({ ...me, hint: "sen" });
      }
      for (const id of recentIds) {
        if (id === selfDevId) continue;
        const p = people.find((x) => x.id === id);
        if (p) priority.push({ ...p, hint: "son bakılan" });
      }
      const rest = people.filter((p) => !priority.some((x) => x.id === p.id));
      return [...priority, ...rest];
    }
    return people.filter((p) => p.display_name.toLocaleLowerCase("tr").includes(q));
  }, [people, query, selfDevId, open]);

  useEffect(() => { setCursor(0); }, [query, open]);

  useEffect(() => {
    function onDoc(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus();
  }, [open]);

  function pick(p) {
    pushRecent(p.id);
    onChange(p.id);
    setOpen(false);
    setQuery("");
  }

  function onKey(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (matches[cursor]) pick(matches[cursor]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="person-picker" ref={boxRef}>
      <button
        type="button"
        className="pp-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="pp-avatar" aria-hidden="true">
          {(selected?.display_name || "?").slice(0, 1).toLocaleUpperCase("tr")}
        </span>
        <span className="pp-name">{selected ? selected.display_name : "Kişi seç…"}</span>
        <span className="pp-caret" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="pp-panel">
          <input
            ref={inputRef}
            className="pp-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKey}
            placeholder="İsimle ara…"
            aria-label="Kişi ara"
          />
          {matches.length === 0 ? (
            <p className="desc pp-empty">Eşleşen kişi yok.</p>
          ) : (
            <ul className="pp-list" role="listbox">
              {matches.map((p, i) => (
                <li key={p.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={p.id === value}
                    className={`pp-item ${i === cursor ? "cursor" : ""} ${p.id === value ? "active" : ""}`}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => pick(p)}
                  >
                    <span className="pp-avatar sm" aria-hidden="true">
                      {p.display_name.slice(0, 1).toLocaleUpperCase("tr")}
                    </span>
                    <span className="pp-item-name">{p.display_name}</span>
                    {p.hint && <span className="pp-hint">{p.hint}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
