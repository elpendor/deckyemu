import { describe, expect, it } from "vitest";

import { blockScreen } from "./blockGate";

describe("the panel when the backend stays off", () => {
  it("shows nothing when the backend is on", () => {
    expect(blockScreen(undefined)).toBeNull();
  });

  it("names the build that holds the state, as it names itself", () => {
    const screen = blockScreen({ reason: "running", build: "The DeckyEmu service", version: "0.20.0" });
    expect(screen?.title).toBe("DeckyEmu is already running");
    expect(screen?.body).toMatch(/^The DeckyEmu service 0\.20\.0 is running/);
  });

  it("still reads as a sentence when the holder said nothing of itself", () => {
    expect(blockScreen({ reason: "running" })?.body).toMatch(/^Another DeckyEmu is running/);
  });

  it("asks for an update when the data is newer than this build reads", () => {
    expect(blockScreen({ reason: "format" })?.title).toBe("Update DeckyEmu");
  });

  it("explains a reason it does not know rather than showing nothing", () => {
    expect(blockScreen({ reason: "something-new" })?.title).toBe("DeckyEmu is off");
  });
});
