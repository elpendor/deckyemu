import { describe, expect, it } from "vitest";

import { titleAfterArtPick } from "./titleFromArt";

/**
 * Whether picking artwork by hand should also name the game.
 *
 * It should, and it did not: a ROM called `smw_hack_final(2).sfc` was added as
 * "smw hack final(2)" even after the user found the right game in the picker --
 * which is the moment they told the plugin what the game was, and the only
 * moment it could have known.
 */
describe("titleAfterArtPick", () => {
  it("takes the picked name over one derived from a bad filename", () => {
    expect(titleAfterArtPick("smw_hack_final(2)", "smw_hack_final(2)", "Super Mario World"))
      .toBe("Super Mario World");
  });

  /*
   * The rule the rest of the plugin uses everywhere it might overwrite
   * something: a value that still matches what the plugin produced is the
   * plugin's to change, and anything else belongs to whoever typed it.
   */
  it("leaves a name the user wrote", () => {
    expect(titleAfterArtPick("My Hack", "smw_hack_final(2)", "Super Mario World"))
      .toBe("My Hack");
  });

  it("still takes it when the automatic name was already good", () => {
    // Picking an entry says "this is the game" whatever the filename gave, and
    // the picked name is the one attached to the artwork now on screen.
    expect(titleAfterArtPick("Super Mario World", "Super Mario World", "Super Mario World 2"))
      .toBe("Super Mario World 2");
  });

  it("keeps what is there when the pick offers no name", () => {
    // A libretro thumbnail with an unreadable name, or a backend old enough not
    // to send one. Blanking the field would be worse than leaving it wrong.
    expect(titleAfterArtPick("smw_hack_final(2)", "smw_hack_final(2)", ""))
      .toBe("smw_hack_final(2)");
  });

  // The field does not trim for the user, and a trailing space is not an edit.
  it("does not treat stray whitespace as a name of their own", () => {
    expect(titleAfterArtPick("  smw_hack_final(2) ", "smw_hack_final(2)", "Super Mario World"))
      .toBe("Super Mario World");
  });

  it("copes with nothing having been resolved at all", () => {
    // No lookup ran -- offline, or it failed -- so there is no automatic name
    // to compare against and the field is empty. Nothing of the user's is at
    // stake, so the pick wins.
    expect(titleAfterArtPick("", "", "Super Mario World")).toBe("Super Mario World");
  });
});
