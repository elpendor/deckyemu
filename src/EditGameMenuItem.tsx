import { findModuleByExport, MenuGroup, MenuItem } from "@decky/ui";

import { addedGame, refreshAddedGames } from "./addedGames";
import { GameEditorModal } from "./GameEditorModal";
import { RemoveGameModal } from "./RemoveGameModal";
import { MENU_ITEM_KEY } from "./steam/contextMenu";
import { openModal } from "./modalStack";

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
    openModal(<GameEditorModal game={game} onSaved={() => void refreshAddedGames()} />);
  const remove = () =>
    openModal(<RemoveGameModal game={game} onRemoved={() => void refreshAddedGames()} />);

  /*
   * `MenuGroup` is found by matching minified Steam source, the same way
   * everything else in this corner is, so it can come back undefined on a
   * client that renamed something -- and rendering `undefined` as a component
   * throws inside Steam's own render, which costs the whole screen.
   *
   * So the group is used only when it is really there, and the fallback is the
   * single item this used to be: Edit alone, with removal still on the panel's
   * game list where it has always been. One action lost beats a black screen.
   */
  const Group = menuGroup();
  if (!Group) {
    return (
      <MenuItem key={MENU_ITEM_KEY} onSelected={edit}>
        Edit in DeckyEmu
      </MenuItem>
    );
  }

  return (
    <Group key={MENU_ITEM_KEY} label="DeckyEmu">
      <MenuItem onSelected={edit}>Edit</MenuItem>
      {/* Steam's own styling for a destructive row, which is what this is: it
          deletes the shortcut, the launcher and the game's files. What that
          means in full is the removal dialog's job to say, and it says it. */}
      <MenuItem tone="destructive" onSelected={remove}>
        Remove
      </MenuItem>
    </Group>
  );
}

/** What `menuGroup` found: `undefined` before it looks, `null` if nothing. */
let repairedGroup: unknown;

/**
 * Steam's menu group component: decky's, or found here when decky could not.
 *
 * Decky finds it by a module whose menu item renders
 * `"emphasis"==this.props.tone`. The client that arrived around 2026-09-10
 * (build 1789086785) writes the same comparison the other way round,
 * `this.props.tone=="emphasis"`, so decky's search matched nothing and every
 * game's menu fell back to one item -- the same minifier change that broke
 * decky's router hook (see `repairRoutes`). `@decky/ui` 4.12.0 still searches
 * the old way.
 *
 * Both orders are accepted here, then the same second step decky takes: the
 * function in that module carrying `bInGamepadUI:`. Checked on the device
 * before shipping -- exactly one module, exactly one such function. Looked for
 * once and remembered, because the search walks every module in Steam. A throw
 * or a miss is `null`, and the caller then draws the single item, never an
 * undefined component.
 */
function menuGroup(): typeof MenuGroup | null {
  if (typeof MenuGroup === "function") return MenuGroup;
  if (repairedGroup === undefined) {
    repairedGroup = null;
    try {
      const module = findModuleByExport((e: unknown) => {
        const candidate = e as {
          prototype?: { Focus?: unknown; OnOKButton?: unknown; render?: unknown };
        };
        const render = candidate?.prototype?.render;
        return Boolean(
          candidate?.prototype?.Focus &&
            candidate?.prototype?.OnOKButton &&
            typeof render === "function" &&
            /"emphasis"==this\.props\.tone|this\.props\.tone=="emphasis"/.test(String(render)),
        );
      }) as Record<string, unknown> | undefined;
      const found = module
        ? Object.values(module).find(
            (e) => typeof e === "function" && String(e).includes("bInGamepadUI:"),
          )
        : undefined;
      if (typeof found === "function") {
        repairedGroup = found;
        // An error rather than info: only console.error from plugin code
        // reaches cef_log.txt, and a repair that leaves no trace is one nobody
        // can confirm.
        console.error("[deckyemu] decky could not find the menu group component; found it");
      }
    } catch (error) {
      console.error("[deckyemu] could not look for the menu group component", error);
    }
  }
  return typeof repairedGroup === "function" ? (repairedGroup as typeof MenuGroup) : null;
}
