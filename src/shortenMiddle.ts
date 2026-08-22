/**
 * Shorten `text` from the middle, keeping both ends.
 *
 * For filenames, and specifically for the two shapes this plugin sees most.
 * A ROM carries its region and revision at the end -- `... (USA) (Rev 2).z64`
 * -- and a .pkg carries the game there too:
 * `UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6.pkg` opens with a product
 * code and only says what the game is two thirds of the way in. So the end is
 * the half a plain `text-overflow: ellipsis` would throw away, which is the
 * wrong half. AddGamePanel says the same thing where it decided to wrap its
 * button label rather than cut it.
 *
 * Cutting the middle instead keeps the part that reads as a title and the part
 * that says which dump it is, and loses the run of characters in between that
 * nobody identifies a file by.
 *
 * Splitting the budget evenly, with the odd character going to the tail: there
 * is no rule about where the interesting part sits that holds for both shapes
 * above, so neither end is favoured beyond breaking the tie.
 */
export function shortenMiddle(text: string, max: number): string {
  // Array.from rather than slice on the string: a name with an emoji in it is
  // rare and cutting one in half would produce a replacement character, which
  // looks like a corrupted filename rather than a shortened one.
  const chars = Array.from(text);
  if (chars.length <= max) return text;
  // Nothing sensible to return from a budget that cannot hold the ellipsis and
  // a character either side of it; the caller gets the head it asked for.
  if (max <= 3) return chars.slice(0, Math.max(0, max)).join("");

  const keep = max - 1;
  const tail = Math.ceil(keep / 2);
  const head = keep - tail;
  return `${chars.slice(0, head).join("")}…${chars.slice(chars.length - tail).join("")}`;
}
