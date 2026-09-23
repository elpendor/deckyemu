import type { UploadInFlight } from "./backend";

/** Everything arriving, added up, for the line that stands in for the rows. */
export interface Arriving {
  files: number;
  received: number;
  total: number;
  /** 0 when nothing declared a size, so the bar sits at zero, not full. */
  fraction: number;
}

/**
 * The transfers in flight as one number each.
 *
 * Two lines per file was already the compact version and is still about 70px,
 * so three files arriving put 210px of bars above the received list — at the
 * moment the list is what the dialog is for. What a glance wants is whether it
 * is moving and how far, which is this; cancelling one of several is what
 * **Details** is for.
 *
 * Bytes rather than an average of the per-file fractions. A 4 GB ROM beside a
 * 2 MB BIOS is 50% by fraction and barely started by bytes, and the number
 * people are waiting on is the second one.
 */
export function summariseUploads(uploads: UploadInFlight[]): Arriving {
  let received = 0;
  let total = 0;
  for (const upload of uploads) {
    received += upload.received;
    total += upload.total;
  }
  return {
    files: uploads.length,
    received,
    total,
    // A sender that declared nothing leaves `total` at zero, and dividing by it
    // would put the bar at NaN — which renders as full.
    fraction: total > 0 ? Math.min(1, received / total) : 0,
  };
}
