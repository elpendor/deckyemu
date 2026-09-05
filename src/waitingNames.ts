/**
 * The emulators waiting to be copied, read as a sentence rather than a list.
 *
 * Shared because two screens say it -- the Quick Access panel when a copy is
 * not coming back for them, and the Library tab whenever anything is waiting --
 * and the same fact worded two ways reads as two different facts.
 *
 * "RetroArch", "RetroArch and Dolphin", "RetroArch, Dolphin and 2 others".
 */
export function namesOf(waiting: { name: string }[]) {
  const names = waiting.map((one) => one.name);
  if (names.length <= 2) return names.join(" and ");
  if (names.length === 3) return `${names[0]}, ${names[1]} and ${names[2]}`;
  return `${names[0]}, ${names[1]} and ${names.length - 2} others`;
}
