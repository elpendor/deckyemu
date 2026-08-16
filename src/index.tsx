import {
  ButtonItem,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
  quickAccessMenuClasses,
  showModal,
} from "@decky/ui";
import { definePlugin, routerHook, useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaCog, FaGamepad } from "react-icons/fa";

import {
  getStatus,
  listAdded,
  shortcutHealth,
  type AddedGame,
  type RetroArchStatus,
} from "./backend";
import { AddGamePanel } from "./AddGamePanel";
import { AddedGamesPanel } from "./AddedGamesPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import { OrphanModal } from "./OrphanModal";
import { shortcutNudge, type ShortcutCounts } from "./shortcutNudge";
import { TransferStatusPanel } from "./TransferStatusPanel";
import { ManagePage, MANAGE_ROUTE, openManagePage } from "./ManagePage";
import { callWithRetry } from "./timeout";

const EMPTY_STATUS: RetroArchStatus = {
  found: false,
  kind: "",
  exe: "",
  config_dir: "",
  core_count: 0,
  core_dirs: [],
  emulator_count: 0,
  default_rom_dir: "",
  waiting_rom_dir: "",
  home_dir: "",
};

const INSTALL_LABELS: Record<string, string> = {
  flatpak: "RetroArch (Flatpak)",
  native: "RetroArch",
  appimage: "RetroArch (AppImage)",
};

/** One line describing what is available to run games with. */
function statusSummary(status: RetroArchStatus): string {
  const parts: string[] = [];
  if (status.found) {
    parts.push(
      `${INSTALL_LABELS[status.kind] ?? "RetroArch"} · ${status.core_count} core${
        status.core_count === 1 ? "" : "s"
      }`,
    );
  }
  if (status.emulator_count > 0) {
    parts.push(
      `${status.emulator_count} emulator${status.emulator_count === 1 ? "" : "s"}`,
    );
  }
  return parts.join(" · ") || "Nothing set up yet";
}

