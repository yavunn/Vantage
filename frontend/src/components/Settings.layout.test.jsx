/**
 * Kenar çubuğu kalıbı TEK yerde tanımlı mı?
 *
 * Yönetici paneli ve Ayarlar aynı düzeni kullanıyor ama kural seti iki kez
 * yazılmıştı (.admin-panel ... ve .side-panel ...) — birinde yapılan düzeltme
 * ötekine geçmiyordu. Kalıp tekilleştirildi; bu test geri kaymayı yakalar.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const stilDizini = path.join(import.meta.dirname, "..", "styles");

function tumCss() {
  return fs.readdirSync(stilDizini)
    .filter((f) => f.endsWith(".css"))
    .map((f) => fs.readFileSync(path.join(stilDizini, f), "utf8"))
    .join("\n")
    .replace(/\/\*[\s\S]*?\*\//g, "");   // yorumlar sayılmasın
}

describe("kenar çubuğu kalıbı", () => {
  it("kural seti yalnız bir seçici ailesinde tanımlı", () => {
    const css = tumCss();
    expect(css).toContain(".side-panel .subtabs");
    expect(css).not.toContain(".admin-panel .subtabs");
  });

  it("yapışkan konum sihirli sayı değil, adlandırılmış bir belirteç", () => {
    // 96px'lik ham değer üst çubuğun yüksekliğine elle uydurulmuştu; üst çubuk
    // değişince sessizce yanlış hizalanıyordu.
    const css = tumCss();
    const kural = css.slice(css.indexOf(".side-panel .subtabs {"));
    expect(kural.slice(0, kural.indexOf("}"))).toContain("var(--shell-offset)");
  });
});
