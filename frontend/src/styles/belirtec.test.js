/**
 * Tasarım sisteminin iki kuralı, testle korunur:
 *
 *  1. HAM RENK yalnız belirteç dosyasında bulunur. Dağılmış hex/rgba, temayı
 *     kısmen değiştirilebilir kılar: Adım 0'da marka lacivert yapıldığında
 *     kimlik ekranındaki pembe/mor ışıklar ham rgba oldukları için yerinde
 *     kalmış ve ekran lacivert zeminde pembe gösteriyordu.
 *  2. TANIMSIZ BELİRTEÇ olmaz. `var(--x)` yazıp tanımlamayı unutmak sessizce
 *     çalışır (kural düşer, yedek varsa yedeğe iner) — ekranda fark edilmesi
 *     günler alır.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const DIZIN = import.meta.dirname;
const BELIRTEC_DOSYASI = "00-belirtecler.css";

function dosyalar() {
  return fs.readdirSync(DIZIN).filter((f) => f.endsWith(".css"));
}

function yorumsuz(kaynak) {
  return kaynak.replace(/\/\*[\s\S]*?\*\//g, "");
}

// Maskede renk aslında OPAKLIK anlamına gelir (siyah = tam görünür), bu yüzden
// belirteçlenmez — bilinçli istisna.
const IZINLI = [/mask-image/];

describe("tasarım belirteçleri", () => {
  it("ham renk yalnız belirteç dosyasında", () => {
    const bulgular = [];
    for (const dosya of dosyalar()) {
      if (dosya === BELIRTEC_DOSYASI) continue;
      const satirlar = yorumsuz(fs.readFileSync(path.join(DIZIN, dosya), "utf8")).split("\n");
      // Yazdırma bloğu bilinçli istisna: kâğıt beyaz, mürekkep siyahtır —
      // ekran teması ne olursa olsun. Blok sınırı satır satır izlenir.
      let yazdirma = 0;
      satirlar.forEach((satir, i) => {
        if (/@media\s+print/.test(satir)) yazdirma = 1;
        if (yazdirma > 0) {
          yazdirma += (satir.match(/{/g) || []).length;
          yazdirma -= (satir.match(/}/g) || []).length;
          if (yazdirma < 0) yazdirma = 0;
          return;
        }
        if (IZINLI.some((k) => k.test(satir))) return;
        const renk = satir.match(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/);
        if (renk) bulgular.push(`${dosya}:${i + 1} ${renk[0]}`);
      });
    }
    expect(bulgular).toEqual([]);
  });

  it("kullanılan her belirteç tanımlı", () => {
    let tanimli = new Set();
    let kullanilan = new Set();
    for (const dosya of dosyalar()) {
      const kaynak = yorumsuz(fs.readFileSync(path.join(DIZIN, dosya), "utf8"));
      for (const m of kaynak.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)) tanimli.add(m[1]);
      for (const m of kaynak.matchAll(/var\((--[a-zA-Z0-9-]+)/g)) kullanilan.add(m[1]);
    }
    const eksik = [...kullanilan].filter((t) => !tanimli.has(t));
    expect(eksik).toEqual([]);
  });

  it("koyu tema ham değer değil, EŞLEME yazar", () => {
    // Koyu blok ham hex tekrar ederse tema iki yerden yönetilmeye başlar.
    const kaynak = yorumsuz(fs.readFileSync(path.join(DIZIN, BELIRTEC_DOSYASI), "utf8"));
    const koyuBloklar = kaynak.split('[data-theme="dark"]').slice(1);
    expect(koyuBloklar.length).toBeGreaterThan(0);
    for (const blok of koyuBloklar) {
      const govde = blok.slice(blok.indexOf("{"), blok.indexOf("}"));
      expect(govde).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    }
  });

  it("tipografi ölçeği: ham punto yalnız bilinçli istisnalarda", () => {
    // 25 farklı font-size vardı (8.5px, 9.5px, 11.5px, 12.5px, 13.5px…) —
    // altı adımlık belirteç ölçeğinin altında ad-hoc bir ölçek duruyordu.
    // Kalan iki istisna: sabit ölçülü daire içindeki işaretler (avatar baş
    // harfi, soru numarası) — orada punto kutunun ölçüsüne bağlıdır.
    const bulgular = [];
    for (const dosya of dosyalar()) {
      if (dosya === BELIRTEC_DOSYASI) continue;
      const satirlar = yorumsuz(fs.readFileSync(path.join(DIZIN, dosya), "utf8")).split("\n");
      satirlar.forEach((satir, i) => {
        if (/\.pp-avatar\.sm|\.survey-q-no/.test(satir)) return;
        const m = satir.match(/font-size:\s*[0-9.]+px/);
        if (m) bulgular.push(`${dosya}:${i + 1} ${m[0]}`);
      });
    }
    expect(bulgular).toEqual([]);
  });

  it("tek mobil ve tek tablet eşiği", () => {
    // Altı farklı eşik vardı (560/640/720/760/860/1200): hangi ekranın nerede
    // kırıldığı kestirilemiyordu.
    const esikler = new Set();
    for (const dosya of dosyalar()) {
      const kaynak = yorumsuz(fs.readFileSync(path.join(DIZIN, dosya), "utf8"));
      for (const m of kaynak.matchAll(/@media\s*\(max-width:\s*(\d+)px\)/g)) esikler.add(m[1]);
    }
    expect([...esikler].sort()).toEqual(["1024", "640"]);
  });
});
