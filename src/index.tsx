import {
  ButtonItem,
  DialogButton,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  quickAccessMenuClasses,
} from "./steamui";
import { addEventListener, removeEventListener, useQuickAccessVisible } from "./host";
import type { ReactElement, ReactNode } from "react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
import { blockScreen } from "./blockGate";
import { deviceGate } from "./deviceGate";
import { updateBadge } from "./updateBadge";
import { noteCheck, noteUpdate, setUpdateDotEnabled } from "./updateSignal";
import { UpdateDot } from "./UpdateDot";
import { UpdateModal } from "./UpdateModal";
import { AddGamePanel } from "./AddGamePanel";
import { editGameMenuItem } from "./EditGameMenuItem";
import { refreshAddedGames, rememberAddedGames } from "./addedGames";
import { repairGameIcons } from "./repairIcons";
import { repairGameLayouts } from "./repairLayouts";
import { AddedGamesPanel } from "./AddedGamesPanel";
import { ErrorBoundary } from "./ErrorBoundary";
import { closeModalsWhenPanelSettles } from "./modalStack";
import { HEADER_BUTTON, SwitchButton, TakeOverRows, onSwitched } from "./SwitchPanel";
import { OrphanModal } from "./OrphanModal";
import { shortcutNudge, type ShortcutCounts } from "./shortcutNudge";
import { CloudStatusPanel } from "./CloudStatusPanel";
import { TransferStatusPanel } from "./TransferStatusPanel";
import { ManagePage, openManagePage } from "./ManagePage";
import { patchGameContextMenu } from "./steam/contextMenu";
import { watchLaunches } from "./launchGate";
import { watchPlaying } from "./playWatch";
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
  port_count: 0,
  default_rom_dir: "",
  waiting_rom_dir: "",
  home_dir: "",
};

/** `3 cores` and `1 core`, for a line made of counted things. */
function counted(many: number, noun: string): string {
  return `${many} ${noun}${many === 1 ? "" : "s"}`;
}

/** One line describing what is available to run games with.
 *
 * How RetroArch was installed is left out. It decides nothing the reader can
 * act on here, it is on the RetroArch tab for anyone who wants it, and it made
 * the one line that has to hold four counts a line about packaging.
 */
