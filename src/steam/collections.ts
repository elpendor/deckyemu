/**
 * Steam collections: filing games onto shelves, and clearing shelves away.
 *
 * Everything here works in collection *names*, because that is what Steam's own
 * lookup takes and what the backend records. `collectionStore.userCollections`
 * is a Map on some builds and an array on others, so it is only ever read
 * through `allCollections`.
 *
 * These are the primitives. Anything that has to tell the backend what happened
 * -- which collections are ours, which have gone -- lives in `src/collections.ts`
 * instead, because this package must stay free of backend imports: it is
 * exercised by tests that run under Node, where `@decky/api` will not load.
 */
import {
  collectionStore,
  overviewsFor,
  type Collection,
  type CollectionExtras,
} from "./client";

/**
 * Every user collection, regardless of how Steam is storing them.
 *
 * `userCollections` is a Map on some Steam builds and an array on others.
 * Iterating it directly with for..of yields [key, value] pairs for a Map, so
 * `displayName` comes back undefined and nothing matches. Both types expose
 * `.values()`, so going through that works either way.
 */
function allCollections(): Collection[] {
  const store = collectionStore();
  const raw = store?.userCollections;
  if (!raw) return [];
  try {
    const iterable = raw as { values?: () => IterableIterator<Collection> };
    if (typeof iterable.values === "function") {
      return Array.from(iterable.values());
    }
    return Array.isArray(raw) ? raw : [];
  } catch (error) {
    console.error("[deckyemu] could not enumerate collections", error);
    return [];
  }
}

function findCollection(tag: string): Collection | undefined {
  const store = collectionStore();
  if (!store) return undefined;
  const id = store.GetCollectionIDByUserTag(tag);
  return typeof id === "string" ? store.GetCollection(id) : undefined;
}

async function getOrCreateCollection(tag: string): Promise<Collection | undefined> {
  const store = collectionStore();
  if (!store) return undefined;

  const existing = findCollection(tag);
  if (existing) return existing;

  const created = store.NewUnsavedCollection(tag, undefined, []);
  if (!created) return undefined;
  await created.Save();
  return created;
}

/**
 * Files games under a user collection so they are grouped in Big Picture
 * instead of being lost among every other non-Steam shortcut.
 */
export async function addAppsToCollection(tag: string, appIds: number[]): Promise<boolean> {
  if (!tag || appIds.length === 0) return true;

  try {
    const collection = await getOrCreateCollection(tag);
    if (!collection) return false;

    const missing = appIds.filter((appId) => !collection.apps.has(appId));
    if (missing.length === 0) return true;

    const overviews = await overviewsFor(missing);
    if (overviews.length === 0) return false;

    collection.AsDragDropCollection().AddApps(overviews);
    await collection.Save();
    return true;
  } catch (error) {
    console.error("[deckyemu] addAppsToCollection failed", error);
    return false;
  }
}

export async function addToCollection(appId: number, tag: string): Promise<boolean> {
  return addAppsToCollection(tag, [appId]);
}

/**
 * Takes games out of a collection, and deletes the collection if we emptied it.
 *
 * The delete is deliberately conditional: the user may have dragged their own
 * games in, and removing a collection that still holds them would be
 * destructive.
 *
 * `deleted` names the collection when this call removed it, and is empty
 * otherwise. Reported rather than kept quiet because the backend records which
 * collections are ours, and a name left in that record after its collection has
 * gone would go on being claimed. Nothing here can tell the backend -- this file
 * must stay free of backend imports -- so it says so to its caller instead.
 */
export async function removeAppsFromCollection(
  tag: string,
  appIds: number[],
): Promise<{ ok: boolean; deleted: string }> {
  if (!tag || appIds.length === 0) return { ok: true, deleted: "" };

  try {
    const collection = findCollection(tag);
    if (!collection) return { ok: true, deleted: "" };

    const present = appIds.filter((appId) => collection.apps.has(appId));
    if (present.length > 0) {
      const overviews = await overviewsFor(present);
      if (overviews.length > 0) {
        collection.AsDragDropCollection().RemoveApps(overviews);
        await collection.Save();
      }
    }

    const extras = collection as unknown as CollectionExtras;
    const remaining = extras.allApps?.length ?? 1;
    if (remaining === 0 && typeof extras.Delete === "function") {
      await extras.Delete();
      console.log(`[deckyemu] deleted now-empty collection "${tag}"`);
      return { ok: true, deleted: tag };
    }
    return { ok: true, deleted: "" };
  } catch (error) {
    console.error("[deckyemu] removeAppsFromCollection failed", error);
    return { ok: false, deleted: "" };
  }
}

