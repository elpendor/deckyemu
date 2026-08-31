import {
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  Spinner,
  Tabs,
} from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { FaGamepad, FaInfoCircle, FaPen, FaPlay, FaTrash } from "react-icons/fa";

import { getSettings, listAdded, type AddedGame } from "./backend";
import { GameEditorModal } from "./GameEditorModal";
import { playGame } from "./playGame";
import { RemoveGameModal } from "./RemoveGameModal";
import { viewGameDetails } from "./viewGameDetails";
import { systemLabel } from "./systemLabel";
import { callWithRetry } from "./timeout";
import { openModal } from "./modalStack";
import { landscapeArtUrls } from "./steam";
import { ICON_BUTTON } from "./iconButton";

interface Props {
  closeModal?: () => void;
  onChanged: () => void;
}

/**
 * **Steam's navigation components fill a sized parent; they do not size to
 * their content.** `Tabs` is the library's own tab row -- `@decky/ui` finds it
 * by matching `TabRowTabs` in Steam's bundle -- and it is built for a
 * full-screen route, where the height is simply there.
 *
 * `ModalRoot` is the opposite: it sizes to its children. Dropped straight in,
 * the tab row and its content pane rendered *below the dialog's own border*,
 * over the Steam background, leaving the modal an empty rectangle holding only
 * the title. Nothing was wrong with the tabs; there was no height for them to
 * fill.
 *
 * So the container below states one. It is the same rule `ManagePage` follows
 * for `SidebarNavigation`, which works because its parent is
 * `height: calc(100% - 40px)` rather than because a sidebar is different from a
 * tab row.
 */
const TABS_HEIGHT = "62vh";

/**
 * The artwork slot on each row.
 *
 * **A fixed box, and that is the point of it.** Some games have no art -- the
 * add flow says so at the time, and it is an ordinary outcome rather than a
 * fault -- so a slot that collapsed when empty would start every other title at
 * a different place down the list. An empty box of the same size keeps one
 * column of names.
 *
 * 84x40 for a 460x215 header, which is very close to its own 2.14:1, so nothing
 * is squashed. It fits inside the row without lengthening it: the rows are
 * already 48px tall because that is the size of the buttons at the other end.
 */
const ART_SLOT: React.CSSProperties = {
  width: "84px",
  height: "40px",
  flexShrink: 0,
  borderRadius: "3px",
  overflow: "hidden",
};

/**
 * What stands in when there is no artwork.
 *
 * An empty box was the first version and read as a rendering fault -- a gap
 * where every other row has a picture looks like something failed rather than
 * like a game nobody found art for, which is an ordinary outcome the add flow
 * reports at the time.
 *
 * Quiet on purpose. It is filling a hole, not asking to be looked at, so it
 * takes the same faint plate the rows use and a muted glyph rather than a
 * colour or a word. At 84x40 a system name would not fit and a title would be
 * illegible.
 */
function ArtPlaceholder() {
  return (
    <div
      style={{
        ...ART_SLOT,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(255, 255, 255, 0.06)",
        color: "rgba(255, 255, 255, 0.28)",
        fontSize: "20px",
      }}
    >
      <FaGamepad />
    </div>
  );
}

/**
 * A game's artwork, or the placeholder above.
 *
 * Its own component because it has to hold state: Steam offers one URL per
 * extension the file might carry and only one of them is real, so this walks
 * the list on each failure rather than trusting the first. Falling off the end
 * lands on the placeholder, which is also what a game with no artwork gets --
 * one path for "there is none" and "none of these loaded", because to a reader
 * they are the same thing.
 */
function RowArt({ urls }: { urls: string[] }) {
  const [tried, setTried] = useState(0);
  if (tried >= urls.length) return <ArtPlaceholder />;
  return (
    <img
      src={urls[tried]}
      alt=""
      style={{ ...ART_SLOT, objectFit: "cover" }}
      onError={() => setTried((n) => n + 1)}
    />
  );
}

/**
 * The tab that was showing when this last closed.
 *
 * Module scope for the reason `romDraft` is: Steam unmounts Quick Access
 * content when a modal opens, so nothing in component state survives the modal
 * closing -- and reopening the list to find yourself back on the first system
 * is the whole complaint. Remembering it here costs one variable and survives
 * every close and reopen in a session.
 *
 * Deliberately not a stored setting. A tab is a position rather than a
 * preference, and persisting it would mean a settings write on every press of
 * a bumper. It resets when the plugin reloads, which is the right lifetime:
 * that only happens on an update or a restart, and neither is a moment when
 * somebody is mid-way through their library.
 */
