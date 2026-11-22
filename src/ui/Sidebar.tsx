import { useEffect, useRef, useState, type ReactNode } from "react";

import { Focusable, GamepadButton, Navigation, playNavSound, type GamepadEvent } from "../steamui/base";
import { styled } from "./styles";

type Any = Record<string, any>;

export interface SidebarPage {
  title: ReactNode;
  content: ReactNode;
  icon?: ReactNode;
  route?: string;
  identifier?: string;
  hideTitle?: boolean;
}

/** The Game Mode window's router history, from Steam's own store. */
function history(): Any | undefined {
  const store = (window as unknown as { SteamUIStore?: Any }).SteamUIStore;
  return store?.WindowStore?.GamepadUIMainWindowInstance?.History;
}

function useCurrentPath(): string {
  const routes = history();
  const [path, setPath] = useState<string>(routes?.location?.pathname ?? "");
  useEffect(() => {
    if (!routes?.listen) return undefined;
    return routes.listen((location: Any) =>
      setPath(location?.pathname ?? location?.location?.pathname ?? ""),
    );
  }, [routes]);
  return path;
}

/**
 * A page list on the left and the chosen page on the right, like Steam's
 * Settings. Each page is reached by its route, so B and a link to one page
 * both work; switching pages replaces the route rather than stacking it, so B
 * leaves the whole screen as it does in Steam's own Settings.
 */
export function SidebarNavigation({ pages, title }: { pages: SidebarPage[]; title?: ReactNode }) {
  const path = useCurrentPath();
  const items = pages.map((page, index) => ({
    ...page,
    id: page.route ?? page.identifier ?? String(index),
  }));
  const active =
    [...items].sort((a, b) => b.id.length - a.id.length).find((item) => path.startsWith(item.id))
      ?.id ?? items[0]?.id;
  const go = (id: string) => {
    if (!id.startsWith("/")) return;
    const routes = history();
    if (typeof routes?.replace === "function") routes.replace(id);
    else Navigation.Navigate(id);
  };
  const current = items.find((item) => item.id === active);
  // As in Steam's Settings: landing on a page shows it with the page sound,
  // and choosing one also moves into it.
  const body = useRef<{ TakeFocus?: () => void } | null>(null);
  const show = (id: string) => {
    playNavSound("PagedNavigation");
    go(id);
  };
  const open = (id: string) => {
    show(id);
    body.current?.TakeFocus?.();
  };

  // Text after the last control has nothing to focus, so the D-pad cannot
  // bring it into view. When a press leaves focus where it was, the page
  // scrolls a step instead, as Steam's own pages do.
  const scroller = useRef<HTMLDivElement | null>(null);
  const onButtonDown = (event: GamepadEvent) => {
    const button = event.detail?.button;
    const down = button === (GamepadButton.DIR_DOWN ?? 10);
    const up = button === (GamepadButton.DIR_UP ?? 9);
    const box = scroller.current;
    if ((!down && !up) || !box) return;
    const doc = box.ownerDocument;
    const before = doc.activeElement;
    window.setTimeout(() => {
      if (doc.activeElement === before) box.scrollBy({ top: down ? 160 : -160, behavior: "smooth" });
    }, 0);
  };

  return (
    <Focusable className="dek-pages" flow-children="row">
      <div className="dek-page-list" ref={styled}>
        {title && <div className="dek-section-title" style={{ padding: "16px 24px 0" }}>{title}</div>}
        <Focusable className="dek-page-items" role="tablist" aria-orientation="vertical"
          flow-children="column">
          {items.map((item) => (
            <Focusable
              key={item.id}
              role="tab"
              aria-selected={item.id === active}
              autoFocus={item.id === active}
              noFocusRing
              preferredFocus={item.id === active}
              className={item.id === active ? "dek-page-item dek-active" : "dek-page-item"}
              onActivate={() => open(item.id)}
              onClick={() => open(item.id)}
              onFocus={() => show(item.id)}
            >
              <div>
                {item.icon && <div className="dek-page-icon">{item.icon}</div>}
                <div className="dek-page-title">{item.title}</div>
              </div>
            </Focusable>
          ))}
        </Focusable>
      </div>
      <div className="dek-page-content" ref={scroller}>
        {/* A column of its own: left unsaid, it takes the row the page uses
            to put the sidebar beside it, and rows need left and right. */}
        <Focusable className="DialogContent _DialogLayout dek-page-body" role="tabpanel"
          flow-children="column" onButtonDown={onButtonDown} navRef={body}>
          <div className="DialogContent_InnerWidth">
            {current && !current.hideTitle && (
              <div className="DialogHeader" role="heading" aria-level={2}>{current.title}</div>
            )}
            {current?.content}
          </div>
        </Focusable>
      </div>
    </Focusable>
  );
}
