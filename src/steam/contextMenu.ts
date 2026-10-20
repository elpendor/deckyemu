/**
 * Our items in a game's context menu -- the one behind the cog.
 *
 * The preload rewrites Steam's game menu so its children pass through
 * `window.__deckyemu.gameMenu` on every render, with the selected games and
 * Steam's own menu components in hand. This registers the builder that runs
 * there. Nothing in here may throw into Steam's render, so the preload catches
 * whatever does, and a builder that answers nothing leaves Steam's menu as it
 * was.
 */

import type { Bridge, MenuModule } from "../preload/bridge";
import { sourceOf } from "../steamui/webpack";

/** Our item, so it can be recognised among Steam's. */
export const MENU_ITEM_KEY = "deckyemu-game-menu";

/** Steam's menu components, picked out of the menu module by what they do. */
export interface MenuParts {
  MenuItem: unknown;
  MenuGroup: unknown | null;
  Separator: unknown | null;
}

function partsOf(menus: MenuModule): MenuParts | null {
  const values = Object.values(menus);
  const pick = (test: (src: string) => boolean) => values.find((value) => test(sourceOf(value))) ?? null;
  const MenuItem = pick((src) => src.includes("bInteractableItem") && src.includes("onDisabledItemSelected"));
  if (!MenuItem) return null;
  return {
    MenuItem,
    MenuGroup: pick((src) => src.includes("bInGamepadUI:")),
    Separator: pick((src) => src.includes("ContextMenuSeparator")),
  };
}

/**
 * Add items to the menu of a single game. `render` builds them for one appid
 * from Steam's parts, or answers null for a game that is not ours.
 *
 * Returns a function that takes the builder away again.
 */
export function patchGameContextMenu(
  render: (appId: number, parts: MenuParts) => unknown | null,
): () => void {
  const bridge = (window as unknown as { __deckyemu?: Bridge }).__deckyemu;
  if (!bridge?.menu) {
    console.error("[deckyemu] the game menu patch is not in place; no menu item");
    return () => undefined;
  }
  bridge.menu.set((apps, _jsx, menus) => {
    if (apps?.length !== 1 || typeof apps[0]?.appid !== "number") return [];
    const parts = partsOf(menus);
    if (!parts) return [];
    const item = render(apps[0].appid, parts);
    return item ? [item] : [];
  });
  return () => bridge.menu.set(() => []);
}
