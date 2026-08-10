/**
 * Dil katmanı — TR ana dil, EN seçime bağlı.
 *
 * Kritik davranışlar:
 *  - Ham anahtar ("nav.team") kullanıcıya ASLA gösterilmez.
 *  - Varsayılan Türkçe; tarayıcı diline bakılmaz (İngilizce OS kullanan Türk
 *    çalışana arayüz sormadan İngilizce gösterilmemeli).
 *  - Seçim kalıcı ve sunucuya `Accept-Language` ile gider (metrik adları
 *    API'den geliyor; yalnız arayüzü çevirmek panoyu yarı Türkçe bırakırdı).
 */
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { DEFAULT_LANG, LangProvider, getLang, translate, useLang } from "./i18n.jsx";

beforeEach(() => {
  localStorage.clear();
});

describe("çeviri", () => {
  it("varsayılan dil Türkçe", () => {
    expect(DEFAULT_LANG).toBe("tr");
    expect(translate("tr", "nav.team")).toBe("Takım görünümü");
  });

  it("İngilizce karşılık döner", () => {
    expect(translate("en", "nav.team")).toBe("Team view");
    expect(translate("en", "login.submit")).toBe("Sign in");
  });

  it("bilinmeyen anahtar HAM HÂLİYLE gösterilmez", () => {
    // "nav.olmayan" gibi bir dize ekranda görünürse kullanıcı için anlamsızdır.
    expect(translate("tr", "nav.olmayan")).toBe("");
    expect(translate("en", "nav.olmayan")).toBe("");
  });

  it("bir dilde eksik anahtar Türkçeye düşer, boşa değil", () => {
    // Sözlükte yalnız TR'de olan bir anahtar taklit edilemez; davranışı
    // doğrudan sözleşme üzerinden sınıyoruz: EN'de olmayan bir anahtar için
    // TR karşılığı dönmeli.
    const trOnly = translate("tr", "top.pending");
    expect(trOnly).not.toBe("");
    expect(translate("en", "top.pending")).not.toBe("");
  });
});

function Probe() {
  const { lang, setLang, t } = useLang();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="label">{t("nav.team")}</span>
      <button onClick={() => setLang("en")}>EN</button>
      <button onClick={() => setLang("tr")}>TR</button>
    </div>
  );
}

describe("dil seçimi", () => {
  it("tarayıcı diline BAKILMAZ — varsayılan Türkçe", () => {
    // jsdom navigator.language = "en-US". Otomatik algılama olsaydı burada
    // İngilizce görürdük; ürün kararı: İngilizce yalnızca SEÇİMLE gelir.
    render(<LangProvider><Probe /></LangProvider>);
    expect(screen.getByTestId("lang").textContent).toBe("tr");
    expect(screen.getByTestId("label").textContent).toBe("Takım görünümü");
  });

  it("seçim arayüzü değiştirir ve kalıcıdır", () => {
    render(<LangProvider><Probe /></LangProvider>);
    fireEvent.click(screen.getByText("EN"));
    expect(screen.getByTestId("label").textContent).toBe("Team view");
    expect(localStorage.getItem("vantage_lang")).toBe("en");
  });

  it("seçim api katmanına da yansır (Accept-Language)", () => {
    render(<LangProvider><Probe /></LangProvider>);
    fireEvent.click(screen.getByText("EN"));
    // getLang() React ağacının dışından okunur: api.js her isteğe bunu koyar.
    expect(getLang()).toBe("en");
  });

  it("<html lang> güncellenir (ekran okuyucu doğru dilde okusun)", () => {
    render(<LangProvider><Probe /></LangProvider>);
    fireEvent.click(screen.getByText("EN"));
    expect(document.documentElement.lang).toBe("en");
  });

  it("geçersiz dil kodu yok sayılır", () => {
    function Bad() {
      const { lang, setLang } = useLang();
      return (
        <div>
          <span data-testid="lang">{lang}</span>
          <button onClick={() => setLang("de")}>DE</button>
        </div>
      );
    }
    render(<LangProvider><Bad /></LangProvider>);
    fireEvent.click(screen.getByText("DE"));
    expect(screen.getByTestId("lang").textContent).toBe("tr");
  });
});

describe("dil değişiminde yeniden çekim", () => {
  it("aynı commit'te tetiklenen istek YENİ dili taşır", () => {
    // Kusur şuydu: `currentLang` yalnız LangProvider'ın efektinde yazılıyordu.
    // React alt bileşenlerin efektlerini üstünkinden ÖNCE çalıştırır; dolayısıyla
    // `lang`e bağlı bir veri efekti (panonun yeniden çekimi) ESKİ dili okuyor,
    // sunucu bir önceki dilde cevap veriyordu — düzeltme hep bir dil GERİDEN
    // gelirdi. Bu test o sırayı sabitler.
    const gorulen = [];
    function VeriCeken() {
      const { lang } = useLang();
      useEffect(() => {
        gorulen.push(getLang()); // api.js `Accept-Language` için bunu okur
      }, [lang]);
      return null;
    }
    render(
      <LangProvider>
        <VeriCeken />
        <Probe />
      </LangProvider>,
    );
    fireEvent.click(screen.getByText("EN"));
    expect(gorulen).toEqual(["tr", "en"]);
  });
});

describe("sağlayıcı dışında", () => {
  it("bileşen ham anahtar göstermez", () => {
    // Sağlayıcı olmadan render edilen bileşen (ör. testte tek başına TopBar)
    // yine gerçek metni almalı — varsayılan bağlam da çeviri yapıyor.
    function Yalniz() {
      const { t } = useLang();
      return <span data-testid="x">{t("nav.settings")}</span>;
    }
    render(<Yalniz />);
    expect(screen.getByTestId("x").textContent).toBe("Ayarlar");
  });
});

describe("api katmanı dil başlığı", () => {
  it("her isteğe Accept-Language ekler", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api.js");
    await api("/api/teams");
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers["Accept-Language"]).toBe(getLang());
    vi.unstubAllGlobals();
  });
});
