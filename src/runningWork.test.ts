import { describe, expect, it } from "vitest";

import { isRunning, runningId } from "./runningWork";

/**
 * A panel that opens mid-install must know to draw the bar, not the button.
 *
 * Steam throws a panel's state away whenever the Quick Access panel closes, so
 * "running" held in a component came back false while the install was still
 * going -- and pressing the button again started a second `flatpak install` of
 * the same app. The backend now refuses the duplicate; these are the half that
 * lets the panel show the truth instead of offering the press.
 */
describe("what is still running", () => {
  const work = [
    { event: "retroarch_install_done", args: [] },
    { event: "emulator_install_done", args: ["cemu"] },
  ];

  it("sees an install that has no id", () => {
    expect(isRunning(work, "retroarch_install_done")).toBe(true);
  });

  it("says no for work that is not there", () => {
    expect(isRunning([], "retroarch_install_done")).toBe(false);
    expect(isRunning(work, "emulator_build_done")).toBe(false);
  });

  it("names the emulator an install is for, so its row is the busy one", () => {
    expect(runningId(work, "emulator_install_done")).toBe("cemu");
  });

  it("names nobody when nothing is running", () => {
    expect(runningId([], "emulator_install_done")).toBe("");
  });

  // A row marked busy for something it did not start is the failure to avoid:
  // it would spin until the next reload with nothing able to finish it.
  it("does not guess an id from work that carries none", () => {
    expect(runningId(work, "retroarch_install_done")).toBe("");
  });

  it("ignores an argument that is not an id", () => {
    expect(runningId([{ event: "emulator_install_done", args: [42] }], "emulator_install_done")).toBe("");
  });
});
