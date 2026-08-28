import { beforeEach, describe, expect, it, vi } from "vitest";

const Navigate = vi.fn();
const CloseSideMenus = vi.fn();

vi.mock("@decky/ui", () => ({
  Navigation: {
    Navigate: (...args: unknown[]) => Navigate(...args),
    CloseSideMenus: (...args: unknown[]) => CloseSideMenus(...args),
  },
}));

const { viewGameDetails, gameRoute } = await import("./viewGameDetails");

beforeEach(() => {
  Navigate.mockReset();
  CloseSideMenus.mockReset();
});

describe("viewGameDetails", () => {
  it("goes to the game's own page", () => {
    viewGameDetails(4242);
    expect(Navigate).toHaveBeenCalledWith("/library/app/4242");
  });

  /**
   * The ordering is the whole point, and it is not cosmetic: Steam re-reveals
   * each modal as the one above it dismisses, so a modal still standing when
   * the navigation happens comes back on top of the page it navigated to.
   */
  it("dismisses before navigating, never after", () => {
    const order: string[] = [];
    Navigate.mockImplementation(() => order.push("navigated"));
    CloseSideMenus.mockImplementation(() => order.push("closed panel"));
    viewGameDetails(7, () => order.push("dismissed"));
    expect(order).toEqual(["dismissed", "navigated", "closed panel"]);
  });

  // Called from places that have no modal to close, so the dismiss is optional
  // rather than a required no-op every caller has to invent.
  it("works with nothing to dismiss", () => {
    expect(() => viewGameDetails(9)).not.toThrow();
    expect(Navigate).toHaveBeenCalledOnce();
  });

  it("builds the route non-Steam shortcuts use too", () => {
    expect(gameRoute(1234567890)).toBe("/library/app/1234567890");
  });
});
