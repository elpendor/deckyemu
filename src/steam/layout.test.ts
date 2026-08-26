import { afterEach, describe, expect, it, vi } from "vitest";

import { GAMEPAD_TEMPLATE, needsGamepadLayout, pinGamepadLayout } from "./layout";

/**
 * Steam picks a layout for a shortcut by name, and sometimes picks a browser.
 *
 * The rule this file protects is that the repair stays narrow: it exists for
 * one failure -- a default Steam chose that cannot drive a gamepad -- and
 * touching anything else would mean overwriting a layout somebody set on
 * purpose, which is worse than the bug.
 */

const DECK = { eControllerType: 4, nControllerIndex: 15 };

/** Steam's globals, as much of them as this file reads. */
function stubSteam(readings: unknown[], controllers: unknown[] = [DECK]) {
  const setActive = vi.fn();
  const queue = [...readings];
  (globalThis as any).ControllerStore = {
    GetControllers: () => controllers,
    GetControllerTypeString: (type: number) =>
      type === 4 ? "controller_steamcontroller_neptune" : "controller_generic",
  };
  (globalThis as any).controllerConfiguratorStore = { SetActiveConfigForApp: setActive };
  (globalThis as any).SteamClient = {
    Input: {
      GetConfigForAppAndController: async () =>
        queue.length > 1 ? queue.shift() : queue[0],
    },
  };
  return setActive;
}

const browser = { Title: "Web Browser", URL: "default://sonic the hedgehog", bUsesGamepad: false };
const guessed = { Title: "Gamepad With Joystick Trackpad", URL: "default://cool spot", bUsesGamepad: true };
const fromExe = { Title: "Gamepad With Joystick Trackpad", URL: "default://cool-spot-81a69dfbsh", bUsesGamepad: true };
const chosen = { Title: "Mouse Only", URL: "template://controller_neptune_mouse.vdf", bUsesGamepad: false };

afterEach(() => {
  delete (globalThis as any).ControllerStore;
  delete (globalThis as any).controllerConfiguratorStore;
  delete (globalThis as any).SteamClient;
});

describe("what counts as a layout worth replacing", () => {
  it("replaces a default Steam guessed that cannot play a game", () => {
    expect(needsGamepadLayout(browser)).toBe(true);
  });

  it("leaves a default alone when it can", () => {
    expect(needsGamepadLayout(guessed)).toBe(false);
  });

  /*
   * The whole reason the URL is checked rather than just the gamepad flag.
   * "Mouse Only" on a point-and-click is a deliberate choice, and it reads as
   * `template://` because a person made it -- Steam's own guesses are always
   * `default://`. Judging on bUsesGamepad alone would undo somebody's work
   * every time their game was re-adopted.
   */
  it("leaves a layout somebody picked alone, gamepad or not", () => {
    expect(needsGamepadLayout(chosen)).toBe(false);
    expect(needsGamepadLayout({ ...browser, URL: "workshop://585907787" })).toBe(false);
  });

  it("says no to an answer it does not understand", () => {
    expect(needsGamepadLayout(null)).toBe(false);
    expect(needsGamepadLayout(undefined)).toBe(false);
    expect(needsGamepadLayout({} as never)).toBe(false);
  });
});

describe("pinning one", () => {
  /*
   * The sequence a real add produces: the first reading is keyed on the
   * executable, because Steam is asked before the name has landed, and it
   * always looks healthy. Judging that reading would miss every case this
   * exists for.
   */
  it("waits for the name key before judging", async () => {
    const setActive = stubSteam([fromExe, browser]);
    expect(await pinGamepadLayout(1234, 4)).toBe(true);
    expect(setActive).toHaveBeenCalledWith(1234, 15, GAMEPAD_TEMPLATE, false);
  });

  it("does nothing once the name key settles on something that works", async () => {
    const setActive = stubSteam([fromExe, guessed]);
    expect(await pinGamepadLayout(1234, 4)).toBe(false);
    expect(setActive).not.toHaveBeenCalled();
  });

  const GYRO = "template://controller_neptune_gamepad_mouse_gyro.vdf";

  /*
   * An emulator that names a layout is not repairing a broken one -- Vita3K's
   * gyro is off unless the running game's layout binds it, and the layout Steam
   * guesses plays the game perfectly well otherwise. So a working guess is
   * replaced here, where the no-template case leaves it alone.
   */
  it("applies a layout the emulator asked for over a working guess", async () => {
    const setActive = stubSteam([fromExe, guessed]);
    expect(await pinGamepadLayout(1234, 4, GYRO)).toBe(true);
    expect(setActive).toHaveBeenCalledWith(1234, 15, GYRO, false);
  });

  it("replaces the plugin's own gyro-less pin", async () => {
    const ours = { Title: "Gamepad", URL: GAMEPAD_TEMPLATE, bUsesGamepad: true };
    const setActive = stubSteam([fromExe, ours]);
    expect(await pinGamepadLayout(1234, 4, GYRO)).toBe(true);
    expect(setActive).toHaveBeenCalledWith(1234, 15, GYRO, false);
  });

  /*
   * The repair path. A game that already exists has no name key on its way --
   * the first reading is the answer -- and waiting for one to arrive timed out
   * on every game, which is how three Vita games kept Steam's layout through a
   * migration that reported nothing wrong.
   */
  it("pins a game that already exists without waiting for a key change", async () => {
    const setActive = stubSteam([guessed, guessed]);
    expect(await pinGamepadLayout(1234, 4, GYRO, true)).toBe(true);
    expect(setActive).toHaveBeenCalledWith(1234, 15, GYRO, false);
  });

  it("and still leaves that game alone when the layout is somebody's own", async () => {
    const setActive = stubSteam([chosen, chosen]);
    expect(await pinGamepadLayout(1234, 4, GYRO, true)).toBe(false);
    expect(setActive).not.toHaveBeenCalled();
  });

  it("still never overrides a layout somebody chose", async () => {
    const setActive = stubSteam([fromExe, chosen]);
    expect(await pinGamepadLayout(1234, 4, GYRO)).toBe(false);
    expect(setActive).not.toHaveBeenCalled();
  });

  it("does nothing when a layout was chosen for that name already", async () => {
    const setActive = stubSteam([fromExe, chosen]);
    expect(await pinGamepadLayout(1234, 4)).toBe(false);
    expect(setActive).not.toHaveBeenCalled();
  });

  /*
   * Each controller type takes templates of its own, and the neptune one would
   * be wrong on a pad. Steam's own default is what those get, which is what
   * they got before any of this existed.
   */
  it("stays out of it when the Deck's own controller is not there", async () => {
    const setActive = stubSteam([browser], [{ eControllerType: 1, nControllerIndex: 3 }]);
    expect(await pinGamepadLayout(1234, 4)).toBe(false);
    expect(setActive).not.toHaveBeenCalled();
  });

  it("survives Steam not having the calls at all", async () => {
    (globalThis as any).ControllerStore = {};
    (globalThis as any).SteamClient = {};
    await expect(pinGamepadLayout(1234, 2)).resolves.toBe(false);
  });
});
