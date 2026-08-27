import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The panel half of the launch gate.
 *
 * The launcher script is what stops a second game; this side collects that
 * decision and asks about it. So what matters here is *deference*: it must not
 * put a dialog up for a launch that was not stopped, must not stop one that was
 * never ours, and must not launch on approval it did not get. Each of those
 * shows up on a device as either a dialog over a running game or a game that
 * will not start, and neither reads as a bug in this file.
 *
 * `./LaunchConflictModal` is mocked because it renders and `react` is not an
 * installed package here; `./backend` because its `callable()` bindings run at
 * import time. `./steam` is real, against the fake Steam globals the rest of the
 * suite uses.
 */

const showLaunchConflict = vi.fn();
const launchBounced = vi.fn();
const approveLaunch = vi.fn();
const addedGame = vi.fn();
const launchNoticesForGame = vi.fn();
const showFixNotice = vi.fn();

vi.mock("./LaunchConflictModal", () => ({
  showLaunchConflict: (...args: unknown[]) => showLaunchConflict(...args),
}));
// Same boundary, same reason: this module renders, so it cannot be imported
// here -- and the decision to open it is what is being tested, not the dialog.
vi.mock("./FixNoticeModal", () => ({
  showFixNotice: (...args: unknown[]) => showFixNotice(...args),
}));
vi.mock("./backend", () => ({
  launchBounced: (...args: unknown[]) => launchBounced(...args),
  approveLaunch: (...args: unknown[]) => approveLaunch(...args),
  launchNoticesForGame: (...args: unknown[]) => launchNoticesForGame(...args),
}));
vi.mock("./addedGames", () => ({ addedGame: (...args: unknown[]) => addedGame(...args) }));
vi.mock("./logError", () => ({ logError: vi.fn() }));

const { watchLaunches, namedFromIds } = await import("./launchGate");

const OURS = { app_id: 100, title: "Donkey Kong Country", core_id: "emu:shadps4" };

/** A Steam with `running` up, recording every launch it is asked for. */
function installSteam(running: { appid: number; display_name: string }[] = []) {
  const launched: string[] = [];
  (globalThis as Record<string, unknown>).appStore = {
    GetAppOverviewByAppID: (appId: number) => ({ appid: appId, gameid: `gid-${appId}` }),
    GetAppOverviewByGameID: (gameId: string) => ({ appid: Number(gameId.replace("gid-", "")) }),
  };
  (globalThis as Record<string, unknown>).SteamUIStore = { RunningApps: running };
  (globalThis as Record<string, unknown>).SteamClient = {
    Apps: {
      RunGame: (gameId: string) => launched.push(gameId),
      RegisterForGameActionStart: (cb: (a: number, g: string, s: string) => void) => {
        fire = cb;
        return { unregister: () => (fire = null) };
      },
    },
  };
  return launched;
}

let fire: ((actionId: number, gameId: string, action: string) => void) | null = null;

/** Let the polling loop and its awaits run. */
const settle = async () => {
  for (let i = 0; i < 30; i += 1) await Promise.resolve();
};

beforeEach(() => {
  for (const spy of [showLaunchConflict, launchBounced, approveLaunch, addedGame,
                     launchNoticesForGame, showFixNotice]) {
    spy.mockReset();
  }
  addedGame.mockReturnValue(undefined);
  launchBounced.mockResolvedValue({ bounced: false, others: "" });
  approveLaunch.mockResolvedValue({ ok: true });
  launchNoticesForGame.mockResolvedValue({ notices: [] });
});

afterEach(() => {
  fire = null;
  for (const key of ["SteamClient", "appStore", "SteamUIStore"]) {
    delete (globalThis as Record<string, unknown>)[key];
  }
});

