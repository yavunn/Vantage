/**
 * İzin panosu: takvim ızgarası + yetkiye göre görünürlük.
 *
 * Buradaki iki şey elle test edilemeyecek kadar sık bozulur:
 *  1) Takvim, ay başlangıcının haftanın hangi gününe düştüğünü doğru hesaplamalı
 *     (Pazartesi başlangıç) ve çok günlü izinler ARADAKİ her güne düşmeli.
 *  2) "Takvim işaretleri" bölümü yalnız yönetici/İK'ya görünmeli — düz çalışan
 *     şirket geneli tatil ekleyememeli (backend de 403 verir, UI de göstermez).
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  listLeaves: vi.fn(),
  listAnnotations: vi.fn(),
  myLeaveRequests: vi.fn(),
  leaveSummary: vi.fn(),
  pendingLeaves: vi.fn(),
  listEmployees: vi.fn(),
  createLeave: vi.fn(),
  deleteLeave: vi.fn(),
  decideLeave: vi.fn(),
  createAnnotation: vi.fn(),
  deleteAnnotation: vi.fn(),
}));

import * as apiMod from "../api.js";
import LeavesPanel from "./LeavesPanel.jsx";

const USER = { display_name: "Ali Veli", developer_id: 1 };
const TEAMS = [{ id: 1, name: "Billing" }, { id: 2, name: "CRM" }];

// Testler "bugün"e göre ay hesapladığı için zamanı sabitliyoruz: 15 Nisan 2026.
// (1 Nisan 2026 = Çarşamba → ızgarada iki boş hücreyle başlamalı.)
const SABIT_GUN = new Date(2026, 3, 15);

function ayIso(gun) {
  return `2026-04-${String(gun).padStart(2, "0")}`;
}

function setupApi({ leaves = [], annotations = [], mine = [], pending = [], summary = [] } = {}) {
  apiMod.listLeaves.mockResolvedValue(leaves);
  apiMod.listAnnotations.mockResolvedValue(annotations);
  apiMod.myLeaveRequests.mockResolvedValue(mine);
  apiMod.pendingLeaves.mockResolvedValue(pending);
  apiMod.leaveSummary.mockResolvedValue(summary);
  apiMod.listEmployees.mockResolvedValue([
    { id: 7, display_name: "Ayşe Yılmaz", developer_id: 3 },
  ]);
  apiMod.createAnnotation.mockResolvedValue({ id: 99 });
  apiMod.deleteAnnotation.mockResolvedValue({ ok: true });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(SABIT_GUN);
  vi.clearAllMocks();
});

describe("takvim ızgarası", () => {
  it("çok günlü izni başlangıç ve bitiş ARASINDAKİ her güne yazar", async () => {
    setupApi({
      leaves: [{
        id: 1, person: "Ayşe Yılmaz", leave_type: "annual", status: "approved",
        start_date: ayIso(6), end_date: ayIso(8), can_delete: false,
      }],
    });

    render(<LeavesPanel user={USER} canManage={false} teams={TEAMS} />);

    // 6, 7 ve 8 Nisan'ın üçünde de kişi görünmeli (tek kayıt, üç gün).
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /Ayşe Yılmaz/ })).toHaveLength(3);
    });
  });

  it("onay bekleyen izni beklemede işaretiyle ayırır", async () => {
    setupApi({
      leaves: [{
        id: 2, person: "Ayşe Yılmaz", leave_type: "sick", status: "pending",
        start_date: ayIso(10), end_date: ayIso(10), can_delete: false,
      }],
    });

    render(<LeavesPanel user={USER} canManage={false} teams={TEAMS} />);

    const chip = await screen.findByRole("button", { name: /Ayşe Yılmaz/ });
    expect(chip).toHaveTextContent("⏳");
    expect(chip.title).toMatch(/beklemede/);
  });

  it("aynı güne düşen tatil işaretini izinden ayrı gösterir", async () => {
    setupApi({
      annotations: [{ id: 5, date: ayIso(23), label: "Ulusal Egemenlik", kind: "holiday", team_id: null }],
    });

    render(<LeavesPanel user={USER} canManage={false} teams={TEAMS} />);

    const chip = await screen.findByTitle(/Tatil: Ulusal Egemenlik/);
    expect(chip).toHaveTextContent("Ulusal Egemenlik");
    // Global işaret olduğu bilgisi ipucunda korunmalı.
    expect(chip.title).toMatch(/tüm takımlar/);
  });
});

describe("yetkiye göre görünürlük", () => {
  it("düz çalışana takvim işareti yönetimi GÖSTERİLMEZ", async () => {
    setupApi();
    render(<LeavesPanel user={USER} canManage={false} teams={TEAMS} />);

    await screen.findByText("İzin takvimi");
    expect(screen.queryByText(/Takvim işaretleri/)).not.toBeInTheDocument();
    // Onay kuyruğu ve İK ay özeti de kapalı olmalı.
    expect(screen.queryByText(/Bekleyen izin onayları/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Ay özeti/)).not.toBeInTheDocument();
    // Çalışan izni doğrudan alamaz, ister.
    expect(screen.getByRole("button", { name: "İstek gönder" })).toBeInTheDocument();
  });

  it("yöneticiye gösterilir ve kapsam seçimi takımları listeler", async () => {
    setupApi();
    render(<LeavesPanel user={USER} canManage teams={TEAMS} />);

    await screen.findByText(/Takvim işaretleri/);
    const kapsam = screen.getByLabelText("Kapsam");
    expect(within(kapsam).getByRole("option", { name: "Tüm takımlar" })).toBeInTheDocument();
    expect(within(kapsam).getByRole("option", { name: "Billing" })).toBeInTheDocument();
    expect(within(kapsam).getByRole("option", { name: "CRM" })).toBeInTheDocument();
  });
});

describe("takvim işareti ekleme", () => {
  // "Tür" etiketi ve işaret adı sayfada birden çok yerde geçiyor (izin formu,
  // takvim çipi). Sorguları işaret bölümüne daraltıyoruz.
  async function isaretBolumu() {
    const baslik = await screen.findByText(/Takvim işaretleri/);
    return baslik.closest("section");
  }

  it("kapsam seçilmezse global (team_id: null) gönderir", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    setupApi();
    render(<LeavesPanel user={USER} canManage teams={TEAMS} />);

    const bolum = await isaretBolumu();
    await user.type(within(bolum).getByPlaceholderText(/Etiket/), "Ramazan Bayramı");
    await user.click(within(bolum).getByRole("button", { name: "Ekle" }));

    await waitFor(() => expect(apiMod.createAnnotation).toHaveBeenCalledTimes(1));
    expect(apiMod.createAnnotation.mock.calls[0][0]).toMatchObject({
      label: "Ramazan Bayramı",
      kind: "holiday",
      team_id: null,
    });
  });

  it("takım seçilirse o takımın id'siyle gönderir", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    setupApi();
    render(<LeavesPanel user={USER} canManage teams={TEAMS} />);

    const bolum = await isaretBolumu();
    await user.type(within(bolum).getByPlaceholderText(/Etiket/), "Sürüm 2.0");
    await user.selectOptions(within(bolum).getByLabelText("Tür"), "release");
    await user.selectOptions(within(bolum).getByLabelText("Kapsam"), "2");
    await user.click(within(bolum).getByRole("button", { name: "Ekle" }));

    await waitFor(() => expect(apiMod.createAnnotation).toHaveBeenCalledTimes(1));
    expect(apiMod.createAnnotation.mock.calls[0][0]).toMatchObject({
      label: "Sürüm 2.0", kind: "release", team_id: 2,
    });
  });

  it("listede yalnız GÖRÜNEN ayın işaretleri sayılır", async () => {
    setupApi({
      annotations: [
        { id: 1, date: ayIso(3), label: "Nisan işareti", kind: "other", team_id: null },
        { id: 2, date: "2026-05-03", label: "Mayıs işareti", kind: "other", team_id: null },
      ],
    });

    render(<LeavesPanel user={USER} canManage teams={TEAMS} />);

    // Başlıktaki sayaç yalnız Nisan'ı saymalı.
    expect(await screen.findByText("Takvim işaretleri (1)")).toBeInTheDocument();
    const bolum = await isaretBolumu();
    expect(within(bolum).getByText("Nisan işareti")).toBeInTheDocument();
    // Mayıs işareti ne listede ne takvimde görünmeli (görünen ay Nisan).
    expect(screen.queryByText("Mayıs işareti")).not.toBeInTheDocument();
  });
});
