import { afterEach, describe, expect, it, vi } from "vitest";

type Page = { __deckyemu?: any; __deckyemuHost?: (payload: string) => void };
const page = globalThis as unknown as Page;

afterEach(() => {
  delete page.__deckyemu;
  delete page.__deckyemuHost;
});

describe("channel across an update", () => {
  it("answers a call the replaced bundle made", async () => {
    const sent: { id: number }[] = [];
    page.__deckyemuHost = (payload) => sent.push(JSON.parse(payload));
    vi.stubGlobal("window", globalThis);

    vi.resetModules();
    const before = await import("./channel");
    before.connect();
    const answer = before.call("get_settings");

    vi.resetModules();
    const after = await import("./channel");
    after.connect();
    const fresh = after.call("get_settings");

    expect(sent[1].id).not.toBe(sent[0].id);
    page.__deckyemu.reply(sent[0].id, true, "old");
    page.__deckyemu.reply(sent[1].id, true, "new");
    await expect(answer).resolves.toBe("old");
    await expect(fresh).resolves.toBe("new");
  });
});
