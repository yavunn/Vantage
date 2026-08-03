/**
 * Açılış/oturum kabuğu: süresi dolmuş bir token'ın kullanıcıya HATA EKRANI değil
 * GİRİŞ EKRANI göstermesi gerekir.
 *
 * Gerçekte yaşanan kusur buydu: App, localStorage'daki kullanıcıyı doğrulamadan
 * set ediyor, bu da veri uçlarını ölü token'la çağırıyordu; dönen 401'ler
 * `error` state'ine yazılıyor ve `error` hiçbir zaman temizlenmediği için
 * kullanıcı giriş yaptıktan SONRA bile tam sayfa "Hata: Oturum geçersiz veya
 * süresi doldu" kutusunda kilitli kalıyordu. Tek çıkış sayfayı yenilemekti.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

function mockResponse({ ok = true, status = 200, body = {} } = {}) {
  return { ok, status, json: async () => body };
}

const UNAUTHORIZED = mockResponse({
  ok: false,
  status: 401,
  body: { detail: "Oturum geçersiz veya süresi doldu" },
});

/**
 * Yol → cevap eşlemesi ile fetch taklidi. Eşleşmeyen /api yolları asla
 * çözülmez (askıda kalır): test ettiğimiz karar noktasından sonrasını
 * render etmeye çalışmayalım diye bilerek böyle.
 */
function stubFetch(routes) {
  const fetchMock = vi.fn((url) => {
    const path = String(url).split("?")[0];
    const hit = routes[path];
    if (!hit) return new Promise(() => {});
    return Promise.resolve(typeof hit === "function" ? hit() : hit);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function calledPaths(fetchMock) {
  return fetchMock.mock.calls.map((c) => String(c[0]).split("?")[0]);
}

describe("açılışta süresi dolmuş token", () => {
  it("veri uçlarını ölü token'la çağırmaz, giriş ekranına düşer", async () => {
    localStorage.setItem("vantage_token", "tok-eski");
    localStorage.setItem("vantage_user", JSON.stringify({ display_name: "Ali", role: "admin" }));
    const fetchMock = stubFetch({
      "/api/auth/setup-status": mockResponse({ body: { needs_setup: false } }),
      // Doğrulama cevabı bilerek geç gelir: iyimser bir setUser bu aralıkta
      // veri uçlarını ateşlerdi. Anında çözülen bir cevapla bu kusur görünmez.
      "/api/auth/me": () => new Promise((res) => setTimeout(() => res(UNAUTHORIZED), 30)),
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Giriş yap" })).toBeInTheDocument();
    // Kimlik doğrulanmadan hiçbir veri ucu çağrılmamalı — 401 hiç doğmasın.
    const paths = calledPaths(fetchMock);
    expect(paths).not.toContain("/api/config/ui");
    expect(paths).not.toContain("/api/teams");
    expect(paths).not.toContain("/api/directory");
    // Oturumun düşmesi bir "hata" değil; ekranda hata kutusu olmamalı.
    expect(screen.queryByText(/^Hata:/)).not.toBeInTheDocument();
    expect(localStorage.getItem("vantage_token")).toBeNull();
  });
});

describe("oturum düştükten sonra yeniden giriş", () => {
  it("önceki oturumun 401 hatasını yeni oturuma taşımaz", async () => {
    localStorage.setItem("vantage_token", "tok-eski");
    localStorage.setItem("vantage_user", JSON.stringify({ display_name: "Ali", role: "admin" }));
    // me geçerli, ardından veri uçları 401: token tam bu arada düşmüş.
    // Paralel 401'lerin ilki oturumu temizlediği için sonrakiler artık
    // session-expired yaymaz — hata yalnızca `error` state'ine yazılır.
    // Girişten SONRA aynı uçlar 401 dönmemeli; yoksa oturum yeniden düşer ve
    // testin ölçtüğü şey (eski hatanın taşınıp taşınmadığı) gölgelenir.
    let loggedOut = true;
    const afterLogin = () => (loggedOut ? UNAUTHORIZED : new Promise(() => {}));
    const fetchMock = stubFetch({
      "/api/auth/setup-status": mockResponse({ body: { needs_setup: false } }),
      "/api/auth/me": mockResponse({ body: { id: 1, display_name: "Ali", role: "admin" } }),
      "/api/config/ui": afterLogin,
      "/api/teams": afterLogin,
      "/api/directory": afterLogin,
      "/api/survey/current": afterLogin,
      "/api/auth/login": mockResponse({
        body: { access_token: "tok-yeni", user: { id: 1, display_name: "Ali", role: "admin" } },
      }),
    });

    render(<App />);

    // 401'ler oturumu düşürdü → giriş ekranı.
    const heading = await screen.findByRole("heading", { name: "Giriş yap" });
    expect(heading).toBeInTheDocument();
    await waitFor(() => expect(calledPaths(fetchMock)).toContain("/api/teams"));

    // Yeniden giriş: bu kez uçlar 401 dönmüyor (askıda bırakılırlar ki panonun
    // tamamını render etmeye çalışmayalım — ölçtüğümüz şey hata kutusu).
    loggedOut = false;
    await userEvent.type(screen.getByLabelText("E-posta"), "ali@ornek.com");
    await userEvent.type(screen.getByLabelText("Parola"), "parola-12345");
    await userEvent.click(screen.getByRole("button", { name: "Giriş yap" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Giriş yap" })).not.toBeInTheDocument()
    );
    // Kusur buradaydı: eski hata temizlenmediği için giriş sonrası tam sayfa
    // "Hata: Oturum geçersiz veya süresi doldu" basılıyordu.
    expect(screen.queryByText(/^Hata:/)).not.toBeInTheDocument();
    expect(screen.getByText("Yükleniyor…")).toBeInTheDocument();
  });
});