let lastTab = "";

/**
 * Every game this plugin added, grouped by the system it runs on.
 *
 * It used to be the Quick Access panel itself, one row per game under
 * "Added games". That reads fine at four games and becomes the panel at forty:
 * everything else — adding a game, the emulator lists, the transfer button —
 * ends up below a list that only grows, on a screen you reach by holding a
 * button mid-session. So the list moved in here and the panel kept the count.
 *
 * **Two layouts, chosen in Settings.** Grouped is the default: every system
 * under a heading in one scroll, so what you own is visible on the way past.
 * Tabbed puts one system per tab, which L1 and R1 page -- fewer presses to a
 * system you already have in mind, and nothing about the others while you are
 * there.
 *
 * Neither wins outright, which is why it is a switch. It turns on the shape of
 * a library rather than on taste: a few games spread thinly across many systems
 * read better grouped, because a tab holding one game is a tab bar entry, a
 * pane and one row. A lot of games on a few systems read better tabbed. This
 * plugin cannot know which somebody has.
 *
 * Both draw the same rows, from `gameRow`, so the two cannot drift.
 *
 * Reads its own copy rather than taking the panel's: Steam unmounts Quick
 * Access content when a modal opens, so the list behind this one is not
 * updating, and removing a game from here has to take it out of *this* list to
 * be believable.
 */
