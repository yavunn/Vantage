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
});
