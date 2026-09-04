import { describe, expect, it } from "vitest";

import type { SaveBackupContents, SaveSource } from "./backend";
import {
  backupSummary,
  defaultSelection,
  listNames,
  missingCount,
  missingIds,
  notInstalled,
  presentCount,
  restoreSummary,
  sourceLine,
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

  // The row for such an emulator says so itself, which is where the decision to
  // untick it gets made. Repeating it here made the summary the longest thing on
  // the screen for no new information.
  it("leaves the whole-directory warning to the row it belongs to", () => {
    const text = backupSummary(totals(sources, new Set(["plain"])), "9 MB");
    expect(text).toBe("40 file(s), 9 MB, from DuckStation.");
  });

  it("says nothing is selected rather than reporting an empty backup", () => {
    expect(backupSummary(totals(sources, new Set()), "0 KB")).toBe("Nothing selected.");
  });

  // A Deck with everything set up made this line a roll-call of fourteen
  // emulators. The figures are the point; which ones is a courtesy that stops
  // being one somewhere around the fourth name.
  it("counts the rest rather than naming every emulator", () => {
    const many = Array.from({ length: 14 }, (_, at) =>
      source({ id: `e${at}`, name: `Emulator ${at}`, files: 1, bytes: 1000 }),
    );
    const text = backupSummary(totals(many, defaultSelection(many)), "14 KB");
    expect(text).toBe(
      "14 file(s), 14 KB, from Emulator 0, Emulator 1, Emulator 2 and 11 more.",
    );
  });
});

describe("listNames", () => {
  it("reads as a sentence up to three", () => {
    expect(listNames([])).toBe("");
    expect(listNames(["A"])).toBe("A");
    expect(listNames(["A", "B"])).toBe("A and B");
    expect(listNames(["A", "B", "C"])).toBe("A, B and C");
  });

  it("counts the rest past that", () => {
    expect(listNames(["A", "B", "C", "D"])).toBe("A, B, C and 1 more");
    expect(listNames(["A", "B", "C", "D", "E"])).toBe("A, B, C and 2 more");
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

  // The case that reads as a failure unless it is named: Restore missing is
  // disabled here, and the sentence has to say why.
  it("names the case where only restoring all of it would do anything", () => {
    const text = restoreSummary([inBackup({ id: "a", files: 12, present: 12 })]);
    expect(text).toContain("all of them already on this Deck");
    expect(text).toContain("so only restoring all of them would change anything");
  });

  // Nothing there is not the same as nothing usable, and saying the second when
  // the first is true sends somebody looking for a fault on their own Deck.
  it("says a storage is empty rather than blaming this Deck", () => {
    expect(restoreSummary([], "storage")).toBe("This storage holds no saves yet.");
    expect(restoreSummary([])).toBe("This backup holds no saves.");
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

describe("sourceLine", () => {
  it("leads with what is missing, since that is what restoring would write", () => {
    expect(sourceLine(inBackup({ id: "a", files: 3, present: 2 }), "40 KB")).toEqual({
      line: "1 of 3 missing here, 40 KB in the backup",
      missing: 1,
    });
  });

  it("says when there is nothing to restore rather than going quiet", () => {
    // A row that said nothing was indistinguishable from one that failed to
    // load, and this is the case where the button beside it is disabled.
    expect(sourceLine(inBackup({ id: "a", files: 3, present: 3 }), "40 KB")).toEqual({
      line: "All 3 already on this Deck",
      missing: 0,
    });
  });

  it("counts everything as missing when none of it is here", () => {
    expect(sourceLine(inBackup({ id: "a", files: 3 }), "40 KB").missing).toBe(3);
  });

  it("says an emulator that is not installed keeps its saves in the backup", () => {
    const said = sourceLine(
      inBackup({ id: "a", files: 3, present: 0, installed: false }),
      "40 KB",
    );
    expect(said).toEqual({
      line: "3 file(s), 40 KB - not installed here, so these stay in the backup",
      missing: 0,
    });
  });

  it("never reports a negative, whatever the archive claims", () => {
    // `present` is counted on this Deck and `files` in the archive, so nothing
    // stops the two disagreeing if a root is listed twice.
    expect(sourceLine(inBackup({ id: "a", files: 1, present: 4 }), "1 KB").missing).toBe(0);
  });
});

describe("missingIds", () => {
  it("is the emulators that would actually be written to", () => {
    // The failure this prevents: one file missing from one emulator asked the
    // storage for all thirteen, a network call per save root of each.
    expect(
      missingIds([
        inBackup({ id: "xenia", files: 3, present: 2 }),
        inBackup({ id: "rpcs3", files: 200, present: 200 }),
        inBackup({ id: "xemu", files: 61, present: 61 }),
      ]),
    ).toEqual(["xenia"]);
  });

  it("leaves out an emulator that is not installed here", () => {
    // Its saves stay where they are; there is nowhere on this Deck to put them.
    expect(
      missingIds([inBackup({ id: "vita3k", files: 9, installed: false })]),
    ).toEqual([]);
  });

  it("is empty when there is nothing to do, which disables the button", () => {
    expect(missingIds([inBackup({ id: "a", files: 3, present: 3 })])).toEqual([]);
  });
});