function Content() {
  const [status, setStatus] = useState<RetroArchStatus>(EMPTY_STATUS);
  const [games, setGames] = useState<AddedGame[]>([]);
  const [loading, setLoading] = useState(true);
  // A backend reload destroys calls in flight without replying, so "loading"
  // needs a way out other than the promise settling.
  const [unreachable, setUnreachable] = useState(false);
  // Shown while retrying, so a wait after a reload does not look like a freeze.
  const [waitNote, setWaitNote] = useState("");
  const [health, setHealth] = useState<ShortcutCounts | null>(null);

  // Its own endpoint rather than the full audit, which walks the ROM library
  // and every previous install looking for things this does not need. Failure
  // is silent: a count nobody asked for must not put an error in front of
  // somebody trying to add a game.
  const loadHealth = useCallback(async () => {
    try {
      setHealth(await shortcutHealth());
    } catch (error) {
      console.error("[deckyemu] could not check shortcut health", error);
    }
  }, []);

  const loadGames = useCallback(() => {
    // Retried for the same reason as the status call: a reload drops whatever was
    // in flight, and this list would otherwise silently stay empty.
    callWithRetry(listAdded)
      .then(setGames)
      .catch((error) => console.error("[deckyemu] could not list added games", error));
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(
        await callWithRetry(getStatus, {
          onAttempt: (attempt, attempts) =>
            setWaitNote(`Waiting for the plugin backend (${attempt}/${attempts})`),
        }),
      );
      setUnreachable(false);
      setWaitNote("");
    } catch (error) {
      console.error("[deckyemu] could not get status", error);
      setUnreachable(true);
    } finally {
      setLoading(false);
    }
  }, []);

  // Re-read on every open: installing RetroArch, adding a core or registering an
  // emulator all happen on the manage page, so the panel would otherwise still
  // be describing the state from before.
  const visible = useQuickAccessVisible();

  // Depending on `visible` makes this run on mount and again on every re-open,
  // which also recovers from a reload that happened while the panel was closed.
  useEffect(() => {
    void loadStatus();
    loadGames();
    void loadHealth();
  }, [visible, loadStatus, loadGames, loadHealth]);

  const nudge = shortcutNudge(health);

  const openManage = useCallback(() => openManagePage(), []);

  const canAddGames = (status.found && status.core_count > 0) || status.emulator_count > 0;

  if (loading) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Looking for emulators..." description={waitNote} />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (unreachable) {
    return (
      <PanelSection title="Plugin backend not responding">
        <PanelSectionRow>
          <Field description="No reply from DeckyEmu's backend after several tries. It restarts whenever its files change, and calls in flight at that moment are dropped, so this is expected right after an update." />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              setLoading(true);
              setWaitNote("");
              void loadStatus();
              loadGames();
            }}
          >
            Try again
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  /*
   * The panel is deliberately just what gets used while playing: add a game, see
   * what has been added, and a way through to everything configured once. Setup
   * lives on its own page, because five stacked sections meant scrolling past
   * four of them to reach Settings.
   */
  return (
    <>
      {/* First, above everything. A transfer is the only thing here that is
          happening *now* and that you may want to stop -- the status line and the
          add flow are still there whenever you scroll. Below the add panel it sat
          most of a screen down, which is no use for something you opened the
          panel to check on. Renders nothing at all when no transfer is running,
          so it costs the usual case no space. */}
      <TransferStatusPanel />

      <PanelSection>
        <PanelSectionRow>
          <Field
            label={canAddGames ? "Ready to use" : "Setup needed"}
            description={statusSummary(status)}
          />
        </PanelSectionRow>

        {/* Only when there is something to say. This exists because the problem
            it reports cannot be found by looking: a shortcut whose launcher and
            registry entry were both deleted sits in the library as a game that
            does nothing, and the screen that fixes it is one nobody opens
            without already suspecting trouble. */}
        {nudge && (
          <>
            <PanelSectionRow>
              <Field label={nudge.label} description={nudge.description} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() =>
                  showModal(
                    <OrphanModal
                      onChanged={() => {
                        loadGames();
                        void loadHealth();
                      }}
                    />,
                  )
                }
              >
                Check the library
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}

        {/* Kept as a full-width button only while there is nothing to play with.
            Routine access to the settings page is the cog in the header now, and
            a second control saying the same thing below it is just a row in the
            way of adding a game.

            It stays for the not-ready state because there it is not "settings",
            it is the only thing to do next -- and a first-time user who has just
            found the plugin should not have to notice a 30px icon to get
            started. */}
        {!canAddGames && (
          <>
            <PanelSectionRow>
              <Field description="Set up RetroArch and a core, or add a standalone emulator, to start adding games." />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={openManage}>
                Set up emulators
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      {canAddGames && <AddGamePanel status={status} onGameAdded={loadGames} />}
      <AddedGamesPanel games={games} onChanged={loadGames} />
    </>
  );
}

/*
 * Module scope, not built inside `definePlugin`. `routerHook` keeps the
 * component it was handed, so a fresh function on every call would be a
 * different component type each time -- React would unmount and remount the
 * whole page rather than update it.
 */
const GuardedManagePage = () => (
  <ErrorBoundary where="The DeckyEmu settings page">
    <ManagePage />
  </ErrorBoundary>
);

/**
 * The plugin's row in the Quick Access header: its name, and a way to the
 * settings page.
 *
 * quickAccessMenuClasses.Title, not staticClasses.Title. The generic title class
 * carries its own padding and line height, which is why the name sat off-centre
 * against decky's back arrow no matter what was done to it from the outside. The
 * Quick Access header has a class of its own that matches the row.
 *
 * The button's numbers are all doing something. `minWidth: 0` because
 * DialogButton is sized for a dialog footer and defaults far wider than a header
 * row has to spare; 28x40 is what a Quick Access header button measures across
 * the plugins that put one there, and the narrower 30px this used before was
 * small enough to be awkward with a thumbstick. `marginRight: auto` on the name
 * is what pushes the button to the right edge rather than leaving it next to
 * the title.
 *
 * The glyph is centred by making the button a flex container rather than by
 * nudging the icon up with a negative margin. The nudge was tuned against one
 * padding value and quietly went wrong whenever the button's size changed --
 * which is how it ended up sitting low here.
 */
function TitleView() {
  return (
    <div
      className={quickAccessMenuClasses.Title}
      style={{
        display: "flex",
        alignItems: "center",
        padding: 0,
        flex: "auto",
        boxShadow: "none",
      }}
    >
      <div style={{ marginRight: "auto" }}>DeckyEmu</div>
      <DialogButton
        style={{
          marginLeft: "5px",
          height: "28px",
          width: "40px",
          minWidth: 0,
          padding: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
        onClick={() => openManagePage()}
      >
        <FaCog style={{ display: "block" }} />
      </DialogButton>
    </div>
  );
}

export default definePlugin(() => {
  // Not exact: each tab has its own URL under this one (see `tabRoute`), and an
  // exact route leaves those unresolved, so tapping a tab navigates to nothing.
  routerHook.addRoute(MANAGE_ROUTE, GuardedManagePage);

  return {
    name: "DeckyEmu",
    titleView: <TitleView />,
    /*
     * Wrapped, because this renders inside decky's panel and a throw here
     * unmounts everything up to whatever boundary decky has -- taking the panel
     * with it, not just this plugin's section of it.
     */
    content: (
      <ErrorBoundary where="The DeckyEmu panel">
        <Content />
      </ErrorBoundary>
    ),
    icon: <FaGamepad />,
    onDismount() {
      routerHook.removeRoute(MANAGE_ROUTE);
    },
  };
});
