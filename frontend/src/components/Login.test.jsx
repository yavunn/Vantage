/**
 * Giriş ekranındaki "parolayı göster" düğmesi.
 *
 * İki kusuru birden kollar:
 * 1. Düğme alanın türünü gerçekten değiştirmeli — yalnız simge değişmesi
 *    kullanıcıya yazdığını göstermez.
 * 2. Düğme formu GÖNDERMEMELİ. Form içindeki tipsiz bir <button> varsayılan
 *    olarak submit'tir; göze basmak eksik parolayla giriş denemesi başlatırdı.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Login from "./Login.jsx";
import { LangProvider } from "../i18n.jsx";

function ekranaBas() {
  return render(
    <LangProvider>
      <Login onSuccess={() => {}} />
    </LangProvider>,
  );
}

describe("giriş ekranı parola görünürlüğü", () => {
  it("düğme parolayı gösterir ve tekrar gizler", async () => {
    const user = userEvent.setup();
    ekranaBas();

    const alan = document.querySelector(".pw-field input");
    await user.type(alan, "gizliparola");
    expect(alan).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "Parolayı göster" }));
    expect(alan).toHaveAttribute("type", "text");
    expect(alan).toHaveValue("gizliparola");

    await user.click(screen.getByRole("button", { name: "Parolayı gizle" }));
    expect(alan).toHaveAttribute("type", "password");
  });

  it("düğmeye basmak formu göndermez", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    ekranaBas();

    await user.click(screen.getByRole("button", { name: "Parolayı göster" }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

/**
 * Ortak alan bileşeni ÇOK alanlı formlarda: her alanın gözü yalnız KENDİ
 * alanını açmalı. Tek anahtarla hepsini açan eski onay kutusu, kullanıcı
 * yalnız yeni parolasını doğrulamak isterken mevcut parolayı da ifşa
 * ediyordu.
 */
describe("çok alanlı parola formu", () => {
  it("her alanın düğmesi yalnız kendi alanını açar", async () => {
    const user = userEvent.setup();
    const { default: ChangePassword } = await import("./ChangePassword.jsx");
    render(
      <LangProvider>
        <ChangePassword onClose={() => {}} />
      </LangProvider>,
    );

    const alanlar = [...document.querySelectorAll(".pw-field input")];
    expect(alanlar).toHaveLength(3);

    const dugmeler = screen.getAllByRole("button", { name: "Parolayı göster" });
    await user.click(dugmeler[1]);

    expect(alanlar.map((a) => a.getAttribute("type")))
      .toEqual(["password", "text", "password"]);
  });
});
