import { ButtonItem, PanelSection, PanelSectionRow, showModal } from "@decky/ui";

import { type AddedGame } from "./backend";
import { AddedGamesModal } from "./AddedGamesModal";

interface Props {
  games: AddedGame[];
  onChanged: () => void;
}

/**
 * One row for every game this plugin added, behind one button.
 *
 * This panel used to be the list itself. That is fine at four games and is the
 * whole panel at forty: adding a game, the emulator lists and the transfer
 * button all end up below something that only ever grows, on a screen reached
 * by holding a button in the middle of playing something.
 *
 * So the list lives in a modal now — see AddedGamesModal, which also groups it
 * by system — and what stays here is the count, which is the part worth seeing
 * without opening anything.
 */
export function AddedGamesPanel({ games, onChanged }: Props) {
  if (games.length === 0) {
    return null;
  }

  return (
    <PanelSection>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => showModal(<AddedGamesModal onChanged={onChanged} />)}
          description="Rename a game, change what runs it, replace its artwork, or remove it."
        >
          {`Added games (${games.length})`}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
