import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Her test taze DOM + taze oturum + taze mock'larla başlasın.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

// jsdom window.confirm'i uygulamaz (Not implemented hatası basar). Silme
// akışları onay soruyor; varsayılan "onayla" ile testler akışı sürdürebilsin.
beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
