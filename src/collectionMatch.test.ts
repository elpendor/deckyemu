import { describe, expect, it } from "vitest";

import { ownedCollectionMatcher } from "./collectionMatch";

/**
 * The rule that decides whether a Steam collection gets deleted.
 *
 * It was checked by a second copy of itself, written in Python inside the
 * backend suite. That proved the copy correct and said nothing about the code
 * that runs -- and the code that runs is the half that deletes. These are the
 * same cases, asserted against the shipped function.
 */
const shape = (base: string, per_platform = true, template = "{name} - {platform}") =>
  ({ base, per_platform, template });

describe("ownedCollectionMatcher", () => {
  it("matches a name it would have produced", () => {
    const matches = ownedCollectionMatcher(shape("DeckyEmu"));
    expect(matches("DeckyEmu - Nintendo 64")).toBe(true);
    expect(matches("DeckyEmu - SNES")).toBe(true);
  });

  // The hazard. A base name is free text: "Emu (Deck) [v2]" is a name, and used
  // unescaped its brackets and parentheses become regex syntax -- so the
  // matcher stops recognising its own collections and starts recognising
  // somebody else's.
  it("treats a base full of regex characters as text", () => {
    const matches = ownedCollectionMatcher(shape("Emu (Deck) [v2]"));
    expect(matches("Emu (Deck) [v2] - Nintendo 64")).toBe(true);
    expect(matches("Emu xDeckx [v2] - Nintendo 64")).toBe(false);
    expect(matches("Emu D [v2] - Nintendo 64")).toBe(false);
  });

  // `.+` rather than `.*`: with `.*` a per-platform setup would also match the
  // bare base name, which is what per-platform *off* produces and may be a
  // collection the user curates by hand.
  it("does not match the bare base name when per-platform is on", () => {
    expect(ownedCollectionMatcher(shape("DeckyEmu"))("DeckyEmu")).toBe(false);
  });

  it("matches only the exact name when per-platform is off", () => {
    const matches = ownedCollectionMatcher(shape("DeckyEmu", false));
    expect(matches("DeckyEmu")).toBe(true);
    expect(matches("DeckyEmu - SNES")).toBe(false);
  });

  it("never matches anything when no name is configured", () => {
    for (const base of ["", "   "]) {
      const matches = ownedCollectionMatcher(shape(base));
      expect(matches("DeckyEmu - SNES")).toBe(false);
      expect(matches("")).toBe(false);
    }
  });

  it("leaves collections it did not make alone", () => {
    const matches = ownedCollectionMatcher(shape("DeckyEmu"));
    for (const other of ["Favourites", "Emulation", "DeckyEmu2 - SNES", "deckyemu - SNES"]) {
      expect(matches(other)).toBe(false);
    }
  });

  it("follows a custom template rather than assuming the default", () => {
    const matches = ownedCollectionMatcher(shape("Emu", true, "{platform} ({name})"));
    expect(matches("SNES (Emu)")).toBe(true);
    expect(matches("Emu - SNES")).toBe(false);
  });

  // A template with no platform placeholder cannot distinguish one system from
  // another; it must still not match everything.
  it("survives a template that uses no placeholders", () => {
    const matches = ownedCollectionMatcher(shape("Emu", true, "Games"));
    expect(matches("Games")).toBe(true);
    expect(matches("Games - SNES")).toBe(false);
  });
});

/*
 * The contract with the backend.
 *
 * The rule for building a collection name lives in Python; the rule for
 * recognising one lives here. Two implementations of one thing, and nothing
 * compared them: each suite checked its own half against names written by hand,
 * which proves only that each half agrees with itself. They already differed --
 * the renderer strips trailing separators and substitutes every occurrence of a
 * placeholder, and the preview that was in this codebase did neither.
 *
 * These strings are the fixture both suites share. scripts/test_backend.py
 * asserts the renderer still produces exactly these for exactly these formats;
 * this asserts the matcher accepts them. Changing how a name is built fails
 * there, and fixing it there without fixing it here fails below.
 */
