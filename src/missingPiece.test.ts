import { describe, expect, it } from "vitest";

import { missingPieceMessage } from "./missingPiece";

/**
 * The dialog exists because the alternative is silence: an uninstalled emulator
 * or an unmounted SD card let the shortcut launch, fail, and return to the
 * library in a second with nothing on screen. So what these messages must do is
 * name the cause and the one place to fix it.
 */
describe("why a game did not start", () => {
  it("names the game, so a dialog over the library is not a mystery", () => {
    expect(missingPieceMessage("rom", "Tom & Jerry").heading).toContain("Tom & Jerry");
    expect(missingPieceMessage("emulator", "Tom & Jerry").heading).toContain("Tom & Jerry");
  });

  it("blames the SD card first for a missing file, since that is the usual cause", () => {
    expect(missingPieceMessage("rom", "X").body).toContain("SD");
  });

  it("sends a missing emulator to the tab that reinstalls it", () => {
    expect(missingPieceMessage("emulator", "X").body).toContain("Emulators tab");
  });

  it("names the emulator, so nobody has to work out which of eight it was", () => {
    expect(missingPieceMessage("emulator", "X", "Ryujinx").body).toContain(
      "Ryujinx is not installed.",
    );
  });

  // The launcher hands over a phrase ready to start a sentence, so a core reads
  // as a core rather than as an emulator nobody has a row for.
  it("reads correctly for a libretro core too", () => {
    expect(missingPieceMessage("emulator", "X", "The snes9x core").body).toContain(
      "The snes9x core is not installed.",
    );
  });

  it("stays readable when the launcher recorded no name", () => {
    const body = missingPieceMessage("emulator", "X").body;
    expect(body).toContain("The emulator it needs is not installed.");
    expect(body).not.toContain("undefined");
  });

  it("uses no markdown -- a Steam dialog would print the asterisks", () => {
    expect(missingPieceMessage("emulator", "X", "Ryujinx").body).not.toContain("*");
  });

  it("says saves survive, because reinstalling sounds destructive and is not", () => {
    expect(missingPieceMessage("emulator", "X").body).toContain("saves");
  });

  it("never blames the user's file for a missing emulator, or the reverse", () => {
    expect(missingPieceMessage("emulator", "X").body).not.toContain("SD");
    expect(missingPieceMessage("rom", "X").body).not.toContain("Emulators tab");
  });

  // It said "removed outside this plugin", which is false in the likeliest case
  // of all: the Emulators tab has a Remove button.
  it("does not guess at how the emulator went", () => {
    const body = missingPieceMessage("emulator", "X", "Ryujinx").body;
    expect(body).not.toContain("outside this plugin");
    expect(body).not.toContain("removed");
  });

  it("stays short enough to read on a handheld", () => {
    for (const piece of ["rom", "emulator"] as const) {
      expect(missingPieceMessage(piece, "X", "Ryujinx").body.length).toBeLessThan(160);
    }
  });
});
