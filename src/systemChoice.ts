import type { CustomEmulator, SystemOption } from "./backend";

/**
 * Which system an emulator record is showing, and what to save for it.
 *
 * Both halves used to be inline in the editor and both were wrong for the same
 * emulator. `list_systems` drops the synthetic `~short` row for a system
 * libretro turns out to know as well, so the two are not offered twice — and
 * the Vita is exactly that. A record saying `platform: "Vita"` looks for a row
 * with id `~Vita`, finds none, and the picker shows "None" for an emulator
 * whose system is set. Pressing Save then wrote that "None" back, so opening
 * Vita3K's editor and saving anything cleared its system.
 */

/** The id to select for `emulator`, before the system list has been consulted. */
export function initialSystemId(emulator?: CustomEmulator | null): string {
  return (
    emulator?.databases?.[0]
    || (emulator?.platform ? `~${emulator.platform}` : "")
  );
}

/**
 * The row this record means, when its own id matches nothing.
 *
 * Matched on the label rather than the id, which finds the libretro row that
 * survived the de-duplication — the one with artwork behind it. Empty when
 * there is nothing better to offer, which leaves the selection alone rather
 * than guessing.
 */
export function adoptedSystemId(
  systems: SystemOption[] | null,
  systemId: string,
  emulator?: CustomEmulator | null,
): string {
  if (!systems || !systemId) return "";
  if (systems.some((entry) => entry.id === systemId)) return "";
  const match = systems.find(
    (entry) =>
      (!!emulator?.platform && entry.short === emulator.platform)
      || (!!emulator?.platform_full && entry.full === emulator.platform_full),
  );
  return match?.id ?? "";
}

/**
 * What to send for the system fields.
 *
 * An id that resolves to no row is the one case where this form knows less than
 * the record does, and clearing the system on the way past is not an edit
 * anybody asked for — so the record's own values are sent back unchanged.
 * Choosing "None" is a decision and does clear it.
 */
export function systemFields(
  systemId: string,
  selected: SystemOption | undefined,
  emulator?: CustomEmulator | null,
): { databases: string[]; platform: string; platform_full: string } {
  if (systemId && !selected) {
    return {
      databases: emulator?.databases ?? [],
      platform: emulator?.platform ?? "",
      platform_full: emulator?.platform_full ?? "",
    };
  }
  return {
    databases: selected?.database ? [selected.database] : [],
    // Only needed when libretro has no database to derive a label from.
    platform: selected && !selected.libretro ? selected.short : "",
    platform_full: selected && !selected.libretro ? selected.full : "",
  };
}
