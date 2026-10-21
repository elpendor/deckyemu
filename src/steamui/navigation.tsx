/**
 * Steam's router, side menus and modal manager, through the objects it keeps
 * on `window.SteamUIStore` -- the Game Mode window's own instance, which holds
 * its navigator, history, menu store and modal manager.
 */

import { createElement, useEffect, useState, type ReactNode } from "react";

import { DialogButton, Focusable, pagedSettingsComponent, registerLookup, type SidebarPage } from "./components";
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
 */
export function showModal(modal: ReactNode, _parent?: unknown, options: Any = {}): ShowModalResult {
  const show = showModalLookup();
  const window_ = mainWindow()?.BrowserWindow;
  if (!show || !window_) throw new Error("Steam's modal manager is not where it was");
  return show(modal, window_, options);
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

// --- a page with a sidebar
// ------------------------------------------------------------

/**
 * Steam's paged settings layout -- the sidebar of Settings -- with each page
 * reached by its route, so the back button and a link to one page both work.
 */
export function SidebarNavigation({ pages, title }: { pages: SidebarPage[]; title?: ReactNode }) {
  const path = useCurrentPath();
  const items = pages.map((page, index) => ({
    identifier: page.route ?? page.identifier ?? String(index),
    title: page.title,
    icon: page.icon,
    content: page.content,
    hideTitle: page.hideTitle,
  }));
  const active =
    [...items].sort((a, b) => b.identifier.length - a.identifier.length).find((item) => path.startsWith(item.identifier))
      ?.identifier ?? items[0]?.identifier;
  // Replaced, not pushed: switching pages is not a step back has to undo, so B
  // leaves the whole screen as it does in Steam's own Settings.
  const go = (identifier: string) => {
    if (!identifier.startsWith("/")) return;
    const history = mainWindow()?.History;
    if (typeof history?.replace === "function") history.replace(identifier);
    else Navigation.Navigate(identifier);
  };
  const Paged = pagedSettingsComponent();
  if (Paged) {
    return createElement(Paged as never, {
      pages: items,
      page: active,
      onPageRequested: go,
      title,
      showTitle: !!title,
    } as never);
  }
  const current = items.find((item) => item.identifier === active);
  return (
    <div style={{ display: "flex", height: "100%" }}>
      <Focusable style={{ width: "240px", display: "flex", flexDirection: "column", gap: "4px", padding: "16px" }}>
        {items.map((item) => (
          <DialogButton key={item.identifier} onClick={() => go(item.identifier)}
            style={{ opacity: item.identifier === active ? 1 : 0.7 }}>
            {item.title}
          </DialogButton>
        ))}
      </Focusable>
      <div style={{ flex: 1, overflow: "auto", padding: "16px" }}>{current?.content}</div>
    </div>
  );
}
