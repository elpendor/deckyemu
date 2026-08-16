import { type CollectionShape } from "./backend";

/**
 * Recognises a collection this plugin made.
 *
 * Two answers, in order, and the first is the one that should win over time.
 *
 * **What was recorded.** `shape.known` is every collection a game was actually
 * filed into, kept by the backend as it happened. It needs no reasoning about
 * naming at all, and it is the only answer that survives the naming changing:
 * a shelf made as "[DeckyEmu] N64" is still ours after the template moves to
 * "N64 (DeckyEmu)", after per-system naming is switched off, and after the base
 * name is edited — none of which the pattern below can say, because it is built
 * from settings that describe today and the question is about the past. That
 * gap was not theoretical: it made every shelf from a previous naming invisible
 * to the one thing that would have cleared it away, permanently.
 *
 * **What the naming would produce.** The pattern is kept as the fallback, for
 * collections filed before the record existed. Everything outside the
 * `{platform}` placeholder is matched literally and escaped first — a base name
 * of "Emu (Deck)" is a name, not a group, and treating it as a pattern is how a
 * matcher for our shelves starts matching somebody else's. `{platform}` becomes
 * `.+` rather than `.*`: with `.*` a per-platform setup would also match the
 * bare base name, which is what the *non*-per-platform setting produces and may
 * well be a collection the user still curates.
 *
 * A union, never an intersection. Either answer saying "ours" is enough.
 *
 * **Every path that touches a collection asks this first.** It used to gate
 * only the deletion of empty ones, so the checks that take games *out* of a
 * collection ran against whatever Steam listed -- and a game of ours sitting on
 * somebody else's shelf read as misplaced. A Unifideck collection was reported
 * as one our games had "left", and turning collections off emptied it. Nothing
 * here may reach a collection this plugin did not make, so the rule cannot be
 * the caller's to remember.
 *
 * Its own module rather than a helper inside OrphanModal, because what it
 * decides is whether a collection gets deleted or emptied, and a rule with that
 * consequence has to be reachable by a test.
 */
export function ownedCollectionMatcher(shape: CollectionShape): (name: string) => boolean {
  const known = new Set(shape.known ?? []);
  const byPattern = patternMatcher(shape);
  return (name) => known.has(name) || byPattern(name);
}

function patternMatcher(shape: CollectionShape): (name: string) => boolean {
  const base = (shape.base || "").trim();
  // No name configured means collections are off, and nothing the *pattern*
  // could recognise is ours. What was recorded still is, which is why this is
  // the inner half rather than an early return from the whole matcher.
  if (!base) return () => false;
  if (!shape.per_platform) return (name) => name === base;

  // No fallback of its own. `collection_shape` resolves the template against
  // the backend's default before sending it, and a second default here is a
  // second thing to keep in step -- which it was not: this said one string
  // while the stored default said another, so a blank setting produced names
  // in one format and was recognised in the other.
  if (!shape.template) return (name) => name === base;

  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = escape(shape.template)
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