export function AddedGamesModal({ closeModal, onChanged }: Props) {
  const [games, setGames] = useState<AddedGame[] | null>(null);
  /**
   * Which tab is showing, or "" before anything has been chosen.
   *
   * Seeded from `lastTab` and resolved against the system list at render: the
   * list arrives asynchronously, so a remembered system cannot be checked here
   * — and one can leave while the modal is open, when its last game is removed
   * from a row two lines down.
   */
  const [tab, setTab] = useState(lastTab);
  /**
   * Which layout to draw, or null until the setting has been read.
   *
   * Null rather than defaulting to `false`: the list and the setting arrive
   * from two calls, and picking a layout before the answer is in means drawing
   * the grouped list and then replacing it with tabs a frame later, in front of
   * somebody who has just opened the dialog.
   */
  const [tabbed, setTabbed] = useState<boolean | null>(null);

  const load = useCallback(() => {
    callWithRetry(listAdded)
      .then(setGames)
      .catch((error) => {
        console.error("[deckyemu] could not list added games", error);
        setGames([]);
      });
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    // A failure here is a layout question, not a data one, so it falls back to
    // the default rather than reporting anything: the list is what the reader
    // came for and it is already on its way.
    callWithRetry(getSettings)
      .then((settings) => setTabbed(Boolean(settings.added_games_tabs)))
      .catch(() => setTabbed(false));
  }, []);

  // Both the panel behind and the list in here: the panel owns the count on the
  // button, and this owns the rows.
  const changed = useCallback(() => {
    load();
    onChanged();
  }, [load, onChanged]);

  const grouped = new Map<string, AddedGame[]>();
  for (const game of games ?? []) {
    const key = systemLabel(game);
    grouped.set(key, [...(grouped.get(key) ?? []), game]);
  }
  const systems = [...grouped.keys()].sort((a, b) => a.localeCompare(b));
  // Falls back to the first system whenever the remembered one is not there:
  // the first ever open, a system whose last game was just removed, and a
  // library that has changed since the modal was last closed.
  const active = systems.includes(tab) ? tab : (systems[0] ?? "");

  const gameRow = (game: AddedGame) => {
    const art = landscapeArtUrls(game.app_id);
    return (
    <Field
      key={game.app_id}
      childrenContainerWidth="min"
      // **The artwork lives in the label, not in `Field`'s `icon` slot.**
      //
      // The slot works and centres its own column -- every ancestor of the
      // image reports `align-items: center` -- but `Field` lays the label out
      // somewhere else, and `verticalAlignment="center"` did not reach it. The
      // title sat ten pixels above the middle of a row whose height comes from
      // the artwork and the buttons either side. Measured rather than judged:
      // row centre 454, title centre 439.
      //
      // One flex row fixes it by no longer asking `Field` to align two things
      // it lays out separately. The image is `alt=""`, so it is decorative and
      // adds nothing to the row's accessible name -- which was the only reason
      // the icon slot looked worth preferring.
      label={
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <RowArt urls={art} />
          <span>{game.title}</span>
        </div>
      }
    >
      <div style={{ display: "flex", gap: "6px" }}>
        {/* First in the row because it is what the list is most often open
            for. Getting to a game otherwise means closing the panel, finding
            it on the shelf and launching it there -- and this list is already
            the one place that knows which games are the plugin's. `playGame`
            takes this modal's dismiss so nothing is left over the game. */}
        <DialogButton
          onClick={() => playGame(game.app_id, game.title, closeModal)}
          style={ICON_BUTTON}
        >
          <FaPlay />
        </DialogButton>
        {/* Second, after play: it is the other thing you might want a game
            *for* rather than a thing you do *to* it, and the two below are.
            Same discipline as play -- the modal is dismissed before the
            navigation, or Steam re-reveals it over the page it just went to. */}
        <DialogButton
          onClick={() => viewGameDetails(game.app_id, closeModal)}
          style={ICON_BUTTON}
        >
          <FaInfoCircle />
        </DialogButton>
        <DialogButton
          // Stacked on this one: Steam nests modals, so closing the editor
          // comes back here rather than to the panel.
          onClick={() =>
            openModal(
              <GameEditorModal
                game={game}
                onSaved={changed}
                // Only for a jump to another screen: this list is where saving
                // and cancelling should land.
                onLeave={closeModal}
              />,
            )
          }
          style={ICON_BUTTON}
        >
          <FaPen />
        </DialogButton>
        <DialogButton
          onClick={() => openModal(<RemoveGameModal game={game} onRemoved={changed} />)}
          style={ICON_BUTTON}
        >
          <FaTrash />
        </DialogButton>
      </div>
    </Field>
    );
  };

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        Added games{games ? ` (${games.length})` : ""}
      </div>

      {games === null && <Spinner style={{ height: "24px" }} />}

      {games?.length === 0 && (
        <Field description="Nothing has been added to Steam from here yet." />
      )}

      {/* Nothing until the setting has been read. Both layouts draw the same
          rows, so the flash would not lose anything -- but it would move every
          row under a thumb already reaching for one. */}
      {systems.length > 0 && tabbed === true && (
        <div
          style={{
            height: TABS_HEIGHT,
            display: "flex",
            flexDirection: "column",
            // **Changing tab is a slide, and it starts off screen.** Steam
            // animates the outgoing pane out one side and the incoming one in
            // from the other. Across a full-width route that happens inside the
            // viewport and is never seen; in a dialog the panes travel in from
            // beyond its edges, and without this you watch a list of games cross
            // the Steam background before it lands.
            //
            // The inner Focusable keeps its own `overflowY`, so clipping here
            // costs the scrolling nothing.
            overflow: "hidden",
          }}
        >
          <Tabs
            activeTab={active}
            onShowTab={(next: string) => {
              setTab(next);
              lastTab = next;
            }}
            tabs={systems.map((system) => ({
              id: system,
              // The count belongs on the tab rather than on every row: the
              // system is already the answer to "what is this", and repeating
              // it per game is what the flat list did.
              title: `${system} (${grouped.get(system)!.length})`,
              content: (
                // Focusable rather than a div, and this is the rule that has
                // cost the most here: a controller cannot enter a scroll region
                // with nothing focusable in it, so the part below the fold is
                // unreachable. The rows carry buttons, so this one is enterable
                // -- but the container still has to be a Focusable to be the
                // thing focus enters.
                <Focusable
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    height: "100%",
                    overflowY: "auto",
                  }}
                >
                  {grouped
                    .get(system)!
                    .sort((a, b) => a.title.localeCompare(b.title))
                    .map((game) => gameRow(game))}
                </Focusable>
              ),
            }))}
          />
        </div>
      )}

      {/* The default. Scrolled, and Focusable rather than a div: a controller
          has to be able to reach past the first screenful, which is the whole
          reason this list stopped being the panel. Same shell as the library
          check. */}
      {systems.length > 0 && tabbed === false && (
        <Focusable
          style={{
            display: "flex",
            flexDirection: "column",
            maxHeight: "60vh",
            overflowY: "auto",
          }}
        >
          {systems.map((system) => (
            <div key={system}>
              <div
                style={{
                  fontWeight: 600,
                  padding: "12px 0 2px",
                  // The count belongs with the heading rather than on every row:
                  // the system is already the answer to "what is this", and
                  // repeating it per game is what the flat list did.
                  opacity: 0.9,
                }}
              >
                {system} ({grouped.get(system)!.length})
              </div>
              {grouped
                .get(system)!
                .sort((a, b) => a.title.localeCompare(b.title))
                .map((game) => gameRow(game))}
            </div>
          ))}
        </Focusable>
      )}

    </ModalRoot>
  );
}
