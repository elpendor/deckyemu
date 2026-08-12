/**
 * Release notes, parsed out of the markdown a release body carries.
 *
 * Separated from rendering so the part with rules in it can be tested. The rules
 * are small but not obvious: a heading opens a section, a bullet adds an item,
 * and a line that is neither is still kept -- the notes are generated today, but
 * a hand-edited release body should show what it says rather than be silently
 * dropped.
 */

export interface NoteSection {
  heading: string;
  items: string[];
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
    sections[sections.length - 1].items.push(entry);
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
