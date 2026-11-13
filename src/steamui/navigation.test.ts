import { describe, expect, it, vi } from "vitest";

// Steam's showModal, as found on the Deck: async, resolving to the handle.
const real = { Close: vi.fn(), Update: vi.fn() };
vi.mock("./webpack", () => ({
  findModule: () => ({}),
  findExport: () => async () => real,
}));
vi.mock("./components", () => ({ registerLookup: () => undefined }));
// Steam's own React at runtime; nothing here renders.
vi.mock("react", () => ({ useEffect: () => undefined, useState: () => [] }));

(globalThis as unknown as { window: unknown }).window = {
  SteamUIStore: { WindowStore: { GamepadUIMainWindowInstance: { BrowserWindow: {} } } },
};

const { showModal } = await import("./navigation");

describe("showModal over Steam's async one", () => {
  it("hands back a handle at once, and a Close before Steam answers still closes", async () => {
    const handle = showModal("dialog");
    handle.Close();
    expect(real.Close).not.toHaveBeenCalled();
    await new Promise((settle) => setTimeout(settle, 0));
    expect(real.Close).toHaveBeenCalledTimes(1);
  });

  it("closes straight through once Steam has answered", async () => {
    real.Close.mockClear();
    const handle = showModal("dialog");
    await new Promise((settle) => setTimeout(settle, 0));
    handle.Close();
    expect(real.Close).toHaveBeenCalledTimes(1);
  });
});
