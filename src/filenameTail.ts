/**
 * Split a filename into the part that may be cut and the part that may not.
 *
 * A ROM carries its region and revision at the end -- `... (USA) (Rev 2).z64`
 * -- and a .pkg names the game two thirds of the way in, after a product code:
 * `UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6.pkg`. So the end is the
 * half a plain `text-overflow: ellipsis` throws away, which is the wrong half.
 * AddGamePanel says the same where it chose to wrap its button label rather
 * than cut it.
 *
 * **Why a split rather than a shortened string.** The first attempt at this
 * built the whole name with an ellipsis already in it, cut to a character
 * budget. That was wrong twice over and looked it on the device: the panel is
 * measured in pixels and the font is proportional, so no character count is
 * right for both `WWWW` and `iiii` -- and when the count came out too long the
 * CSS clamp underneath cut it *again*, so the row showed two ellipses:
 *
 *     JihleyZwknjKiJCTeSMYV…iUQnYgWjyAzaeJpi…
 *
 * Handing the two pieces to a flex row instead lets the browser do the
 * measuring it is already doing. The head shrinks and ellipsizes; the tail
 * never shrinks. One ellipsis, in the middle, at whatever width the panel
 * happens to be -- and none at all when the name fits, which no budget can
 * promise.
 *
 * What is left here is the only part that is genuinely about filenames: how
 * much of the end is identity rather than padding.
 */

/**
 * How many characters at the end to protect from being cut.
 *
 * Sized against what actually appears there -- `(USA) (Rev 2).z64` is 17,
 * `(Disc 1 of 2).chd` is 17, `_fbd920a6.pkg` is 13. Above this the head starts
 * losing the part that reads as a title for the sake of padding; below it a
 * revision marker gets cut in half, which is worse than dropping it, because
 * `(Rev` reads as a different file rather than a shortened one.
 */
export const TAIL_CHARS = 17;

/**
 * `[head, tail]` for `name` — concatenating them is always the original.
 *
 * The tail is never longer than the name, so a short name comes back as
 * `["", name]` and renders whole with nothing to cut.
 */
export function splitTail(name: string, tailChars: number = TAIL_CHARS): [string, string] {
  // Code points rather than string indices: cutting a surrogate pair in half
  // yields a replacement character, which reads as a corrupted filename rather
  // than a shortened one.
  const chars = Array.from(name);
  if (chars.length <= tailChars) return ["", name];
  const cut = chars.length - tailChars;
  return [chars.slice(0, cut).join(""), chars.slice(cut).join("")];
}
