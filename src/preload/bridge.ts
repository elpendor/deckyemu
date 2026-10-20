/**
 * What the preload leaves on `window.__deckyemu` for the main bundle.
 *
 * Types, and the one shared constant. The preload and the bundle are built
 * separately and meet at runtime, so this file is the whole of the contract
 * between them.
 */

/** The key our Quick Access tab is listed under. Steam's own run 0-8. */
export const TAB_KEY = 4242;

export interface Store<T> {
  get(): T | undefined;
  set(value: T): void;
  subscribe(listener: () => void): () => void;
}

/** Steam's jsx runtime: `jsx(type, props, key)` and `jsxs`, and `Fragment`. */
export interface JsxRuntime {
  jsx(type: unknown, props: Record<string, unknown>, key?: string): unknown;
  jsxs(type: unknown, props: Record<string, unknown>, key?: string): unknown;
  Fragment: unknown;
}

/** Steam's context menu components, as the game menu's module imports them. */
export type MenuModule = Record<string, unknown>;

export interface Bridge {
  status: {
    version: string;
    /** The preload arrived after Steam's chunks had started loading. */
    late: boolean;
    /** Per patch: "waiting", "patched <module>", or "refused: <why>". */
    patches: Record<string, string>;
    /** Steam has called our tab placeholder: the Quick Access patch is live. */
    rendered: boolean;
    /** Set by the bundle when it could not start; the tab shows it. */
    failed?: string;
    /** Set by the bundle once it has registered everything. */
    started?: string;
  };
  /** Steam's own React pieces, captured from the Quick Access module. */
  steam: {
    jsx?: JsxRuntime;
    Focusable?: unknown;
    React?: unknown;
    ReactDOM?: unknown;
    Route?: unknown;
  };
  qam: Store<{ icon: unknown; title: unknown; content: unknown }>;
  pages: Store<() => unknown>;
  menu: Store<(apps: { appid: number }[], jsx: JsxRuntime, menus: MenuModule) => unknown[]>;
  qamTabs(jsx: JsxRuntime, Focusable: unknown, React: unknown, ReactDOM: unknown): unknown[];
  routes(jsx: JsxRuntime, Route: unknown): unknown[];
  gameMenu(apps: { appid: number }[], jsx: JsxRuntime, menus: MenuModule, children: unknown[]): unknown[];
  /** Set by the service, before it evaluates the bundle. */
  service?: { version: string };
  /** Set by the bundle: undoes what it registered, before a newer one loads. */
  unload?: () => void;
}
