/**
 * A list of note fragments, as something that reads like a sentence.
 *
 * Two toasts are built by collecting fragments as things happen -- "renamed",
 * "moved to [DeckyEmu] Game Boy", "no artwork found" -- and joining them. Each
 * reads correctly in the middle of a list and wrongly at the front of one, so
 * the toast came out as "renamed" while the fallback beside it in the same call
 * said "Saved."
 *
 * Capitalising at the join rather than writing every fragment twice: a fragment
 * has to work in both positions, and only the joined string knows which one it
 * ended up in.
 */
export function sentence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "";

  // Only a letter. A body opening with a count -- "3 artwork image(s) applied"
  // -- or a filename is already right, and forcing a case on either would be
  // wrong for the filename.
  const first = trimmed[0];
  const opened = first.toLowerCase() !== first.toUpperCase()
    ? first.toUpperCase() + trimmed.slice(1)
    : trimmed;

  return /[.!?]$/.test(opened) ? opened : opened + ".";
}
