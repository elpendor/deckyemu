import { DialogButton, Field, ModalRoot, Spinner } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";

import {
  listAdded,
  listInstalledVitaGames,
  prepareVitaGame,
  type Ps3Game,
} from "./backend";
import { addPreparedGame } from "./addGame";
import { getDraft } from "./romDraft";
import { lookupArtwork } from "./addFlow";

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
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

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

  const add = (game: Ps3Game) => {
    setBusy(game.title_id);
    setError("");
    void (async () => {
      try {
        const prepared = await prepareVitaGame(game.title_id);
        if (!prepared.ok) {
          setError(prepared.error);
          return;
        }

        // The name comes from the game's own param.sfo, so SteamGridDB is
        // asked about "GRAVITY RUSH" rather than about a product code. The
        // result lands in the shared draft, which is where lookupArtwork puts
        // it — read back here rather than returned, because the panel behind
        // this modal is unmounted and that is the only place it survives.
        //
        // Looked up before the shortcut exists, unlike the add flow, because
        // there is no panel here to have done it already.
        await lookupArtwork(prepared.rom_path ?? "", prepared.core_id ?? "", prepared.title);

        // Shortcut, artwork, collection, registry -- the same five steps the
        // add flow runs, which this file used to keep its own copy of. See
        // addGame.ts.
        const added = await addPreparedGame({
          prepared,
          romPath: prepared.rom_path ?? "",
          coreId: prepared.core_id ?? "",
          system: "Sony - PlayStation Vita",
          art: getDraft().resolved?.art,
          // What boots is eboot.bin for every Vita game, so remembering this
          // core for `.bin` would suggest Vita3K for the next PS1 disc image.
          rememberCore: false,
        });

        toaster.toast({
          title: `${prepared.title} added`,
          body: added.artApplied
            ? `${added.artApplied} artwork image(s) applied.`
            : "It is in your library.",
        });
        onAdded();
        closeModal?.();
      } catch (addError) {
        console.error("[deckyemu] could not add the Vita game", addError);
        setError(addError instanceof Error ? addError.message : "Could not add that game.");
      } finally {
        setBusy("");
      }
    })();
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
            disabled={Boolean(busy)}
            onClick={() => add(game)}
            style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
          >
            {busy === game.title_id ? "Adding..." : "Add"}
          </DialogButton>
        </Field>
      ))}

      {error && <Field description={error} />}
    </ModalRoot>
  );
}