describe("watchLaunches", () => {
  it("ignores a game this plugin did not add", async () => {
    // Somebody else's launcher, which we neither gate nor get to comment on.
    installSteam([{ appid: 7, display_name: "PARANORMASIGHT" }]);
    watchLaunches();
    fire!(1, "gid-7", "LaunchApp");
    await settle();
    expect(launchBounced).not.toHaveBeenCalled();
    expect(showLaunchConflict).not.toHaveBeenCalled();
  });

  /**
   * The notice about a fix the emulator no longer needs.
   *
   * Said as the game starts because that is where it is read: the same words in
   * a settings page reach only people who were already going to open it, and
   * they are not the ones still running a retired fix.
   */
  it("says so when a game launches with a fix its emulator has retired", async () => {
    installSteam();
    addedGame.mockReturnValue({ ...OURS, core_id: "emu:retired" });
    const notice = {
      id: "motion",
      name: "Motion controls",
      state: "retired",
      note: "The emulator has this fixed now. You can switch it off.",
    };
    launchNoticesForGame.mockResolvedValue({ notices: [notice] });
    watchLaunches();

    fire!(1, "gid-100", "LaunchApp");
    await settle();
    // The sentence comes from the backend and is passed through untouched --
    // the row, the Emulators tab and this dialog all show that one string, so
    // none of them can word the same fact differently.
    expect(showFixNotice).toHaveBeenCalledWith([notice]);

    // Once per emulator, not once per launch. A dialog every time is how a
    // notice becomes something people dismiss without reading -- and this one
    // stands in front of a game somebody just pressed play on.
    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showFixNotice).toHaveBeenCalledTimes(1);
  });

  /**
   * The mirror case, and the one that is otherwise invisible: the switch says
   * on, the emulator behaves as though it were off, and without this nothing
   * anywhere says why.
   */
  it("says so when a fix could not be applied to the installed build", async () => {
    installSteam();
    addedGame.mockReturnValue({ ...OURS, core_id: "emu:unpatched" });
    launchNoticesForGame.mockResolvedValue({
      notices: [{
        id: "vita-motion",
        name: "Motion controls",
        state: "unavailable",
        note: "This build of the emulator would not take the fix, so it is not running.",
      }],
    });
    watchLaunches();

    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showFixNotice).toHaveBeenCalledTimes(1);
    expect(showFixNotice.mock.calls[0][0][0]).toMatchObject({
      id: "vita-motion",
      state: "unavailable",
    });
  });

  it("says nothing when there is nothing to report", async () => {
    installSteam();
    addedGame.mockReturnValue({ ...OURS, core_id: "emu:quiet" });
    watchLaunches();

    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showFixNotice).not.toHaveBeenCalled();
  });

  // A launch is not ours to fail. The game is starting either way, and a notice
  // that could stop it would be a worse bug than the one it mentions.
  it("still gates the launch when the notice cannot be fetched", async () => {
    installSteam();
    addedGame.mockReturnValue({ ...OURS, core_id: "emu:broken" });
    launchNoticesForGame.mockRejectedValue(new Error("backend is down"));
    launchBounced.mockResolvedValue({ bounced: true, others: "77" });
    watchLaunches();

    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showLaunchConflict).toHaveBeenCalledTimes(1);
  });

  it("says nothing when our game launched normally", async () => {
    // The whole point of asking the launcher instead of working it out here: no
    // note means nothing was stopped, so a dialog would be over a running game.
    installSteam();
    addedGame.mockReturnValue(OURS);
    watchLaunches();
    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showLaunchConflict).not.toHaveBeenCalled();
  });

  it("asks once the launcher says it refused", async () => {
    installSteam([{ appid: 7, display_name: "PARANORMASIGHT" }]);
    addedGame.mockReturnValue(OURS);
    launchBounced.mockResolvedValue({ bounced: true, others: "7" });
    watchLaunches();
    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showLaunchConflict).toHaveBeenCalledTimes(1);
    const asked = showLaunchConflict.mock.calls[0][0];
    expect(asked.title).toBe("Donkey Kong Country");
    expect(asked.running.map((g: { title: string }) => g.title)).toEqual(["PARANORMASIGHT"]);
  });

  it("falls back to the ids the launcher saw when Steam's list is empty", async () => {
    // The two are read a moment apart. The dialog puts running[0] into a
    // sentence, so it must never open with nothing behind it.
    installSteam();
    addedGame.mockReturnValue(OURS);
    launchBounced.mockResolvedValue({ bounced: true, others: "7 9" });
    watchLaunches();
    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showLaunchConflict.mock.calls[0][0].running).toHaveLength(2);
  });

  it("approves before relaunching, so the second attempt is not stopped too", async () => {
    const launched = installSteam([{ appid: 7, display_name: "PARANORMASIGHT" }]);
    addedGame.mockReturnValue(OURS);
    launchBounced.mockResolvedValue({ bounced: true, others: "7" });
    watchLaunches();
    fire!(1, "gid-100", "LaunchApp");
    await settle();

    showLaunchConflict.mock.calls[0][0].onLaunch();
    await settle();
    expect(approveLaunch).toHaveBeenCalledWith(100);
    expect(launched).toEqual(["gid-100"]);
  });

  it("does not relaunch when the approval could not be written", async () => {
    // The token is what gets past the gate. Launching without it bounces again,
    // which is a loop with no way out -- better that nothing starts.
    const launched = installSteam([{ appid: 7, display_name: "PARANORMASIGHT" }]);
    addedGame.mockReturnValue(OURS);
    launchBounced.mockResolvedValue({ bounced: true, others: "7" });
    approveLaunch.mockRejectedValue(new Error("no"));
    watchLaunches();
    fire!(1, "gid-100", "LaunchApp");
    await settle();

    showLaunchConflict.mock.calls[0][0].onLaunch();
    await settle();
    expect(launched).toEqual([]);
  });

  it("gives up quietly when the backend cannot answer", async () => {
    // Nothing here can improve on a decision the launcher already made.
    installSteam();
    addedGame.mockReturnValue(OURS);
    launchBounced.mockRejectedValue(new Error("gone"));
    watchLaunches();
    fire!(1, "gid-100", "LaunchApp");
    await settle();
    expect(showLaunchConflict).not.toHaveBeenCalled();
  });

  it("stops listening when the plugin unmounts", async () => {
    installSteam();
    addedGame.mockReturnValue(OURS);
    launchBounced.mockResolvedValue({ bounced: true, others: "7" });
    watchLaunches()();
    expect(fire).toBeNull();
  });
});

describe("namedFromIds", () => {
  it("turns the launcher's list into something the dialog can show", () => {
    expect(namedFromIds("7 9")).toEqual([
      { appId: 7, title: "another game", gameId: "7" },
      { appId: 9, title: "another game", gameId: "9" },
    ]);
  });

  it("survives an empty note", () => {
    expect(namedFromIds("")).toEqual([]);
  });
});
