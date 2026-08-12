import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";

import {
  deletePackagedGame,
  deleteRom,
  packagedGameInfo,
  unregisterGame,
  type AddedGame,
} from "./backend";
import { removeAppsFromCollection, removeShortcut } from "./steam";
import { humanSize } from "./TransferModal";

interface Props {
  closeModal?: () => void;
  game: AddedGame;
  onRemoved: () => void;
}

/**
 * Removing a game, which deletes the game.
 *
 * This was a checkbox, off by default, on the reasoning that deleting somebody's
 * ROM by accident costs them a trip to another machine while leaving it costs
 * only disk. What that reasoning missed is where the leftovers end up: files
 * the plugin put on the disk, that nothing in the library points at, needing
 * their own sweep to find and their own dialog to explain. Kept files are not
 * free — they are a second thing to reconcile forever.
 *
 * So removal takes everything the plugin put there: the shortcut, the launcher,
 * and the game itself, whether that is a ROM filed under its system or a game
 * unpacked inside an emulator. No option, and the dialog says exactly what goes
 * and what getting it back would cost, because an unmissable sentence is the
 * whole of the protection now.
 *
 * The one thing never deleted is a ROM this plugin did not file. On an SD card,
 * in a library some other tool laid out, anywhere of the user's own: it was never
 * moved here and is not ours to remove. The dialog says that too.
 */
export function RemoveGameModal({ closeModal, game, onRemoved }: Props) {
  // What removing this game could also delete. Two kinds of thing behind one
  // question: a game the plugin unpacked inside an emulator, or a ROM it filed
  // under its system. They cost the same to get wrong -- a trip to another
  // machine -- so the dialog stopped treating them differently.
  const [extra, setExtra] = useState<{
    kind: "packaged" | "rom";
    system?: "ps3" | "ps4" | "vita";
    title_id?: string;
    bytes: number;
    files?: string[];
    folder?: string;
  } | null>(null);

  useEffect(() => {
    let live = true;
    packagedGameInfo(game.rom_path)
      .then((info) => {
        if (!live || !info.ok) return;
        setExtra({
          kind: info.kind ?? "packaged",
          system: info.system,
          title_id: info.title_id,
          bytes: info.bytes ?? 0,
          files: info.files,
          folder: info.folder,
        });
      })
      .catch((error) => console.error("[deckyemu] could not read game info", error));
    return () => {
      live = false;
    };
  }, [game.rom_path]);

  return (
    <ConfirmModal
      closeModal={closeModal}
      strTitle={`Remove ${game.title}?`}
      // Spelled out rather than summarised. Removing a game deletes the game,
      // and the only defence against that being a surprise is saying so in the
      // sentence the user reads before pressing.
      strDescription={
        extra?.kind === "rom"
          ? `This deletes the Steam shortcut, its launcher script, and the ROM itself ` +
            `— ${humanSize(extra.bytes)} from roms/${extra.folder}` +
            ((extra.files?.length ?? 0) > 1
              ? `, all ${extra.files!.length} of its files. `
              : ". ") +
            "Playing it again means sending it from another machine again. Save data is kept."
          : extra
            ? `This deletes the Steam shortcut, its launcher script, and the game itself ` +
              `— ${humanSize(extra.bytes)} from ${
                { ps3: "RPCS3", ps4: "shadPS4", vita: "Vita3K" }[extra.system!]
              }. Playing it again means sending the package from another machine and ` +
              `unpacking it again. Your save data is kept` +
              (extra.system === "ps4" ? "." : ", and so is your licence.")
            : "This deletes the Steam shortcut and its launcher script. The ROM is somewhere " +
              "of your own rather than in this plugin's folder, so it is left alone."
      }
      strOKButtonText={extra ? "Remove and delete" : "Remove"}
      bDestructiveWarning
      onOK={() => {
        void (async () => {
          try {
            removeShortcut(game.app_id);
            const forgotten = await unregisterGame(game.app_id);

            // Take it out of its collection too, and let that collection go if
            // it is now empty. Removing the shortcut alone left the collection
            // holding an app id that no longer exists -- so it never counted as
            // empty, and a shelf for a console with no games on it stayed in
            // the library forever. Conditional inside removeAppsFromCollection:
            // one still holding games the user dragged in survives.
            if (forgotten?.collection) {
              await removeAppsFromCollection(forgotten.collection, [game.app_id]);
            }

            let freed = 0;
            if (extra) {
              const result =
                extra.kind === "rom"
                  ? await deleteRom(game.rom_path)
                  : await deletePackagedGame(extra.system!, extra.title_id!);
              if (!result.ok) {
                // The shortcut is already gone, so this is not a failed
                // removal — it is a removal with the files still there, and
                // saying which happened is the useful part.
                toaster.toast({
                  title: "Removed, but the files are still there",
                  body: result.error ?? "",
                });
                onRemoved();
                return;
              }
              freed = result.freed ?? 0;
            }

            toaster.toast({
              title: "Removed from Steam",
              body: freed ? `${game.title} — ${humanSize(freed)} freed` : game.title,
            });
            onRemoved();
          } catch (error) {
            console.error("[deckyemu] remove failed", error);
            toaster.toast({ title: "Could not remove the game", body: game.title });
          }
        })();
      }}
    >
    </ConfirmModal>
  );
}
