import "@testing-library/jest-dom/vitest";
import { createElement } from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { LangProvider } from "../i18n.jsx";

// Her test taze DOM + taze oturum + taze mock'larla başlasın.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  // Seçili dil React state'inin YANINDA modül seviyesinde de tutulur (api.js
  // her isteğe `Accept-Language` koyar ve React ağacının dışındadır). Bu kopya
  // cleanup ile sıfırlanmaz, yani İngilizceye geçen bir test SONRAKİNE
  // İngilizce bir arayüz bırakır — sağlayıcısız render edilen bir bileşen
  // (ör. tek başına TopBar) beklenmedik dilde çıkar. Taze bir sağlayıcı mount
  // etmek modül kopyasını varsayılana döndürür: testler sıraya bağlı kalmasın.
  render(createElement(LangProvider));
  cleanup();
});

// jsdom window.confirm'i uygulamaz (Not implemented hatası basar). Silme
// akışları onay soruyor; varsayılan "onayla" ile testler akışı sürdürebilsin.
beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
