/**
 * İş ↔ commit onay ekranı.
 *
 * Buradaki asıl risk şu: bağ TAHMİNdir (ölçülen ilk sıra isabeti ~%50) ve
 * analiz yalnız ONAYLANMIŞ bağlardan üretilir. Arayüz bu iki şeyi bozarsa
 * kullanıcı farkında olmadan tahmin üstüne analiz üretilmiş sanır:
 *
 *  1) Onaylı bağ yokken "Süreç analizi üret" TIKLANAMAZ olmalı — backend zaten
 *     LLM'i çağırmaz ama düğmenin açık olması kullanıcıya yanlış vaat eder.
 *  2) Skor ekranda GÖRÜNMELİ — kullanıcı neye onay verdiğini görmeden karar
 *     veremez; skoru gizlemek tahmini kesinlik gibi sunmak olurdu.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({
  getTeamTaskLinks: vi.fn(),
  decideTaskLink: vi.fn(),
  analyzeTask: vi.fn(),
}));

import * as apiMod from "../api.js";
import TaskLinksPanel from "./TaskLinksPanel.jsx";

const TEAMS = [{ id: 7, name: "Platform" }];

function payload({ confirmed = 0, pending = 1, status = "suggested" } = {}) {
  return {
    team_id: 7,
    tasks: [
      {
        task_id: 225,
        title: "Çalışan Memnuniyet anketi Geliştirmesi",
        status: "DONE",
        pending,
        confirmed,
        links: [
          {
            commit_id: 11,
            sha: "c781ab5f",
            message: "Add anonymous employee satisfaction survey",
            committed_at: "2026-07-23T10:00:00+00:00",
            status,
            score: 0.667,
            in_window: true,
            decided_at: null,
          },
        ],
      },
    ],
  };
}

describe("TaskLinksPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMod.getTeamTaskLinks.mockResolvedValue(payload());
  });

  it("bağın benzerlik skorunu gösterir (tahmin olduğu gizlenmez)", async () => {
    render(<TaskLinksPanel teams={TEAMS} canManage />);
    expect(await screen.findByText(/0\.667/)).toBeInTheDocument();
  });

  it("onaylı bağ yokken analiz düğmesi kapalıdır", async () => {
    render(<TaskLinksPanel teams={TEAMS} canManage />);
    const btn = await screen.findByRole("button", { name: /Süreç analizi üret/ });
    expect(btn).toBeDisabled();
  });

  it("onaylı bağ varken analiz düğmesi açılır ve sonucu gösterir", async () => {
    apiMod.getTeamTaskLinks.mockResolvedValue(
      payload({ confirmed: 1, pending: 0, status: "confirmed" })
    );
    apiMod.analyzeTask.mockResolvedValue({
      task_id: 225,
      status: "ok",
      analysis: "Bu iş 4 günde tamamlandı [1].",
      commits_used: ["c781ab5f"],
    });

    render(<TaskLinksPanel teams={TEAMS} canManage />);
    const btn = await screen.findByRole("button", { name: /Süreç analizi üret/ });
    expect(btn).toBeEnabled();

    await userEvent.click(btn);
    expect(await screen.findByText(/4 günde tamamlandı/)).toBeInTheDocument();
  });

  it("uyum yargısını rozet olarak gösterir, sapmayı suçlama diline çevirmez", async () => {
    apiMod.getTeamTaskLinks.mockResolvedValue(
      payload({ confirmed: 1, pending: 0, status: "confirmed" })
    );
    apiMod.analyzeTask.mockResolvedValue({
      task_id: 225,
      status: "ok",
      analysis: "Commit'ler başka bir modüle dokunuyor [1].",
      commits_used: ["c781ab5f"],
      alignment: "sapma",
      alignment_label: "Karttan sapmış",
    });

    render(<TaskLinksPanel teams={TEAMS} canManage />);
    await userEvent.click(await screen.findByRole("button", { name: /Süreç analizi üret/ }));

    expect(await screen.findByText("Karttan sapmış")).toBeInTheDocument();
    // Sapma bir kusur değil: ekran bunu açıkça söylemeli.
    expect(screen.getByText(/kart\s+güncellenmemiştir/)).toBeInTheDocument();
  });

  it("yargı üretilemediyse rozet HİÇ gösterilmez (uydurulmuş 'uyuyor' yok)", async () => {
    apiMod.getTeamTaskLinks.mockResolvedValue(
      payload({ confirmed: 1, pending: 0, status: "confirmed" })
    );
    apiMod.analyzeTask.mockResolvedValue({
      task_id: 225,
      status: "ok",
      analysis: "Serbest metin [1].",
      commits_used: ["c781ab5f"],
      alignment: null,
      alignment_label: null,
    });

    render(<TaskLinksPanel teams={TEAMS} canManage />);
    await userEvent.click(await screen.findByRole("button", { name: /Süreç analizi üret/ }));

    expect(await screen.findByText(/Serbest metin/)).toBeInTheDocument();
    expect(screen.queryByText(/uyuyor|sapmış/i)).toBeNull();
  });

  it("onaylayınca API'ye karar gider ve liste tazelenir", async () => {
    apiMod.decideTaskLink.mockResolvedValue({ status: "confirmed" });
    render(<TaskLinksPanel teams={TEAMS} canManage />);

    await userEvent.click(await screen.findByRole("button", { name: "Onayla" }));

    expect(apiMod.decideTaskLink).toHaveBeenCalledWith(7, 225, 11, "confirmed");
    // Karar sonrası liste yeniden okunur (ilk yükleme + tazeleme).
    await waitFor(() => expect(apiMod.getTeamTaskLinks).toHaveBeenCalledTimes(2));
  });

  it("yetkisiz kullanıcıya karar düğmeleri gösterilmez", async () => {
    render(<TaskLinksPanel teams={TEAMS} canManage={false} />);
    await screen.findByText(/Çalışan Memnuniyet/);
    expect(screen.queryByRole("button", { name: "Onayla" })).toBeNull();
  });

  // Konvansiyon bağı ile tahmin bağı ekranda AYNI görünürse kullanıcı hangisine
  // güveneceğini bilemez; ikisini ayırmak bu özelliğin tek görünür faydasıdır.
  it("kesin bağı benzerlik skoru gibi göstermez", async () => {
    const p = payload({ confirmed: 1, pending: 0, status: "confirmed" });
    p.tasks[0].links[0] = {
      ...p.tasks[0].links[0], matched_by: "convention", score: null,
    };
    apiMod.getTeamTaskLinks.mockResolvedValue(p);

    render(<TaskLinksPanel teams={TEAMS} canManage />);

    expect(await screen.findByText(/kesin bağ: commit mesajında kart numarası/))
      .toBeInTheDocument();
    expect(screen.queryByText(/benzerlik/)).toBeNull();
  });

  it("kart numarasını gösterir — yazılacak değer bilinmeden konvansiyon kullanılamaz", async () => {
    const p = payload();
    p.tasks[0].task_key = "42";
    p.tasks[0].task_url = "https://trello.com/c/aBcD1234";
    apiMod.getTeamTaskLinks.mockResolvedValue(p);

    render(<TaskLinksPanel teams={TEAMS} canManage />);

    expect(await screen.findByText("[#42]")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "kartı aç" })).toHaveAttribute(
      "href", "https://trello.com/c/aBcD1234"
    );
  });
});
