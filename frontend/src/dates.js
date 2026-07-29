// Tarih yardımcıları — TEK KAYNAK.
//
// Bunlar daha önce LeavesPanel, HrDashboard ve AdminPanel'de birebir kopyalanmıştı.
// Kopyaların hepsi UTC'ye çevirmeden yerel tarih üretiyordu; bu bilinçli bir
// karar (izin günü "kullanıcının takvimindeki gün"dür, UTC'ye kaydırılırsa
// GMT+3'te gece yarısından sonra bir gün geriye kayar). Kural tek yerde dursun
// ki bir düzeltme hepsini kapsasın.

export function pad(n) {
  return String(n).padStart(2, "0");
}

/** Date → "YYYY-MM-DD" (yerel; TZ kaydırması YOK). */
export function ymd(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Date → "YYYY-MM" (yerel). */
export function monthKey(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
}

/** Bugünün yerel tarihi, "YYYY-MM-DD". */
export function todayIso() {
  return ymd(new Date());
}
