/**
 * The DeckyEmu tile in the Steam library.
 *
 * A non-Steam shortcut to the service's `rescue.sh`, which opens the rescue
 * page: status, update, roll back, restart. It is the way in that needs
 * nothing of ours inside Steam to work, so it is added while everything does,
 * once, and put back if somebody deletes it.
 *
 * The app id is kept in this page's localStorage rather than the backend's
 * settings: it is a fact about this Steam install, and Steam keeps the storage
 * with it.
 */

import { call } from "./host/channel";
import { createShortcut, removeShortcut, setShortcutIcon, shortcutExists } from "./steam";

const KEY = "deckyemu.rescueTile";

interface Tile {
  name: string;
  exe: string;
  start_dir: string;
  icon?: string;
}

export async function ensureRescueTile(): Promise<void> {
  try {
    const tile = await call<Tile>("host.tile");
    // Steam's own list is the record that survives; localStorage alone let a
    // reload add the tile again, five times over on the development Deck.
    const apps = (window as unknown as { appStore?: { allApps?: { appid: number; display_name: string }[] } })
      .appStore?.allApps ?? [];
    const existing = apps.filter((app) => app.display_name === tile.name).map((app) => app.appid);
    const known = Number(localStorage.getItem(KEY) || 0);
    const keep = existing.includes(known) ? known : existing[0];
    if (keep && shortcutExists(keep)) {
      for (const extra of existing) if (extra !== keep) removeShortcut(extra);
      localStorage.setItem(KEY, String(keep));
      return;
    }
    const appId = await createShortcut({
      title: tile.name,
      exe: tile.exe,
      startDir: tile.start_dir,
      launchOptions: "",
    });
    if (tile.icon) setShortcutIcon(appId, tile.icon);
    localStorage.setItem(KEY, String(appId));
    console.log(`[deckyemu] added the library tile as ${appId}`);
  } catch (error) {
    console.error("[deckyemu] could not add the library tile", error);
  }
}
