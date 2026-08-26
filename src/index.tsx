import {
  ButtonItem,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
  quickAccessMenuClasses,
} from "@decky/ui";
import {
  addEventListener,
  definePlugin,
  removeEventListener,
  routerHook,
  useQuickAccessVisible,
} from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaCog, FaGamepad } from "react-icons/fa";

import {
  checkForUpdate,
  getSettings,
  getStatus,
  listAdded,
  setSettings,
  shortcutHealth,
  type AddedGame,
  type RetroArchStatus,
  type UpdateCheck,
} from "./backend";
import { deviceGate } from "./deviceGate";
import { updateBadge } from "./updateBadge";
import { noteCheck, noteUpdate, setUpdateDotEnabled } from "./updateSignal";
import { UpdateDot } from "./UpdateDot";
import { AddGamePanel } from "./AddGamePanel";
import { editGameMenuItem } from "./EditGameMenuItem";
import { refreshAddedGames, rememberAddedGames } from "./addedGames";
import { repairGameLayouts } from "./repairLayouts";
import { AddedGamesPanel } from "./AddedGamesPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import { closeModalsOnPanelOpen } from "./modalStack";
import { OrphanModal } from "./OrphanModal";
import { shortcutNudge, type ShortcutCounts } from "./shortcutNudge";
import { TransferStatusPanel } from "./TransferStatusPanel";
import { ManagePage, MANAGE_ROUTE, openManagePage } from "./ManagePage";
import { patchGameContextMenu } from "./steam/contextMenu";
import { watchLaunches } from "./launchGate";
import { OVER_THE_NETWORK, callWithRetry } from "./timeout";
import { openModal } from "./modalStack";

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
  const [update, setUpdate] = useState<UpdateCheck | null>(null);

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

  /*
   * Unforced, so the backend's hourly cache decides whether this costs anything:
   * opening the panel twenty times in an evening asks GitHub once, and the cache
   * now survives a backend restart so a reload does not reset that.
   *
   * Nothing is retried and no failure reaches the screen. Nobody opened the
   * Quick Access panel to check for updates -- it is answered here because this
   * is the screen people actually open, and until now nothing asked at all
   * unless you went to Manage and pressed a button. A check that fails should
   * therefore leave no trace here; the Updates tab explains it to whoever goes
   * looking.
   */
  const loadUpdate = useCallback(async () => {
    try {
      const found = await checkForUpdate(false);
      setUpdate(found);
      // Shared with the icon, which has no other way to hear about this one.
      // This is also the check that decides what a user actually experiences:
      // the backend's timer is a six-hour floor for a device whose panel is
      // never opened, and it counts awake time rather than clock time, so on a
      // Deck that suspends it can be days. Opening the panel checks -- bounded
      // by the backend's own hour-long cache, so this is cheap to call on every
      // open. `noteCheck` because a check that failed must leave the dot
      // exactly as it found it.
      noteCheck(found);
    } catch (error) {
      console.error("[deckyemu] could not check for updates", error);
    }
  }, []);

  const loadGames = useCallback(() => {
    // Retried for the same reason as the status call: a reload drops whatever was
    // in flight, and this list would otherwise silently stay empty.
    callWithRetry(listAdded)
      .then((list) => {
        setGames(list);
        // The context menu reads this list while rendering and cannot await, so
        // it is fed from here -- the panel already re-reads on every open and
        // after every change, which is exactly when the menu would be wrong.
        rememberAddedGames(list);
      })
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
    void loadUpdate();
  }, [visible, loadStatus, loadGames, loadHealth, loadUpdate]);

  /*
   * Nothing of ours may still be on the modal stack while this panel is up.
   *
   * Steam re-reveals each modal as the one above it dismisses, so one left
   * standing arrives on top of the panel rather than behind it -- and takes the
   * active overlay with it. Leaving the added-games list open, opening Quick
   * Access, and picking a ROM was enough: the file browser dismissed, the list
   * came back over the panel, and the panel could not be opened again.
   *
   * `closeOpenModals` was written for exactly this and had one caller, in the
   * transfer dialog, covering the one route that had been found. The rule is not
   * about that route -- it is that opening Quick Access means the user has moved
   * on from whatever was in front of them. One place, so no call site can be the
   * one that forgets.
   *
   * **Only when becoming visible, never when hiding.** Opening one of our modals
   * is itself what hides this panel, so running this on the way down would
   * dismiss the modal the user just asked for, about a frame after it appeared.
   */
  useEffect(() => closeModalsOnPanelOpen(visible), [visible]);

  const nudge = shortcutNudge(health);
  const badge = updateBadge(update);

  /*
   * Written once because it renders in two places, and the second one is not
   * decoration: `check_for_update` is on the backend's ungated list precisely so
   * that a device wrongly refused by the gate can still update its way out. A
   * block screen with no way to reach a newer build would make that escape
   * hatch theoretical.
   */
  const updateRow = badge && (
    <>
      <PanelSectionRow>
        <Field label={badge.label} description={badge.description} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => openManagePage("updates")}>
          See what's new
        </ButtonItem>
      </PanelSectionRow>
    </>
  );

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

  // Before anything else that renders a working plugin. Nothing here has been
  // tested off a Steam Deck, so on other hardware the panel is the explanation
  // and the way past it, and nothing else -- showing the add flow first and the
  // warning underneath would be an invitation with a footnote.
  const gate = deviceGate(status.device);
  if (gate.blocked) {
    return (
      <PanelSection title={gate.title}>
        <PanelSectionRow>
          <Field description={gate.body} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field description={gate.caveat} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              // Awaited before re-reading, or the status call races the write
              // and the panel re-renders still blocked -- which reads as the
              // button not working and gets pressed again.
              setSettings({ allow_unsupported_device: true })
                .then(() => loadStatus())
                .catch((error) =>
                  console.error("[deckyemu] could not set the device override", error),
                );
            }}
          >
            Use it anyway
          </ButtonItem>
        </PanelSectionRow>
        {updateRow}
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
                  openModal(
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

        {/* Last on the section, because it is the least urgent thing on it: a
            newer version is worth knowing about and is never the reason the
            panel was opened. Above the add flow it would put a version number
            between somebody and the button they came for. */}
        {updateRow}
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

  // The "DeckyEmu" submenu behind the cog on a game's page -- Edit and Remove.
  // The cache is filled first because the item decides whether to appear by
  // reading it, and a menu opened before the first read would show nothing for
  // a game that is ours.
  void refreshAddedGames();
  const unpatchContextMenu = patchGameContextMenu(editGameMenuItem);

  // Steam will not warn before launching one of our games over a running one
  // -- its check is gated on an app_type our shortcuts do not carry. The
  // launcher script is what actually stops it; this is the panel collecting
  // that decision and asking. See launchGate.ts.
  const stopWatchingLaunches = watchLaunches();

  /*
   * Games added before their emulator asked for a layout do not have it, and
   * for Vita3K that means a gyro the Deck never powers on. Repaired here rather
   * than asked of the user, because the symptom is invisible: motion simply
   * does nothing, in a game that never mentions motion, for a reason that lives
   * in a Steam menu three levels away. See repairLayouts.ts -- it only replaces
   * layouts Steam guessed or this plugin pinned, never one somebody chose.
   */
  void repairGameLayouts().catch((error: unknown) =>
    console.error("[deckyemu] could not repair game layouts", error),
  );

  /*
   * The backend checks on a timer and says so here. Registered at plugin scope
   * rather than inside the panel because that is the whole point of it: the icon
   * has to carry the dot before anybody opens the panel, and `Content` does not
   * exist until they do.
   */
  const onUpdateAvailable = (available: boolean, version: string) =>
    noteUpdate(Boolean(available), version || "");
  addEventListener<[boolean, string]>("update_available", onUpdateAvailable);

  /*
   * And ask once, rather than only listening.
   *
   * The backend's first check used to be 30 seconds after start, which hid a
   * race this has now: the check is immediate, the two halves of the plugin
   * load at roughly the same moment, and an event emitted before this listener
   * exists reaches nobody. The dot would then stay dark until somebody opened
   * the panel -- which is the one thing it is there to save them from.
   *
   * Cheap: the backend has just checked, and this is unforced, so it is
   * answered from the same cache rather than another request.
   */
  void callWithRetry(() => checkForUpdate(false), OVER_THE_NETWORK)
    .then(noteCheck)
    .catch((error) => console.error("[deckyemu] could not check for updates", error));

  /*
   * Whether the dot is wanted, read once at load.
   *
   * Here rather than in whichever panel renders first, because the icon is one
   * of the things that exists before any panel does -- and somebody who turned
   * the dot off should not see it once more on every boot while something
   * catches up. Failure leaves it on, which is the stored default.
   */
  void callWithRetry(getSettings)
    .then((settings) => setUpdateDotEnabled(settings.show_update_dot !== false))
    .catch((error) =>
      console.error("[deckyemu] could not read the update dot setting", error),
    );

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
    /*
     * Two children rather than one, which is how decky puts its own update dot
     * on its own plug icon. `UpdateDot` renders nothing at all until there is
     * something to say, so the ordinary case is the glyph exactly as before.
     */
    icon: (
      <>
        <FaGamepad />
        <UpdateDot />
      </>
    ),
    onDismount() {
      routerHook.removeRoute(MANAGE_ROUTE);
      removeEventListener("update_available", onUpdateAvailable);
      // Steam keeps the patched component, so leaving this would put a dead
      // item in every game menu until the client restarts.
      unpatchContextMenu();
      // Same reason: Steam keeps the registration, and a plugin update would
      // otherwise leave the old copy toasting alongside the new one.
      stopWatchingLaunches();
    },
  };
});
