import { describe, expect, it } from "vitest";

import {
  firmwareState,
  optionalSummary,
  STATE_COLOR,
  STATE_TITLE,
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

  // A BIOS another emulator already holds is one press away, the same as one
  // just sent -- calling it missing would ask for a file the Deck already has.
  it("is waiting when another emulator already holds the file", () => {
    expect(
      firmwareState({ ...req(), elsewhere: [{ name: "scph5501.bin", from: "DuckStation" }] }),
    ).toBe("waiting");
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

describe("optionalSummary", () => {
  // The names live behind the info button; a partial list here said nothing.
  it("counts the files and names none", () => {
    expect(optionalSummary(27)).toBe(
      "27 files your games run without. A core uses them if they are here.",
    );
  });

  it("says file for one", () => {
    expect(optionalSummary(1)).toMatch(/^1 file your/);
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
