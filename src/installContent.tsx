import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { installGameContent, type GameContentOwner, type RomProbe } from "./backend";
import { logError } from "./logError";
import { openModal } from "./modalStack";

/**
 * Install a Switch update or DLC into the game it names, from wherever it was
 * picked.
 *
 * One function for the transfer list and the add panel, so the two Install
 * buttons cannot drift into different rules. Refusals are a dialog: in both
 * places the file is about to be looked at again, and a toast in a corner over
 * a list is how the editor's own refusal went unseen.
 *
 * Resolves whether the file went in.
 */
export async function installContentFor(
  owner: GameContentOwner,
  path: string,
): Promise<boolean> {
  const refuse = (body: string, title = "Not installed") =>
    openModal(
      <ConfirmModal
        strTitle={title}
        strDescription={body}
        strOKButtonText="Close"
        bAlertDialog
      />,
    );

  // Install is offered whether or not the game is in the library, and says so
  // when pressed. A row that read "add its game first" instead of a button was
  // a sentence standing where every other file has something to press.
  if (!owner.app_id) {
    refuse(owner.problem || "The game this is for has not been added yet.", "Game not added yet");
    return false;
  }
  try {
    const result = await installGameContent(owner.app_id, path);
    if (!result.ok) {
      refuse(result.error || "Could not install that file.");
      return false;
    }
    toaster.toast({ title: `${owner.label} installed`, body: owner.title });
    return true;
  } catch (error) {
    logError("could not install an update or DLC", error);
    refuse("Could not install that file.");
    return false;
  }
}

/**
 * Install what was sent with a game, straight after the game is added.
 *
 * The game is in the library by now and stays there whatever happens here, so
 * a file that will not go in is reported and nothing is undone: a game without
 * its update still plays, and the editor can install it again. All refusals go
 * into one dialog rather than one each, since several at once is the likely
 * shape -- an update and its DLC sent for a game whose file says nothing.
 *
 * Resolves how many went in.
 */
export async function installWaitingContent(
  appId: number,
  waiting: NonNullable<RomProbe["content_waiting"]>,
): Promise<number> {
  let installed = 0;
  const refused: string[] = [];
  for (const one of waiting) {
    try {
      const result = await installGameContent(appId, one.path);
      if (result.ok) installed += 1;
      else refused.push(`${one.label}: ${result.error}`);
    } catch (error) {
      logError("could not install an update or DLC after adding", error);
      refused.push(`${one.label}: could not install it.`);
    }
  }
  if (refused.length) {
    openModal(
      <ConfirmModal
        strTitle="The game was added, but not all of its updates and DLC"
        strDescription={`${refused.join(" ")} The files are still in the transfer folder, and the game's editor can install them.`}
        strOKButtonText="Close"
        bAlertDialog
      />,
    );
  }
  return installed;
}