function statusSummary(status: RetroArchStatus): string {
  const parts: string[] = [];
  if (status.found) {
    parts.push(`RetroArch · ${counted(status.core_count, "core")}`);
  }
  // Ports are registered exactly as emulators are, so the count of emulators
  // includes them and has to have them taken back out -- otherwise a Deck with
  // one of each reads as two emulators.
  const emulators = status.emulator_count - status.port_count;
  if (emulators > 0) parts.push(counted(emulators, "emulator"));
  if (status.port_count > 0) parts.push(counted(status.port_count, "port"));
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
  // Not loading the list must not read as having no games.
  const [gamesFailed, setGamesFailed] = useState(false);

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
        setGamesFailed(false);
        // The context menu reads this list while rendering and cannot await, so
        // it is fed from here -- the panel already re-reads on every open and
        // after every change, which is exactly when the menu would be wrong.
        rememberAddedGames(list);
      })
      .catch((error) => {
        console.error("[deckyemu] could not list added games", error);
        setGamesFailed(true);
      });
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

  // The switch lives in the header (SwitchButton); the panel shows the result.
  useEffect(() => onSwitched(() => void loadStatus()), [loadStatus]);

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
  //
  // **And only once it stays visible.** A dropdown closing inside one of our
  // modals flashes the panel visible for a millisecond; see PANEL_SETTLE_MS.
  useEffect(() => closeModalsWhenPanelSettles(visible), [visible]);

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
    <PanelSectionRow>
      {/* One row, not a Field and a button in two. Steam rules between rows, so
          the version and the button that acts on it were separated by a line
          that reads as "these are two different things" -- and the button under
          it then looks like it belongs to whatever comes next. `ButtonItem`
          carries the label and description itself, which is what the rest of
          the plugin already does. */}
      <ButtonItem
        layout="below"
        label={badge.label}
        description={badge.description}
        onClick={() => openModal(<UpdateModal />)}
      >
        See what's new
      </ButtonItem>
    </PanelSectionRow>
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
      <PanelSection title="DeckyEmu is not responding">
        <PanelSectionRow>
          <Field description="No reply from DeckyEmu's backend after several tries. It restarts when it updates, and calls in flight at that moment are dropped, so this is expected right after an update." />
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

  // First of all: a backend that stays off answers nothing else. Update stays
  // on offer, since a newer build is the way past newer data.
  const block = blockScreen(status.blocked);
  if (block) {
    return (
      <PanelSection title={block.title}>
        <PanelSectionRow>
          <Field description={block.body} />
        </PanelSectionRow>
        {status.blocked?.reason === "switched" && (
          <TakeOverRows onTaken={() => void loadStatus()} inUse={status.blocked?.kind} />
        )}
        {updateRow}
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
          {/* The caveat rides on the button rather than in a row above it: it
              is the condition of pressing it, and a rule between the two makes
              it read as a separate remark. `gate.body` keeps its own row --
              that one is about the device, not about this button. */}
          <ButtonItem
            layout="below"
            description={gate.caveat}
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

      {/* Under the transfer row and above everything else, for the same reason
          that one is where it is: both are "something is happening right now",
          and neither is why the panel was opened. Renders nothing when no copy
          is running, which is nearly always. */}
      <CloudStatusPanel />

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
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              label={nudge.label}
              description={nudge.description}
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
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              description="Set up RetroArch and a core, or add a standalone emulator, to start adding games."
              onClick={openManage}
            >
              Set up emulators
            </ButtonItem>
          </PanelSectionRow>
        )}

        {/* Last of the notices, because it is the least urgent of them: a newer
            version is worth knowing about and is never the reason the panel was
            opened. Above the status line or the library nudge it would put a
            version number in front of something that actually needs attention.

            Still above the row below it, though. Everything to here is the
            panel telling you something; what follows is the first thing you
            press on purpose, and mixing a notice in after it reads as an
            afterthought. */}
        {updateRow}

        {/* Above the add flow, because the add flow is the tallest thing in the
            panel -- a ROM row, a core picker and a system picker -- and this
            was below all of it. On a Deck that put the library, and the count
            of what is in it, off the bottom of the screen: the one row here
            worth reading without opening anything was the one row you had to
            scroll to find.

            In this section rather than one of its own, so it is spaced like the
            rows around it. It renders nothing until a game has been added, so
            the first-run panel is unchanged and adding a game stays the top
            control until there is something to go back to. */}
        {gamesFailed && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              label="Could not load your added games"
              description="They are still in Steam; only this list did not arrive."
              onClick={loadGames}
            >
              Try again
            </ButtonItem>
          </PanelSectionRow>
        )}
        <AddedGamesPanel games={games} onChanged={loadGames} />
      </PanelSection>

      {canAddGames && <AddGamePanel status={status} onGameAdded={loadGames} />}

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
 * Our tab's title in the Quick Access header: its name, and a way to the
 * settings page.
 *
 * quickAccessMenuClasses.Title, the Quick Access header's own class, so the
 * name sits on the same line as Steam's own tab titles.
 *
 * The button's numbers are all doing something. `minWidth: 0` because
 * DialogButton is sized for a dialog footer and defaults far wider than a header
 * row has to spare; 28x40 is what a Quick Access header button measures, and
 * the narrower 30px this used before was small enough to be awkward with a
 * thumbstick. At the right edge of the panel, not of the title row: Steam
 * stretches the row across a column far wider than the panel shows, and caps
 * only the panel below it (its own `max-width`), so the row copies that width.
 *
 * The glyph is centred by making the button a flex container rather than by
 * nudging the icon up with a negative margin. The nudge was tuned against one
 * padding value and quietly went wrong whenever the button's size changed --
 * which is how it ended up sitting low here.
 */
