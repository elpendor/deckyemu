/**
 * The order emulators are listed in, everywhere they are listed.
 *
 * Three panels show overlapping sets of the same things — the catalog, the
 * firmware they need, and the ones registered by hand — and each took whatever
 * order its data arrived in. The catalog's is the order entries were written
 * into the file, which is nobody's idea of an order; the registered list's is
 * the order they were added. So the same emulators appeared in three different
 * sequences, and finding one meant reading every row.
 *
 * Sorted by name, in the display layer rather than the backend, deliberately:
 * the order emulators are matched in decides which one is suggested for a file
 * type two of them can open, and that is not a question about presentation.
 */
export const byName = <T extends { name: string }>(a: T, b: T) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
