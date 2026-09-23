import { describe, expect, it } from "vitest";

import type { UploadInFlight } from "./backend";
import { summariseUploads } from "./arriving";

function upload(received: number, total: number, id = received): UploadInFlight {
  return { id, name: `f${id}`, received, total, cancelled: false };
}

describe("summariseUploads", () => {
  it("adds the bytes rather than averaging the fractions", () => {
    // A 4 GB ROM barely started beside a finished 2 MB BIOS. By fraction that
    // is halfway; by bytes it has not begun, and bytes is what is being waited
    // on.
    const summary = summariseUploads([upload(0, 4_000_000_000), upload(2_000_000, 2_000_000)]);
    expect(summary.files).toBe(2);
    expect(summary.received).toBe(2_000_000);
    expect(summary.total).toBe(4_002_000_000);
    expect(Math.round(summary.fraction * 100)).toBe(0);
  });

  it("is zero when nothing declared a size", () => {
    // Dividing by zero renders as a full bar, which reads as finished.
    expect(summariseUploads([upload(0, 0)]).fraction).toBe(0);
  });

  it("never reports more than finished", () => {
    // A sender that under-declared its length. The bar has nowhere above full
    // to go, and a number over 100% reads as a fault in the plugin.
    expect(summariseUploads([upload(120, 100)]).fraction).toBe(1);
  });

  it("is empty for nothing in flight, which is what hides the line", () => {
    expect(summariseUploads([])).toEqual({
      files: 0,
      received: 0,
      total: 0,
      fraction: 0,
    });
  });
});
