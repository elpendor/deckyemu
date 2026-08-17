import {
  afterPatch,
  fakeRenderComponent,
  findInReactTree,
  findInTree,
  findModuleByExport,
  type Patch,
} from "@decky/ui";

/**
 * Adding an item to the game context menu -- the one behind the cog.
 *
 * There is no API for this. Steam's `LibraryContextMenu` is found by matching
 * strings in minified source, its render is patched, and an element is spliced
 * into the children by hand. Every plugin that does it does it this way; this
 * follows decky-steamgriddb and hltb-for-deck, both of which are installed on
 * the development Deck and were read rather than guessed at.
 *
 * **Nothing here may throw.** This runs inside Steam's render, for every game
 * menu, including games this plugin has never heard of -- and §5 is explicit
 * that an uncaught throw there unmounts to whatever boundary Steam happens to
 * have, which in Game Mode is an empty screen recoverable only by restarting
 * Steam. Every step bails out instead: a shape that is not what was expected
 * means no menu item, never an exception.
 *
 * Expect this to break on a Steam update. It already has for the others --
 * decky-steamgriddb carries an `// Oct 2025 client` branch for the day the
 * appid moved. When the item disappears, this file is why.
 */

/** Our item, so it can be found again and replaced rather than duplicated. */
export const MENU_ITEM_KEY = "deckyemu-edit-game";

/**
 * Steam's game context menu component, or null if it cannot be found.
 *
 * Matched on the minified source containing `().LibraryContextMenu`, then on
 * the sibling that mentions `navigator:` -- the same two strings both other
 * plugins use, which is the only reason to believe they are stable at all.
 */
function libraryContextMenu(): { prototype: unknown } | null {
  try {
    const module = findModuleByExport(
      (exported: { toString?: () => string }) =>
        Boolean(exported?.toString && exported.toString().includes("().LibraryContextMenu")),
    );
    if (!module) return null;
    const sibling = Object.values(module).find(
      (value: unknown) =>
        Boolean((value as { toString?: () => string })?.toString?.().includes("navigator:")),
    );
    if (!sibling) return null;
    return fakeRenderComponent(sibling as never)?.type ?? null;
  } catch {
    return null;
  }
}

/**
 * Which game this menu belongs to.
 *
 * Three strategies, because two other plugins independently ended up with the
 * same three and two of them are scar tissue:
 *
 *  - the owner's overview, which is where it used to simply be;
 *  - a *different* appid found among the children, because Steam sometimes
 *    hands over one cached from a previously opened menu -- so the first answer
 *    can be confidently wrong rather than missing;
 *  - a search of the tree for `app.appid`, which is where an Oct 2025 client
 *    moved it.
 *
 * Getting this wrong is not cosmetic for us: the appid is the key into the
 * registry, so a stale one opens the editor on the wrong game. The caller
 * checks the answer against the library before showing anything.
 */
function appIdFor(component: unknown, children: unknown): number | null {
  const fromOwner = (node: unknown) =>
    (node as { _owner?: { pendingProps?: { overview?: { appid?: number } } } })
      ?._owner?.pendingProps?.overview?.appid ?? null;

  const direct = fromOwner(component);

  if (Array.isArray(children)) {
    const other = children.find((child) => {
      const found = fromOwner(child);
      return found !== null && found !== direct;
    });
    const corrected = fromOwner(other);
    if (corrected !== null) return corrected;
  }

  const inTree = findInTree(children, (node: { app?: { appid?: number } }) => Boolean(node?.app?.appid), {
    walkable: ["props", "children"],
  });
  return inTree?.app?.appid ?? direct;
}

/** Where "Properties..." is, which is the slot both other plugins sit above. */
function propertiesIndex(children: unknown[]): number {
  return children.findIndex((item) =>
    findInReactTree(item, (node: { onSelected?: () => void }) =>
      Boolean(node?.onSelected && node.onSelected.toString().includes("AppProperties")),
    ),
  );
}

/**
 * Put our item into `children`, replacing any copy already there.
 *
 * Steam re-renders this menu when it refreshes an app overview, so without the
 * removal the menu grows one of ours per render.
 */
