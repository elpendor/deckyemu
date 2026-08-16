import { beforeEach, describe, expect, it } from "vitest";

import { EMPTY_DRAFT, getDraft, resetDraft, subscribeDraft, updateDraft } from "./romDraft";

/**
 * The draft exists because Steam unmounts a Quick Access panel's content when
 * anything modal opens over it -- a file picker, a modal, and a dropdown, whose
 * ContextMenu behaves the same way. Component state does not survive that.
 *
 * These checks are about the property that makes it worth having: a value put
 * in before the unmount is still there after, and the remount reads it rather
 * than an initial value. Every field that a control writes has to live here or
 * it silently reverts, which is not visible in a rendering test -- there is no
 * DOM environment -- and was not visible in review either.
 */
describe("romDraft", () => {
  beforeEach(() => {
    resetDraft();
  });

  it("survives the remount a dropdown causes", () => {
    // What the panel does when the user picks a core from the suggestions.
    updateDraft({ installableId: "gambatte" });
    // The unmount and remount: a new component instance reading module scope.
    const afterRemount = getDraft();
    expect(afterRemount.installableId).toBe("gambatte");
  });

  it("starts with no core chosen, meaning the first suggestion", () => {
    // "" is not "nothing selected" -- the panel resolves it to installable[0],
    // which is the backend's own best answer. A missing default would render a
    // dropdown with no value at all.
    expect(EMPTY_DRAFT.installableId).toBe("");
    expect(getDraft().installableId).toBe("");
  });

  it("notifies a mounted panel when a field changes", () => {
    // The half that makes a late async result reach whatever is mounted now.
    let seen = "";
    const unsubscribe = subscribeDraft((next) => {
      seen = next.installableId;
    });
    updateDraft({ installableId: "sameboy" });
    unsubscribe();
    expect(seen).toBe("sameboy");
  });

  it("keeps a chosen licence key across the same remount", () => {
    // Worth its own check rather than trusting the one above: the wrong key
    // installs a Vita game and then fails to decrypt it, so a choice that
    // quietly reverts to the first candidate is one the user made and did not
    // get -- and the failure surfaces long afterwards, at launch.
    updateDraft({ keyChoice: "MyGame.zrif" });
    expect(getDraft().keyChoice).toBe("MyGame.zrif");
    resetDraft();
    expect(getDraft().keyChoice).toBe("");
  });

  it("clears the chosen core when the draft is reset", () => {
    // A core chosen for one ROM is not a choice anyone made about the next.
    updateDraft({ installableId: "gambatte" });
    resetDraft();
    expect(getDraft().installableId).toBe("");
  });
});
