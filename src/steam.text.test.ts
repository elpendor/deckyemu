import { afterEach, describe, expect, it, vi } from "vitest";

import { steamText } from "./steam/text";

/**
 * Borrowing Steam's own UI strings.
 *
 * The substitution is the reason this module exists at all:
 * `LocalizationManager.LocalizeString` hands back the raw string with its
 * `%1$s` placeholders still in it, and Steam's own components format them
 * afterwards. A version that skipped that step would put
 * "You are currently running %1$s." in front of somebody, which is worse than
 * not translating it.
 *
 * The rest is what happens when the global is not what it was. It is injected
 * and undocumented like every other one here, so each check below is a way for
 * it to be missing or renamed, and the answer is always the English fallback
 * rather than an exception inside a dialog.
 */

const withLocalization = (value: unknown) => {
  (globalThis as Record<string, unknown>).LocalizationManager = {
    LocalizeString: () => value,
  };
};

afterEach(() => {
  delete (globalThis as Record<string, unknown>).LocalizationManager;
  vi.restoreAllMocks();
});

describe("steamText", () => {
  it("fills in Steam's placeholders, which Steam does not", () => {
    withLocalization("Close %1$s and launch %2$s");
    expect(steamText("#token", "fallback", "Mina", "Sonic")).toBe("Close Mina and launch Sonic");
  });

  it("takes the arguments by position, not in order", () => {
    // Translations reorder them, and "Close %2$s and launch %1$s" is a sentence
    // some language wants. Reading them sequentially would swap the two games.
    withLocalization("Launch %2$s, closing %1$s");
    expect(steamText("#token", "fallback", "Mina", "Sonic")).toBe("Launch Sonic, closing Mina");
  });

  it("leaves a placeholder alone when nothing was passed for it", () => {
    // Better a visible `%2$s` than the string "undefined" in the middle of a
    // sentence: one is obviously a bug and the other reads as a game's name.
    withLocalization("Close %1$s and launch %2$s");
    expect(steamText("#token", "fallback", "Mina")).toBe("Close Mina and launch %2$s");
  });

  it("formats the fallback the same way when there is no Steam to ask", () => {
    expect(steamText("#token", "Launch %1$s", "Sonic")).toBe("Launch Sonic");
  });

  it("falls back when the token comes back as itself", () => {
    // How some builds report a token they do not have. Showing it would put a
    // "#GameAction_..." on screen.
    withLocalization("#GameAction_Launch_Multiple_Title");
    expect(steamText("#GameAction_Launch_Multiple_Title", "Launch %1$s", "Sonic")).toBe(
      "Launch Sonic",
    );
  });

  it("falls back on an empty answer", () => {
    withLocalization("");
    expect(steamText("#token", "Cancel")).toBe("Cancel");
  });

  it("falls back when LocalizeString has been renamed away", () => {
    (globalThis as Record<string, unknown>).LocalizationManager = {};
    expect(steamText("#token", "Cancel")).toBe("Cancel");
  });

  it("falls back when the whole thing throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    (globalThis as Record<string, unknown>).LocalizationManager = {
      LocalizeString: () => {
        throw new Error("gone");
      },
    };
    expect(steamText("#token", "Cancel")).toBe("Cancel");
  });
});
