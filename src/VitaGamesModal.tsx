import { DialogButton, Field, ModalRoot, Spinner } from "./steamui";
import { useEffect, useState } from "react";

import { listAdded, listInstalledVitaGames, type Ps3Game } from "./backend";
import { startBatch } from "./batchImport";
import { BatchImportModal } from "./BatchImportModal";
import { ICON_BUTTON_WIDE } from "./iconButton";
import { closeOpenModals, openModal } from "./modalStack";

interface Props {
  closeModal?: () => void;
  onAdded: () => void;
}

/**
 * The PS Vita games Vita3K has installed, and one press to put one in Steam.
 *
 * Vita is the one console here the plugin cannot install for. Vita3K decrypts
 * content as it installs, so files copied into `ux0/app` produce a game it
 * lists and refuses to start — the install has to happen in its own interface.
 * Everything after that is ours, and this is it.
 *
 * These go in through a different door from the other consoles: nothing is
 * added by picking a file, because the file was consumed by an installer we
 * did not run. The list is the only place these games exist to be chosen from.
 */
export function VitaGamesModal({ closeModal, onAdded }: Props) {
  const [games, setGames] = useState<Ps3Game[] | null>(null);

  // Only what is not already in the library. This is a list to add *from*, so
  // a game that has been added is finished business -- offering it again
  // invites a second shortcut for the same game, which Steam is perfectly
  // happy to make.
  useEffect(() => {
    Promise.all([listInstalledVitaGames(), listAdded()])
      .then(([installed, added]) => {
        const inSteam = new Set(added.map((game) => game.rom_path));
        setGames((installed.games ?? []).filter((game) => !inSteam.has(game.eboot)));
      })
      .catch((listError) => {
        console.error("[deckyemu] could not list Vita games", listError);
        setGames([]);
      });
  }, []);

  // Into the review like any other game: its name, cover and emulator are
  // checked there, and it is added the way an installed package's game is.
  const add = (game: Ps3Game) => {
    void startBatch([{
      path: game.eboot, name: game.title,
      packaged: { system: "vita", titleId: game.title_id },
    }]);
    onAdded();
    closeModal?.();
    closeOpenModals();
    openModal(<BatchImportModal />);
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        PlayStation Vita games in Vita3K
      </div>

      {games === null && <Spinner style={{ height: "24px" }} />}

      {games?.length === 0 && (
        // Two different empty states, and telling them apart matters: one
        // means "go and install something", the other means "you are done".
        <Field description="Nothing left to add — every game Vita3K has installed is already in your library. Install more from a .pkg in Add a game, or through Vita3K's own File > Install." />
      )}

      {games?.map((game) => (
        <Field
          key={game.title_id}
          label={game.title}
          description={game.title_id}
          childrenContainerWidth="min"
        >
          <DialogButton
            onClick={() => add(game)}
            style={ICON_BUTTON_WIDE}
          >
            Add
          </DialogButton>
        </Field>
      ))}
    </ModalRoot>
  );
}
