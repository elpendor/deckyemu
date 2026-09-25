import {
  ConfirmModal,
  DialogButton,
  Field,
  ModalRoot,
  Spinner,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";

import { addRomPatch, patchTargets, type PatchTarget } from "./backend";
import { MUTED } from "./dialogStyle";
import { ICON_BUTTON_WIDE } from "./iconButton";
import { logError } from "./logError";
import { openModal } from "./modalStack";
import { ScrollList } from "./ScrollList";

/**
 * Install a ROM hack from wherever it was picked: the transfer list or the add
 * panel.
 *
 * The same **Install** a Switch update has, with one question in front of it. An
 * update names its game and a patch does not, so this asks which game -- and the
 * one wanted is nearly always named in the patch's filename, which is what puts
 * it at the top of the list.
 *
 * `onDone` hears whether the patch went in, so the add panel can clear itself.
 */
export function openPatchInstall(
  path: string,
  name: string,
  onDone?: (installed: boolean) => void,
) {
  openModal(<PatchTargetModal path={path} name={name} onDone={onDone} />);
}

function refuse(body: string) {
  openModal(
    <ConfirmModal
      strTitle="Not installed"
      strDescription={body}
      strOKButtonText="Close"
      bAlertDialog
    />,
  );
}

interface Props {
  path: string;
  name: string;
  onDone?: (installed: boolean) => void;
  closeModal?: () => void;
}

/**
 * The games a patch could go on, one row each with Install.
 *
 * Built like the added games list -- a title, a `ScrollList` of `Field` rows,
 * a button on each -- because that is the dialog here that already holds a
 * long list of games, and a controller can reach every row of it.
 */
function PatchTargetModal({ path, name, onDone, closeModal }: Props) {
  const [targets, setTargets] = useState<PatchTarget[] | null>(null);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    let live = true;
    patchTargets(path)
      .then((result) => {
        if (!live) return;
        if (result.ok) setTargets(result.games);
        else setProblem(result.error);
      })
      .catch((error) => {
        logError("could not list games for a patch", error);
        if (live) setProblem("Could not list your games.");
      });
    return () => {
      live = false;
    };
  }, [path]);

  const install = async (game: PatchTarget) => {
    // Closed first: whatever this reports is a dialog of its own, and one left
    // underneath would come back over the list when it closes.
    closeModal?.();
    try {
      const result = await addRomPatch(game.app_id, path);
      if (!result.ok) {
        refuse(result.error || "Could not install that patch.");
        onDone?.(false);
        return;
      }
      toaster.toast({ title: "Patch installed", body: `${name} on ${game.title}` });
      onDone?.(true);
    } catch (error) {
      logError("could not install a patch", error);
      refuse("Could not install that patch.");
      onDone?.(false);
    }
  };

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "6px" }}>
        Install on which game?
      </div>
      <div style={{ ...MUTED, marginBottom: "10px", overflowWrap: "anywhere" }}>
        {name} — RetroArch applies it as the game loads. Your ROM file is not changed.
      </div>

      {targets === null && !problem && <Spinner style={{ height: "24px" }} />}
      {problem && <Field description={problem} />}
      {targets?.length === 0 && (
        <Field description="None of your games can take a patch. ROM hacks work with games that run in RetroArch." />
      )}

      {targets && targets.length > 0 && (
        <ScrollList style={{ maxHeight: "55vh" }}>
          {targets.map((game) => (
            <Field
              key={game.app_id}
              label={game.title}
              description={
                [game.likely ? "Named in the patch" : "", game.platform, game.warning]
                  .filter(Boolean)
                  .join(" · ")
              }
              childrenContainerWidth="min"
            >
              <DialogButton onClick={() => void install(game)} style={ICON_BUTTON_WIDE}>
                Install
              </DialogButton>
            </Field>
          ))}
        </ScrollList>
      )}
    </ModalRoot>
  );
}