export interface StaleCollection {
  tag: string;
  appIds: number[];
}

/**
 * Collections holding our games that those games no longer belong to.
 *
 * Needed because games added by an older build did not record their collection,
 * so a rename could not know where to remove them from and left the old
 * collection populated. Rather than guessing a name, this looks at what Steam
 * actually contains.
 *
 * Only collections holding a game we registered are considered, and the caller
 * is expected to show the list for confirmation before anything is removed --
 * one of these could be a collection the user curates by hand.
 */
/**
 * Which collections actually hold our games, whatever the registry believes.
 *
 * Asked of Steam rather than of `library.json`, because the two can disagree
 * and only one of them is what the user is looking at. A game added by a build
 * that did not record its collection -- or one whose record was cleared by an
 * unfiling that then failed -- sits in a collection while its entry says it is
 * nowhere. Trusting the entry there means "turn collections off" quietly does
 * nothing while the shelves stay on screen, which is exactly what it did.
 *
 * Expressed as "every game belongs nowhere", which is what makes any collection
 * holding one of them stale.
 */
export function findFiledGames(appIds: number[]): StaleCollection[] {
  const nowhere: Record<string, string> = {};
  for (const appId of appIds) nowhere[String(appId)] = "";
  return findStaleCollections(nowhere);
}

export function findStaleCollections(
  targets: Record<string, string>,
): StaleCollection[] {
  const store = collectionStore();
  if (!store) return [];

  const stale: StaleCollection[] = [];
  try {
    for (const collection of allCollections()) {
      const tag = collection.displayName;
      if (!tag) continue;

      const misplaced: number[] = [];
      for (const [appIdText, target] of Object.entries(targets)) {
        const appId = Number(appIdText);
        if (!appId || tag === target) continue;
        if (collection.apps?.has?.(appId)) misplaced.push(appId);
      }

      if (misplaced.length > 0) stale.push({ tag, appIds: misplaced });
    }
  } catch (error) {
    console.error("[deckyemu] findStaleCollections failed", error);
  }

  return stale;
}

/**
 * Games that are not in the collection they belong to.
 *
 * The mirror of `findStaleCollections`: that one finds our games in the wrong
 * place, this one finds them missing from the right one. Neither implies the
 * other, and neither is answerable from the registry -- a game can be recorded
 * as filed and simply not be there, because the add failed when it was first put
 * in or because the collection was deleted in Steam afterwards. The migration is
 * blind to it by construction: it moves games whose target differs from what was
 * recorded, and here the two agree.
 *
 * Grouped by collection, so the caller can add them in one call per shelf.
 */
export function findUnfiledGames(targets: Record<string, string>): StaleCollection[] {
  const store = collectionStore();
  if (!store) return [];

  const missing = new Map<string, number[]>();
  try {
    for (const [appIdText, tag] of Object.entries(targets)) {
      const appId = Number(appIdText);
      if (!appId || !tag) continue;

      const collection = findCollection(tag);
      // A build that exposes no readable membership is "cannot tell", never
      // "not there" -- the same rule findEmptyCollections uses. Reporting every
      // game as unfiled on such a build would be a finding that never clears.
      if (collection && typeof collection.apps?.has !== "function") continue;
      // No collection at all means every game bound for it is unfiled, which is
      // the deleted-in-Steam case.
      if (collection?.apps?.has?.(appId)) continue;

      missing.set(tag, [...(missing.get(tag) ?? []), appId]);
    }
  } catch (error) {
    console.error("[deckyemu] findUnfiledGames failed", error);
  }

  return [...missing].map(([tag, appIds]) => ({ tag, appIds }));
}

/** Put games on the shelf they belong to. Returns how many were filed. */
export async function fileUnfiledGames(unfiled: StaleCollection[]): Promise<number> {
  let filed = 0;
  for (const entry of unfiled) {
    if (await addAppsToCollection(entry.tag, entry.appIds)) filed += entry.appIds.length;
  }
  return filed;
}

/**
 * Collections this plugin made that now hold nothing.
 *
 * A collection is emptied as its last game leaves, but only where something was
 * there to notice. Remove a shortcut in Steam itself, or use a build from
 * before removal did this, and the shelf stays in the library with nothing on
 * it -- and by then no registered game names it, so it cannot be found the way
 * every other collection here is found.
 *
 * `matches` decides ours from the user's own, and is built from the same
 * template the name was made with. Nothing that fails it is touched, however
 * empty: an empty collection somebody made by hand is theirs to keep.
 */
