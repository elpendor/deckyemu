import { describe, expect, it } from "vitest";

import { toolLine } from "./toolState";
import type { HelperTool } from "./backend/firmware";

/**
 * The Tools section exists because the motion server was fetched silently: a
 * Deck where GitHub had rate-limited the download was indistinguishable from
 * one where gyro simply did not work, and the only way to tell was a log.
 */
const tool = (over: Partial<HelperTool> = {}): HelperTool =>
  ({
    name: "gyro-dsu",
    label: "Motion server",
    repo: "kmicki/SteamDeckGyroDSU",
    why: "Sends the Deck's gyro to the emulator.",
    needed_by: ["Ryujinx", "Cemu"],
    installed: true,
    path: "/home/deck/deckyemu/tools/gyro-dsu/sdgyrodsu",
    size: 183072,
    wanted: true,
    waiting: 0,
    ...over,
  }) as HelperTool;

const size = (bytes: number) => (bytes ? `${Math.round(bytes / 1024)} KB` : "");

describe("what a tool's row says", () => {
  it("says it is here -- silence cannot answer 'is it installed?'", () => {
    expect(toolLine(tool(), size)).toContain("Installed, 179 KB.");
  });

  it("names where it came from, so no binary is unattributed", () => {
    expect(toolLine(tool(), size)).toContain("From kmicki/SteamDeckGyroDSU.");
  });

  it("says when it is absent", () => {
    expect(toolLine(tool({ installed: false }), size)).toContain("Not downloaded yet.");
  });

  it("reads a rate limit as a wait, not a failure", () => {
    const line = toolLine(tool({ installed: false, waiting: 61 }), size);
    expect(line).toContain("Waiting to retry, about 2 min.");
    expect(line).not.toContain("Not downloaded yet.");
  });

  it("still says something useful when the size is unknown", () => {
    expect(toolLine(tool({ size: 0 }), size)).toContain("Installed.");
  });
});
