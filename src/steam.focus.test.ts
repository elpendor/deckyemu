import { describe, expect, it, vi } from "vitest";

import { navNodeFrom, takeGamepadFocus } from "./steam/focus";

/**
 * The fiber walk, which is the part that can be tested here.
 *
 * There is no DOM environment in this suite, deliberately, so the Steam page
 * itself is out of reach. What these cover is the traversal and the refusal to
 * throw -- the two things that decide whether a Steam update turns into a ring
 * that does not move or into an exception in a rendered panel.
 */

/** A provider fiber carrying `value`, chained to a parent. */
const fiber = (value: unknown, parent: unknown = null) =>
  ({ memoizedProps: { value }, return: parent }) as never;

const navNode = () => ({ BTakeFocus: vi.fn(() => true) });

describe("navNodeFrom", () => {
  it("finds the node on the fiber it starts at", () => {
    const node = navNode();
    expect(navNodeFrom(fiber(node))).toBe(node);
  });

  it("walks outwards to the provider that has one", () => {
    // Focusable renders the provider several levels above the button, which is
    // why this looks up the tree rather than at one element.
    const node = navNode();
    const chain = fiber({}, fiber(undefined, fiber(node)));
    expect(navNodeFrom(chain)).toBe(node);
  });

  it("takes the nearest one, not the outermost", () => {
    // Focusables nest. The ring belongs to the closest one that owns this
    // element, and jumping to an ancestor's would move focus to the wrong row.
    const near = navNode();
    const far = navNode();
    expect(navNodeFrom(fiber(near, fiber(far)))).toBe(near);
  });

  it("ignores provider values that are not navigation nodes", () => {
    // Plenty of context providers sit in this chain -- themes, routers. Only a
    // BTakeFocus makes one the thing we are after.
    expect(navNodeFrom(fiber({ some: "context" }, fiber("a string")))).toBe(null);
  });

  it("gives up rather than walking for ever", () => {
    // A cycle, which a malformed tree could present. Without a bound this is a
    // hang, and a hang inside a frame callback takes the panel with it.
    const loop: { memoizedProps: { value: unknown }; return: unknown } = {
      memoizedProps: { value: {} }, return: null,
    };
    loop.return = loop;
    expect(navNodeFrom(loop as never)).toBe(null);
  });

  it("answers null for nothing", () => {
    expect(navNodeFrom(null)).toBe(null);
    expect(navNodeFrom(undefined)).toBe(null);
  });
});

describe("takeGamepadFocus", () => {
  it("says so when there is no element", () => {
    expect(takeGamepadFocus(null)).toBe(false);
    expect(takeGamepadFocus(undefined)).toBe(false);
  });

  it("never throws on an element React knows nothing about", () => {
    // The whole point of the guard: this reaches through React's internals into
    // Steam's, and a plugin that cannot move a ring must still do its job.
    expect(takeGamepadFocus({} as Element)).toBe(false);
  });
});
