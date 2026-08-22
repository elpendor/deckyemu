import { splitTail } from "./filenameTail";

/**
 * A filename on screen, cut the way the surrounding thing needs it cut.
 *
 * Long filenames have now caused the same fault in four places, and the fix was
 * not the same fix each time -- which is why this exists as a component with a
 * mode rather than one rule applied everywhere. Both behaviours are correct;
 * choosing between them is a question about the *reader*, not the string.
 *
 * A `.pkg` arrives named
 * `UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6....pkg` -- a hundred
 * characters with no spaces in them. There is no break for a layout to find, so
 * left alone it runs straight out of whatever is holding it.
 *
 * **`clamp`** keeps it to one line, cutting the middle. For a row in a list,
 * and especially one that repolls: the transfer status row re-reads every
 * couple of seconds, and a name allowed to reflow would change the panel's
 * height each time the byte count grows a digit. The middle rather than the end
 * because the end is the half worth keeping -- a ROM carries its region and
 * revision there, `... (USA) (Rev 2).z64`, and a .pkg does not say what the
 * game is until two thirds of the way in.
 *
 * **`wrap`** keeps all of it, over as many lines as it takes. For the thing
 * being decided about: a delete confirmation is asked once, costs nothing to
 * grow, and the answer depends on being sure which file it is. AddGamePanel
 * reached the same conclusion for its picker button -- *kept whole rather than
 * truncated* -- before any of this was shared.
 *
 * The rule, then: **a list clamps, a decision wraps.**
 */

interface Props {
  name: string;
  /** `clamp` for a row in a list, `wrap` for the file a dialog is about. */
  mode?: "clamp" | "wrap";
  /** Merged onto the outer element, for weight or colour at the call site. */
  style?: React.CSSProperties;
}

export function FileName({ name, mode = "clamp", style }: Props) {
  if (mode === "wrap") {
    // `anywhere` rather than `break-word`: these names have no spaces, so a
    // rule that only breaks between words has nothing to break between.
    return <div style={{ overflowWrap: "anywhere", ...style }}>{name}</div>;
  }

  /*
   * The measuring is the browser's, which is the point.
   *
   * A character budget was tried first and produced a name with two ellipses in
   * it: the panel is measured in pixels and the font is proportional, so no
   * count is right for both `WWWW` and `iiii` -- and when the count came out
   * long, the CSS clamp underneath cut it again. Handing the two pieces to a
   * flex row lets the head shrink and ellipsize while the tail never does. One
   * ellipsis, at whatever width the container happens to be, and none at all
   * when the name fits.
   *
   * `minWidth: 0` on both, because a flex child defaults to `min-width: auto`
   * and refuses to shrink below its content -- which is exactly the overflow
   * this is here to prevent.
   */
  const [head, tail] = splitTail(name);
  return (
    <div style={{ display: "flex", minWidth: 0, overflow: "hidden", ...style }}>
      <span
        style={{
          minWidth: 0,
          flex: "0 1 auto",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {head}
      </span>
      {/* Never shrinks, so the region, revision and extension survive whatever
          happens to the front of the name. */}
      <span style={{ flex: "0 0 auto", whiteSpace: "nowrap" }}>{tail}</span>
    </div>
  );
}
