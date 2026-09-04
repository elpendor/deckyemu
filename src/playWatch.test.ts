import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * When a game ending turns into a copy, and when it does not.
 *
 * The whole of this module is an interval and the two conditions that end it,
 * and neither is reachable by looking at it: the first frames of a launch look
 * exactly like a game that has already closed, because Steam has not listed it
 * yet. A fake clock reaches both.
 */

const running = vi.hoisted(() => ({ ids: [] as number[] }));
const copied = vi.hoisted(() => ({ calls: [] as string[] }));

vi.mock("./steam", () => ({
  onGameLaunch: () => () => undefined,
  runningGames: () => running.ids.map((appId) => ({ appId, title: "x", gameId: "x" })),
}));
vi.mock("./backend", () => ({
  cloudBackupAfterPlay: (coreId: string) => {
    copied.calls.push(coreId);
    return Promise.resolve({ ok: true });
  },
  cloudHoldLaunch: () => Promise.resolve({ ok: true, held: false }),
  cloudBeforePlay: () => Promise.resolve({ ok: true, differing: [], restored: 0 }),
  cloudTakeTheirs: () => Promise.resolve({ ok: true }),
}));
vi.mock("./CloudDifferModal", () => ({ showCloudDiffer: () => undefined }));
// @decky/api reaches for a manifest that only exists in a built plugin.
vi.mock("@decky/api", () => ({
  addEventListener: () => () => undefined,
  removeEventListener: () => undefined,
}));
// Pulls in @decky/ui, which needs Steam's webpack chunk to exist. There is no
// DOM here on purpose -- see the repo's test notes.
vi.mock("./CloudFetchModal", () => ({ showCloudFetch: () => () => undefined }));
vi.mock("./addedGames", () => ({ addedGame: () => undefined }));
vi.mock("./logError", () => ({ logError: () => undefined }));

const { watchOne } = await import("./playWatch");

const TICK = 4000;

beforeEach(() => {
  vi.useFakeTimers();
  running.ids = [];
  copied.calls = [];
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

describe("watchOne", () => {
  it("copies once the game it was given has gone", () => {
    running.ids = [77];
    watchOne(77, "emu:xenia");
    vi.advanceTimersByTime(TICK * 2);
    expect(copied.calls).toEqual([]);

    running.ids = [];
    vi.advanceTimersByTime(TICK);
    expect(copied.calls).toEqual(["emu:xenia"]);
  });

  it("does not copy on a launch that has not been listed yet", () => {
    // The failure this prevents: Steam lists a game a moment after it says the
    // launch began, so the first look finds nothing running -- which is the
    // same thing an ended game looks like. Copying there would fire on every
    // single launch and call it the end of a session.
    running.ids = [];
    watchOne(78, "emu:rpcs3");
    vi.advanceTimersByTime(TICK * 3);
    expect(copied.calls).toEqual([]);

    running.ids = [78];
    vi.advanceTimersByTime(TICK);
    expect(copied.calls).toEqual([]);

    running.ids = [];
    vi.advanceTimersByTime(TICK);
    expect(copied.calls).toEqual(["emu:rpcs3"]);
  });

  it("stops looking once it has copied", () => {
    running.ids = [79];
    watchOne(79, "emu:xemu");
    vi.advanceTimersByTime(TICK);
    running.ids = [];
    vi.advanceTimersByTime(TICK * 5);
    expect(copied.calls).toEqual(["emu:xemu"]);
  });

  it("ignores a second watch of a game already being watched", () => {
    // A relaunch while the first watch is still live would otherwise leave two
    // intervals on one game and copy twice.
    running.ids = [80];
    watchOne(80, "emu:cemu");
    watchOne(80, "emu:cemu");
    vi.advanceTimersByTime(TICK);
    running.ids = [];
    vi.advanceTimersByTime(TICK);
    expect(copied.calls).toEqual(["emu:cemu"]);
  });

  it("gives up on a game that never ends rather than leaving a timer forever", () => {
    running.ids = [81];
    watchOne(81, "emu:ppsspp");
    vi.advanceTimersByTime(9 * 60 * 60 * 1000);
    running.ids = [];
    vi.advanceTimersByTime(TICK * 2);
    // The watch was abandoned, so nothing is copied -- and, more to the point,
    // no interval is still running eight hours later.
    expect(copied.calls).toEqual([]);
  });
});
