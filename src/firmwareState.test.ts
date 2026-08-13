import { describe, expect, it } from "vitest";

import {
  firmwareState,
  STATE_COLOR,
  STATE_TITLE,
  worstState,
  type FirmwareCounts,
} from "./firmwareState";

const req = (installed: string[] = [], waiting: string[] = []): FirmwareCounts => ({
  installed,
  waiting,
});

describe("firmwareState", () => {
  it("is installed when something is in place", () => {
    expect(firmwareState(req(["keys.txt"]))).toBe("installed");
  });

  it("is missing when nothing is anywhere", () => {
    expect(firmwareState(req())).toBe("missing");
  });

  it("is waiting when the file is here but not installed", () => {
    expect(firmwareState(req([], ["keys.txt"]))).toBe("waiting");
  });

  /*
   * Importing reads the source file rather than moving it, so a satisfied
   * requirement routinely still has its .PUP sitting in the transfer folder.
   * Flagging that as needing attention would mean RPCS3's firmware row asked to
   * be dealt with forever, for a file the row itself describes as no longer
   * needed.
   */
  it("counts installed-with-leftovers as done, not outstanding", () => {
    expect(firmwareState(req(["4.93"], ["PS3UPDAT.PUP"]))).toBe("installed");
  });
});

describe("worstState", () => {
  it("reports the thing most worth knowing", () => {
    expect(worstState([req(["a"]), req(), req([], ["b"])])).toBe("missing");
    expect(worstState([req(["a"]), req([], ["b"])])).toBe("waiting");
    expect(worstState([req(["a"]), req(["b"])])).toBe("installed");
  });

  // xemu asks for two dumps and a disk image. One satisfied requirement must
  // not make the emulator look ready when another is still missing.
  it("does not let one satisfied requirement mask an unmet one", () => {
    expect(worstState([req(["mcpx.bin"]), req()])).toBe("missing");
  });

  // An emulator with nothing to ask for never reaches this panel, but a state
  // machine that answers "missing" for an empty set would be a trap for the
  // next person who reuses it.
  it("treats nothing to supply as fine", () => {
    expect(worstState([])).toBe("installed");
  });
});

describe("the colours", () => {
  /*
   * On a fresh install every requirement is missing. A column of red says the
   * plugin is broken; amber says it is your turn. Red stays for things that
   * actually failed.
   */
  it("does not paint an unmet prerequisite as an error", () => {
    expect(STATE_COLOR.missing).not.toBe("#e35d5d");
    expect(STATE_COLOR.missing).toBe(STATE_COLOR.waiting);
  });

  it("sets installed apart from the two that want something", () => {
    expect(STATE_COLOR.installed).not.toBe(STATE_COLOR.missing);
  });

  it("names every state", () => {
    for (const state of ["installed", "waiting", "missing"] as const) {
      expect(STATE_TITLE[state].length).toBeGreaterThan(0);
      expect(STATE_COLOR[state]).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});
