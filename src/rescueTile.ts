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
import { applyArtwork, createShortcut, removeShortcut, setShortcutIcon, shortcutExists } from "./steam";
import type { ArtImage } from "./backend/games";

const KEY = "deckyemu.rescueTile";
const ART_KEY = "deckyemu.rescueTile.art";
// How long to wait for Steam to load the library at boot.
const LIBRARY_WAIT_MS = 60_000;

interface Tile {
  name: string;
  exe: string;
  start_dir: string;
  icon?: string;
  art?: Partial<Record<"capsule" | "header" | "hero" | "logo", ArtImage>>;
  art_version?: string;
}

type App = { appid: number; display_name: string };

function libraryApps(): App[] {
  return (window as unknown as { appStore?: { allApps?: App[] } }).appStore?.allApps ?? [];
}

/** Resolves once Steam's library has loaded, or after the wait runs out. */
async function libraryLoaded(): Promise<boolean> {
  const until = Date.now() + LIBRARY_WAIT_MS;
  while (libraryApps().length === 0) {
    if (Date.now() > until) return false;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return true;
}

export async function ensureRescueTile(): Promise<void> {
  try {
    const tile = await call<Tile>("host.tile");
    // Before the library loads, every tile looks missing; deciding then added
    // a second one at boot.
    if (!(await libraryLoaded())) {
      console.warn("[deckyemu] Steam's library never loaded; the tile is left alone");
      return;
    }
    const existing = libraryApps().filter((app) => app.display_name === tile.name).map((app) => app.appid);
    const known = Number(localStorage.getItem(KEY) || 0);
    let appId = known && shortcutExists(known) ? known : existing.find((id) => shortcutExists(id));
    if (appId) {
      for (const extra of existing) if (extra !== appId) removeShortcut(extra);
    } else {
      appId = await createShortcut({
        title: tile.name,
        exe: tile.exe,
        startDir: tile.start_dir,
        launchOptions: "",
      });
      if (tile.icon) setShortcutIcon(appId, tile.icon);
      localStorage.removeItem(ART_KEY);
      console.log(`[deckyemu] added the library tile as ${appId}`);
    }
    localStorage.setItem(KEY, String(appId));

    if (tile.art && tile.art_version && localStorage.getItem(ART_KEY) !== tile.art_version) {
      // The icon is part of the art's version, so a new one reaches a tile
      // that already exists.
      if (tile.icon) setShortcutIcon(appId, tile.icon);
      if (await applyArtwork(appId, tile.art)) localStorage.setItem(ART_KEY, tile.art_version);
    }
  } catch (error) {
    console.error("[deckyemu] could not add the library tile", error);
  }
}
