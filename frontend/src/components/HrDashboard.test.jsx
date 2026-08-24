/**
 * İK panosunun ısı haritası: yoğunluk okunabilir mi?
 *
 * Kusur: yoğunluk hücrenin OPAKLIĞI ile veriliyordu (0.25–1.0). Opaklık
 * yazıyı da soldurduğu için az izinli günlerde hücredeki rakam neredeyse
 * görünmüyordu. Artık yoğunluk zemin tonuyla veriliyor ve kademe bir veri
 * özniteliğiyle bildiriliyor — yazı rengini CSS tona göre seçiyor.
 */
import { describe, expect, it } from "vitest";

import { yogunlukSeviyesi } from "./HrDashboard.jsx";

describe("ısı haritası yoğunluk kademesi", () => {
  it("izinsiz gün nötr kalır", () => {
    expect(yogunlukSeviyesi(0, 5)).toBe("yok");
  });

  it("kademeler orana göre ayrılır", () => {
    expect(yogunlukSeviyesi(1, 6)).toBe("az");
    expect(yogunlukSeviyesi(3, 6)).toBe("orta");
    expect(yogunlukSeviyesi(6, 6)).toBe("cok");
  });

  it("tek kişilik ay tepeyi doğru işaretler", () => {
    // enYuksek = 1 iken oran 1.0; "az" demek yanıltıcı olurdu.
    expect(yogunlukSeviyesi(1, 1)).toBe("cok");
  });
});
