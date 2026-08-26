/**
 * Keeping Steam from handing a game a layout that cannot play it.
 *
 * Steam Input does not key a non-Steam shortcut's layout to its appid. It keys
 * it to the shortcut's **name**, lowercased: every shortcut this plugin makes
 * reports a selected config whose URL is `default://cool spot`,
 * `default://comix zone`, and so on. Measured on the Deck, and the consequences
 * are the whole reason this file exists:
 *
 * - The key outlives the shortcut. Delete a game and add it again and it lands
 *   on the same layout, because the name is the same.
 * - The key is shared with whatever else has carried that name, including the
 *   retail game on Steam. Asking Steam for the layouts available to a shortcut
 *   called "Sonic The Hedgehog" returns the *Workshop* configs published for
 *   SEGA's Steam release, and a shortcut called "Comix Zone" is offered
 *   "CC's Comix Zone Config". The shortcut inherits the retail title's Steam
 *   Input identity, and with it whatever default that identity carries.
 * - When that inherited default is a browser layout -- it happened to
 *   "Sonic The Hedgehog" and "Sonic The Hedgehog 3", both arriving as a config
 *   owned by an account that was not the user's -- the game opens with the
 *   sticks driving a mouse cursor and no face buttons. Nothing local set it;
 *   there was no entry for either name in `configset_controller_neptune.vdf`.
 *
 * This is not something the plugin can avoid by naming games differently: clean
 * canonical titles are the point of the name cleanup, and a title that matches
 * the retail release is the *good* outcome everywhere else -- boxart, the
 * release-era check, the collection label. What the plugin can do is what
 * EmuDeck and RetroDECK already do for their own shortcuts, which is why the
 * user's `configset_controller_neptune.vdf` is full of their templates: state a
 * layout explicitly instead of leaving Steam to guess. An explicit selection is
 * written under the name key and wins from then on.
 *
 * The repair is deliberately narrow. It fires only when Steam is still on a
 * *default* it chose itself and that default cannot drive a gamepad, so it
 * never overwrites a layout somebody picked, and it never argues with a default
 * that was already right -- which it is for almost every game.
 */
import { controllerConfiguratorStore, controllerStore, sleep, steamClient } from "./client";

/**
 * What Steam picks for a Deck gamepad game when it gets it right.
 *
 * Not an opinion: the sixteen shortcuts that were *not* broken all resolved to
 * this template's contents through their `default://` key -- Steam titles it
 * "Gamepad With Joystick Trackpad". Pinning it therefore changes nothing except
 * in the case being repaired.
 */
export const GAMEPAD_TEMPLATE = "template://controller_neptune_gamepad_fps.vdf";

/** The type string Steam gives the Deck's own controller. */
const NEPTUNE = "controller_steamcontroller_neptune";

/** The parts of Steam's controller config info this file reads. */
export interface ControllerConfigInfo {
  Title?: string;
  URL?: string;
  bUsesGamepad?: boolean;
}

/**
 * Whether Steam has left this app on a guessed layout that cannot play a game.
 *
 * Both halves matter. `default://` means Steam chose this itself and no
 * selection was ever made for the name -- anything a person picked reads back
 * as `template://` or `workshop://`, and must be left alone. `bUsesGamepad`
 * false is the actual complaint: a browser or mouse layout on a game that can
 * only be played with a pad.
 */
export function needsGamepadLayout(config: ControllerConfigInfo | null | undefined): boolean {
  if (!config || typeof config.URL !== "string") return false;
  return config.URL.startsWith("default://") && config.bUsesGamepad === false;
}

/**
 * Whether a layout the *emulator* asked for may replace what Steam chose.
 *
 * Looser than `needsGamepadLayout` on purpose. That one repairs a layout which
 * cannot play a game at all; this one applies a layout a game needs for a
 * reason invisible from the outside -- Vita3K's is that the Deck powers its gyro
 * down unless the running game's layout binds it, so an ordinary, perfectly
 * playable gamepad layout still means a sensor that never moves.
 *
 * The `default://` test is the same and carries the same promise: anything a
 * person picked reads back as `template://` or `workshop://`, and is theirs.
 */
export function mayPinEmulatorLayout(config: ControllerConfigInfo | null | undefined): boolean {
  if (!config || typeof config.URL !== "string") return false;
  // Steam's own guess, or the layout *this plugin* pinned. The second is the
  // one worth spelling out: `GAMEPAD_TEMPLATE` binds no gyro, and a game added
  // before an emulator declared a layout is sitting on it -- treating our own
  // pin as somebody's choice would leave motion broken on every game already
  // added, with no way to notice short of playing one.
  return config.URL.startsWith("default://") || config.URL === GAMEPAD_TEMPLATE;
}

