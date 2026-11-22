import { ButtonItem, PanelSectionRow } from "./steamui";

import { PackagedGamesModal } from "./PackagedGamesModal";
import { VitaGamesModal } from "./VitaGamesModal";
import { openModal } from "./modalStack";

/**
 * The way to games RPCS3, shadPS4 and Vita3K have installed but that are not in
 * the library: a package unpacked earlier, or a Vita game installed in Vita3K's
 * own interface. Each list leads to the review, like any other way in.
 */

interface EntryProps {
  ps3Count: number;
  ps4Count: number;
  vitaCount: number;
  disabled: boolean;
  onGameAdded: () => void;
}

/**
 * The way back to games these emulators already have installed.
 *
 * A PS3 or PS4 game is the one thing with no ROM to point the picker at: the
 * `.pkg` was consumed installing it, and what boots lives inside a hidden
 * directory under a product code. Without these rows, a game removed from the
 * library and kept on disk could only be added back by typing that path.
 *
 * Counted rather than listed, and counted after subtracting what is already in
 * the library, so the number on the button matches the number of rows behind
 * it. Advertising "(2)" and opening an empty list is worse than no button.
 */
export function PackagedGameEntries({
  ps3Count,
  ps4Count,
  vitaCount,
  disabled,
  onGameAdded,
}: EntryProps) {
  return (
    <>
      {ps3Count > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<PackagedGamesModal system="ps3" />)}
            disabled={disabled}
            description="Games RPCS3 has already installed. They have no ROM file to browse to, so this is the way back to them."
          >
            {`PlayStation 3 games in RPCS3 (${ps3Count})`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {ps4Count > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<PackagedGamesModal system="ps4" />)}
            disabled={disabled}
            description="Games shadPS4 has already installed. They have no ROM file to browse to, so this is the way back to them."
          >
            {`PlayStation 4 games in shadPS4 (${ps4Count})`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {/* Vita3K installs and decrypts its own games, so unlike every other
          system here there is no file to pick — the installed list is the only
          door in. */}
      {vitaCount > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<VitaGamesModal onAdded={onGameAdded} />)}
            disabled={disabled}
            description="Games Vita3K has installed. It decrypts them as it installs, so they are added from here rather than by choosing a file."
          >
            {`PlayStation Vita games in Vita3K (${vitaCount})`}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}
