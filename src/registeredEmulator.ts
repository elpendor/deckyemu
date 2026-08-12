import { type CustomEmulator } from "./backend";

/**
 * How a registered emulator describes itself in the list.
 *
 * The registered list and the catalog list above it overlap: installing an
 * emulator from the catalog registers it, so it appears in both. The rows were
 * identical in every visible way -- same name, same system, same file
 * extensions -- which made the second list look like a duplicate of the first
 * rather than a different question about the same emulator.
 *
 * So a registered row says what is true of the *registration* and nothing the
 * catalog already said. Where it came from is the useful half of that: it is
 * the fact that explains why some of these also appear above.
 *
 * File extensions are deliberately not here. They are in the catalog row, where
 * they help decide whether to install something, and in the editor, where they
 * can be changed. Repeating them in a third place was the redundancy that
 * started this, and showing them on hand-added rows only would have left the
 * list with two row shapes, which reads as a bug rather than a distinction.
 */

/**
 * What system this emulator runs, for display.
 *
 * `databases` is empty for the systems libretro has no entry for -- Switch,
 * Wii U, PS3 -- and those store their label directly instead. Reading only
 * `databases` reported "No system set" for a Switch emulator with Nintendo
 * Switch selected, which reads like the setting failed to save.
 */
export function systemLabel(emulator: CustomEmulator): string {
  return (
    emulator.databases[0] ||
    emulator.platform_full ||
    emulator.platform ||
    "No system set"
  );
}

/** Where a registered emulator's definition came from. */
export function originLabel(emulator: CustomEmulator): string {
  return emulator.from_catalog ? "from the catalog" : "added by hand";
}

/** The description under a registered emulator's name. */
export function registeredDescription(emulator: CustomEmulator): string {
  return `${systemLabel(emulator)} · ${originLabel(emulator)}`;
}
