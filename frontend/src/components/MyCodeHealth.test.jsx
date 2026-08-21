/**
 * "Kodum — AI kod sağlığı" bölümünün durum mesajları.
 *
 * İki gerçek kusuru kollar:
 * 1. "Veri eksik" durumları YEŞİL başarı kutusunda çıkıyordu (`ok-inline`).
 *    Şiddet hesaplanıyordu ama yalnız toast'a gidiyordu; kutunun sınıfı
 *    sabitti. Kullanıcı, analizin başarıyla bittiğini sanıyordu.
 * 2. Tanınmayan bir durumda `JSON.stringify(r)` ile ham yanıt ekrana
 *    dökülüyordu; bilinen durumlarda da sunucunun geliştirici notu
 *    ("developer.external_ids['git']") kullanıcıya gösteriliyordu.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  api: vi.fn(() => Promise.resolve(null)),
  apiPost: vi.fn(),
}));

import * as apiMod from "../api.js";
import MyCodeHealth from "./MyCodeHealth.jsx";
import { LangProvider } from "../i18n.jsx";

const USER = { developer_id: 7 };

function ekranaBas() {
  return render(
    <LangProvider>
      <MyCodeHealth user={USER} />
    </LangProvider>,
  );
}

async function analizEt(yanit) {
  apiMod.apiPost.mockResolvedValue(yanit);
  const user = userEvent.setup();
  ekranaBas();
  await user.click(screen.getByRole("button", { name: "Kodumu analiz et" }));
  return await waitFor(() => {
    const p = document.querySelector(".ok-inline, .warn-inline, .error-inline");
    expect(p).not.toBeNull();
    return p;
  });
}

describe("Kodum — analiz durum mesajı", () => {
  it("git kimliği yoksa UYARI kutusu çıkar, başarı kutusu değil", async () => {
    const kutu = await analizEt({
      status: "no_identity",
      analyzed: 0,
      note: "Bu kişinin git e-postası tanımlı değil (developer.external_ids['git']). "
          + "Atıf yapılamaz — veri kaynağı gerekli.",
    });
    expect(kutu.className).toBe("warn-inline");
    // Sunucunun geliştirici notu kullanıcıya gösterilmez.
    expect(kutu.textContent).not.toMatch(/external_ids/);
    expect(kutu.textContent).toMatch(/Kaynak kimliklerim/);
  });

  it("başarıda yeşil kutu korunur", async () => {
    const kutu = await analizEt({ status: "ok", analyzed: 3, cached: 1 });
    expect(kutu.className).toBe("ok-inline");
    expect(kutu.textContent).toMatch(/3/);
  });

  it("hatada kırmızı kutu ve sunucunun NET sebebi gösterilir", async () => {
    const kutu = await analizEt({
      status: "error", analyzed: 0,
      note: "AI hız limiti/aşırı yük — biraz sonra tekrar dene.",
    });
    expect(kutu.className).toBe("error-inline");
    expect(kutu.textContent).toMatch(/hız limiti/);
  });

  it("tanınmayan durumda ham JSON dökülmez", async () => {
    const kutu = await analizEt({ status: "beklenmedik_durum", analyzed: 0, gizli: "iç veri" });
    expect(kutu.className).toBe("warn-inline");
    expect(kutu.textContent).not.toMatch(/beklenmedik_durum|gizli|\{/);
  });
});
