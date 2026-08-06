/**
 * Kabuk gezinmesi — asıl testi ETİK SINIR:
 * İK rolü takım/bireysel performans sekmelerini GÖRMEMELİ. Backend de bu
 * uçlara 403 verir; ikisi birbirinin yedeğidir, ikisi de test edilmeli.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./NotificationBell.jsx", () => ({
  default: () => <div data-testid="bell" />,
}));

import TopBar from "./TopBar.jsx";

const TEAMS = [{ id: 1, name: "Billing" }, { id: 2, name: "CRM" }];

function ciz(props = {}) {
  const varsayilan = {
    user: { display_name: "Ali Veli" },
    isAdmin: false,
    isHr: false,
    tab: "team",
    onTab: vi.fn(),
    teams: TEAMS,
    teamId: 1,
    onTeam: vi.fn(),
    individualAvailable: true,
    surveyRespondent: true,
    surveyPending: false,
    anonymized: false,
    themeLabel: "Oto",
    onCycleTheme: vi.fn(),
    onOpenPalette: vi.fn(),
    onLogout: vi.fn(),
  };
  const p = { ...varsayilan, ...props };
  render(<TopBar {...p} />);
  return p;
}

function sekmeAdlari() {
  const nav = screen.getByRole("navigation", { name: "Ana gezinme" });
  return within(nav).getAllByRole("button").map((b) => b.textContent.trim());
}

describe("rol bazlı sekme kümesi", () => {
  it("İK'ya performans sekmeleri gösterilmez", () => {
    ciz({ isHr: true });
    const sekmeler = sekmeAdlari();
    expect(sekmeler).toEqual([
      "İK Panosu", "İzinler", "Evraklar", "Hesaplar", "Anket", "Ayarlar",
    ]);
    // Etik sınır: bunların HİÇBİRİ görünmemeli.
    expect(sekmeler).not.toContain("Takım görünümü");
    expect(sekmeler).not.toContain("Bireysel görünüm");
    expect(sekmeler).not.toContain("Yönetici paneli");
  });

  it("düz çalışana yönetici paneli gösterilmez", () => {
    ciz();
    expect(sekmeAdlari()).not.toContain("Yönetici paneli");
  });

  it("yöneticiye yönetici paneli gösterilir", () => {
    ciz({ isAdmin: true });
    expect(sekmeAdlari()).toContain("Yönetici paneli");
  });

  it("bireysel görünüm kapalıysa sekme hiç çizilmez", () => {
    ciz({ individualAvailable: false });
    expect(sekmeAdlari()).not.toContain("Bireysel görünüm");
  });

  it("anket katılımcısı değilse anket sekmesi yok", () => {
    ciz({ surveyRespondent: false });
    expect(sekmeAdlari()).not.toContain("Anket");
  });
});

describe("bağlam ve eylemler", () => {
  it("takım seçici YALNIZ takım sekmesinde görünür", () => {
    ciz({ tab: "team" });
    expect(screen.getByLabelText("Takım seç")).toBeInTheDocument();
  });

  it("başka sekmedeyken takım seçici gizlenir", () => {
    ciz({ tab: "settings" });
    expect(screen.queryByLabelText("Takım seç")).not.toBeInTheDocument();
  });

  it("sekmeye tıklayınca onTab çağrılır", async () => {
    const user = userEvent.setup();
    const p = ciz({ isAdmin: true });
    await user.click(screen.getByRole("button", { name: "Yönetici paneli" }));
    expect(p.onTab).toHaveBeenCalledWith("admin");
  });

  it("takım değişince onTeam sayıyla çağrılır (string değil)", async () => {
    const user = userEvent.setup();
    const p = ciz({ tab: "team" });
    await user.selectOptions(screen.getByLabelText("Takım seç"), "2");
    expect(p.onTeam).toHaveBeenCalledWith(2);
  });

  it("anonim mod açıkken alt açıklamada belirtilir", () => {
    ciz({ anonymized: true });
    expect(screen.getByText(/Anonim mod açık/)).toBeInTheDocument();
  });

  it("rol rozetleri yalnız ilgili rolde çıkar", () => {
    ciz({ isHr: true });
    expect(screen.getByText("İK")).toBeInTheDocument();
    expect(screen.queryByText("admin")).not.toBeInTheDocument();
  });
});
