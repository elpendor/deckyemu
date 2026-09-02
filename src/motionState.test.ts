import { describe, expect, it } from "vitest";

import { motion } from "./motionState";
import type { CatalogEmulator } from "./backend/firmware";

/**
 * The line on the Emulators tab that says whether gyro is actually available.
 *
 * It exists because nothing said anything: the server is fetched quietly, and a
 * Deck where GitHub had rate-limited the download looked exactly like one where
 * motion was simply not a feature. The only way to tell them apart was reading a
 * plugin log over SSH, which is not a thing to ask of anybody.
 */
const base = (over: Partial<CatalogEmulator> = {}) =>
  ({
    id: "ryujinx",
    present: true,
    motion: { declared: true, ready: true, configured: true, waiting: 0 },
    ...over,
  }) as CatalogEmulator;

describe("the motion server's state, in words", () => {
  it("says so when it is there -- silence cannot answer 'is it installed?'", () => {
    expect(motion(base())).toBe("motion ready");
  });

  it("says so when it is not", () => {
    expect(motion(base({ motion: { declared: true, ready: false, configured: true, waiting: 0 } }))).toBe(
      "motion server not downloaded yet",
    );
  });

  it("reads a wait as a wait, not a failure: a rate limit clears itself", () => {
    expect(motion(base({ motion: { declared: true, ready: false, configured: true, waiting: 61 } }))).toBe(
      "motion server retrying in 2 min",
    );
  });

  it("says nothing for the emulators that have no motion server, which is most", () => {
    expect(motion(base({ motion: { declared: false, ready: false, configured: true, waiting: 0 } }))).toBe("");
  });

  it("and nothing before the emulator is installed -- that step is not reached yet", () => {
    expect(motion(base({ present: false }))).toBe("");
  });
});

describe("when the emulator owns its own controller config", () => {
  it("does not claim ready -- the binary is here and nothing is using it", () => {
    const line = motion(
      base({ motion: { declared: true, ready: true, configured: false, waiting: 0 } }),
    );
    expect(line).toContain("not using it");
    expect(line).not.toBe("motion ready");
  });

  it("and says ready when both halves are true", () => {
    expect(
      motion(base({ motion: { declared: true, ready: true, configured: true, waiting: 0 } })),
    ).toBe("motion ready");
  });
});
