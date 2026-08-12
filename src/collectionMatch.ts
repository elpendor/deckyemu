import { type CollectionShape } from "./backend";

/**
 * Recognises a collection name this plugin would have produced.
 *
 * Built from the very template the name was built with, so it cannot drift
 * from it. Everything outside the `{platform}` placeholder is matched
 * literally and escaped first — a base name of "Emu (Deck)" is a name, not a
 * group, and treating it as a pattern is how a matcher for our shelves starts
 * matching somebody else's.
 *
 * `{platform}` becomes `.+` rather than `.*`: with `.*` a per-platform setup
 * would also match the bare base name, which is what the *non*-per-platform
 * setting produces and may well be a collection the user still curates.
 *
 * Returns a matcher that says no to everything when there is no name
 * configured. Collections are off in that case, so nothing here is ours.
 *
 * Its own module rather than a helper inside OrphanModal, because what it
 * decides is whether a collection gets deleted, and a rule with that
 * consequence has to be reachable by a test. It was checked by a second copy
 * of itself written in Python, which proved the copy right and said nothing
 * about this.
 */
export function emptyCollectionMatcher(shape: CollectionShape): (name: string) => boolean {
  const base = (shape.base || "").trim();
  if (!base) return () => false;
  if (!shape.per_platform) return (name) => name === base;

  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = escape(shape.template || "{name} - {platform}")
    .replace(/\\\{name\\\}/g, escape(base))
    .replace(/\\\{platform\\\}/g, ".+");
  let expression: RegExp;
  try {
    expression = new RegExp(`^${pattern}$`);
  } catch {
    return () => false;
  }
  return (name) => expression.test(name);
}
