import { beforeEach, describe, expect, it, vi } from "vitest";

const listAdded = vi.fn();
const gamesWithoutIcon = vi.fn();
const gameIcon = vi.fn();
const hasShortcutIcon = vi.fn();
const setShortcutIcon = vi.fn();

vi.mock("./backend", () => ({
  listAdded: () => listAdded(),
  gamesWithoutIcon: () => gamesWithoutIcon(),
  gameIcon: (appId: number, data: string) => gameIcon(appId, data),
}));
vi.mock("./steam", () => ({
  hasShortcutIcon: (appId: number) => hasShortcutIcon(appId),
  setShortcutIcon: (appId: number, path: string) => setShortcutIcon(appId, path),
}));
vi.mock("./logError", () => ({ logError: () => undefined }));

const { repairGameIcons } = await import("./repairIcons");

describe("giving older games an icon", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    listAdded.mockReset();
    gamesWithoutIcon.mockReset().mockResolvedValue([]);
    gameIcon.mockReset().mockResolvedValue({ path: "/plugin/assets/game-icon.png" });
    hasShortcutIcon.mockReset();
    setShortcutIcon.mockReset().mockReturnValue(true);
  });

  /** The loop sleeps between games, so the timers have to be run for it. */
  async function run() {
    const finished = repairGameIcons();
    await vi.runAllTimersAsync();
    return finished;
  }

  it("sets one on a game that has none", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }]);
    gamesWithoutIcon.mockResolvedValue([{ app_id: 1, title: "One" }]);
    hasShortcutIcon.mockReturnValue(false);

    expect(await run()).toBe(1);
    expect(setShortcutIcon).toHaveBeenCalledWith(1, "/plugin/assets/game-icon.png");
  });

  it("leaves an icon that is already there alone", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }]);
    gamesWithoutIcon.mockResolvedValue([{ app_id: 1, title: "One" }]);
    hasShortcutIcon.mockReturnValue(true);

    expect(await run()).toBe(0);
    expect(setShortcutIcon).not.toHaveBeenCalled();
  });

  // Steam materialises overviews as it loads. Reading "not said yet" as "no
  // icon" would set the shipped tile over an icon that was simply not visible.
  it("skips a game Steam has not described yet, rather than guessing", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }]);
    gamesWithoutIcon.mockResolvedValue([{ app_id: 1, title: "One" }]);
    hasShortcutIcon.mockReturnValue(undefined);

    expect(await run()).toBe(0);
    expect(gameIcon).not.toHaveBeenCalled();
  });

  // The whole reason the backfill exists is that it costs nothing. Asking for
  // artwork here would be a SteamGridDB search per game on every start.
  it("never asks for artwork, only the shipped picture", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }, { app_id: 2 }]);
    gamesWithoutIcon.mockResolvedValue([
      { app_id: 1, title: "One" },
      { app_id: 2, title: "Two" },
    ]);
    hasShortcutIcon.mockReturnValue(false);

    await run();
    expect(gameIcon.mock.calls).toEqual([
      [1, ""],
      [2, ""],
    ]);
  });

  it("carries on past a game that failed", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }, { app_id: 2 }]);
    gamesWithoutIcon.mockResolvedValue([
      { app_id: 1, title: "One" },
      { app_id: 2, title: "Two" },
    ]);
    hasShortcutIcon.mockReturnValue(false);
    gameIcon.mockRejectedValueOnce(new Error("no"));

    expect(await run()).toBe(1);
    expect(setShortcutIcon).toHaveBeenCalledWith(2, "/plugin/assets/game-icon.png");
  });

  /*
   * The regression this exists for. Steam's overview can read "no icon" for a
   * few seconds after a reload, and the first version of this trusted it -- so
   * it wrote the plain tile over the real icons a whole library had just been
   * given. A game we hold a file for is never asked about.
   */
  it("re-points a game we have an icon for, whatever Steam says", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }]);
    gamesWithoutIcon.mockResolvedValue([]); // we have a file for it
    hasShortcutIcon.mockReturnValue(false); // and Steam says there is none
    gameIcon.mockResolvedValue({ path: "/icons/1.png" });

    expect(await run()).toBe(1);
    expect(setShortcutIcon).toHaveBeenCalledWith(1, "/icons/1.png");
  });

  it("does nothing at all when the library cannot be read", async () => {
    listAdded.mockRejectedValue(new Error("gone"));

    expect(await run()).toBe(0);
    expect(setShortcutIcon).not.toHaveBeenCalled();
  });

  // A path the backend refused to name is a file that is not there, and Steam
  // would record it anyway.
  it("does not hand Steam an empty path", async () => {
    listAdded.mockResolvedValue([{ app_id: 1 }]);
    gamesWithoutIcon.mockResolvedValue([{ app_id: 1, title: "One" }]);
    hasShortcutIcon.mockReturnValue(false);
    gameIcon.mockResolvedValue({ path: "" });

    expect(await run()).toBe(0);
    expect(setShortcutIcon).not.toHaveBeenCalled();
  });
});
