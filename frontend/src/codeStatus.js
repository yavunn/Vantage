// AI kod analizi: sunucunun DURUM KODUNU kullanıcıya dönük mesaja çevirir.
//
// Sunucunun ham `note` alanı geliştiriciye bakar (config/DB alan adları) ve
// arayüzde gösterilmez: kullanıcı ne olduğunu ve ne yapacağını okumalı, bir
// alan adını değil. Aynı çeviri hem "Kodum" (kişi) hem "AI Kod Analizi"
// (yönetici) panelinde kullanılır; ikisi ayrı ayrı yazıldığında biri
// düzeltilirken öteki ham not göstermeye devam ediyordu.
//
// `error` istisna: sunucu orada zaten kullanıcıya dönük NET bir sebep üretir
// (bakiye yetersiz, anahtar geçersiz, hız limiti) — onu göstermek en yararlısı
// ve durumu istemcide tahmin etmek mümkün değil.
//
// Tanınmayan durumda mesaj GENEL kalır; ham yanıtı (JSON.stringify) ekrana
// dökmek iç veriyi sızdırıyordu.
//
// `yonetici: true` → başkasının kodunu analiz eden yöneticiye, düzeltmeyi
// nerede yapacağını söyleyen karşılık.
export function durumMesaji(t, r, { yonetici = false } = {}) {
  const k = (ad) => (yonetici ? t(`code.admin.${ad}`) : t(`code.${ad}`));
  switch (r?.status) {
    case "ok":
      return {
        sev: "ok",
        text: t("Analiz tamam: {n} yeni, {c} önbellek.", { n: r.analyzed ?? 0, c: r.cached ?? 0 }),
      };
    case "no_identity":
      return { sev: "warn", text: k("noIdentity") };
    case "disabled":
      return { sev: "warn", text: k("disabled") };
    case "no_source":
      return { sev: "warn", text: k("noSource") };
    case "error":
      return { sev: "error", text: r.note || t("code.failed") };
    default:
      return { sev: "warn", text: t("code.failed") };
  }
}
