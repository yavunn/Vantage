/**
 * Bekleme göstergesi: beş panelde "yükleniyor" hâli ya hiç yoktu ya da her
 * birinde farklı görünüyordu. Boş liste ile "henüz gelmedi" aynı göründüğü
 * sürece kullanıcı "tıkladım, bir şey oldu mu?" diye düşünür.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Yukleniyor from "./Yukleniyor.jsx";
import { LangProvider } from "../i18n.jsx";

function ciz(props) {
  return render(<LangProvider><Yukleniyor {...props} /></LangProvider>);
}

describe("bekleme göstergesi", () => {
  it("ekran okuyucuya beklendiğini bildirir", () => {
    ciz();
    const kutu = screen.getByLabelText("Yükleniyor…");
    expect(kutu).toHaveAttribute("aria-busy", "true");
  });

  it("liste beklerken listenin şeklini gösterir", () => {
    const { container } = ciz({ adet: 5 });
    expect(container.querySelectorAll(".sk-line")).toHaveLength(5);
  });

  it("kart beklerken kart ızgarasının şeklini gösterir", () => {
    const { container } = ciz({ bicim: "kart", adet: 3 });
    expect(container.querySelectorAll(".card.skeleton")).toHaveLength(3);
  });
});
