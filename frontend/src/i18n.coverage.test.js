/**
 * Çeviri KAPSAMI: kaynakta `t("...")` ile sarılan her Türkçe metnin İngilizce
 * karşılığı var mı?
 *
 * NEDEN AYRI BİR TEST: eksik çeviri sessizce Türkçeye düşer — bu i18n.jsx'in
 * bilinçli tasarımı (boş kutu göstermekten iyidir). Ama aynı sessizlik, yeni
 * eklenen bir metnin sözlüğe yazılmadığını da gizler: İngilizce arayüzde
 * Türkçe bir cümle belirir ve kimse fark etmez. Bu testin tek işi o sessizliği
 * bozmak.
 *
 * YÖNTEM: kaynak dosyalar DİSKTEN okunur (import edilmez) — denetlenen şey
 * çalışma zamanı davranışı değil, kaynak metinle sözlüğün eşleşmesi. Bir
 * anahtar "çevrilmemiş" sayılır: EN çıktısı TR çıktısıyla AYNI ve metin
 * Türkçe. `t(DEĞİŞKEN)` biçimindeki çalışma zamanı anahtarları (durum/tür
 * etiketi sözlükleri) statik olarak çözülemez, atlanır.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { translate } from "./i18n.jsx";

const SRC = path.dirname(fileURLToPath(import.meta.url));

// Türkçe'ye özgü harf yoksa da Türkçe olabilir ("E-posta ve parola").
const TR_KELIME = /(^|[^a-zçğıöşü])(ve|ile|bir|bu|için|yok|var|tüm|gün|kişi|takım|veri|değer|durum|hata|göster|kaydet|sil|ekle|seç|yükle|gönder|ayar|kayıt|sayfa|adet|toplam)([^a-zçğıöşü]|$)/i;
const TR_HARF = /[çğıöşüÇĞİÖŞÜ]/;

// Bilerek çevrilmeyen anahtarlar: metin ZATEN İngilizce ya da bir marka/terim.
// Listeye satır eklemek bilinçli bir karar olmalı — girmeyen her Türkçe metin
// testi düşürür.
const BILEREK_CEVRILMEDI = new Set([
  "Composite",            // skor adının kendisi, iki dilde de aynı
  "Contents: Read-only",  // GitHub izin adı — arayüzde birebir böyle geçer
  "Incident",             // anotasyon türü; TR arayüzde de "Incident"
]);

function kaynakDosyalari(dir = SRC) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...kaynakDosyalari(p));
    else if (/\.(jsx|js)$/.test(e.name) && !/\.test\./.test(e.name)
             && !["i18n-en.js", "i18n.jsx"].includes(e.name)) out.push(p);
  }
  return out;
}

// Yorumdaki örnek `t("...")` gerçek bir çağrı değildir.
function yorumsuz(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

// t( çağrısının İLK argümanı: bitişik dize birleştirmesi ("a" + "b"), kaçışlı
// tırnak ve \n gibi kaçışlar dahil. Dize değilse null (çalışma zamanı anahtarı).
const KACIS = { n: "\n", t: "\t", r: "\r" };

function ilkArguman(src, i) {
  const parcalar = [];
  for (;;) {
    while (i < src.length && /\s/.test(src[i])) i += 1;
    const tirnak = src[i];
    if (tirnak !== '"' && tirnak !== "'") return parcalar.length ? parcalar.join("") : null;
    i += 1;
    let buf = "";
    while (i < src.length) {
      if (src[i] === "\\") {
        const k = src[i + 1];
        buf += KACIS[k] ?? k;
        i += 2;
        continue;
      }
      if (src[i] === tirnak) { i += 1; break; }
      buf += src[i];
      i += 1;
    }
    parcalar.push(buf);
    while (i < src.length && /\s/.test(src[i])) i += 1;
    if (src[i] !== "+") return parcalar.join("");
    i += 1;
  }
}

function anahtarlar(src) {
  const out = [];
  const re = /(^|[^A-Za-z0-9_$.])t\(/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    const k = ilkArguman(src, m.index + m[0].length);
    if (k) out.push(k);
  }
  return out;
}

function turkceMi(metin) {
  return TR_HARF.test(metin) || TR_KELIME.test(metin);
}

describe("çeviri kapsamı", () => {
  const dosyalar = kaynakDosyalari();

  it("kaynak taraması çalışıyor (kendi kendini doğrular)", () => {
    expect(dosyalar.length).toBeGreaterThan(20);
    expect(anahtarlar('t("Kaydet")')).toEqual(["Kaydet"]);
    // Bitişik birleştirme TEK anahtar olarak çözülmeli — yarısını anahtar
    // sanmak uydurma "eksik çeviri" raporlardı.
    expect(anahtarlar('t("ilk " +\n  "ikinci")')).toEqual(["ilk ikinci"]);
    expect(anahtarlar('t("kaçışlı \\"tırnak\\" var")')).toEqual(['kaçışlı "tırnak" var']);
    // Kaçışlar gerçek karakterine çözülmeli: "\\n" iki harf olarak kalsaydı
    // anahtar sözlüktekiyle eşleşmez ve uydurma bir eksik raporlanırdı.
    expect(anahtarlar('t("iki\\nsatır")')).toEqual(["iki\nsatır"]);
    expect(anahtarlar(yorumsuz('// t("yorumdaki")\nt("gerçek")'))).toEqual(["gerçek"]);
    // Değişkenli çağrı statik olarak çözülemez, sessizce atlanır.
    expect(anahtarlar("t(LABEL[x])")).toEqual([]);
    // Heuristiğin kendisi de sınanır: özel harf yoksa da Türkçe yakalanmalı.
    expect(turkceMi("E-posta ve parola")).toBe(true);
    expect(turkceMi("Composite")).toBe(false);
  });

  it("İngilizce karşılığı olmayan Türkçe metin yok", () => {
    const eksik = [];
    for (const dosya of dosyalar) {
      const src = yorumsuz(fs.readFileSync(dosya, "utf8"));
      for (const k of anahtarlar(src)) {
        if (BILEREK_CEVRILMEDI.has(k)) continue;
        if (/\.(jsx|js)$/.test(k)) continue;         // lazy import yolu
        const tr = translate("tr", k);
        const en = translate("en", k);
        if (en === tr && turkceMi(tr)) eksik.push(`${path.basename(dosya)}: ${k}`);
      }
    }
    expect(eksik).toEqual([]);
  });

  it("noktalı anahtar ekranda HAM görünmez (iki dilde de karşılığı var)", () => {
    const eksik = [];
    for (const dosya of dosyalar) {
      const src = yorumsuz(fs.readFileSync(dosya, "utf8"));
      for (const k of anahtarlar(src)) {
        if (!/^[\w.]+$/.test(k) || !k.includes(".")) continue;
        if (/\.(jsx|js)$/.test(k)) continue;
        for (const dil of ["tr", "en"]) {
          if (translate(dil, k) === "") eksik.push(`${path.basename(dosya)} [${dil}]: ${k}`);
        }
      }
    }
    expect(eksik).toEqual([]);
  });
});
