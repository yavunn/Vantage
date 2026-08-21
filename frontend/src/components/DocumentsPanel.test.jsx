/**
 * Evrak panosu: form türe göre şekil değiştirmeli, İK bölümleri çalışana kapalı.
 *
 * Buradaki iki şey elle test edilemeyecek kadar sık bozulur:
 *  1) Zorunlu alanlar KATALOGDAN gelir. "İstirahat raporu" tarih ister,
 *     "İcra kesintisi" dönem ister, "İş sözleşmesi" ikisini de istemez. Katalog
 *     sunucudan geldiği için bu mantık koda gömülemez — bayrağa bakmalı.
 *  2) İK'ya özel bölümler (eksik evrak tablosu, dönem özeti, kimin adına
 *     yükleme) düz çalışana ÇİZİLMEMELİ. Sunucu da 403 verir; ikisi birbirinin
 *     yedeğidir, ikisi de test edilmeli.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  documentTypes: vi.fn(),
  listDocuments: vi.fn(),
  myDocumentSummary: vi.fn(),
  documentChecklist: vi.fn(),
  documentSummary: vi.fn(),
  listEmployees: vi.fn(),
  uploadDocument: vi.fn(),
  decideDocument: vi.fn(),
  deleteDocument: vi.fn(),
  downloadDocument: vi.fn(),
  leavesByUser: vi.fn(),
  myLeaveRequests: vi.fn(),
}));

import * as apiMod from "../api.js";
import DocumentsPanel from "./DocumentsPanel.jsx";

const TYPES = {
  categories: [
    { key: "leave", label: "İzin / devamsızlık belgeleri" },
    { key: "payroll", label: "Kesinti / kazanç belgeleri" },
    { key: "personnel", label: "Özlük dosyası (işe giriş)" },
  ],
  types: [
    {
      key: "sick_report", label: "İstirahat raporu (iş göremezlik)", category: "leave",
      effect: "İlk 2 gün işveren, sonrası SGK ödeneği.",
      affects_payroll: true, needs_period: true, needs_dates: true, required: false,
    },
    {
      key: "garnishment", label: "İcra / maaş haczi müzekkeresi", category: "payroll",
      effect: "Net ücretin en çok 1/4'ü kesilir.",
      affects_payroll: true, needs_period: true, needs_dates: false, required: false,
    },
    {
      key: "employment_contract", label: "İş sözleşmesi", category: "personnel",
      effect: "Ücret ve görevin yazılı dayanağı.",
      affects_payroll: false, needs_period: false, needs_dates: false, required: true,
    },
  ],
};

const DOC = {
  id: 5, user_id: 1, person: "Ali Veli", doc_type: "sick_report",
  doc_label: "İstirahat raporu (iş göremezlik)", category: "leave",
  affects_payroll: true, period: "2026-08", start_date: "2026-08-03",
  end_date: "2026-08-05", note: null, leave_id: null, file_name: "rapor.pdf",
  size_bytes: 2048, status: "pending", review_note: null, reviewed_at: null,
  uploaded_by_me: true, created_at: "2026-08-03T09:00:00Z", own: true,
  can_delete: true, can_decide: false,
};

function setupApi({ docs = [], mine = null, checklist = null, summary = null, myLeaves = [] } = {}) {
  apiMod.documentTypes.mockResolvedValue(TYPES);
  apiMod.listDocuments.mockResolvedValue(docs);
  apiMod.myDocumentSummary.mockResolvedValue(
    mine ?? { required_total: 3, approved_count: 3, missing: [] }
  );
  apiMod.documentChecklist.mockResolvedValue(
    checklist ?? { required_total: 3, rows: [] }
  );
  apiMod.documentSummary.mockResolvedValue(
    summary ?? { period: "2026-08", total: 0, blocking_payroll: 0, by_type: [] }
  );
  apiMod.listEmployees.mockResolvedValue([
    { id: 7, display_name: "Ayşe Yılmaz", is_active: true },
  ]);
  apiMod.myLeaveRequests.mockResolvedValue(myLeaves);
  apiMod.leavesByUser.mockResolvedValue(myLeaves);
}

const USER = { id: 1, display_name: "Ali Veli" };

beforeEach(() => {
  vi.clearAllMocks();
});

// Evraklar kenar çubuğu kalıbına geçti: bölümler yan yana değil, solda seçilen
// alan sağda tek başına açılıyor. `alan` verilirse render sonrası oraya geçilir
// — testlerin İDDİALARI değişmedi, yalnızca oraya gidiliyor.
async function ciz(props = {}, alan = null) {
  render(<DocumentsPanel user={USER} canManage={false} {...props} />);
  // Katalog yüklenene kadar bekle (tür seçici dolmadan form anlamsız).
  await waitFor(() => expect(screen.getByLabelText(/Belge türü/)).toBeInTheDocument());
  if (alan) fireEvent.click(screen.getByRole("button", { name: alan }));
}

describe("yükleme formu türe göre şekilleniyor", () => {
  it("istirahat raporu tarih + dönem ister", async () => {
    const user = userEvent.setup();
    setupApi();
    await ciz();
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "sick_report");
    expect(screen.getByLabelText(/Bordro dönemi/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Başlangıç/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Bitiş/)).toBeInTheDocument();
  });

  it("izin kategorisi seçilince ilgili izin kaydı seçicisi çıkar", async () => {
    const user = userEvent.setup();
    setupApi();
    await ciz();
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "sick_report");
    expect(screen.getByLabelText(/İlgili izin kaydı/)).toBeInTheDocument();
    // "İzin dışı" bir tür seçiliyken bu alan görünmemeli.
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "garnishment");
    expect(screen.queryByLabelText(/İlgili izin kaydı/)).not.toBeInTheDocument();
  });

  it("var olan izin kaydı seçilince tarihler otomatik dolar ve kilitlenir", async () => {
    const user = userEvent.setup();
    setupApi({
      myLeaves: [{
        id: 41, leave_type: "sick", start_date: "2026-08-10", end_date: "2026-08-12",
        status: "pending", has_document: false,
      }],
    });
    await ciz();
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "sick_report");
    await waitFor(() => expect(apiMod.myLeaveRequests).toHaveBeenCalled());
    await user.selectOptions(screen.getByLabelText(/İlgili izin kaydı/), "41");
    expect(screen.getByLabelText(/Başlangıç/)).toHaveValue("2026-08-10");
    expect(screen.getByLabelText(/Bitiş/)).toHaveValue("2026-08-12");
    expect(screen.getByLabelText(/Başlangıç/)).toBeDisabled();
    expect(screen.getByText(/Tarihler seçilen izin kaydından alınıyor/)).toBeInTheDocument();
  });

  it("İK başkası adına yüklerken o kişinin izinlerini getirir (leavesByUser)", async () => {
    const user = userEvent.setup();
    setupApi({ myLeaves: [] });
    await ciz({ canManage: true });
    await user.selectOptions(screen.getByLabelText(/Kimin adına/), "7");
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "sick_report");
    await waitFor(() => expect(apiMod.leavesByUser).toHaveBeenCalledWith(7));
    expect(apiMod.myLeaveRequests).not.toHaveBeenCalled();
  });

  it("icra yazısı dönem ister ama tarih istemez", async () => {
    const user = userEvent.setup();
    setupApi();
    await ciz();
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "garnishment");
    expect(screen.getByLabelText(/Bordro dönemi/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Başlangıç/)).not.toBeInTheDocument();
  });

  it("iş sözleşmesi ikisini de istemez", async () => {
    const user = userEvent.setup();
    setupApi();
    await ciz();
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "employment_contract");
    expect(screen.queryByLabelText(/Bordro dönemi/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Başlangıç/)).not.toBeInTheDocument();
  });

  it("bordroyu etkileyen tür seçilince uyarı gösterilir", async () => {
    const user = userEvent.setup();
    setupApi();
    await ciz();
    await user.selectOptions(screen.getByLabelText(/Belge türü/), "sick_report");
    // Etiket "Bordroyu etkiler · " olarak ayırıcıyla birlikte basılıyor.
    expect(screen.getByText(/Bordroyu etkiler/)).toBeInTheDocument();
    // Etkisi ne olduğu da yazmalı: kullanıcı neyi neden yüklediğini bilsin.
    expect(screen.getByText(/SGK ödeneği/)).toBeInTheDocument();
  });
});

describe("rol sınırı", () => {
  it("çalışana İK bölümleri çizilmez", async () => {
    setupApi();
    await ciz({ canManage: false });
    expect(screen.queryByText("Dönem özeti")).not.toBeInTheDocument();
    expect(screen.queryByText("Özlük dosyası eksikleri")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Kimin adına/)).not.toBeInTheDocument();
    expect(screen.getByText("Belgelerim")).toBeInTheDocument();
    // Çalışan uçları hiç ÇAĞRILMAMALI (403 üretip konsolu kirletmesin).
    expect(apiMod.documentChecklist).not.toHaveBeenCalled();
    expect(apiMod.documentSummary).not.toHaveBeenCalled();
  });

  it("İK'ya eksik evrak tablosu ve dönem özeti çizilir", async () => {
    setupApi({
      checklist: {
        required_total: 3,
        rows: [{
          user_id: 7, person: "Ayşe Yılmaz", required_total: 3, approved_count: 1,
          missing: [{ key: "employment_contract", label: "İş sözleşmesi" }],
          pending: [],
        }],
      },
      summary: {
        period: "2026-08", total: 2, blocking_payroll: 2,
        by_type: [{
          doc_type: "sick_report", label: "İstirahat raporu (iş göremezlik)",
          affects_payroll: true, total: 2, approved: 0, pending: 2, rejected: 0,
        }],
      },
    });
    await ciz({ canManage: true });
    expect(screen.getByText("Dönem özeti")).toBeInTheDocument();
    expect(screen.getByText("Özlük dosyası eksikleri")).toBeInTheDocument();
    expect(screen.getByText("Tüm belgeler")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dönem özeti" }));
    expect(screen.getByText(/Bordroyu etkileyen 2 belge hâlâ incelenmedi/)).toBeInTheDocument();
    // İsim de tür adı da seçicilerde geçiyor — eksik TABLOSUNDA aranmalı.
    // Kenar çubuğunda aynı metin bir düğme olarak da var; bölüm BAŞLIĞINDAN
    // gidilir, yoksa closest("section") düğmede null döner.
    fireEvent.click(screen.getByRole("button", { name: "Özlük dosyası eksikleri" }));
    const eksikBolum = screen
      .getByRole("heading", { name: "Özlük dosyası eksikleri" })
      .closest("section");
    const eksikSatiri = within(eksikBolum).getByText("Ayşe Yılmaz").closest("tr");
    expect(within(eksikSatiri).getByText(/İş sözleşmesi/)).toBeInTheDocument();
    expect(within(eksikSatiri).getByText("1/3")).toBeInTheDocument();
  });
});

describe("belge listesi", () => {
  it("eksik zorunlu belge uyarısı çalışana gösterilir", async () => {
    setupApi({
      mine: {
        required_total: 3, approved_count: 1,
        missing: [{ key: "id_copy", label: "Kimlik fotokopisi" }],
      },
    });
    await ciz();
    expect(screen.getByText(/Özlük dosyanda 1 zorunlu belge eksik/)).toBeInTheDocument();
    expect(screen.getByText(/Kimlik fotokopisi/)).toBeInTheDocument();
  });

  it("bekleyen belge durumu ve bordro rozetiyle listelenir", async () => {
    setupApi({ docs: [DOC] });
    await ciz({}, "Belgelerim");
    // "İncelemede" durum filtresinde de bir seçenek — LİSTE satırında aranmalı.
    const satir = await screen.findByRole("listitem");
    expect(within(satir).getByText("İncelemede")).toBeInTheDocument();
    expect(within(satir).getByText("Bordro")).toBeInTheDocument();
    expect(within(satir).getByText(/rapor\.pdf/)).toBeInTheDocument();
    expect(within(satir).getByText("2026-08-03 → 2026-08-05")).toBeInTheDocument();
  });

  it("İK karar verirken redde gerekçe girilmezse istek atılmaz", async () => {
    const user = userEvent.setup();
    setupApi({ docs: [{ ...DOC, own: false, can_decide: true, can_delete: true }] });
    vi.spyOn(window, "prompt").mockReturnValue("");
    await ciz({ canManage: true }, "Tüm belgeler");
    await waitFor(() => expect(screen.getByText("Kabul etme")).toBeInTheDocument());
    await user.click(screen.getByText("Kabul etme"));
    expect(apiMod.decideDocument).not.toHaveBeenCalled();
  });

  it("gerekçe girilince red isteği gönderilir", async () => {
    const user = userEvent.setup();
    setupApi({ docs: [{ ...DOC, own: false, can_decide: true, can_delete: true }] });
    vi.spyOn(window, "prompt").mockReturnValue("Okunmuyor");
    apiMod.decideDocument.mockResolvedValue({ ok: true });
    await ciz({ canManage: true }, "Tüm belgeler");
    await waitFor(() => expect(screen.getByText("Kabul etme")).toBeInTheDocument());
    await user.click(screen.getByText("Kabul etme"));
    expect(apiMod.decideDocument).toHaveBeenCalledWith(5, "rejected", "Okunmuyor");
  });

  it("silme onay ister", async () => {
    const user = userEvent.setup();
    setupApi({ docs: [DOC] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await ciz({}, "Belgelerim");
    await waitFor(() => expect(screen.getByText("Sil")).toBeInTheDocument());
    await user.click(screen.getByText("Sil"));
    expect(apiMod.deleteDocument).not.toHaveBeenCalled();
  });
});
