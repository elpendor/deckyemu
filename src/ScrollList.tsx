import { Focusable } from "@decky/ui";
import type { CSSProperties, ReactNode } from "react";

import {
  SCROLLER_CLASS,
  SCROLLER_CSS,
  SCROLLER_ROW_CLASS,
  SCROLLER_ROW_CSS,
  SCROLLER_ROW_FOCUS_CLASS,
} from "./dialogStyle";

const noop = () => {};

/**
 * A bounded list that scrolls, and says that it does.
 *
 * Every dialog here had its own `<Focusable style={{ maxHeight, overflowY }}>`,
 * which is three quarters of a scroll region: a controller can enter it, but
 * nothing tells the reader there is anything below the fold, because Steam's
 * CEF draws no scrollbar. This carries the rule that restores one, so the next
 * dialog with a long list gets it by using this instead of writing the pair of
 * properties again.
 *
 * The rule is rendered here rather than by whichever panel opened the dialog. A
 * modal is its own tree and a panel's `<style>` is not always in the document
 * when one is up -- the same arrangement, and the same reason, as `DANGER_CSS`.
 * Repeating the tag per list is harmless: identical rules, and the last one
 * wins with the same values.
 *
 * `overscroll-behavior: contain` stops the scroll chaining to the dialog body,
 * which also scrolls -- without it, reaching the end of this list scrolls the
 * dialog underneath instead.
 *
 * **No `flow-children`.** It was tried while the escaping focus ring was still
 * unexplained, and the explanation turned out to be elsewhere. It tells Steam
 * how to navigate the children, and setting it here would impose a column on
 * every caller -- including the ones holding a form or a whole panel rather
 * than a list, whose navigation nobody has tested since. A caller that needs it
 * can say so itself.
 */
export function ScrollList({
  className,
  style,
  children,
}: {
  /** A caller's class, for rules about the children. Added, not replacing. */
  className?: string;
  /** Whatever bounds it: `maxHeight`, and any layout the caller had. */
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <>
      <style>{SCROLLER_CSS + SCROLLER_ROW_CSS}</style>
      <Focusable
        className={className ? `${SCROLLER_CLASS} ${className}` : SCROLLER_CLASS}
        style={{
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          overflowY: "auto",
          overscrollBehavior: "contain",
          // Room for a focus ring, and a margin for the row being scrolled into
          // view, so neither lands flush against the clip.
          padding: "2px",
          scrollPaddingBlock: "6px",
          ...style,
        }}
      >
        {children}
      </Focusable>
    </>
  );
}

/**
 * A row in a `ScrollList` that is read rather than pressed.
 *
 * **Steam's focus ring is drawn outside the element's box**, so a clipped list
 * cannot contain it: the ring on the first and last rows appears above and
 * below the list, over whatever is there. `noFocusRing` turns it off and the
 * class draws an inset highlight instead, which paints within the row and so
 * within the clip.
 *
 * Only for a row with nothing to press. Where the rows are buttons, Steam's
 * ring is the focus appearance every button in the interface has, and trading
 * that for a local one would be a worse bargain than the ring overhanging.
 *
 * `onActivate` is what makes the row reachable at all: a controller cannot
 * enter a scroll region with nothing focusable in it, so a list of plain text
 * has everything below the fold unreachable without this.
 */
export function ScrollRow({ children }: { children: ReactNode }) {
  return (
    <Focusable
      className={SCROLLER_ROW_CLASS}
      style={{ scrollMarginBlock: "6px" }}
      noFocusRing
      focusWithinClassName={SCROLLER_ROW_FOCUS_CLASS}
      onActivate={noop}
    >
      {children}
    </Focusable>
  );
}
