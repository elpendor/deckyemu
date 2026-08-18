import { MenuGroup, MenuItem, showModal } from "@decky/ui";

import { addedGame, refreshAddedGames } from "./addedGames";
import { GameEditorModal } from "./GameEditorModal";
import { RemoveGameModal } from "./RemoveGameModal";
import { MENU_ITEM_KEY } from "./steam/contextMenu";

/**
 * The "DeckyEmu" submenu in a game's context menu, or nothing for other games.
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
 *
 * A group rather than one item per action, for the same reason: two of our rows
 * in somebody's game menu is twice the space taken by a plugin they opened the
 * menu for other reasons. One row that opens into ours costs what the old
 * single "Edit in DeckyEmu" cost.
 */
export function editGameMenuItem(appId: number): unknown | null {
  const game = addedGame(appId);
  if (!game) return null;

  // Nothing on this screen is showing the library list, so there is no caller
  // to tell. The cache is refreshed instead, so a rename or a removal here is
  // what the next menu and the next panel both read -- and a removed game stops
  // producing this submenu at all, because that is the same lookup.
  const edit = () =>
    showModal(<GameEditorModal game={game} onSaved={() => void refreshAddedGames()} />);
  const remove = () =>
    showModal(<RemoveGameModal game={game} onRemoved={() => void refreshAddedGames()} />);

  /*
   * `MenuGroup` is found by matching minified Steam source, the same way
   * everything else in this corner is, so it can come back undefined on a
   * client that renamed something -- and rendering `undefined` as a component
   * throws inside Steam's own render, which §5 says costs the whole screen.
   *
   * So the group is used only when it is really there, and the fallback is the
   * single item this used to be: Edit alone, with removal still on the panel's
   * game list where it has always been. One action lost beats a black screen.
   */
  if (typeof MenuGroup !== "function") {
    return (
      <MenuItem key={MENU_ITEM_KEY} onSelected={edit}>
        Edit in DeckyEmu
      </MenuItem>
    );
  }

  return (
    <MenuGroup key={MENU_ITEM_KEY} label="DeckyEmu">
      <MenuItem onSelected={edit}>Edit</MenuItem>
      {/* Steam's own styling for a destructive row, which is what this is: it
          deletes the shortcut, the launcher and the game's files. What that
          means in full is the removal dialog's job to say, and it says it. */}
      <MenuItem tone="destructive" onSelected={remove}>
        Remove
      </MenuItem>
    </MenuGroup>
  );
}
