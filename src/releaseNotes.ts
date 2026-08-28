/**
 * Release notes, parsed out of the markdown a release body carries.
 *
 * Separated from rendering so the part with rules in it can be tested. The rules
 * are small but not obvious: a heading opens a section, a bullet adds an item,
 * and a line that is neither is still kept -- the notes are generated today, but
 * a hand-edited release body should show what it says rather than be silently
 * dropped.
 *
 * That last case stopped being hypothetical: a release body now opens with a
 * written summary above the generated sections, and it is prose. Rendered as
 * bullets it read as three changelog entries that happened to be sentences, and
 * its `**emphasis**` came out as literal asterisks -- so a line's *kind* is
 * carried through, and the emphasis is split out for the renderer rather than
 * shown raw.
 */

export interface NoteSpan {
  text: string;
  bold: boolean;
}

export interface NoteItem {
  /** The line, split into runs so `**this**` can be rendered as bold. */
  spans: NoteSpan[];
  /** Whether it was written as a list entry. Prose gets no bullet. */
  bullet: boolean;
}

export interface NoteSection {
  heading: string;
  items: NoteItem[];
}

/**
 * Split `**bold**` runs out of a line.
 *
 * Only double asterisks, and only in pairs. Markdown has a dozen other marks and
 * a release body is written by one person for this one panel -- supporting the
 * one that is actually used beats a half-renderer that gets italics subtly
 * wrong. An unpaired `**` is left exactly as typed, because a stray asterisk in
 * prose is more likely than an unclosed emphasis.
 */
export function inlineSpans(text: string): NoteSpan[] {
  const spans: NoteSpan[] = [];
  let rest = text;
  for (;;) {
    const open = rest.indexOf("**");
    if (open < 0) break;
    const close = rest.indexOf("**", open + 2);
    if (close < 0) break;
    if (open > 0) spans.push({ text: rest.slice(0, open), bold: false });
    const inner = rest.slice(open + 2, close);
    if (inner) spans.push({ text: inner, bold: true });
    rest = rest.slice(close + 2);
  }
  if (rest) spans.push({ text: rest, bold: false });
  return spans.length > 0 ? spans : [{ text, bold: false }];
}

export function parseNotes(text: string): NoteSection[] {
  const sections: NoteSection[] = [];

  for (const line of text.split("\n")) {
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      sections.push({ heading: heading[1], items: [] });
      continue;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const entry = (bullet ? bullet[1] : line).trim();
    if (!entry) continue;
    if (sections.length === 0) sections.push({ heading: "", items: [] });
    sections[sections.length - 1].items.push({
      spans: inlineSpans(entry),
      bullet: Boolean(bullet),
    });
  }

  return sections.filter((section) => section.items.length > 0);
}

export function countItems(sections: NoteSection[]): number {
  return sections.reduce((total, section) => total + section.items.length, 0);
}

/**
 * The first `limit` items, keeping them under the heading they belong to.
 *
 * `limit` of 0 means everything. Sections are truncated in order and an emptied
 * one is dropped rather than left as a bare heading, which would read as a
 * section that changed nothing.
 *
 * This exists because a long changelog pushed **Check for updates** so far down
 * the page that reaching it meant scrolling past every entry. The notes were
 * written to be shown in full on the grounds that this tab scrolls anyway --
 * true, but it made the button's distance from the top a function of how much
 * changed, which is worst exactly when a release is big enough to want checking.
 */
export function clampNotes(sections: NoteSection[], limit: number): NoteSection[] {
  if (limit <= 0) return sections;

  const kept: NoteSection[] = [];
  let left = limit;
  for (const section of sections) {
    if (left <= 0) break;
    const items = section.items.slice(0, left);
    left -= items.length;
    if (items.length > 0) kept.push({ heading: section.heading, items });
  }
  return kept;
}
