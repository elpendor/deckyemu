import { describe, expect, it, vi, beforeEach } from "vitest";

const gamesNeedingLayout = vi.fn();
const pinGamepadLayout = vi.fn();
const unpinEmulatorLayout = vi.fn();

vi.mock("./backend", () => ({ gamesNeedingLayout: () => gamesNeedingLayout() }));
vi.mock("./steam", () => ({
  pinGamepadLayout: (
    appId: number,
    attempts: number,
    layout: string,
    settled?: boolean,
    restore?: boolean,
  ) => pinGamepadLayout(appId, attempts, layout, settled, restore),
  unpinEmulatorLayout: (appId: number) => unpinEmulatorLayout(appId),
}));
vi.mock("./logError", () => ({ logError: () => undefined }));

const { repairGameLayouts } = await import("./repairLayouts");

const GYRO = "template://deckyemu_controller_neptune_gamepad_gyro.vdf";

describe("repairing layouts for games added earlier", () => {
  beforeEach(() => {
    gamesNeedingLayout.mockReset();
    pinGamepadLayout.mockReset();
    unpinEmulatorLayout.mockReset();
    pinGamepadLayout.mockResolvedValue(true);
  });

  /**
   * The other direction, and the one that bit: an emulator whose motion has
   * been switched off wants its games taken *off* the gyro layout. Leaving it
   * pinned is worse than never having pinned it -- the layout sends gyro to the
   * right stick, and with motion off the emulator reads Steam's virtual pad,
   * which is what receives it, so tilting the Deck drifts the camera.
   */
  it("takes games off the gyro layout when their emulator's motion is off", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: "" },
      { app_id: 22, layout: GYRO },
    ]);
    pinGamepadLayout.mockResolvedValue(true);
    unpinEmulatorLayout.mockResolvedValue(true);

    await repairGameLayouts();

    // Un-pinning asks what the game is *wearing* rather than why, which is
    // what keeps it working after the workaround is deleted from the catalog.
    expect(unpinEmulatorLayout).toHaveBeenCalledWith(11);
    expect(pinGamepadLayout).toHaveBeenCalledWith(22, 8, GYRO, true, undefined);
  });

  /**
   * The gap this closed. Every game of a plugin-managed emulator is now
   * reported, so a game still wearing a layout from a workaround that no longer
   * exists is offered for un-pinning -- previously nothing described that layout
   * any more, so nothing asked for it back and the game kept it forever.
   */
  it("offers games whose emulator no longer asks for any layout", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: "" },
      { app_id: 22, layout: "" },
    ]);
    unpinEmulatorLayout.mockResolvedValueOnce(true).mockResolvedValueOnce(false);

    // Counted only where something actually moved: a game on a layout of its
    // own is left alone and `unpinEmulatorLayout` says so.
    expect(await repairGameLayouts()).toBe(1);
    expect(pinGamepadLayout).not.toHaveBeenCalled();
  });

  it("gives each game the layout its emulator needs", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: GYRO },
      { app_id: 22, layout: GYRO },
    ]);
    expect(await repairGameLayouts()).toBe(2);
    expect(pinGamepadLayout).toHaveBeenCalledWith(11, 8, GYRO, true, undefined);
    expect(pinGamepadLayout).toHaveBeenCalledWith(22, 8, GYRO, true, undefined);
  });

  /*
   * The count is what was changed, not what was looked at. A game already on
   * the right layout reads back as an explicit selection and is left alone by
   * `pinGamepadLayout`, which is what makes running this every start harmless.
   */
  it("counts only the games it actually changed", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: GYRO },
      { app_id: 22, layout: GYRO },
    ]);
    pinGamepadLayout.mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    expect(await repairGameLayouts()).toBe(1);
  });

  /*
   * An empty layout used to mean "nothing to do" and now means "put this game
   * back on a plain gamepad layout", so the only entry with nothing to apply is
   * one that was never added to Steam.
   */
  it("skips entries that were never added to Steam", async () => {
    gamesNeedingLayout.mockResolvedValue([{ app_id: 0, layout: GYRO }]);
    expect(await repairGameLayouts()).toBe(0);
    expect(pinGamepadLayout).not.toHaveBeenCalled();
  });

  /*
   * A start that cannot reach the backend is a start, not a failure: the cost
   * of giving up here is motion missing in games that were already missing it.
   */
  it("survives a backend that will not answer", async () => {
    gamesNeedingLayout.mockRejectedValue(new Error("no backend"));
    expect(await repairGameLayouts()).toBe(0);
    expect(pinGamepadLayout).not.toHaveBeenCalled();
  });

  it("keeps going when one game throws", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: GYRO },
      { app_id: 22, layout: GYRO },
    ]);
    pinGamepadLayout.mockRejectedValueOnce(new Error("steam said no"));
    expect(await repairGameLayouts()).toBe(1);
    expect(pinGamepadLayout).toHaveBeenCalledTimes(2);
  });
});
