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
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import { LangProvider } from "./i18n.jsx";

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
 *
 * Fonksiyon cevaplara isteğin DİLİ geçilir: sunucu metrik adlarını ve durum
 * etiketlerini `Accept-Language`e göre çevirir, taklit de aynısını yapabilsin.
 */
function stubFetch(routes) {
  const fetchMock = vi.fn((url, init) => {
    const path = String(url).split("?")[0];
    const hit = routes[path];
    if (!hit) return new Promise(() => {});
    const lang = init?.headers?.["Accept-Language"] || "tr";
    return Promise.resolve(typeof hit === "function" ? hit(lang) : hit);
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

// Oturum açmış pano render'ı iki describe tarafından da kullanılır
// (dil tazeleme ve kabuk yapısı), bu yüzden modül seviyesinde.
const oturumAc = () => {
  localStorage.setItem("vantage_token", "tok");
  localStorage.setItem(
    "vantage_user",
    JSON.stringify({ id: 1, display_name: "Ali", role: "admin" }),
  );
};

const RAPOR = (lang) =>
  mockResponse({
    body: {
      metrics: [{
        key: "cycle_time",
        name: lang === "en" ? "Cycle Time" : "Cycle Time",
        description: lang === "en" ? "Average time from work opened to done" : "Ortalama tamamlanma süresi",
        value: 3, unit: "gün",
        status: "green",
        status_label: lang === "en" ? "Flowing" : "Akıyor",
        data_completeness: 1,
      }],
      recommendations: [],
      series: [],
      signals: [],
    },
  });

function stubPano() {
  return stubFetch({
    "/api/auth/setup-status": mockResponse({ body: { needs_setup: false } }),
    "/api/auth/me": mockResponse({ body: { id: 1, display_name: "Ali", role: "admin" } }),
    "/api/config/ui": mockResponse({ body: { individual_view_enabled: false, anonymize_individuals: false, metric_thresholds: {} } }),
    "/api/teams": mockResponse({ body: [{ id: 1, name: "Takım A" }] }),
    "/api/directory": mockResponse({ body: [] }),
    "/api/survey/current": mockResponse({ body: { enabled: false } }),
    "/api/me/notifications": mockResponse({ body: [] }),
    "/api/annotations": mockResponse({ body: [] }),
    "/api/teams/1/report": RAPOR,
    "/api/teams/1/code-health": mockResponse({ body: null }),
    "/api/teams/1/code-health/series": mockResponse({ body: null }),
  });
}

describe("dil değişimi", () => {
  /**
   * Kusur: dil seçici arayüz metinlerini anında çeviriyordu ama SUNUCUDAN gelen
   * metinleri (metrik adı, durum etiketi) çevirmiyordu — hiçbir veri efekti
   * `lang`e bağlı değildi. Pano verisi App'in kendi state'inde durur ve App hiç
   * unmount olmaz; bu yüzden sekme değiştirip geri gelmek de kurtarmıyordu,
   * kartlar sayfa yenilenene kadar eski dilde kalıyordu.
   */
  it("sunucudan gelen metinleri de yeni dilde tazeler", async () => {
    oturumAc();
    stubPano();

    render(<LangProvider><App /></LangProvider>);

    // Türkçe pano: durum etiketi SUNUCUDAN geldi.
    expect(await screen.findByText(/Akıyor/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "EN" }));

    // Arayüz metni (istemci sözlüğü) VE sunucu metni birlikte İngilizceye geçmeli.
    expect(await screen.findByText(/Flowing/)).toBeInTheDocument();
    expect(screen.queryByText(/Akıyor/)).not.toBeInTheDocument();

    // Tazeleme ağacı baştan kurduğu için düğme de yeniden doğar; klavyeyle
    // gezen kullanıcı az önce bastığı düğmeyi kaybetmemeli.
    expect(screen.getByRole("button", { name: "EN" })).toHaveFocus();
  });

  it("dil değişince istekler yeni Accept-Language ile gider", async () => {
    oturumAc();
    const fetchMock = stubPano();

    render(<LangProvider><App /></LangProvider>);
    await screen.findByText(/Akıyor/);

    await userEvent.click(screen.getByRole("button", { name: "EN" }));

    await waitFor(() => {
      const raporlar = fetchMock.mock.calls.filter((c) =>
        String(c[0]).startsWith("/api/teams/1/report"),
      );
      // İlk çekim tr, dil değişimiyle gelen ikinci çekim en olmalı — bir dil
      // GERİDEN gelmemeli (currentLang efekte bırakılırsa tam olarak bu olur).
      expect(raporlar.map((c) => c[1].headers["Accept-Language"])).toEqual(["tr", "en"]);
    });
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

describe("kabuk yapısı", () => {
  it("her ekranın kendi başlığı ve içerik bölgesi var", async () => {
    // Daha önce hiçbir panelde <h1> yoktu: kullanıcının konumunu anlamasının
    // tek yolu hangi sekmenin koyu göründüğüydü. Başlık sekme durumundan
    // türetilir, böylece yeni panel eklendiğinde unutulamaz.
    oturumAc();
    stubPano();

    render(<LangProvider><App /></LangProvider>);

    const baslik = await screen.findByRole("heading", { level: 1, name: "Takım görünümü" });
    expect(baslik).toBeInTheDocument();
    // Marka artık başlık değil — ikisi yarışmamalı.
    expect(screen.queryByRole("heading", { name: "Vantage" })).not.toBeInTheDocument();

    // Klavye kullanıcısı sekmeleri atlayabilsin; içerik işaretli bir bölge olsun.
    expect(screen.getByRole("main")).toContainElement(baslik);
    expect(screen.getByRole("link", { name: "İçeriğe atla" })).toHaveAttribute("href", "#icerik");
  });

  it("sekme değişince başlık da değişir", async () => {
    oturumAc();
    stubPano();

    render(<LangProvider><App /></LangProvider>);
    await screen.findByRole("heading", { level: 1, name: "Takım görünümü" });

    await userEvent.click(screen.getByRole("button", { name: "Ayarlar" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Ayarlar" })).toBeInTheDocument();
  });
});

describe("pano geri bildirimi", () => {
  it("hata durumunda ne olduğunu VE ne yapılacağını söyler", async () => {
    // Önceki hâli tek satırlık kırmızı yazıydı ("Hata: Failed to fetch") ve
    // kullanıcıya hiçbir çıkış yolu bırakmıyordu.
    oturumAc();
    stubFetch({
      "/api/auth/setup-status": mockResponse({ body: { needs_setup: false } }),
      "/api/auth/me": mockResponse({ body: { id: 1, display_name: "Ali", role: "admin" } }),
      "/api/config/ui": mockResponse({ ok: false, status: 500, body: { detail: "sunucu hatası" } }),
      "/api/teams": mockResponse({ body: [] }),
      "/api/directory": mockResponse({ body: [] }),
      "/api/survey/current": mockResponse({ body: { enabled: false } }),
      "/api/me/notifications": mockResponse({ body: [] }),
    });

    render(<LangProvider><App /></LangProvider>);

    const uyari = await screen.findByRole("alert");
    expect(within(uyari).getByRole("heading", { level: 1 })).toHaveTextContent("Pano yüklenemedi");
    expect(within(uyari).getByRole("button", { name: "Sayfayı yenile" })).toBeInTheDocument();
  });
});
