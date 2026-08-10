import { describe, expect, it } from "vitest";

import { clearWarning, shouldConfirmClear } from "./clearWarning";

describe("shouldConfirmClear", () => {
  it("confirms when there is something to remove", () => {
    expect(shouldConfirmClear(1)).toBe(true);
    expect(shouldConfirmClear(47)).toBe(true);
  });

  it("skips the dialog for a known-empty library", () => {
    expect(shouldConfirmClear(0)).toBe(false);
  });

  // "Could not ask" is not "nothing there". Refusing here would silently block
  // a cleanup somebody navigated to this tab to do, on the strength of one
  // dropped call -- and a dropped call is routine right after a plugin reload.
  it("still confirms when the count could not be read", () => {
    expect(shouldConfirmClear(null)).toBe(true);
  });
});

describe("clearWarning", () => {
  it("states the exact number of games", () => {
    expect(clearWarning(47)).toContain("all 47 games");
  });

  it("reads correctly for a single game", () => {
    const text = clearWarning(1);
    expect(text).toContain("the 1 game");
    expect(text).not.toContain("1 games");
  });

  /*
   * The invariant that matters most. A number in a destructive confirmation is
   * only protection if it is right: somebody can recognise "all 47 games" as
   * wrong about their own library and stop. A guessed number is worse than none,
   * because it invites exactly that trust and does not deserve it.
   */
  it("claims no number when the count is unknown", () => {
    const text = clearWarning(null);
    expect(text).not.toMatch(/\d/);
    expect(text).toContain("every Steam shortcut");
  });

  // Whatever the count, the dialog has to say the two things somebody needs to
  // decide: that the ROMs go, and what survives. These were in one branch of an
  // if before this was its own function.
  it("always says what is destroyed and what survives", () => {
    for (const count of [null, 0, 1, 2, 999]) {
      const text = clearWarning(count);
      expect(text, `count ${count}`).toContain("the ROMs it filed");
      expect(text, `count ${count}`).toContain("Save data is kept");
      expect(text, `count ${count}`).toContain("not touched");
      expect(text, `count ${count}`).toMatch(/\.$/);
    }
  });

  // Reachable only through a caller ignoring shouldConfirmClear, so it must not
  // produce "all 0 games" -- a dialog that says nothing will be deleted while
  // offering a button that deletes.
  it("does not announce zero games", () => {
    expect(clearWarning(0)).not.toContain("0 game");
  });
});
