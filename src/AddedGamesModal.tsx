import { DialogButton, Field, Focusable, ModalRoot, showModal, Spinner } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { FaPen, FaTrash } from "react-icons/fa";

import { listAdded, type AddedGame } from "./backend";
import { GameEditorModal } from "./GameEditorModal";
import { RemoveGameModal } from "./RemoveGameModal";
import { systemLabel } from "./systemLabel";
import { callWithRetry } from "./timeout";

interface Props {
  closeModal?: () => void;
  onChanged: () => void;
}

/**
 * Every game this plugin added, grouped by the system it runs on.
 *
 * It used to be the Quick Access panel itself, one row per game under
 * "Added games". That reads fine at four games and becomes the panel at forty:
 * everything else — adding a game, the emulator lists, the transfer button —
 * ends up below a list that only grows, on a screen you reach by holding a
 * button mid-session. So the list moved in here and the panel kept the count.
 *
 * Grouped because the flat list had no order anyone could use. Sorted by system
 * and then by title, so a game is where you would look for it.
 *
 * Reads its own copy rather than taking the panel's: Steam unmounts Quick
 * Access content when a modal opens, so the list behind this one is not
 * updating, and removing a game from here has to take it out of *this* list to
 * be believable.
 */
export function AddedGamesModal({ closeModal, onChanged }: Props) {
  const [games, setGames] = useState<AddedGame[] | null>(null);

  const load = useCallback(() => {
    callWithRetry(listAdded)
      .then(setGames)
      .catch((error) => {
        console.error("[deckyemu] could not list added games", error);
        setGames([]);
      });
  }, []);

  useEffect(load, [load]);

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

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        Added games{games ? ` (${games.length})` : ""}
      </div>

      {games === null && <Spinner style={{ height: "24px" }} />}

      {games?.length === 0 && (
        <Field description="Nothing has been added to Steam from here yet." />
      )}

      {/* Scrolled, and Focusable rather than a div: a controller has to be
          able to reach past the first screenful, which is the whole reason this
          list stopped being the panel. Same shell as the library check. */}
      <Focusable
        style={{
          display: "flex",
          flexDirection: "column",
          maxHeight: "60vh",
          overflowY: "auto",
        }}
      >
      {systems.map((system) => {
        const inSystem = grouped
          .get(system)!
          .sort((a, b) => a.title.localeCompare(b.title));
        return (
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
              {system} ({inSystem.length})
            </div>
            {inSystem.map((game) => (
              <Field key={game.app_id} label={game.title} childrenContainerWidth="min">
                <div style={{ display: "flex", gap: "6px" }}>
                  <DialogButton
                    // Stacked on this one: Steam nests modals, so closing the
                    // editor comes back here rather than to the panel.
                    onClick={() =>
                      showModal(
                        <GameEditorModal
                          game={game}
                          onSaved={changed}
                          // Only for a jump to another screen: this list is
                          // where saving and cancelling should land.
                          onLeave={closeModal}
                        />,
                      )
                    }
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaPen />
                  </DialogButton>
                  <DialogButton
                    onClick={() =>
                      showModal(<RemoveGameModal game={game} onRemoved={changed} />)
                    }
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaTrash />
                  </DialogButton>
                </div>
              </Field>
            ))}
          </div>
        );
      })}
      </Focusable>
    </ModalRoot>
  );
}
