import { describe, expect, it } from "vitest";

import type { SaveBackupContents, SaveSource } from "./backend";
import {
  backupSummary,
  defaultSelection,
  missingCount,
  notInstalled,
  presentCount,
  restoreSummary,
  totals,
} from "./saveBackup";

const source = (over: Partial<SaveSource> & { id: string }): SaveSource => ({
  name: over.id,
  whole: false,
  paths: [],
  files: 0,
  bytes: 0,
  ...over,
});

const sources: SaveSource[] = [
  source({ id: "retroarch", name: "RetroArch", files: 12, bytes: 400_000 }),
  source({ id: "rpcs3", name: "RPCS3", files: 3, bytes: 28_000 }),
  source({ id: "plain", name: "DuckStation", files: 40, bytes: 9_000_000, whole: true }),
];

describe("totals", () => {
  it("counts only what is still ticked", () => {
    const sum = totals(sources, new Set(["retroarch", "rpcs3"]));
    expect(sum.files).toBe(15);
    expect(sum.bytes).toBe(428_000);
    expect(sum.names).toEqual(["RetroArch", "RPCS3"]);
  });

  it("is zero once everything is unticked", () => {
    expect(totals(sources, new Set())).toEqual({
      files: 0,
      bytes: 0,
      names: [],
      whole: [],
    });
  });

  // The row whose size can dwarf every other one. The modal has to be able to
  // say which emulator that is, so it is carried through rather than counted.
  it("names the emulators contributing their whole directory", () => {
    expect(totals(sources, new Set(["plain", "rpcs3"])).whole).toEqual(["DuckStation"]);
  });
});

describe("defaultSelection", () => {
  it("starts with everything ticked", () => {
    expect([...defaultSelection(sources)]).toEqual(["retroarch", "rpcs3", "plain"]);
  });
});

describe("backupSummary", () => {
  it("says what is going in", () => {
    const text = backupSummary(totals(sources, new Set(["retroarch", "rpcs3"])), "418 KB");
    expect(text).toBe("15 file(s), 418 KB, from RetroArch and RPCS3.");
  });

  it("warns that a whole-directory emulator carries more than saves", () => {
    const text = backupSummary(totals(sources, new Set(["plain"])), "9 MB");
    expect(text).toContain("Everything DuckStation keeps is included, not only saves");
  });

  it("says nothing is selected rather than reporting an empty backup", () => {
    expect(backupSummary(totals(sources, new Set()), "0 KB")).toBe("Nothing selected.");
  });
});

const inBackup = (
  over: Partial<SaveBackupContents> & { id: string },
): SaveBackupContents => ({
  name: over.id,
  installed: true,
  files: 0,
  bytes: 0,
  present: 0,
  ...over,
});

describe("restoreSummary", () => {
  it("says how much of the backup is already here", () => {
    expect(restoreSummary([inBackup({ id: "a", files: 12, present: 5 })])).toBe(
      "12 file(s), 5 of them already on this Deck.",
    );
  });

  it("says so when none of it is", () => {
    expect(restoreSummary([inBackup({ id: "a", files: 12 })])).toBe(
      "12 file(s), none of them already here.",
    );
  });

  // The case that reads as a failure unless it is named: Restore what is missing
  // is disabled here, and the sentence has to say why.
  it("names the case where only replacing would do anything", () => {
    const text = restoreSummary([inBackup({ id: "a", files: 12, present: 12 })]);
    expect(text).toContain("all of them already on this Deck");
    expect(text).toContain("Only replacing would change anything");
  });

  // An uninstalled emulator contributes nothing and must not be counted, or the
  // sentence promises files that are never written.
  it("ignores emulators this Deck does not have", () => {
    expect(
      restoreSummary([
        inBackup({ id: "a", files: 4 }),
        inBackup({ id: "b", files: 99, installed: false }),
      ]),
    ).toBe("4 file(s), none of them already here.");
  });

  it("says so when none of them are installed", () => {
    expect(restoreSummary([inBackup({ id: "b", files: 99, installed: false })])).toBe(
      "None of these emulators are installed on this Deck.",
    );
  });
});

describe("missingCount and presentCount", () => {
  // What the two buttons are wired to: nothing missing disables the plain
  // restore, and the count present is what the replace confirmation promises to
  // destroy.
  it("count only what an installed emulator contributes", () => {
    const contents = [
      inBackup({ id: "a", files: 12, present: 5 }),
      inBackup({ id: "b", files: 99, installed: false }),
    ];
    expect(missingCount(contents)).toBe(7);
    expect(presentCount(contents)).toBe(5);
  });

  it("report nothing missing once every file is here", () => {
    expect(missingCount([inBackup({ id: "a", files: 12, present: 12 })])).toBe(0);
  });
});

describe("notInstalled", () => {
  it("names the emulators whose saves stay in the archive", () => {
    expect(
      notInstalled([
        inBackup({ id: "a", name: "RPCS3" }),
        inBackup({ id: "b", name: "Vita3K", installed: false }),
      ]),
    ).toEqual(["Vita3K"]);
  });
});
