import { describe, expect, it } from "vitest";

import type { FirmwareReport, FirmwareState } from "./backend";
import { requirementForFile } from "./firmwareMatch";

function requirement(overrides: Partial<FirmwareState> = {}): FirmwareState {
  return {
    name: "BIOS",
    note: "",
    expects: "",
    manual: "",
    dest: "",
    waiting: [],
    installed: [],
    foreign: [],
    can_install: true,
    can_remove: false,
    imported: false,
    can_fetch: false,
    ...overrides,
  };
}

function report(emulators: FirmwareReport["emulators"]): FirmwareReport {
  return { path: "/home/deck/deckyemu/firmware", emulators };
}

/*
 * The bug this exists for, in one sentence: xemu wants three different dumps,
 * and the dialog offered the same requirement against every file that arrived.
 * Pressing Install on the second ran the first one's requirement, which matches
 * by size, found nothing, and said so about a file that was never that dump.
 */
const XEMU = report([
  {
    id: "xemu",
    name: "xemu",
    requirements: [
      requirement({ name: "MCPX boot ROM", waiting: ["mcpx.bin"] }),
      requirement({ name: "Xbox BIOS", waiting: ["complex.bin"] }),
      requirement({ name: "Hard disk image", waiting: [] }),
    ],
  },
]);

describe("requirementForFile", () => {
  it("gives each file the requirement that is actually waiting for it", () => {
    expect(requirementForFile(XEMU, "mcpx.bin")?.requirement).toBe("MCPX boot ROM");
    expect(requirementForFile(XEMU, "complex.bin")?.requirement).toBe("Xbox BIOS");
  });

  it("carries the emulator, so the caller need not look it up again", () => {
    const match = requirementForFile(XEMU, "mcpx.bin");
    expect(match?.entryId).toBe("xemu");
    expect(match?.emulatorName).toBe("xemu");
  });

  it("says nothing for a file no requirement wants", () => {
    expect(requirementForFile(XEMU, "holiday-photo.jpg")).toBeUndefined();
  });

  it("says nothing when the report has not loaded", () => {
    expect(requirementForFile(null, "mcpx.bin")).toBeUndefined();
  });

  /*
   * The second half of the same report: installing this one is not a copy at
   * all. Missing it sent the transfer dialog down the copy path, which has no
   * destination for it and returned the requirement's own instructions as the
   * error -- the plugin appearing to refuse the thing it was describing.
   */
  it("flags a requirement the emulator installs through its own window", () => {
    const ryujinx = report([
      {
        id: "ryujinx",
        name: "Ryujinx",
        requirements: [
          requirement({
            name: "Switch firmware",
            waiting: ["Firmware 20.1.0.zip"],
            gui_install: true,
            prompt: "Press Yes to confirm.",
          }),
        ],
      },
    ]);
    const match = requirementForFile(ryujinx, "Firmware 20.1.0.zip");
    expect(match?.guiInstall).toBe(true);
    expect(match?.prompt).toBe("Press Yes to confirm.");
  });

  it("treats an ordinary requirement as a copy", () => {
    expect(requirementForFile(XEMU, "mcpx.bin")?.guiInstall).toBe(false);
  });

  /*
   * A file already in place is not in `waiting`, so it gets no button -- which
   * is the point. Offering Install for something installed is what the settings
   * page did once, and it reads as the install having silently failed.
   */
  it("ignores a file that is already installed", () => {
    const done = report([
      {
        id: "duckstation",
        name: "DuckStation",
        requirements: [
          requirement({ name: "PS1 BIOS", waiting: [], installed: ["scph1001.bin"] }),
        ],
      },
    ]);
    expect(requirementForFile(done, "scph1001.bin")).toBeUndefined();
  });

  /*
   * A PS1 BIOS serves DuckStation and a libretro core alike. Either is a
   * correct place to put it, so one is chosen rather than asking the user to
   * pick between two identical outcomes.
   */
  it("picks the first of two emulators wanting the same dump", () => {
    const shared = report([
      {
        id: "duckstation",
        name: "DuckStation",
        requirements: [requirement({ name: "PS1 BIOS", waiting: ["scph1001.bin"] })],
      },
      {
        id: "pcsx2",
        name: "PCSX2",
        requirements: [requirement({ name: "PS1 BIOS", waiting: ["scph1001.bin"] })],
      },
    ]);
    expect(requirementForFile(shared, "scph1001.bin")?.entryId).toBe("duckstation");
  });
});
