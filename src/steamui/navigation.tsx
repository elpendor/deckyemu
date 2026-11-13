/**
 * Steam's router, side menus and modal manager, through the objects it keeps
 * on `window.SteamUIStore` -- the Game Mode window's own instance, which holds
 * its navigator, history, menu store and modal manager.
 */

import { useEffect, useState, type ReactNode } from "react";

import { registerLookup } from "./components";
import { findExport, findModule } from "./webpack";

type Any = Record<string, any>;

function store(): Any | undefined {
  return (window as unknown as { SteamUIStore?: Any }).SteamUIStore;
}

/** The Game Mode window: navigator, history, menus, modals and its window. */
export function mainWindow(): Any | undefined {
  return store()?.WindowStore?.GamepadUIMainWindowInstance;
}

/** Steam's side menus, by the number its menu store uses. */
export const SideMenu = { None: 0, Main: 1, QuickAccess: 2 } as const;

export const Navigation = {
  Navigate(path: string) {
    const instance = mainWindow();
    if (instance?.Navigate) instance.Navigate(path);
    else store()?.Navigate?.(path);
  },
  NavigateBack() {
    mainWindow()?.NavigateBack?.();
  },
  /** Steam's in-app browser, which is the only one Game Mode has. */
  NavigateToExternalWeb(url: string) {
    mainWindow()?.Navigator?.ExternalWeb?.(url);
  },
  CloseSideMenus() {
    store()?.CloseSideMenus?.();
  },
  /** Open the Quick Access menu, on `tab` when given. */
  OpenQuickAccessMenu(tab?: number) {
    mainWindow()?.MenuStore?.OpenQuickAccessMenu?.(tab);
  },
};

/** The path the Game Mode window is showing, kept current. */
export function useCurrentPath(): string {
  const history = mainWindow()?.History;
  const [path, setPath] = useState<string>(history?.location?.pathname ?? "");
  useEffect(() => {
    if (!history?.listen) return undefined;
    return history.listen((location: Any) => setPath(location?.pathname ?? location?.location?.pathname ?? ""));
  }, [history]);
  return path;
}

// --- modals
// -------------------------------------------------------------------

export interface ShowModalResult {
  Close(): void;
  Update?(modal: ReactNode): void;
}

const showModalLookup = (() => {
  let done = false;
  let found: ((...args: unknown[]) => ShowModalResult) | null = null;
  return () => {
    if (!done) {
      const module = findModule("modal manager", ["Conflicting popout options; will ignore bNeverPopOut"]);
      found = findExport("showModal", module, (_v, src) => src.includes("bHideMainWindowForPopouts:!0"));
      done = true;
    }
    return found;
  };
})();

registerLookup(showModalLookup);

/**
 * Show `modal` over the Game Mode window. Throws if Steam's modal manager could
 * not be found, which the caller is better placed to explain than a blank
 * dialog would be.
 *
 * Steam's is async: it resolves to the handle. Callers get one at once, as
 * every caller here expects, and a Close asked for early is kept until the
 * real one lands.
 */
export function showModal(modal: ReactNode, _parent?: unknown, options: Any = {}): ShowModalResult {
  const show = showModalLookup();
  const window_ = mainWindow()?.BrowserWindow;
  if (!show || !window_) throw new Error("Steam's modal manager is not where it was");
  let real: ShowModalResult | null = null;
  let closed = false;
  let latest: ReactNode | undefined;
  void Promise.resolve(show(modal, window_, options)).then((handle) => {
    real = handle;
    if (closed) handle.Close();
    else if (latest !== undefined) handle.Update?.(latest);
  }).catch((error) => console.error("[deckyemu] could not show a dialog", error));
  return {
    Close() {
      closed = true;
      real?.Close();
    },
    Update(next: ReactNode) {
      latest = next;
      real?.Update?.(next);
    },
  };
}

// --- the Quick Access menu
// ---------------------------------------------------------

const sideMenuHook = (() => {
  let done = false;
  let found: ((menu: number) => boolean) | null = null;
  return () => {
    if (!done) {
      const module = findModule("side menu hooks", ["RemotePlayTogetherControls=1", "IsSideMenuVisible"]);
      // The hook, not the store class beside it, which has the same method.
      found = findExport("useQuickAccessVisible", module, (v, src) =>
        typeof v === "function" && !src.startsWith("class") && src.includes("IsSideMenuVisible("),
      );
      done = true;
    }
    return found;
  };
})();

registerLookup(sideMenuHook);

/** Whether the Quick Access menu is open. True if Steam's hook went missing. */
export function useQuickAccessVisible(): boolean {
  const hook = sideMenuHook();
  // The hook is chosen once and never changes, so the rule of hooks holds.
  return hook ? hook(SideMenu.QuickAccess) : true;
}