export function findEmptyCollections(matches: (name: string) => boolean): string[] {
  const store = collectionStore();
  if (!store) return [];

  const empty: string[] = [];
  try {
    for (const collection of allCollections()) {
      const tag = collection.displayName;
      if (!tag || !matches(tag)) continue;
      const extras = collection as unknown as CollectionExtras;
      // Absent rather than zero means a Steam build that does not expose it.
      // Deleting on "I could not tell" is not a trade worth making.
      if (Array.isArray(extras.allApps) && extras.allApps.length === 0) empty.push(tag);
    }
  } catch (error) {
    console.error("[deckyemu] findEmptyCollections failed", error);
  }
  return empty;
}

/** Delete collections by tag. Returns how many went. */
export async function deleteCollections(tags: string[]): Promise<number> {
  let deleted = 0;
  for (const tag of tags) {
    try {
      const collection = findCollection(tag);
      if (!collection) continue;
      const extras = collection as unknown as CollectionExtras;
      // Re-checked at the moment of deleting, not trusted from when the list
      // was built: a dialog can sit open for a while, and a collection that
      // gained a game in between must not be deleted for being empty earlier.
      if ((extras.allApps?.length ?? 1) !== 0) continue;
      if (typeof extras.Delete !== "function") continue;
      await extras.Delete();
      deleted += 1;
    } catch (error) {
      console.error(`[deckyemu] could not delete collection "${tag}"`, error);
    }
  }
  return deleted;
}

/**
 * Remove our games from collections they no longer belong to.
 *
 * `deleted` is whichever of them this emptied and removed, for the caller to
 * stop claiming. See `removeAppsFromCollection`.
 */
export async function pruneStaleCollections(
  stale: StaleCollection[],
): Promise<{ pruned: number; deleted: string[] }> {
  let pruned = 0;
  const deleted: string[] = [];
  for (const entry of stale) {
    const result = await removeAppsFromCollection(entry.tag, entry.appIds);
    if (result.ok) pruned += entry.appIds.length;
    if (result.deleted) deleted.push(result.deleted);
  }
  return { pruned, deleted };
}

export interface CollectionMove {
  app_id: number;
  title: string;
  from: string;
  to: string;
}

/**
 * Move already-added games between collections after a settings change.
 *
 * Additions happen before removals so a game is never briefly in no collection
 * at all, which would show up as a flicker in the library.
 */
export async function migrateCollections(
  moves: CollectionMove[],
): Promise<{ moved: number; assignments: Record<string, string>; deleted: string[] }> {
  const assignments: Record<string, string> = {};
  // Collections emptied and removed on the way, for the caller to stop
  // claiming. A rename is the operation most likely to empty one.
  const deleted: string[] = [];
  if (moves.length === 0) return { moved: 0, assignments, deleted };

  const byTarget = new Map<string, number[]>();
  const bySource = new Map<string, number[]>();
  // Appended in place. Rebuilding the array per move copies every id already
  // grouped under that name, which is quadratic in the size of a rename -- and a
  // rename is exactly the operation that touches the whole library at once.
  const group = (map: Map<string, number[]>, tag: string, appId: number) => {
    const existing = map.get(tag);
    if (existing) existing.push(appId);
    else map.set(tag, [appId]);
  };
  // A move with no target takes a game out of collections and puts it nowhere:
  // the feature switched off, or the name cleared. It has no addition to make,
  // so it needs tracking separately -- grouping by target would drop it, which
  // is what made turning collections off do nothing at all.
  const unfiling = new Set<number>();
  for (const move of moves) {
    if (move.to) group(byTarget, move.to, move.app_id);
    else unfiling.add(move.app_id);
    if (move.from) group(bySource, move.from, move.app_id);
  }

  let moved = 0;
  for (const [tag, appIds] of byTarget) {
    if (await addAppsToCollection(tag, appIds)) {
      for (const appId of appIds) {
        assignments[String(appId)] = tag;
        moved += 1;
      }
    }
  }

  for (const [tag, appIds] of bySource) {
    // Only pull a game out of its old collection once it is safely in the new
    // one, so a failure mid-way leaves it findable rather than orphaned. A game
    // being unfiled has no new collection to reach: the removal is the whole
    // operation, so it is recorded and counted only once that has succeeded --
    // otherwise the entry would forget a collection it is still sitting in.
    const settled = appIds.filter(
      (appId) => unfiling.has(appId) || assignments[String(appId)],
    );
    if (settled.length === 0) continue;
    const result = await removeAppsFromCollection(tag, settled);
    if (result.deleted) deleted.push(result.deleted);
    if (!result.ok) continue;
    for (const appId of settled) {
      if (!unfiling.has(appId)) continue;
      assignments[String(appId)] = "";
      moved += 1;
    }
  }

  return { moved, assignments, deleted };
}