function TitleView() {
  const row = useRef<HTMLDivElement>(null);
  const [cap, setCap] = useState<string>();
  const [inset, setInset] = useState<string>();
  useLayoutEffect(() => {
    const panel = row.current?.nextElementSibling;
    if (!row.current || !panel) return;
    // Steam's Title pads only the left; the right mirrors it to line up with
    // the rows below.
    setInset(getComputedStyle(row.current).paddingLeft);
    // The panel's CSS cap, not its measured width: this often mounts while
    // the menu is closed, when the panel measures zero.
    const max = getComputedStyle(panel).maxWidth;
    if (max && max !== "none") setCap(max);
  }, []);
  // Its own focus group: Steam renders the title beside the tab's panel, not
  // inside it, and a bare button there is a leaf no direction leads to.
  return (
    <Focusable
      flow-children="horizontal"
      // Only from inside the tab, so entering it still lands on the panel.
      fnCanTakeFocus={() => !!row.current?.parentElement?.contains(row.current.ownerDocument.activeElement)}
      ref={row}
      className={quickAccessMenuClasses.Title}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        boxSizing: "border-box",
        maxWidth: cap,
        paddingRight: inset,
        boxShadow: "none",
      }}
    >
      <div>DeckyEmu</div>
      <div style={{ display: "flex", gap: "6px" }}>
        <SwitchButton />
        <DialogButton style={HEADER_BUTTON} onClick={() => openManagePage()}>
          <FaCog style={{ display: "block" }} />
        </DialogButton>
      </div>
    </Focusable>
  );
}

/** What `start` hands the bundle's entry to put in the Quick Access tab. */
export interface Started {
  title: ReactElement;
  content: ReactElement;
  icon: ReactElement;
  /** The full-screen page, served under `/deckyemu`. */
  page: () => ReactNode;
  stop(): void;
}

/** What `start` runs once it knows the backend is on. */
function startWithState() {
  // For the "DeckyEmu" submenu behind the cog on a game's page: the item
  // decides whether to appear by reading this cache, so it is filled first.
  void refreshAddedGames();

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
   * And the same for icons: a game added before the plugin set one is a blank
   * square in the library list. Only the shipped picture, and only where there
   * is no icon at all -- see repairIcons.ts for why it does not look anything
   * up while it is at it.
   */
  void repairGameIcons().catch((error: unknown) =>
    console.error("[deckyemu] could not repair game icons", error),
  );

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

}

/** Start the panel: everything that runs whether or not it is open. */
export function start(): Started {

  const unpatchContextMenu = patchGameContextMenu(editGameMenuItem);

  // Steam will not warn before launching one of our games over a running one
  // -- its check is gated on an app_type our shortcuts do not carry. The
  // launcher script is what actually stops it; this is the panel collecting
  // that decision and asking. See launchGate.ts.
  const stopWatchingLaunches = watchLaunches();

  /*
   * And the other end of a game: copying its saves up once it is closed.
   *
   * Here rather than in the launcher script, which is where it looks like it
   * belongs. Steam's reaper waits for every descendant of what it started, so
   * an upload in the launcher's exit trap holds the library tile on "Running"
   * until the network is finished. See playWatch.ts.
   */
  const stopWatchingPlaying = watchPlaying();

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
   * The rest reads the state, so only when this build is the one in use: a
   * backend that stays off refuses each of them (see claim.py). Asked once;
   * after a switch, Steam restarts and this runs again.
   */
  void callWithRetry(getStatus)
    .then((status) => {
      if (!status.blocked) startWithState();
    })
    .catch((error) => console.error("[deckyemu] could not read the status", error));

  return {
    title: <TitleView />,
    page: GuardedManagePage,
    /*
     * Wrapped, because this renders inside Steam's Quick Access menu and a
     * throw
     * here unmounts everything up to whatever boundary Steam has -- taking the
     * whole menu with it, not just our tab.
     */
    content: (
      <ErrorBoundary where="The DeckyEmu panel">
        <Content />
      </ErrorBoundary>
    ),
    /*
     * Two children rather than one, so the update dot sits on the tab's own
     * glyph. `UpdateDot` renders nothing at all until there is something to
     * say, so the ordinary case is the glyph alone.
     */
    icon: (
      <>
        <FaGamepad />
        <UpdateDot />
      </>
    ),
    stop() {
      removeEventListener("update_available", onUpdateAvailable);
      // Steam keeps the patched component, so leaving this would put a dead
      // item in every game menu until the client restarts.
      unpatchContextMenu();
      // Same reason: Steam keeps the registration, and an update would
      // otherwise leave the old copy toasting alongside the new one.
      stopWatchingLaunches();
      stopWatchingPlaying();
    },
  };
}
