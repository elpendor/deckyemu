import {
  ButtonItem,
  Field,
  Navigation,
  PanelSection,
  PanelSectionRow,
  SidebarNavigation,
} from "@decky/ui";
import { useCallback, useEffect, useState } from "react";

import { getStatus, refreshRetroArch, type RetroArchStatus } from "./backend";
import { ArtworkPanel } from "./ArtworkPanel";
import { CollectionsPanel } from "./CollectionsPanel";
import { DevPanel } from "./DevPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import { EmulatorsPanel } from "./EmulatorsPanel";
import { LibraryPanel } from "./LibraryPanel";
import { RetroArchPanel } from "./RetroArchPanel";
import { UpdatePanel } from "./UpdatePanel";
import { callWithRetry } from "./timeout";
import { IS_DEV_BUILD } from "./version";

export const MANAGE_ROUTE = "/deckyemu/manage";

/**
 * A route per tab, because the route *is* the selection.
 *
 * SidebarNavigation has no "selected page" prop, whatever `@decky/ui`'s types
 * suggest. Steam's own component picks the tab by matching the current URL
 * against each page's `route` and falls back to the first page, then navigates
 * with `history.replace` when a tab is tapped. Pages carrying no route all
 * compare equal to "no route", which is why supplying `page`/`onPageRequested`
 * made every tab a no-op.
 *
 * Selection living in the URL is also what fixes the tab being lost: opening
 * SteamGridDB pushes the browser route, and pressing B pops back to this exact
 * URL rather than to a bare page that starts over at the first tab.
 *
 * `MANAGE_ROUTE` must be registered non-exact for these to resolve (see
 * `index.tsx`).
 */
const tabRoute = (tab: string) => `${MANAGE_ROUTE}/${tab}`;

/** Navigate to the setup page. */
export function openManagePage() {
  Navigation.Navigate(MANAGE_ROUTE);
  Navigation.CloseSideMenus();
}

const PAGE: React.CSSProperties = {
  // Steam's own pages inset their content; matching that keeps the page from
  // sitting flush against the screen edge.
  marginTop: "40px",
  height: "calc(100% - 40px)",
};

/**
 * The setup and maintenance side of the plugin, on its own screen.
 *
 * These sections used to live in the Quick Access panel alongside adding games,
 * which meant scrolling past four of them to reach Settings. The panel is now
 * only what you use while playing; everything configured once lives here, where
 * there is room for it.
 */
export function ManagePage() {
  const [status, setStatus] = useState<RetroArchStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await callWithRetry(getStatus));
      setUnreachable(false);
    } catch (error) {
      // Same reload hazard as the panel: never wait forever on a lost reply.
      console.error("[deckyemu] could not load status", error);
      setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rescan = useCallback(() => {
    refreshRetroArch()
      .then(setStatus)
      .catch((error) => console.error("[deckyemu] rescan failed", error));
  }, []);

  // Bumped after a development reset, and read by the core list. Every panel
  // here holds a picture of what is installed, taken when it mounted; a reset
  // makes all of them wrong at once, and none of them would ever find out.
  const [resets, setResets] = useState(0);
  const afterReset = useCallback(() => {
    rescan();
    setResets((count) => count + 1);
  }, [rescan]);

  if (!status) {
    return (
      <div style={PAGE}>
        <PanelSection title={unreachable ? "Backend not responding" : "Loading..."}>
          {unreachable && (
            <>
              <PanelSectionRow>
                <Field description="No reply from DeckyEmu's backend. It may have restarted mid-request." />
              </PanelSectionRow>
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => void load()}>
                  Try again
                </ButtonItem>
              </PanelSectionRow>
            </>
          )}
        </PanelSection>
      </div>
    );
  }

  const pages = [
    // Ordered by how most people get here: RetroArch and its cores are the main
    // path and the only tab that matters before anything can be added, so it
    // leads. Custom emulators are the alternative to it, artwork and collections
    // shape what the library looks like afterwards, and the last two are
    // maintenance you visit rarely.
    {
      title: "RetroArch",
      route: tabRoute("retroarch"),
      content: <RetroArchPanel status={status} onRefresh={rescan} reloadKey={resets} />,
    },
    {
      title: "Emulators",
      route: tabRoute("emulators"),
      content: <EmulatorsPanel onChanged={rescan} />,
    },
    {
      title: "Artwork",
      route: tabRoute("artwork"),
      content: <ArtworkPanel />,
    },
    {
      title: "Collections",
      route: tabRoute("collections"),
      content: <CollectionsPanel />,
    },
    {
      title: "Library",
      route: tabRoute("library"),
      content: <LibraryPanel onRefresh={rescan} />,
    },
    {
      title: "Updates",
      route: tabRoute("updates"),
      content: <UpdatePanel />,
    },
    // Development builds only, and absent rather than hidden: IS_DEV_BUILD is a
    // build-time constant, so a release bundle contains no Reset tab and no
    // DevPanel to reach. See version.ts.
    ...(IS_DEV_BUILD
      ? [
          {
            title: "Reset",
            route: tabRoute("reset"),
            content: <DevPanel onChanged={afterReset} />,
          },
        ]
      : []),
  ];

  /*
   * A boundary per tab rather than one around the page. Both keep a throw out
   * of Steam's tree, but per tab the sidebar survives it: the tab that broke
   * says so and every other one still works, where a single outer boundary
   * would replace the whole screen -- including the way to the Updates tab,
   * which is how a bad build gets replaced.
   */
  const guarded = pages.map((page) => ({
    ...page,
    content: <ErrorBoundary where={`The ${page.title} tab`}>{page.content}</ErrorBoundary>,
  }));

  return (
    <div style={PAGE}>
      <SidebarNavigation pages={guarded} />
    </div>
  );
}
