import { describe, expect, it, vi, beforeEach } from "vitest";

const gamesNeedingLayout = vi.fn();
const pinGamepadLayout = vi.fn();

vi.mock("./backend", () => ({ gamesNeedingLayout: () => gamesNeedingLayout() }));
vi.mock("./steam", () => ({
  pinGamepadLayout: (appId: number, attempts: number, layout: string) =>
    pinGamepadLayout(appId, attempts, layout),
}));
vi.mock("./logError", () => ({ logError: () => undefined }));

const { repairGameLayouts } = await import("./repairLayouts");

const GYRO = "template://deckyemu_controller_neptune_gamepad_gyro.vdf";

describe("repairing layouts for games added earlier", () => {
  beforeEach(() => {
    gamesNeedingLayout.mockReset();
    pinGamepadLayout.mockReset();
    pinGamepadLayout.mockResolvedValue(true);
  });

  it("gives each game the layout its emulator needs", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: GYRO },
      { app_id: 22, layout: GYRO },
    ]);
    expect(await repairGameLayouts()).toBe(2);
    expect(pinGamepadLayout).toHaveBeenCalledWith(11, 8, GYRO);
    expect(pinGamepadLayout).toHaveBeenCalledWith(22, 8, GYRO);
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

  it("skips entries with nothing to apply", async () => {
    gamesNeedingLayout.mockResolvedValue([
      { app_id: 11, layout: "" },
      { app_id: 0, layout: GYRO },
    ]);
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