/**
 * The Deck's built-in controller, or null when it is not there.
 *
 * Found by type rather than by index or position: the index is assigned by
 * Steam and is not 0 -- it was 15 on the device this was written against, which
 * is why every call that passed 0 came back empty. Only the Deck's own
 * controller is handled, because it is the only one Game Mode guarantees and
 * because each controller type takes templates of its own; leaving an attached
 * pad to Steam's default is exactly the behaviour there was before this file.
 */
function deckControllerIndex(): number | null {
  const store = controllerStore();
  try {
    const controllers = store?.GetControllers?.() ?? [];
    for (const controller of controllers) {
      if (store?.GetControllerTypeString?.(controller?.eControllerType) === NEPTUNE) {
        return controller.nControllerIndex ?? null;
      }
    }
  } catch (error) {
    console.error("[deckyemu] could not read the controller list", error);
  }
  return null;
}

async function selectedConfig(
  appId: number,
  controllerIndex: number,
): Promise<ControllerConfigInfo | null> {
  try {
    const input = steamClient()?.Input;
    return (await input?.GetConfigForAppAndController?.(appId, controllerIndex)) ?? null;
  } catch (error) {
    console.error("[deckyemu] could not read the layout for", appId, error);
    return null;
  }
}

/**
 * Give `appId` a gamepad layout if Steam has guessed one that cannot play it.
 *
 * The wait is load-bearing. Steam keys the layout on whatever identifies the
 * shortcut *at the moment it is asked*, and a shortcut is created before its
 * name is applied: read immediately after `AddShortcut` and the key is derived
 * from the executable (`default://deckyemu-probesh`), which collides with
 * nothing and always looks healthy. The name key replaced it within half a
 * second in every measurement. So this polls until the answer changes, and only
 * then judges it -- a fixed sleep would be either too short to be right or too
 * long to be free.
 *
 * Returns whether it changed anything. A failure is untidy rather than broken:
 * the game still launches, its layout is just whatever Steam decided, which is
 * the situation this exists to improve rather than to depend on.
 */
export async function pinGamepadLayout(
  appId: number,
  attempts = 8,
  template = "",
  settled = false,
): Promise<boolean> {
  const controllerIndex = deckControllerIndex();
  if (controllerIndex === null) return false;

  // An emulator that names a layout needs it applied over any layout Steam
  // guessed, not only over one that cannot play a game.
  const wanted = template || GAMEPAD_TEMPLATE;
  const ready = template ? mayPinEmulatorLayout : needsGamepadLayout;

  const first = await selectedConfig(appId, controllerIndex);
  let current = first;

  // `settled` is a game that already exists rather than one being added, so
  // there is no name key on its way: the reading below is the answer. Waiting
  // for it to *change* -- which is right for a new shortcut -- would time out
  // on every game and repair none of them, which is exactly what it did.
  for (let attempt = 0; !settled && attempt < attempts; attempt += 1) {
    // A named template matches the executable-keyed reading too -- every fresh
    // shortcut is on a `default://` key until Steam notices the name -- so it
    // has to wait for that key to land rather than judge the first answer.
    if (template ? attempt > 0 && current?.URL !== first?.URL : ready(current)) break;
    // The key has settled and is not the problem this repairs.
    if (!template && attempt > 0 && current?.URL !== first?.URL) return false;
    await sleep(250);
    current = await selectedConfig(appId, controllerIndex);
  }

  // A name key that never landed is not one to write against: it collides with
  // nothing, so the layout would be filed under a key no launch ever reads.
  if (template && !settled && current?.URL === first?.URL) return false;
  if (!ready(current)) return false;

  try {
    // Through the configurator store rather than `SteamClient.Input` directly:
    // it works out the "only controller of this type" argument Steam wants,
    // which is what its own settings page does on the way to the same call.
    controllerConfiguratorStore()?.SetActiveConfigForApp?.(
      appId,
      controllerIndex,
      wanted,
      false,
    );
    console.log(
      `[deckyemu] replaced Steam's "${current?.Title}" default for ${appId} with a gamepad layout`,
    );
    return true;
  } catch (error) {
    console.error("[deckyemu] could not set the layout for", appId, error);
    return false;
  }
}
