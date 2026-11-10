import { describe, expect, it, vi } from "vitest";

/**
 * When the "Getting your saves" dialog opens during a held launch.
 *
 * A small save's only progress event is the 100 sent once the copy has
 * ended, a moment before the game starts. The dialog opened on it stayed
 * over the running game, so 100 must not open one.
 */

const heard = vi.hoisted(() => new Map<string, (...args: unknown[]) => unknown>());
const opened = vi.hoisted(() => ({ count: 0, closed: 0 }));

vi.mock("./steam", () => ({ onGameLaunch: () => () => undefined, runningGames: () => [] }));
vi.mock("./backend", () => ({
  cloudBackupAfterPlay: () => Promise.resolve({ ok: true }),
  cloudReleaseLaunch: () => Promise.resolve({ ok: true }),
}));
vi.mock("./CloudDifferModal", () => ({ showCloudDiffer: () => undefined }));
vi.mock("./host", () => ({
  addEventListener: (name: string, listener: (...args: unknown[]) => unknown) => {
    heard.set(name, listener);
    return listener;
  },
  removeEventListener: () => undefined,
}));
vi.mock("./CloudFetchModal", () => ({
  showCloudFetch: () => {
    opened.count += 1;
    return () => {
      opened.closed += 1;
    };
  },
}));
vi.mock("./addedGames", () => ({ addedGame: () => undefined }));
vi.mock("./logError", () => ({ logError: () => undefined }));

const { watchPlaying } = await import("./playWatch");
watchPlaying();
const send = (name: string, ...args: unknown[]) => heard.get(name)?.(...args);

describe("the save fetch dialog", () => {
  it("does not open for a copy that has already finished", () => {
    opened.count = 0;
    send("cloud_fetch_started", 7, "Made Up");
    send("cloud_sync_progress", "pcsx2", 100, "", "launch");
    send("cloud_fetch_done", 7, []);
    expect(opened.count).toBe(0);
  });

  it("opens while files are moving, and closes when the fetch is done", () => {
    opened.count = 0;
    opened.closed = 0;
    send("cloud_fetch_started", 7, "Made Up");
    send("cloud_sync_progress", "pcsx2", 40, "", "launch");
    send("cloud_sync_progress", "pcsx2", 100, "", "launch");
    send("cloud_fetch_done", 7, []);
    expect([opened.count, opened.closed]).toEqual([1, 1]);
  });
});
