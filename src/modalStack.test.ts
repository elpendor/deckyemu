import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Knowing which modals this plugin has open, so they can be closed together.
 *
 * Steam has no close-all, and `showModal` hands back a `Close` that nothing was
 * keeping — so the plugin could open a modal and then have no way to dismiss it
 * from anywhere else. That is not tidiness: Steam re-reveals each modal as the
 * one above it dismisses, so one left on the stack lands on top of whatever
 * comes next. Taking a received file into the add flow closed the transfer
 * dialog and opened the Quick Access panel, and the added-games list underneath
 * was revealed straight over it — the panel appeared with the game ready and
 * vanished a second later.
 *
 * The two things worth checking are the two ways the set goes wrong: a handle
 * left in it after its modal closed on its own, and a handle missing from it
 * because a call site did not register. The first is what `fnOnClose` is for;
 * the second is why every `showModal` in the plugin goes through here.
 */

const closes: string[] = [];
let nextId = 0;

const showModal = vi.fn((_modal: unknown, _parent: unknown, props: any) => {
  const id = `modal-${(nextId += 1)}`;
  return {
    id,
    Close: () => {
      closes.push(id);
      // Steam calls this when a modal goes, however it went.
      props?.fnOnClose?.();
    },
    Update: vi.fn(),
  };
});

vi.mock("@decky/ui", () => ({ showModal: (...args: unknown[]) => (showModal as any)(...args) }));

const { openModal, closeOpenModals, closeModalsOnPanelOpen, openModalCount } =
  await import("./modalStack");

beforeEach(() => {
  closeOpenModals();
  closes.length = 0;
  showModal.mockClear();
});

describe("openModal", () => {
  it("shows the modal and hands back Steam's own handle", () => {
    const handle = openModal(null);
    expect(showModal).toHaveBeenCalledTimes(1);
    expect(typeof handle.Close).toBe("function");
  });

  it("keeps decky's own defaults, which passing props would otherwise replace", () => {
    openModal(null);
    const props = showModal.mock.calls[0][2];
    expect(props.strTitle).toBe("Decky Dialog");
    expect(props.bHideMainWindowForPopouts).toBe(false);
  });

  it("counts what is open", () => {
    openModal(null);
    openModal(null);
    expect(openModalCount()).toBe(2);
  });

  it("forgets a modal that closed on its own", () => {
    // The B button, its own Close button, a dialog dismissing itself. Without
    // this the set fills with handles for modals that went long ago, and
    // closeOpenModals spends its time calling Close on nothing.
    const handle = openModal(null);
    handle.Close();
    expect(openModalCount()).toBe(0);
  });
});

describe("closeOpenModals", () => {
  it("closes everything the plugin has open", () => {
    // The case that was broken: the transfer dialog closes itself, and the
    // added-games list underneath has to go too or it is revealed over the
    // panel being opened.
    openModal(null);
    openModal(null);
    closeOpenModals();
    expect(closes).toHaveLength(2);
    expect(openModalCount()).toBe(0);
  });

  it("is fine with nothing open", () => {
    expect(() => closeOpenModals()).not.toThrow();
    expect(closes).toEqual([]);
  });

  it("does not close a modal twice", () => {
    // Closing one can close others -- a parent dismissing takes its children --
    // so the set is emptied as it goes rather than after.
    const handle = openModal(null);
    openModal(null);
    handle.Close();
    closes.length = 0;
    closeOpenModals();
    expect(closes).toHaveLength(1);
  });

  it("carries on when one refuses to close", () => {
    // A handle whose modal has already gone is the ordinary case during a
    // cascade, and it is not a reason to leave the rest standing.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const bad = openModal(null);
    bad.Close = () => {
      throw new Error("gone");
    };
    openModal(null);
    closeOpenModals();
    expect(closes).toHaveLength(1);
    expect(openModalCount()).toBe(0);
  });
});

describe("closeModalsOnPanelOpen", () => {
  it("clears the stack when the panel becomes visible", () => {
    // The reported fault: the added-games list left open, Quick Access opened,
    // a ROM picked -- and as the file browser dismissed, the list came back
    // over the panel and took the overlay, so the panel would not open again.
    openModal(null);
    openModal(null);
    closeModalsOnPanelOpen(true);
    expect(closes).toHaveLength(2);
    expect(openModalCount()).toBe(0);
  });

  // The guard, and the reason it exists. Opening one of our modals is what
  // hides the panel, so closing on the way down would dismiss the modal the
  // user just asked for about a frame after it appeared.
  it("leaves them alone when the panel is hiding", () => {
    openModal(null);
    closeModalsOnPanelOpen(false);
    expect(closes).toEqual([]);
    expect(openModalCount()).toBe(1);
  });

  it("is fine with nothing open", () => {
    expect(() => closeModalsOnPanelOpen(true)).not.toThrow();
    expect(closes).toEqual([]);
  });
});

describe("every modal in the plugin goes through here", () => {
  it("has no showModal call left outside this module", async () => {
    // A registry that some call sites use is worse than none: it reads as a
    // guarantee that everything can be closed, and one stray `showModal` makes
    // that false in exactly the way that is hard to notice -- a modal nobody
    // can dismiss, revealed over whatever comes next. Cheaper to check than to
    // remember, and the failure names the file.
    const { readdirSync, readFileSync } = await import("node:fs");
    const stray = readdirSync("src")
      .filter((name) => /\.tsx?$/.test(name) && !name.includes(".test.")
        && name !== "modalStack.ts")
      .filter((name) => /\bshowModal\s*\(/.test(readFileSync(`src/${name}`, "utf-8")));
    expect(stray).toEqual([]);
  });
});
