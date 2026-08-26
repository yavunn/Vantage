/**
 * Yönetici "AI Kod Analizi" panelinin durum mesajları.
 *
 * Kollanan kusur: kişi bazlı analizde sunucunun GELİŞTİRİCİ notu
 * ("developer.external_ids['git']") ekrana basılıyordu; tanınmayan durumda ise
 * `JSON.stringify(r)` ile ham yanıt dökülüyordu. Ayrıca kutu her zaman yeşil
 * "ok-inline" olduğu için uyarılar başarı gibi görünüyordu.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const CFG = {
  llm_provider: "local", model: "qwen2.5:14b",
  weights: {}, max_files_per_run: 10, max_diff_lines: 400,
};
const DEVS = [{ id: 7, display_name: "Ayşe", git_email: null, composite: null,
                analyzed_files: 0, analyzable: true }];

vi.mock("../api.js", () => ({
  api: vi.fn((url) => {
    if (url.startsWith("/api/admin/code-analysis/developers")) return Promise.resolve(DEVS);
    if (url.startsWith("/api/admin/code-analysis/audit")) return Promise.resolve([]);
    if (url.startsWith("/api/admin/code-analysis/overview")) return Promise.resolve(null);
    if (url === "/api/admin/code-analysis") return Promise.resolve(CFG);
    return Promise.resolve(null);
  }),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  getLlmProvider: vi.fn(() => Promise.resolve(null)),
  updateLlmProvider: vi.fn(),
}));

import * as apiMod from "../api.js";
import CodeAnalysisPanel from "./CodeAnalysisPanel.jsx";
import { LangProvider } from "../i18n.jsx";

async function kisiyiAnalizEt(yanit) {
  apiMod.apiPost.mockResolvedValue(yanit);
  const user = userEvent.setup();
  render(
    <LangProvider>
      <CodeAnalysisPanel me={{ is_owner: false }} />
    </LangProvider>,
  );
  const secim = await screen.findByLabelText("Kişi seç");
  await user.selectOptions(secim, "7");
  await user.click(await screen.findByRole("button", { name: "Bu kişiyi analiz et" }));
  return await waitFor(() => {
    const p = document.querySelector(".ok-inline, .warn-inline, .error-inline");
    expect(p).not.toBeNull();
    return p;
  });
}

describe("AI Kod Analizi — kişi bazlı analiz durum mesajı", () => {
  it("git kimliği yoksa uyarı kutusu çıkar ve sunucunun ham notu gösterilmez", async () => {
    const kutu = await kisiyiAnalizEt({
      status: "no_identity",
      analyzed: 0,
      note: "Bu kişinin git commit e-postası bağlı değil (developer.external_ids['git']).",
    });
    expect(kutu.className).toBe("warn-inline");
    expect(kutu.textContent).not.toMatch(/external_ids/);
    expect(kutu.textContent).toMatch(/Ayşe/);
    // Yönetici düzeltmeyi kendi panelinde yapar: "yöneticinize başvurun" değil.
    expect(kutu.textContent).toMatch(/Tüm kişiler/);
  });

  it("başarıda yeşil kutu ve sayılar", async () => {
    const kutu = await kisiyiAnalizEt({ status: "ok", analyzed: 3, cached: 1 });
    expect(kutu.className).toBe("ok-inline");
    expect(kutu.textContent).toMatch(/3/);
  });

  it("tanınmayan durumda ham JSON dökülmez", async () => {
    const kutu = await kisiyiAnalizEt({ status: "beklenmedik", analyzed: 0, gizli: "iç veri" });
    expect(kutu.className).toBe("warn-inline");
    expect(kutu.textContent).not.toMatch(/beklenmedik|gizli|\{/);
  });
});