const RENDERED: Array<[template: string, name: string]> = [
  ["[{name}] {platform}", "[DeckyEmu] Nintendo 64"],
  ["{platform}", "Nintendo 64"],
  ["{name}: {platform}", "DeckyEmu: Nintendo 64"],
  ["{name} · {platform}", "DeckyEmu · Nintendo 64"],
  ["{name} - {platform}", "DeckyEmu - Nintendo 64"],
  ["{platform} ({name})", "Nintendo 64 (DeckyEmu)"],
  ["{name}\\n{platform}", "DeckyEmu\nNintendo 64"],
];

describe("ownedCollectionMatcher, against names the backend really produces", () => {
  it.each(RENDERED)("recognises what %s renders", (template, name) => {
    // The shape arrives with the newline already real, because collection_shape
    // unescapes it before sending -- so the matcher never sees the escape.
    const matches = ownedCollectionMatcher(
      shape("DeckyEmu", true, template.replace("\\n", "\n")),
    );
    expect(matches(name)).toBe(true);
  });

  // The formats differ mostly in their separators, so a matcher built from one
  // must not accept a name built by another -- that is what would let a rename
  // delete a shelf still holding the games it was renamed away from.
  it("does not accept a name another format produced", () => {
    const matches = ownedCollectionMatcher(shape("DeckyEmu", true, "[{name}] {platform}"));
    expect(matches("DeckyEmu - Nintendo 64")).toBe(false);
    expect(matches("DeckyEmu: Nintendo 64")).toBe(false);
  });
});

/*
 * What was recorded beats what the settings would produce.
 *
 * The pattern above can only describe shelves the *current* naming would make,
 * and an empty shelf is reached long after the naming that made it moved on. So
 * every change to the naming used to orphan every collection made before it --
 * silently, and with no way back, because nothing else remembered they were
 * ours.
 */
describe("ownedCollectionMatcher, what the backend recorded", () => {
  const withKnown = (known: string[], base = "DeckyEmu", per_platform = true) =>
    ownedCollectionMatcher({ ...shape(base, per_platform), known });

  it("claims a shelf the current naming would never produce", () => {
    const matches = withKnown(["[DeckyEmu] N64"]);
    // The template is "{name} - {platform}" now; this one was made under
    // "[{name}] {platform}" and the pattern cannot see it.
    expect(matches("[DeckyEmu] N64")).toBe(true);
  });

  it("still claims one after per-system naming is switched off", () => {
    expect(withKnown(["DeckyEmu - SNES"], "DeckyEmu", false)("DeckyEmu - SNES")).toBe(true);
  });

  it("still claims one after the base name is edited", () => {
    expect(withKnown(["OldName - SNES"], "NewName")("OldName - SNES")).toBe(true);
  });

  // Collections are off, so the pattern half says no to everything -- but a
  // shelf this plugin made is still one it made, and switching the feature off
  // is the moment those are most likely to be left empty.
  it("still claims one when no name is configured at all", () => {
    expect(withKnown(["[DeckyEmu] N64"], "")("[DeckyEmu] N64")).toBe(true);
    expect(withKnown(["[DeckyEmu] N64"], "")("Shooters I like")).toBe(false);
  });

  it("leaves alone anything neither recorded nor matching", () => {
    const matches = withKnown(["[DeckyEmu] N64"]);
    expect(matches("Shooters I like")).toBe(false);
    expect(matches("[DeckyEmu] SNES")).toBe(false);
  });

  // The union runs the other way too: an install from before the record existed
  // has nothing in it, and its shelves are still recognised by the pattern.
  it("falls back to the pattern when nothing was recorded", () => {
    const matches = ownedCollectionMatcher({ ...shape("DeckyEmu"), known: [] });
    expect(matches("DeckyEmu - SNES")).toBe(true);
  });

  it("and when the backend is old enough not to send one", () => {
    expect(ownedCollectionMatcher(shape("DeckyEmu"))("DeckyEmu - SNES")).toBe(true);
  });
});
