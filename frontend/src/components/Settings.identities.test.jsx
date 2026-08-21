/**
 * Ayarlar → "Kaynak kimliklerim".
 *
 * Buradaki asıl risk sessiz kimlik çakışmasıdır: başkasında olan bir Trello
 * üyeliğini seçtirmek, kullanıcıyı sebebini bilmediği bir 409'a sokar — ya da
 * daha kötüsü, bağ kurulursa o kişinin kartları yanlış insana atfedilir.
 * O yüzden alınmış kimlik SEÇİLEMEZ olmalı.
 *
 * İkinci risk: git e-postası tek alan olarak sunulursa aynı insanın GitHub
 * noreply adresi hiç girilemez ve commit'leri ikiye bölünür.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  MIN_PASSWORD_LENGTH: 10,
  changePassword: vi.fn(),
  updateProfile: vi.fn(),
  getMyIdentities: vi.fn(),
  updateMyIdentities: vi.fn(),
}));

import * as apiMod from "../api.js";
import Settings from "./Settings.jsx";

const USER = { email: "ayse@sirket.com", display_name: "Ayşe", role: "user" };

const KIMLIKLER = {
  developer_id: 5,
  display_name: "Ayşe",
  git_emails: ["ayse@sirket.com"],
  task_source: "trello",
  task_identity: null,
  members: [
    { member_id: "m1", full_name: "Ayşe Yılmaz", username: "ayse",
      board_name: "Pano", available: true },
    { member_id: "m2", full_name: "Mehmet", username: "mehmet",
      board_name: "Pano", available: false },
  ],
  warnings: [],
};

// Ayarlar artık kenar çubuğu kalıbını kullanıyor: bölümler yan yana değil,
// solda seçilen alan sağda tek başına açılıyor. Kimlikler bölümü bu yüzden bir
// tık uzakta — testlerin İDDİALARI değişmedi, yalnızca oraya gidiliyor.
function renderSettings() {
  const utils = render(
    <Settings
      user={USER}
      onCycleTheme={() => {}}
      themeLabel="Tema: Oto"
      onLogout={() => {}}
      onProfileUpdated={() => {}}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Kaynak kimliklerim" }));
  return utils;
}

describe("Kaynak kimliklerim", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMod.getMyIdentities.mockResolvedValue(KIMLIKLER);
    apiMod.updateMyIdentities.mockResolvedValue({ ok: true });
  });

  it("mevcut git e-postalarını satır satır gösterir", async () => {
    renderSettings();
    const alan = await screen.findByLabelText(/Git commit e-postalarım/);
    expect(alan.value).toBe("ayse@sirket.com");
  });

  it("birden çok e-posta gönderilebilir (GitHub noreply adresi dahil)", async () => {
    const user = userEvent.setup();
    renderSettings();
    const alan = await screen.findByLabelText(/Git commit e-postalarım/);
    await user.clear(alan);
    await user.type(alan, "ayse@sirket.com\n1+ayse@users.noreply.github.com");
    await user.click(screen.getByRole("button", { name: "E-postaları kaydet" }));

    await waitFor(() =>
      expect(apiMod.updateMyIdentities).toHaveBeenCalledWith({
        git_emails: ["ayse@sirket.com", "1+ayse@users.noreply.github.com"],
      })
    );
  });

  it("başka hesapta olan Trello üyeliği SEÇİLEMEZ", async () => {
    renderSettings();
    await screen.findByLabelText(/Git commit e-postalarım/);
    const secenekler = screen.getAllByRole("option");
    const alinmis = secenekler.find((o) => o.value === "m2");
    const bosta = secenekler.find((o) => o.value === "m1");

    expect(alinmis).toBeDisabled();
    expect(alinmis.textContent).toContain("başka hesapta");
    expect(bosta).not.toBeDisabled();
  });

  it("Trello üyeliği seçilip kaydedilir", async () => {
    const user = userEvent.setup();
    renderSettings();
    const secim = await screen.findByLabelText(/Trello üyeliğim/);
    await user.selectOptions(secim, "m1");
    await user.click(screen.getByRole("button", { name: "Trello üyeliğini kaydet" }));

    await waitFor(() =>
      expect(apiMod.updateMyIdentities).toHaveBeenCalledWith({ task_identity: "m1" })
    );
  });

  it("görev kaynağı Trello değilse üyelik bölümü hiç çıkmaz", async () => {
    apiMod.getMyIdentities.mockResolvedValue({ ...KIMLIKLER, task_source: "none", members: [] });
    renderSettings();
    await screen.findByLabelText(/Git commit e-postalarım/);
    expect(screen.queryByLabelText(/Trello üyeliğim/)).toBeNull();
  });
});
