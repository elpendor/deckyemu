/**
 * The script Steam's UI runs before any of its own code.
 *
 * The service registers this on the SharedJSContext page, so it runs at the
 * start of every document that page loads, and evaluates it once more in the
 * document already loading when the service attached. It does three things,
 * all by rewriting one of Steam's webpack module factories before Steam first
 * calls it:
 *
 *  - the Quick Access menu gets a tab, at the end of Steam's own tab list;
 *  - the Game Mode router gets a `/deckyemu` route, at the start of its list;
 *  - the game context menu gets our items, ahead of Properties.
 *
 * Each insertion is a permanent placeholder that renders whatever the main
 * bundle registers on `window.__deckyemu` later, because Steam builds these
 * lists once, before the bundle can load.
 *
 * Every anchor is a string literal, a localization key or a prop name --
 * nothing minification renames. Any doubt leaves Steam's factory exactly as it
 * was: a missing anchor, a capture that fails, or patched source that does not
 * compile. The worst a Steam update can do is take our tab away.
 */

import { TAB_KEY, type Bridge, type Store } from "./bridge";

declare const __DECKYEMU_VERSION__: string;

type Factory = (...args: unknown[]) => unknown;
type Chunk = [unknown, Record<string, Factory>, ...unknown[]];

interface Patch {
  name: string;
  /** Every one of these must appear in the module's source. */
  anchors: string[];
  /** The patched source, or a reason it could not be patched. */
  apply(src: string): string | { refused: string };
}

const CALL = "globalThis.__deckyemu";

/**

 * Insert `text` at `at`, after checking `at` is where exactly one `marker` is.

 */
function insertAtUnique(src: string, marker: string, text: string, after = false): string | { refused: string } {
  const at = src.indexOf(marker);
  if (at < 0) return { refused: `no ${marker}` };
  if (src.indexOf(marker, at + 1) >= 0) return { refused: `${marker} is not unique` };
  const where = after ? at + marker.length : at;
  return src.slice(0, where) + text + src.slice(where);
}

/**
 * The index of the bracket closing the one at `open`, skipping string and
 * template literals, or -1. Minified code has no comments, and a regex literal
 * containing a bracket is not something these few modules write.
 */
export function closingBracket(src: string, open: number): number {
  const pairs: Record<string, string> = { "[": "]", "(": ")", "{": "}" };
  const stack: string[] = [];
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === '"' || c === "'" || c === "`") {
      for (i++; i < src.length && src[i] !== c; i++) if (src[i] === "\\") i++;
      continue;
    }
    if (pairs[c]) stack.push(pairs[c]);
    else if (c === "]" || c === ")" || c === "}") {
      if (stack.pop() !== c) return -1;
      if (stack.length === 0) return i;
    }
  }
  return -1;
}

