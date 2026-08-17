import { describe, expect, it } from "vitest";

import { filenameNamesTheGame } from "./lookupTerm";

describe("filenameNamesTheGame", () => {
  it("says no for the eboot every packaged game boots", () => {
    // PS3, PS4 and Vita all land here, and the folder above is a title id
    // rather than a name -- so the filename identifies nothing, identically,
    // for every game of those three systems.
    expect(filenameNamesTheGame("/home/deck/.local/share/Vita3K/Vita3K/ux0/app/PCSA00011/eboot.bin"))
      .toBe(false);
    expect(filenameNamesTheGame("/home/deck/games/BLUS30184/USRDIR/EBOOT.BIN")).toBe(false);
  });

  it("is not fooled by case, which differs by console", () => {
    // PS3 ships it upper case and Vita lower.
    expect(filenameNamesTheGame("/x/EBOOT.BIN")).toBe(false);
    expect(filenameNamesTheGame("/x/eboot.bin")).toBe(false);
    expect(filenameNamesTheGame("/x/Eboot.Bin")).toBe(false);
  });

  it("says yes for an ordinary ROM", () => {
    expect(filenameNamesTheGame("/home/deck/deckyemu/roms/gbc/Mario Tennis (USA).zip")).toBe(true);
    expect(filenameNamesTheGame("/roms/snes/Super Metroid.sfc")).toBe(true);
  });

  it("takes a short name at face value rather than guessing", () => {
    // The rule is a list of stems that are never titles, not a theory about
    // which words look like names. "Golf" is a real NES game.
    expect(filenameNamesTheGame("/roms/nes/Golf.nes")).toBe(true);
    expect(filenameNamesTheGame("/roms/misc/a.bin")).toBe(true);
  });

  it("handles a name with dots in it", () => {
    // Only the last dot is the extension; a version in the name is not one.
    expect(filenameNamesTheGame("/roms/pc/Doom v1.9.zip")).toBe(true);
  });

  it("handles a file with no extension at all", () => {
    expect(filenameNamesTheGame("/roms/arcade/mslug")).toBe(true);
    expect(filenameNamesTheGame("/x/eboot")).toBe(false);
  });

  it("says no for a path with no filename, rather than searching for nothing", () => {
    expect(filenameNamesTheGame("/roms/snes/")).toBe(false);
    expect(filenameNamesTheGame("")).toBe(false);
  });
});
