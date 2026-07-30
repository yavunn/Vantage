/**
 * API istemcisinin sözleşmesi: her istek token taşır, 401 oturumu temiz düşürür,
 * FastAPI'nin makine-okur 422 gövdesi kullanıcıya Türkçe cümle olur.
 *
 * Bunlar hep birlikte "oturum süresi doldu" deneyimini belirler; sessizce
 * bozulurlarsa kullanıcı ya sonsuz boş ekran görür ya da anlamsız "[object
 * Object]" mesajı alır.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, apiPost, getToken, getStoredUser } from "./api.js";

function mockResponse({ ok = true, status = 200, body = {} } = {}) {
  return { ok, status, json: async () => body };
}

describe("istek başlıkları", () => {
  beforeEach(() => {
    localStorage.setItem("vantage_token", "tok-123");
  });

  it("token varsa Authorization başlığı ekler", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ body: { ok: 1 } }));
    vi.stubGlobal("fetch", fetchMock);

    await api("/api/teams");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/teams");
    expect(init.headers.Authorization).toBe("Bearer tok-123");
  });

  it("POST gövdeyi JSON olarak yollar ve token'ı korur", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ body: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await apiPost("/api/annotations", { label: "Yılbaşı" });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers.Authorization).toBe("Bearer tok-123");
    expect(JSON.parse(init.body)).toEqual({ label: "Yılbaşı" });
  });

  it("token yoksa Authorization göndermez (public uçlar için)", async () => {
    localStorage.clear();
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ body: {} }));
    vi.stubGlobal("fetch", fetchMock);

    await api("/api/auth/setup-status");

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });
});

describe("401 → oturumu temiz düşür", () => {
  it("kimlikli istekte 401 gelirse oturumu siler ve olay yayar", async () => {
    localStorage.setItem("vantage_token", "tok-eski");
    localStorage.setItem("vantage_user", JSON.stringify({ display_name: "Ali" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 401, body: { detail: "Oturum süresi doldu" } })
    ));
    const onExpired = vi.fn();
    window.addEventListener("vantage:session-expired", onExpired);

    await expect(api("/api/teams")).rejects.toThrow("Oturum süresi doldu");

    expect(getToken()).toBeNull();
    expect(getStoredUser()).toBeNull();
    expect(onExpired).toHaveBeenCalledTimes(1);
    window.removeEventListener("vantage:session-expired", onExpired);
  });

  it("token yokken gelen 401 olay yaymaz (login ekranı zaten açık)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 401, body: { detail: "Yetkisiz" } })
    ));
    const onExpired = vi.fn();
    window.addEventListener("vantage:session-expired", onExpired);

    await expect(api("/api/teams")).rejects.toThrow("Yetkisiz");

    expect(onExpired).not.toHaveBeenCalled();
    window.removeEventListener("vantage:session-expired", onExpired);
  });

  it("403'te oturum DÜŞMEZ — yetki hatası oturum hatası değildir", async () => {
    localStorage.setItem("vantage_token", "tok-123");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockResponse({ ok: false, status: 403, body: { detail: "Yetkiniz yok" } })
    ));

    await expect(api("/api/developers/5/summary")).rejects.toThrow("Yetkiniz yok");

    expect(getToken()).toBe("tok-123");
  });
});

describe("FastAPI 422 gövdesi → okunur Türkçe mesaj", () => {
  it("kısa parolayı alan adıyla birlikte anlatır", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse({
      ok: false,
      status: 422,
      body: {
        detail: [{
          loc: ["body", "new_password"],
          type: "string_too_short",
          ctx: { min_length: 10 },
          msg: "String should have at least 10 characters",
        }],
      },
    })));

    await expect(apiPost("/api/auth/change-password", {}))
      .rejects.toThrow("Yeni parola en az 10 karakter olmalı");
  });

  it("eksik alanı 'zorunlu' diye bildirir", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse({
      ok: false,
      status: 422,
      body: { detail: [{ loc: ["body", "email"], type: "missing", msg: "Field required" }] },
    })));

    await expect(apiPost("/api/auth/login", {})).rejects.toThrow("E-posta zorunlu");
  });

  it("birden çok hatayı tek satırda birleştirir", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse({
      ok: false,
      status: 422,
      body: {
        detail: [
          { loc: ["body", "email"], type: "missing", msg: "Field required" },
          { loc: ["body", "password"], type: "missing", msg: "Field required" },
        ],
      },
    })));

    await expect(apiPost("/api/auth/login", {}))
      .rejects.toThrow("E-posta zorunlu · Parola zorunlu");
  });

  it("gövde hiç JSON değilse HTTP kodunu gösterir, çökmez", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => { throw new Error("not json"); },
    }));

    await expect(api("/api/teams")).rejects.toThrow("HTTP 500");
  });
});