const PATCHES: Patch[] = [
  {
    name: "quick access tab",
    anchors: ['"QuickAccessMenuBrowserView"', "#QuickAccess_Tab_Help_Title"],
    apply(src) {
      const jsx = /tab:\(0,([\w$]+)\.jsx\)/.exec(src);
      const focusable = /\(0,[\w$]+\.jsxs?\)\(([\w$]+\.[\w$]+),\{id:"QuickAccess-Menu"/.exec(src);
      const react = /return ([\w$]+)\.useMemo\(\(\)=>\{let [\w$]+=\[/.exec(src);
      const dom = /([\w$]+)\.createPortal\(/.exec(src);
      if (!jsx || !focusable || !react || !dom) return { refused: "a capture is missing" };
      return insertAtUnique(
        src,
        "].filter(Boolean)",
        `,...(${CALL}?.qamTabs(${jsx[1]},${focusable[1]},${react[1]},${dom[1]})||[])`,
      );
    },
  },
  {
    name: "route",
    anchors: ["GamepadUI.Oobe.Root()", "GamepadUI.Login()"],
    apply(src) {
      const list = /\{children:\[\(0,([\w$]+)\.jsx\)\(([\w$]+\.[\w$]+),\{path:[\w$]+\.[\w$]+\.GamepadUI\.Oobe\.Root\(\),/.exec(src);
      if (!list) return { refused: "no route list" };
      const at = list.index + "{children:[".length;
      if (src.indexOf(list[0], list.index + 1) >= 0) return { refused: "route list is not unique" };
      return src.slice(0, at) + `...(${CALL}?.routes(${list[1]},${list[2]})||[]),` + src.slice(at);
    },
  },
  {
    name: "game menu",
    anchors: ['"#GameAction_GameProperties"', "this.GetTargetApps()"],
    apply(src) {
      const menu = /render\(\)\{const ([\w$]+)=this\.GetTargetApps\(\)[\s\S]*?return\(0,([\w$]+)\.jsxs\)\(([\w$]+)\.[\w$]+,\{label:[\s\S]*?children:\[/.exec(src);
      if (!menu || menu[0].length > 2000) return { refused: "no menu render" };
      // The whole children array is handed over, so our items can go where they
      // belong -- above Properties, Steam's last entry -- rather than first.
      const open = menu.index + menu[0].length - 1;
      const close = closingBracket(src, open);
      if (close < 0) return { refused: "the menu's children do not close" };
      const items = src.slice(open, close + 1);
      if (!items.includes('"#GameAction_GameProperties"')) return { refused: "Properties is not in the menu" };
      return (
        src.slice(0, open) +
        `(${CALL}?.gameMenu(${menu[1]},${menu[2]},${menu[3]},${items})??${items})` +
        src.slice(close + 1)
      );
    },
  },
];

function store<T>(): Store<T> {
  let value: T | undefined;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set(next) {
      value = next;
      listeners.forEach((listener) => {
        try {
          listener();
        } catch (error) {
          console.error("[deckyemu] listener failed", error);
        }
      });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

(() => {
  const w = window as unknown as { __deckyemu?: Bridge; webpackChunksteamui?: Chunk[] };
  // Registered on every page target, and possibly evaluated twice in this one.
  if (location.host !== "steamloopback.host" || w.__deckyemu) return;

  const status: Bridge["status"] = {
    version: __DECKYEMU_VERSION__,
    late: !!w.webpackChunksteamui,
    patches: Object.fromEntries(PATCHES.map((p) => [p.name, "waiting"])),
    rendered: false,
  };
  const note = (message: string) => console.log("[deckyemu] " + message);

  const qam = store<NonNullable<ReturnType<Bridge["qam"]["get"]>>>();
  const pages = store<NonNullable<ReturnType<Bridge["pages"]["get"]>>>();
  const menu = store<NonNullable<ReturnType<Bridge["menu"]["get"]>>>();

  // Built once, from the React that renders them: hooks have to come from
  // Steam's own copy or they throw.
  let parts: null | {
    TabIcon: () => unknown;
    TabTitle: () => unknown;
    TabPanel: () => unknown;
  } = null;

  function useStore<T>(React: any, which: Store<T>): T | undefined {
    const [, bump] = React.useState(0);
    React.useEffect(() => which.subscribe(() => bump((n: number) => n + 1)), [which]);
    return which.get();
  }

  function makeParts(jsx: any, React: any) {
    const fallback = (text: string) =>
      jsx.jsx("div", { style: { padding: "16px", lineHeight: "1.4" }, children: text });
    return {
      TabIcon() {
        const registered = useStore(React, qam);
        return registered?.icon ?? jsx.jsx("div", { style: { fontWeight: "bold" }, children: "DE" });
      },
      TabTitle() {
        const registered = useStore(React, qam);
        return registered?.title ?? jsx.jsx("div", { children: "DeckyEmu" });
      },
      TabPanel() {
        const registered = useStore(React, qam);
        if (registered) return registered.content;
        return fallback(
          w.__deckyemu?.status.failed
            ? `DeckyEmu could not start: ${w.__deckyemu.status.failed}. Open DeckyEmu from your library to repair or update it.`
            : "DeckyEmu is starting...",
        );
      },
    };
  }

  // No hooks here, so it needs no React: by the time anybody navigates to one
  // of our pages the bundle has registered it, and if it has not there is
  // nothing to wait for.
  let routeJsx: any = null;
  function PageHost() {
    const page = pages.get();
    if (page) return routeJsx.jsx(page, {});
    return routeJsx.jsx("div", {
      style: { padding: "48px" },
      children: w.__deckyemu?.status.failed
        ? `DeckyEmu could not start: ${w.__deckyemu.status.failed}`
        : "DeckyEmu is starting...",
    });
  }

  const bridge: Bridge = {
    status,
    steam: {},
    qam,
    pages,
    menu,
    qamTabs(jsx, Focusable, React, ReactDOM) {
      status.rendered = true;
      bridge.steam = { ...bridge.steam, jsx, Focusable, React, ReactDOM };
      // The bundle is built with these three as globals: one React, Steam's.
      Object.assign(window, { DECKYEMU_REACT: React, DECKYEMU_JSX: jsx, DECKYEMU_REACTDOM: ReactDOM });
      parts ??= makeParts(jsx, React);
      return [
        {
          key: TAB_KEY,
          tab: jsx.jsx(parts.TabIcon, {}),
          title: jsx.jsx(parts.TabTitle, {}),
          strTitle: "DeckyEmu",
          panel: jsx.jsx(parts.TabPanel, {}),
          vrPopupSize: "fit-content",
          vrLocation: "quick-access-menu",
        },
      ];
    },
    routes(jsx, Route) {
      bridge.steam.Route = Route;
      routeJsx = jsx;
      return [jsx.jsx(Route, { path: "/deckyemu", children: jsx.jsx(PageHost, {}) }, "deckyemu")];
    },
    gameMenu(apps, jsx, Menus, children) {
      const build = menu.get();
      if (!build || !Array.isArray(children)) return children;
      try {
        const ours = build(apps, jsx, Menus) ?? [];
        if (!ours.length) return children;
        // Steam's last entry is the Properties group; ours go just above it.
        return [...children.slice(0, -1), ...ours, ...children.slice(-1)];
      } catch (error) {
        console.error("[deckyemu] the game menu builder failed", error);
        return children;
      }
    },
  };
  w.__deckyemu = bridge;

  function patchChunk(chunk: Chunk) {
    const modules = chunk?.[1];
    if (!modules || typeof modules !== "object") return;
    for (const id of Object.keys(modules)) {
      let src: string | null = null;
      for (const patch of PATCHES) {
        if (status.patches[patch.name] !== "waiting") continue;
        src ??= Function.prototype.toString.call(modules[id]);
        if (!patch.anchors.every((anchor) => src!.includes(anchor))) continue;
        const out = patch.apply(src);
        if (typeof out !== "string") {
          status.patches[patch.name] = `refused: ${out.refused}`;
          note(`${patch.name}: ${out.refused}`);
          continue;
        }
        try {
          const factory = (0, eval)("(" + out + ")");
          if (typeof factory !== "function") throw new Error("not a function");
          modules[id] = factory;
          src = out;
          status.patches[patch.name] = `patched ${id}`;
          note(`${patch.name}: patched module ${id}`);
        } catch (error) {
          status.patches[patch.name] = `refused: ${String(error)}`;
          note(`${patch.name}: patched source rejected: ${String(error)}`);
        }
      }
    }
  }

  // Webpack replaces push once its runtime loads, keeping the old one to call
  // through to. Each wrapper captures the push current when it was read, so
  // that chain never loops back into itself.
  const chunks: Chunk[] = w.webpackChunksteamui || [];
  let push: (...items: Chunk[]) => number = chunks.push;
  Object.defineProperty(chunks, "push", {
    configurable: true,
    get: () => {
      const inner = push;
      return (...items: Chunk[]) => {
        items.forEach(patchChunk);
        return inner.apply(chunks, items);
      };
    },
    set: (fn) => {
      push = fn;
    },
  });
  // Arriving late: chunks already pushed may not have been run yet. If the
  // runtime has already copied a factory, swap its copy too; that only helps if
  // Steam has not required the module, which `rendered` will show.
  chunks.forEach(patchChunk);
  if (status.late && push !== Array.prototype.push) {
    let require: { m?: Record<string, Factory> } | undefined;
    push.call(chunks, [[Symbol("deckyemu")], {}, (r: typeof require) => (require = r)] as unknown as Chunk);
    for (const chunk of chunks) {
      for (const [id, factory] of Object.entries(chunk?.[1] ?? {})) {
        if (require?.m && Object.values(status.patches).includes(`patched ${id}`)) require.m[id] = factory;
      }
    }
  }
  w.webpackChunksteamui = chunks;
})();
