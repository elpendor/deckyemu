import { describe, expect, it } from "vitest";

import { plural } from "./plural";

describe("plural", () => {
  it("matches the noun to the count", () => {
    expect(plural(1, "file")).toBe("1 file");
    expect(plural(0, "file")).toBe("0 files");
    expect(plural(3, "artwork image")).toBe("3 artwork images");
  });
});