function spliceItem(children: unknown[], item: unknown): void {
  const existing = children.findIndex(
    (child) => (child as { key?: string })?.key === MENU_ITEM_KEY,
  );
  if (existing !== -1) children.splice(existing, 1);

  const before = propertiesIndex(children);
  // No Properties entry means this is not the menu we think it is. Adding our
  // item to the end of some other menu is worse than not adding it.
  if (before === -1) return;
  children.splice(before, 0, item);
}

/**
 * Whether these children are a *game's* menu rather than another one.
 *
 * Screenshots and other lists use the same component. Both other plugins test
 * this the same way: only a game's menu has an entry whose handler mentions
 * `launchSource`.
 */
function isGameMenu(children: unknown): boolean {
  if (!Array.isArray(children) || children.length === 0) return false;
  return Boolean(
    findInReactTree(children, (node: { props?: { onSelected?: () => void } }) =>
      Boolean(
        node?.props?.onSelected && node.props.onSelected.toString().includes("launchSource"),
      ),
    ),
  );
}

/**
 * Add an item to every game context menu.
 *
 * `render` builds the element for one appid; returning null from it is how the
 * caller says "not one of ours", and nothing is spliced.
 *
 * Returns a function that removes the patches, for `onDismount`.
 */
export function patchGameContextMenu(
  render: (appId: number) => unknown | null,
): () => void {
  const menu = libraryContextMenu();
  if (!menu) {
    console.error("[deckyemu] could not find Steam's game context menu; no Edit item");
    return () => undefined;
  }

  let inner: Patch | undefined;
  let outer: Patch | undefined;

  /**
   * `hint` is only a hint, and re-resolving is the whole of this.
   *
   * The inner patches below are installed once and close over the appid from
   * the render that installed them, so a captured id names the first game whose
   * menu was ever opened -- and every menu after it. Trusting that put "Edit in
   * DeckyEmu" on a Steam-installed game, because that game was being judged
   * against a DeckyEmu game's id.
   *
   * The children being rendered right now are the reliable answer; the hint is
   * for when they do not carry one. decky-steamgriddb does the same and calls
   * the reason "sometimes cached from another context menu".
   */
  const apply = (children: unknown, hint: number | null) => {
    try {
      if (!Array.isArray(children) || !isGameMenu(children)) return;
      const appId = appIdFor(null, children) ?? hint;
      if (appId === null) return;
      const item = render(appId);
      if (item) spliceItem(children, item);
    } catch (error) {
      // Deliberately swallowed. See the note at the top of this file: the cost
      // of a throw here is the whole screen.
      console.error("[deckyemu] could not add the context menu item", error);
    }
  };

  try {
    outer = afterPatch(
      (menu as { prototype: any }).prototype,
      "render",
      // `any` at every boundary with Steam, narrowed immediately inside.
      // afterPatch hands over whatever the component returned and there is
      // no honest type for it.
      (_args: any[], component: any) => {
        try {
          const children = (component as { props?: { children?: unknown } })?.props?.children;
          const appId = appIdFor(component, children);

          if (!inner) {
            inner = afterPatch(component, "type", (_a: any[], ret: any) => {
              const prototype = ret?.type?.prototype;
              if (!prototype) return ret;

              // The first render of the menu itself.
              afterPatch(prototype, "render", (_b: any[], menuRet: any) => {
                const items = menuRet?.props?.children?.[0];
                apply(items, appId);
                return menuRet;
              });

              // And again when Steam refreshes the overview behind it, which
              // re-renders the menu without going back through the above.
              afterPatch(
                prototype,
                "shouldComponentUpdate",
                (args: any[], shouldUpdate: boolean) => {
                  const nextProps = args?.[0];
                  if (shouldUpdate === true) apply(nextProps?.children, appId);
                  return shouldUpdate;
                },
              );
              return ret;
            });
          } else {
            apply(children, appId);
          }
        } catch (error) {
          console.error("[deckyemu] context menu patch failed", error);
        }
        return component;
      },
    );
  } catch (error) {
    console.error("[deckyemu] could not patch the game context menu", error);
  }

  return () => {
    try {
      outer?.unpatch();
      inner?.unpatch();
    } catch (error) {
      console.error("[deckyemu] could not remove the context menu patch", error);
    }
  };
}
