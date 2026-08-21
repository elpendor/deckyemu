import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Starting a game from inside a modal, and what happens when one is already on.
 *
 * Two things here fail only on a device and never as an error. The modal has to
 * be gone *before* Steam is asked to launch, because Steam re-reveals each modal
 * as the one above it dismisses and a game cannot be backed out of the way a
 * page can. And when something is already running the order inverts: the list
 * has to still be there, because it is what the dialog's Cancel goes back to.
 * Getting either wrong looks like a layout quirk rather than a bug, which is the
 * shape of thing this suite exists for.
 *
 * `@decky/api` is mocked because it does not load under Node (see
 * `addGame.test.ts`), and `./LaunchConflictModal` because it renders: `react` is
 * not an installed package here, so importing anything that does takes the file
 * down before a check runs. What the dialog would have been handed is asserted
 * instead, which is the part this module decides.
 *
 * `./steam` is not mocked: whether a launch is even attempted is half of what is
 * being checked, so it runs for real against the fake Steam globals the rest of
 * the suite uses.
 */

const toast = vi.fn();
const showLaunchConflict = vi.fn();
vi.mock("@decky/api", () => ({ toaster: { toast: (...args: unknown[]) => toast(...args) } }));
vi.mock("./LaunchConflictModal", () => ({
  showLaunchConflict: (...args: unknown[]) => showLaunchConflict(...args),
}));

const { playGame } = await import("./playGame");

/** A Steam that records the order things happened in. */
function installSteam({
  accepts = true,
  running = [] as { appid: number; display_name: string; gameid?: string }[],
} = {}) {
  const order: string[] = [];
  (globalThis as Record<string, unknown>).appStore = {
    GetAppOverviewByAppID: (appId: number) => ({ appid: appId, gameid: `gid-${appId}` }),
  };
  (globalThis as Record<string, unknown>).SteamUIStore = { RunningApps: running };
  (globalThis as Record<string, unknown>).SteamClient = {
    Apps: {
      RunGame: (...args: unknown[]) => {
        order.push(`RunGame(${String(args[0])})`);
        if (!accepts) throw new Error("no");
      },
      TerminateApp: (...args: unknown[]) => order.push(`TerminateApp(${String(args[0])})`),
    },
  };
  return order;
}

beforeEach(() => {
  toast.mockClear();
  showLaunchConflict.mockClear();
});

afterEach(() => {
  for (const key of ["SteamClient", "appStore", "SteamUIStore", "LocalizationManager"]) {
    delete (globalThis as Record<string, unknown>)[key];
  }
});

describe("playGame with nothing else running", () => {
  it("dismisses the modal before asking Steam to launch", () => {
    const order = installSteam();
    expect(playGame(42, "A Game", () => order.push("dismiss"))).toBe("launched");
    expect(order).toEqual(["dismiss", "RunGame(gid-42)"]);
    expect(showLaunchConflict).not.toHaveBeenCalled();
  });

  it("launches with no modal to dismiss", () => {
    const order = installSteam();
    expect(playGame(42, "A Game")).toBe("launched");
    expect(order).toEqual(["RunGame(gid-42)"]);
  });

  it("says so when Steam refuses, having already closed the modal", () => {
    // The modal is gone by then, so the toast is the only place left to say it
    // -- which is why the message names the library as the way through.
    const order = installSteam({ accepts: false });
    expect(playGame(42, "A Game", () => order.push("dismiss"))).toBe("refused");
    expect(order).toEqual(["dismiss", "RunGame(gid-42)"]);
    expect(toast.mock.calls[0][0].title).toBe("Could not start the game");
  });

  it("still closes the modal when Steam has no RunGame at all", () => {
    // A Steam update that renames the method degrades one button; it must not
    // leave the list sitting there with nothing having happened and no toast.
    const dismiss = vi.fn();
    (globalThis as Record<string, unknown>).SteamClient = { Apps: {} };
    expect(playGame(42, "A Game", dismiss)).toBe("refused");
    expect(dismiss).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("treats an unreadable running-apps store as nothing running", () => {
    // A rename here should cost the warning, not the play button.
    const order = installSteam();
    (globalThis as Record<string, unknown>).SteamUIStore = {};
    expect(playGame(42, "A Game")).toBe("launched");
    expect(order).toEqual(["RunGame(gid-42)"]);
  });

  it("does not count the game being launched as a conflict", () => {
    // Relaunching what is already on is not two games at once, and a dialog
    // about the game you just pressed would be a dialog about itself.
    const order = installSteam({ running: [{ appid: 42, display_name: "A Game" }] });
    expect(playGame(42, "A Game")).toBe("launched");
    expect(order).toEqual(["RunGame(gid-42)"]);
  });
});

describe("playGame with another game running", () => {
  const RUNNING = [{ appid: 7, display_name: "Mina the Hollower", gameid: "7" }];

  it("asks instead of launching, and leaves the list standing to go back to", () => {
    const order = installSteam({ running: RUNNING });
    const dismiss = vi.fn();
    expect(playGame(42, "A Game", dismiss)).toBe("asked");
    expect(order).toEqual([]);
    expect(dismiss).not.toHaveBeenCalled();
    expect(showLaunchConflict).toHaveBeenCalledTimes(1);
  });

  it("hands the dialog what is running and what was asked for", () => {
    installSteam({ running: RUNNING });
    playGame(42, "A Game");
    const props = showLaunchConflict.mock.calls[0][0];
    expect(props.title).toBe("A Game");
    expect(props.running).toEqual([
      { appId: 7, title: "Mina the Hollower", gameId: "7" },
    ]);
  });

  it("dismisses and launches only once the dialog says to", () => {
    // The same ordering as the plain path, moved to the far side of the
    // question: nothing may be left over the game once it is actually starting.
    const order = installSteam({ running: RUNNING });
    playGame(42, "A Game", () => order.push("dismiss"));
    showLaunchConflict.mock.calls[0][0].onLaunch();
    expect(order).toEqual(["dismiss", "RunGame(gid-42)"]);
  });

  it("names every running game, so closing them all is one decision", () => {
    installSteam({
      running: [
        { appid: 7, display_name: "Mina the Hollower", gameid: "7" },
        { appid: 9, display_name: "Balatro", gameid: "9" },
      ],
    });
    playGame(42, "A Game");
    expect(showLaunchConflict.mock.calls[0][0].running.map((g: { appId: number }) => g.appId)).toEqual(
      [7, 9],
    );
  });

  it("falls back to a name when Steam has none for what is running", () => {
    // The dialog puts this straight into a sentence, so an empty string would
    // read as "You are currently running .".
    installSteam({ running: [{ appid: 7, display_name: "" }] });
    playGame(42, "A Game");
    expect(showLaunchConflict.mock.calls[0][0].running[0].title).toBe("another game");
  });
});
