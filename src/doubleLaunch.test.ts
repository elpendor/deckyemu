import { describe, expect, it, vi } from "vitest";

/**
 * Deciding whether two running games are worth mentioning.
 *
 * The whole of what can go wrong here is saying something when nobody wanted to
 * hear it. This fires on *every* app Steam brings up, the user's entire library
 * included, so the rules about staying quiet matter more than the rule about
 * speaking: a toast on somebody else's launch is noise the plugin has no
 * business making, and Steam has already shown its own dialog for the case
 * where both sides are its own.
 *
 * Three mocks, none of them reached by the pure functions below -- they are
 * what the module under test imports. `@decky/api` does not load under Node,
 * `./LaunchConflictModal` renders, and `./addedGames` reaches `./backend`,
 * whose `callable()` bindings run at import time.
 */

vi.mock("@decky/api", () => ({ toaster: { toast: vi.fn() } }));
vi.mock("./LaunchConflictModal", () => ({ showCloseRunning: vi.fn() }));
vi.mock("./addedGames", () => ({ addedGame: vi.fn() }));

const { othersToMention, stillRunningLine } = await import("./doubleLaunch");

const game = (appId: number, title: string) => ({ appId, title, gameId: String(appId) });

/** Two of ours: 100 and 101. Everything else is somebody else's. */
const ours = (appId: number) => appId === 100 || appId === 101;

describe("othersToMention", () => {
  it("says nothing when a game starts on its own", () => {
    expect(othersToMention(100, [], ours)).toBeNull();
  });

  it("names what was already running when one of ours starts over it", () => {
    const running = [game(7, "PARANORMASIGHT")];
    expect(othersToMention(100, running, ours)).toEqual(running);
  });

  it("also fires the other way round, which Steam misses too", () => {
    // A real Steam game launched over one of ours: Steam's check does not count
    // a running shortcut, so nobody warns unless this does.
    const running = [game(100, "Famicom Detective Club 1")];
    expect(othersToMention(7, running, ours)).toEqual(running);
  });

  it("stays out of it when neither side is ours", () => {
    // Steam showed its own dialog a second ago. Repeating it is noise about
    // somebody else's decision, on every launch the user makes.
    expect(othersToMention(7, [game(8, "Balatro")], ours)).toBeNull();
  });

  it("speaks up when one of several already-running games is ours", () => {
    const running = [game(8, "Balatro"), game(101, "Chrono Trigger")];
    expect(othersToMention(7, running, ours)).toEqual(running);
  });

  it("does not treat the game that just started as something to close", () => {
    // `runningGames` already excludes it, and this must not put it back: the
    // toast would offer to close the game the user just asked for.
    expect(othersToMention(100, [game(100, "itself")], ours)).toEqual([game(100, "itself")]);
  });
});

describe("stillRunningLine", () => {
  it("names the one game, because the name is the useful part", () => {
    expect(stillRunningLine([game(7, "PARANORMASIGHT")])).toBe(
      "PARANORMASIGHT is still running.",
    );
  });

  it("counts past one rather than listing them into a toast", () => {
    expect(stillRunningLine([game(7, "A"), game(8, "B")])).toBe(
      "2 other games are still running.",
    );
  });
});
