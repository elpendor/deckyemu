import { describe, expect, it } from "vitest";

import { emptyCollectionMatcher } from "./collectionMatch";

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

describe("emptyCollectionMatcher", () => {
  it("matches a name it would have produced", () => {
    const matches = emptyCollectionMatcher(shape("DeckyEmu"));
    expect(matches("DeckyEmu - Nintendo 64")).toBe(true);
    expect(matches("DeckyEmu - SNES")).toBe(true);
  });

  // The hazard. A base name is free text: "Emu (Deck) [v2]" is a name, and used
  // unescaped its brackets and parentheses become regex syntax -- so the
  // matcher stops recognising its own collections and starts recognising
  // somebody else's.
  it("treats a base full of regex characters as text", () => {
    const matches = emptyCollectionMatcher(shape("Emu (Deck) [v2]"));
    expect(matches("Emu (Deck) [v2] - Nintendo 64")).toBe(true);
    expect(matches("Emu xDeckx [v2] - Nintendo 64")).toBe(false);
    expect(matches("Emu D [v2] - Nintendo 64")).toBe(false);
  });

  // `.+` rather than `.*`: with `.*` a per-platform setup would also match the
  // bare base name, which is what per-platform *off* produces and may be a
  // collection the user curates by hand.
  it("does not match the bare base name when per-platform is on", () => {
    expect(emptyCollectionMatcher(shape("DeckyEmu"))("DeckyEmu")).toBe(false);
  });

  it("matches only the exact name when per-platform is off", () => {
    const matches = emptyCollectionMatcher(shape("DeckyEmu", false));
    expect(matches("DeckyEmu")).toBe(true);
    expect(matches("DeckyEmu - SNES")).toBe(false);
  });

  it("never matches anything when no name is configured", () => {
    for (const base of ["", "   "]) {
      const matches = emptyCollectionMatcher(shape(base));
      expect(matches("DeckyEmu - SNES")).toBe(false);
      expect(matches("")).toBe(false);
    }
  });

  it("leaves collections it did not make alone", () => {
    const matches = emptyCollectionMatcher(shape("DeckyEmu"));
    for (const other of ["Favourites", "Emulation", "DeckyEmu2 - SNES", "deckyemu - SNES"]) {
      expect(matches(other)).toBe(false);
    }
  });

  it("follows a custom template rather than assuming the default", () => {
    const matches = emptyCollectionMatcher(shape("Emu", true, "{platform} ({name})"));
    expect(matches("SNES (Emu)")).toBe(true);
    expect(matches("Emu - SNES")).toBe(false);
  });

  // A template with no platform placeholder cannot distinguish one system from
  // another; it must still not match everything.
  it("survives a template that uses no placeholders", () => {
    const matches = emptyCollectionMatcher(shape("Emu", true, "Games"));
    expect(matches("Games")).toBe(true);
    expect(matches("Games - SNES")).toBe(false);
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
describe("emptyCollectionMatcher, what the backend recorded", () => {
  const withKnown = (known: string[], base = "DeckyEmu", per_platform = true) =>
    emptyCollectionMatcher({ ...shape(base, per_platform), known });

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
    const matches = emptyCollectionMatcher({ ...shape("DeckyEmu"), known: [] });
    expect(matches("DeckyEmu - SNES")).toBe(true);
  });

  it("and when the backend is old enough not to send one", () => {
    expect(emptyCollectionMatcher(shape("DeckyEmu"))("DeckyEmu - SNES")).toBe(true);
  });
});
