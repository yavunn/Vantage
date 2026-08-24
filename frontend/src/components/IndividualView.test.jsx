/**
 * Bireysel görünümün GERİ BİLDİRİM hâlleri: yükleniyor / erişim yok / dolu.
 *
 * Kusur: ekran veri gelene kadar tek satırlık "Yükleniyor…" yazısıydı; ilk
 * bakışta boş sayfa gibi duruyordu. 403 mesajı da ham sunucu metnini
 * gösteriyordu ("Bu görünümü yalnızca…"), kullanıcıya ne yapacağını söylemiyordu.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import IndividualView from "./IndividualView.jsx";
import { LangProvider } from "../i18n.jsx";

function yanit({ ok = true, status = 200, body = {} } = {}) {
  return { ok, status, json: async () => body };
}

const OZET = {
  developer: { id: 1, display_name: "Ali" },
  window_days: 30,
  overall: { score: 7.2, label: "İyi durumda", covered: 3, total: 4, breakdown: [], note: "not" },
  commit_alignment: null,
  metrics: [],
  note: "Bu görünüm yalnızca sizin erişiminize açıktır.",
};

beforeEach(() => {
  localStorage.setItem("vantage_token", "tok");
});

function ciz() {
  return render(<LangProvider><IndividualView devId={1} /></LangProvider>);
}

describe("bireysel görünüm durumları", () => {
  it("veri gelmeden önce iskelet gösterir, boş sayfa değil", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));  // hiç çözülmeyen istek
    const { container } = ciz();

    const iskelet = container.querySelector(".indiv-skeleton");
    expect(iskelet).toBeInTheDocument();
    expect(iskelet).toHaveAttribute("aria-busy", "true");
    expect(container.querySelectorAll(".card.skeleton").length).toBeGreaterThan(0);
  });

  it("erişim yoksa sebebi insan diliyle söyler", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => yanit({ ok: false, status: 403, body: { detail: "yasak" } })));
    ciz();

    const uyari = await screen.findByRole("alert");
    expect(uyari).toHaveTextContent("yalnızca kişinin kendisi ve yöneticisi");
  });

  it("veri gelince blok başlıkları ikinci seviyeden başlar", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      if (String(url).includes("task-links")) return yanit({ body: { tasks: [] } });
      return yanit({ body: OZET });
    }));
    ciz();

    expect(await screen.findByText("İyi durumda")).toBeInTheDocument();
    // Sayfa başlığı <h1> (App.jsx); blokların <h3> ile başlaması seviye atlıyordu.
    expect(screen.queryAllByRole("heading", { level: 3 })).toHaveLength(0);
  });
});
