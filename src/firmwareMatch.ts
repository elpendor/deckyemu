import type { FirmwareReport } from "./backend";

/**
 * Which requirement a sent file actually satisfies.
 *
 * The transfer dialog used to be told one requirement when it opened -- the row
 * whose Send button was pressed -- and then offered that same one against every
 * file that arrived. It is the right answer only for the first file, and only
 * when nothing else was sent alongside.
 *
 * What that cost: xemu wants three different dumps, so sending two and pressing
 * Install on the second ran the *first* one's requirement again, which matches
 * by size and therefore found nothing -- "Nothing in the firmware folder looks
 * like MCPX boot ROM yet", against a file that was never an MCPX boot ROM. The
 * fix from the user's side was to close the dialog and go to the settings page,
 * where the rows do know what they are.
 *
 * The report already carries the answer: each requirement lists the files
 * waiting for it, which is the backend's own matching -- by name, and by size
 * where a name cannot tell an MCPX ROM from a BIOS. So this reads the answer
 * rather than working it out a second time and getting it subtly different.
 */
export interface RequirementMatch {
  entryId: string;
  emulatorName: string;
  requirement: string;
  /** Installing means opening the emulator's own window, not copying a file. */
  guiInstall: boolean;
  /** What the user will be asked once that window is open. */
  prompt: string;
}

/**
 * The requirement waiting for `name`, or undefined when nothing is.
 *
 * First match wins where two emulators want the same dump -- a PS1 BIOS serves
 * DuckStation and a libretro core alike. Either is a correct place to put it,
 * and offering a choice between two identical outcomes is worse than picking
 * one; the settings page still lists both rows for anyone who wants the other.
 */
export function requirementForFile(
  report: FirmwareReport | null,
  name: string,
): RequirementMatch | undefined {
  for (const emulator of report?.emulators ?? []) {
    for (const requirement of emulator.requirements) {
      if (requirement.waiting.includes(name)) {
        return {
          entryId: emulator.id,
          emulatorName: emulator.name,
          requirement: requirement.name,
          guiInstall: Boolean(requirement.gui_install),
          prompt: requirement.prompt ?? "",
        };
      }
    }
  }
  return undefined;
}
