/**
 * Moving Steam's gamepad focus ring, which is not DOM focus.
 *
 * `element.focus()` moves `document.activeElement` and nothing else. The ring
 * the user actually sees, and the thing the A button acts on, is Steam's own
 * navigation tree -- so a plugin that calls `focus()` gets a probe that says it
 * worked and a device where nothing moved. Three attempts at this were reported
 * as fixed on that evidence before the difference was understood.
 *
 * The node that owns the ring is not on the element. `Focusable` renders a
 * React context provider whose *value* is the navigation node, so it is reached
 * by walking the fiber from the element outwards until a provider value turns
 * up carrying `BTakeFocus`. Found by reading TabMaster's bundle, which does the
 * same thing from the other side -- patching `Focusable.render` to catch
 * `ret.props.value` as it is created. Walking the fiber needs no patching and
 * no library, and gets the same object.
 *
 * `m_navNode` on the DOM node is the version of this that older guides describe.
 * It does not exist on this client: measured on the device, not one element in
 * the whole document carries it.
 *
 * All of it is undocumented and none of it is a contract, which is why it lives
 * here with the rest of the Steam internals and behind one function. When a
 * Steam update breaks it, this is the file, and the failure is a ring that does
 * not move rather than an exception.
 */

/** How far out to look. The provider sits a handful of levels up; 40 is slack. */
const MAX_DEPTH = 40;

/**
 * Steam's focus reason. TabMaster passes 3 and so does this.
 *
 * The enum is not published and the values were not worth reverse-engineering
 * for one call: 3 was observed to move the ring and keep it there. If a future
 * value is needed, TabMaster's bundle is where this one came from.
 */
const TAKE_FOCUS_REASON = 3;

interface NavNode {
  BTakeFocus(reason: number): boolean;
}

interface Fiber {
  memoizedProps?: { value?: unknown };
  return?: Fiber | null;
}

function isNavNode(value: unknown): value is NavNode {
  return (
    typeof value === "object" && value !== null &&
    typeof (value as NavNode).BTakeFocus === "function"
  );
}

/**
 * The nearest navigation node at or above `fiber`, or null.
 *
 * Exported for the tests, which can build a fiber chain but cannot build a
 * Steam page: there is no DOM environment in the suite, deliberately.
 */
export function navNodeFrom(fiber: Fiber | null | undefined): NavNode | null {
  let current = fiber;
  for (let depth = 0; depth < MAX_DEPTH && current; depth += 1) {
    const value = current.memoizedProps?.value;
    if (isNavNode(value)) return value;
    current = current.return;
  }
  return null;
}

/** The React fiber React attached to a DOM node, under a per-build key. */
function fiberOf(element: Element): Fiber | null {
  const key = Object.keys(element).find((name) => name.startsWith("__reactFiber"));
  return key ? ((element as unknown as Record<string, Fiber>)[key] ?? null) : null;
}

/**
 * Put the gamepad ring on `element`. Returns whether anything was moved.
 *
 * Never throws: this reaches through React's internals into Steam's, and a
 * plugin that cannot move a focus ring should carry on doing the rest of its
 * job. The caller decides whether a false is worth reporting.
 */
export function takeGamepadFocus(element: Element | null | undefined): boolean {
  if (!element) return false;
  try {
    const node = navNodeFrom(fiberOf(element));
    if (!node) return false;
    node.BTakeFocus(TAKE_FOCUS_REASON);
    return true;
  } catch {
    return false;
  }
}
