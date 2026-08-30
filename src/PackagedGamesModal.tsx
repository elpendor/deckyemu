import { DialogButton, Field, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useState } from "react";

import {
  listAdded,
  listInstalledPs3Games,
  listInstalledPs4Games,
  type Ps3Game,
} from "./backend";
import { selectPackagedGame } from "./addFlow";
import { ICON_BUTTON_WIDE } from "./iconButton";

/**
 * The games RPCS3 or shadPS4 already has, as somewhere to add one from.
 *
 * Every other system can be re-added from the ROM picker, because the ROM is
 * still where the user put it. These two cannot: the `.pkg` was consumed
 * installing the game and is deleted afterwards, and what boots is buried under
 * a product code — `~/.config/rpcs3/dev_hdd0/game/NPUB30133/USRDIR/EBOOT.BIN`.
 * Without this list, a game removed from the library and kept on disk could
 * only be added back by typing that path, which is the exact thing this plugin
 * exists to avoid. shadPS4 had no such list, so a removed PS4 game was simply
 * unreachable: the package that installed it was already gone.
 *
 * One component for both because the two are the same in every way that
 * reaches the user — a list, a name, a product code, one press. Vita keeps its
 * own, since it launches by title id and adds itself rather than filling the
 * draft.
 *
 * Picking one hands off to the same path a fresh install takes: the name comes
 * from the game's own PARAM.SFO and the artwork from SteamGridDB. The draft is
 * written directly rather than through a callback, because Steam unmounts the
 * panel behind this modal — see romDraft.ts.
 */
const CONSOLES = {
  ps3: {
    title: "PlayStation 3 games in RPCS3",
    games: listInstalledPs3Games,
    empty:
      "RPCS3 has no games installed yet. Choose a .pkg from the ROM picker and it will be installed first.",
  },
  ps4: {
    title: "PlayStation 4 games in shadPS4",
    games: listInstalledPs4Games,
    empty:
      "shadPS4 has no games installed yet. Choose a .pkg from the ROM picker and it will be installed first.",
  },
} as const;

interface Props {
  system: keyof typeof CONSOLES;
  closeModal?: () => void;
}

export function PackagedGamesModal({ system, closeModal }: Props) {
  const [games, setGames] = useState<Ps3Game[] | null>(null);
  const console_ = CONSOLES[system];

  // Only what is not already in the library, for the same reason as the Vita
  // list: this is somewhere to add *from*, and offering a game that is already
  // there invites a second shortcut for it.
  useEffect(() => {
    Promise.all([console_.games(), listAdded()])
      .then(([installed, added]) => {
        const inSteam = new Set(added.map((game) => game.rom_path));
        setGames((installed.games ?? []).filter((game) => !inSteam.has(game.eboot)));
      })
      .catch((error) => {
        console.error(`[deckyemu] could not list installed ${system} games`, error);
        setGames([]);
      });
  }, [system, console_]);

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        {console_.title}
      </div>

      {games === null && <Spinner style={{ height: "24px" }} />}

      {games?.length === 0 && <Field description={console_.empty} />}

      {games?.map((game) => (
        <Field
          key={game.title_id}
          label={game.title}
          // A store game with no licence installs, adds and then refuses to
          // start with "Failed to decrypt content" — so it is said here, where
          // the game is still being chosen. Only known for games this plugin
          // installed; anything else says nothing rather than guessing. PS4
          // games carry no licence_state at all, so they never show this.
          description={
            game.licence_state === ""
              ? `${game.title_id} · no .rap licence installed`
              : game.title_id
          }
          childrenContainerWidth="min"
        >
          <DialogButton
            onClick={() => {
              // Deliberately not awaited: the modal closes immediately and the
              // lookup finishes into the draft, which the panel is subscribed
              // to whether or not it is mounted right now.
              void selectPackagedGame(system, game.title_id);
              closeModal?.();
            }}
            style={ICON_BUTTON_WIDE}
          >
            Add
          </DialogButton>
        </Field>
      ))}
    </ModalRoot>
  );
}
