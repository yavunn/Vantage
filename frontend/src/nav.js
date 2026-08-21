// Gezinme durumu ve tema — saf yardımcılar (React'e bağlı değil, test edilebilir).
//
// App.jsx'ten çıkarıldı: bunlar bileşen değil, kalıcılık kuralları. Aynı
// dosyada durdukları için App her gezinme değişikliğinde tekrar okunuyordu.

export const RANGE_OPTIONS = [7, 30, 90];

const TAB_KEY = "vantage_tab";
const TEAM_KEY = "vantage_team";
const RANGE_KEY = "vantage_range";

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else delete root.dataset.theme;
}

/**
 * Gezinme durumunu oku. URL hash (paylaşılabilir/yer imi) ÖNCELİKLİ, yoksa
 * localStorage (reload'da kaldığın yer). Biçim: #tab=team&team=1&range=30
 * Geçersiz range değerleri sessizce 30'a düşer — bozuk bir yer imi ekranı
 * boş bırakmasın.
 */
export function readNav() {
  const h = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  const ls = (k) => localStorage.getItem(k) || undefined;
  const rangeRaw = h.get("range") || ls(RANGE_KEY);
  const teamRaw = h.get("team") || ls(TEAM_KEY);
  const tabRaw = h.get("tab") || ls(TAB_KEY);
  return {
    tab: tabRaw || "team",
    // Sekmeyi kullanıcı mı belirledi (yer imi / son kaldığı yer), yoksa
    // varsayılana mı düşüldü? Rol bazlı açılış ekranı yalnızca ikinci
    // durumda devreye girer — kimsenin seçimi ezilmez.
    tabExplicit: tabRaw != null,
    range: RANGE_OPTIONS.includes(Number(rangeRaw)) ? Number(rangeRaw) : 30,
    team: teamRaw != null ? Number(teamRaw) : null,
  };
}

/** Durumu hem localStorage'a hem URL hash'ine yazar (geçmişi kirletmeden). */
export function writeNav({ tab, team, range }) {
  if (tab) localStorage.setItem(TAB_KEY, tab);
  if (team != null) localStorage.setItem(TEAM_KEY, String(team));
  if (range) localStorage.setItem(RANGE_KEY, String(range));
  const p = new URLSearchParams();
  if (tab) p.set("tab", tab);
  if (team != null) p.set("team", String(team));
  if (range) p.set("range", String(range));
  const next = "#" + p.toString();
  if (location.hash !== next) history.replaceState(null, "", next);
}
