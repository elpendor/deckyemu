import { MenuItem, showModal } from "@decky/ui";

import { addedGame, refreshAddedGames } from "./addedGames";
import { GameEditorModal } from "./GameEditorModal";
import { MENU_ITEM_KEY } from "./steam/contextMenu";

/**
 * "Edit in DeckyEmu" for the game context menu, or nothing for other games.
 *
 * The scoping lives here rather than in the patch, and that is the whole point
 * of the split: the patch stays one dumb thing that always does the same, and
 * the only judgement about *our* games sits in one component. A registry that
 * cannot answer produces no item, which is also what a games-we-do-not-know
 * answer produces -- so a failed lookup degrades to the menu Steam would have
 * shown anyway.
 *
 * Absent rather than present-and-refusing, because almost every game in a
 * library is not ours. An item that appears on all of them and says "not a
 * DeckyEmu game" for nearly all of them is noise in a menu the user opens for
 * other reasons.
 */
export function editGameMenuItem(appId: number): unknown | null {
  const game = addedGame(appId);
  if (!game) return null;

  return (
    <MenuItem
      key={MENU_ITEM_KEY}
      onSelected={() => {
        showModal(
          <GameEditorModal
            game={game}
            // Nothing on this screen is showing the library list, so there is
            // no caller to tell. The cache is refreshed instead, so a rename
            // here is what the next menu and the next panel both read.
            onSaved={() => void refreshAddedGames()}
          />,
        );
      }}
    >
      Edit in DeckyEmu
    </MenuItem>
  );
}
