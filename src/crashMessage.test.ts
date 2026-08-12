import { describe, expect, it } from "vitest";

import { crashMessage } from "./crashMessage";

describe("crashMessage", () => {
  it("uses the error's own message", () => {
    expect(crashMessage(new Error("collectionStore is undefined"))).toBe(
      "collectionStore is undefined",
    );
  });

  it("reads a thrown string", () => {
    expect(crashMessage("no core for this ROM")).toBe("no core for this ROM");
  });

  /*
   * The invariant the boundary depends on. `message` doubles as the flag saying
   * the fallback is showing, so an empty one renders the children that just
   * threw -- which throws again, and again. A render loop in the Quick Access
   * panel is worse than the crash it was meant to contain.
   */
  it("is never empty, whatever was thrown", () => {
    const thrown: unknown[] = [
      new Error(""),
      new Error("   "),
      new TypeError(),
      "",
      "   ",
      null,
      undefined,
      0,
      false,
      {},
      [],
      Symbol("nope"),
      NaN,
    ];
    for (const value of thrown) {
      const message = crashMessage(value);
      expect(message.length, `empty message for ${String(value)}`).toBeGreaterThan(0);
      expect(message.trim()).toBe(message);
    }
  });

  it("keeps falsy primitives that still say something", () => {
    // 0 and false are values a caller can act on; dropping them for being
    // falsy would report "no description" about something that had one.
    expect(crashMessage(0)).toBe("0");
    expect(crashMessage(false)).toBe("false");
  });

  it("does not hand back [object Object]", () => {
    // Steam rejections arrive as plain objects. "[object Object]" on screen is
    // noise where "no description" at least tells the user to read the log.
    expect(crashMessage({ code: 5 })).not.toContain("[object");
  });
});
