import { ConfirmModal } from "@decky/ui";

import { openModal } from "./modalStack";

/**
 * Ask before installing a BIOS the checksum list does not recognise.
 *
 * Not a refusal: the list is not complete -- open replacement BIOS files,
 * patched fast-boot ones and uncatalogued revisions are all legitimate and all
 * missing from it. But a bad dump installs and then fails inside the game, so
 * the press that installs one should be a decision rather than a reflex.
 * Resolves true to install.
 */
export function confirmUnknownDump(names: string[], requirement: string): Promise<boolean> {
  return new Promise((resolve) =>
    openModal(
      <ConfirmModal
        strTitle="Install an unrecognised file?"
        strDescription={`${names.join(", ")} is not a known dump of ${requirement}, so it may be damaged or altered and the game may not work. Install it anyway?`}
        strOKButtonText="Install anyway"
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    ),
  );
}
