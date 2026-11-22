import { findExport, findModule, once } from "./webpack";

/** The navigation sounds our controls play, by Steam's own names. */
export type NavSound =
  | "ChangeTabs"
  | "DefaultOk"
  | "FailedNav"
  | "PagedNavigation"
  | "ToggleOff"
  | "ToggleOn";

type Dispatcher = { PlayNavSound: (sound: number, now?: boolean) => void };

/**
 * Steam's sound dispatcher and its enum of sound names, from the one module
 * holding both. Through it Steam's volume, its UI-sounds switch and its rule
 * that the more specific of two sounds wins all apply.
 */
const sounds = once(() => {
  const module = findModule("navSounds", ['"ChangeTabs"', "RegisterCallbackOnPlaySound"]);
  const names = findExport<Record<string, number>>("navSoundNames", module,
    (value) => typeof (value as Record<string, unknown>)?.ChangeTabs === "number");
  const dispatcher = findExport<Dispatcher>("navSoundPlayer", module,
    (value) => typeof (value as Dispatcher)?.PlayNavSound === "function");
  return names && dispatcher ? { names, dispatcher } : null;
});

/** Play one of Steam's navigation sounds; silent if Steam moved them. */
export function playNavSound(name: NavSound): void {
  try {
    const found = sounds();
    const id = found?.names[name];
    if (typeof id === "number") found!.dispatcher.PlayNavSound(id);
  } catch (error) {
    console.error("[deckyemu] could not play a sound", error);
  }
}
