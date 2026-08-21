import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Starting a game from inside a modal.
 *
 * There is only one thing here worth a check and it is the ordering: the modal
 * has to be gone *before* Steam is asked to launch, because Steam re-reveals
 * each modal as the one above it dismisses and a game cannot be backed out of
 * the way a page can. Nothing about that is visible in the types, it fails only
 * on a real device, and it fails as "the panel is over my game" rather than as
 * an error -- which is exactly the shape of thing this suite exists for.
 *
 * `@decky/api` is mocked because it will not load under Node (see
 * `addGame.test.ts`). `./steam` is not: whether the launch is even attempted is
 * half of what is being checked, so it runs for real against the fake Steam
 * globals the rest of the suite uses.
 */

const toast = vi.fn();
vi.mock("@decky/api", () => ({ toaster: { toast: (...args: unknown[]) => toast(...args) } }));

const { playGame } = await import("./playGame");

/** A Steam that records the order things happened in. */
function installSteam({ accepts = true }: { accepts?: boolean } = {}) {
  const order: string[] = [];
  (globalThis as Record<string, unknown>).appStore = {
    GetAppOverviewByAppID: (appId: number) => ({ appid: appId, gameid: `gid-${appId}` }),
  };
  (globalThis as Record<string, unknown>).SteamClient = {
    Apps: {
      RunGame: (...args: unknown[]) => {
        order.push(`RunGame(${String(args[0])})`);
        if (!accepts) throw new Error("no");
      },
    },
  };
  return order;
}

beforeEach(() => {
  toast.mockClear();
});

afterEach(() => {
  delete (globalThis as Record<string, unknown>).SteamClient;
  delete (globalThis as Record<string, unknown>).appStore;
});

describe("playGame", () => {
  it("dismisses the modal before asking Steam to launch", () => {
    const order = installSteam();
    expect(playGame(42, () => order.push("dismiss"))).toBe(true);
    expect(order).toEqual(["dismiss", "RunGame(gid-42)"]);
  });

  it("launches with no modal to dismiss", () => {
    // The panel's own row has nothing stacked over it.
    const order = installSteam();
    expect(playGame(42)).toBe(true);
    expect(order).toEqual(["RunGame(gid-42)"]);
  });

  it("says so when Steam refuses, having already closed the modal", () => {
    // The modal is gone by then, so the toast is the only place left to say it
    // -- which is why the message names the library as the way through.
    const order = installSteam({ accepts: false });
    expect(playGame(42, () => order.push("dismiss"))).toBe(false);
    expect(order).toEqual(["dismiss", "RunGame(gid-42)"]);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(toast.mock.calls[0][0].title).toBe("Could not start the game");
  });

  it("still closes the modal when Steam has no RunGame at all", () => {
    // A Steam update that renames the method degrades one button; it must not
    // leave the list sitting there with nothing having happened and no toast.
    const dismiss = vi.fn();
    (globalThis as Record<string, unknown>).SteamClient = { Apps: {} };
    expect(playGame(42, dismiss)).toBe(false);
    expect(dismiss).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("does not toast on success", () => {
    installSteam();
    playGame(42);
    expect(toast).not.toHaveBeenCalled();
  });
});
