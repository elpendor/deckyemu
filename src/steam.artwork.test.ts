import { afterEach, describe, expect, it } from "vitest";

import { applyArtwork } from "./steam";

/**
 * Putting one game's artwork over another's.
 *
 * A source does not necessarily fill all four slots. libretro carries a boxart
 * and nothing else, so picking one filled the capsule and left the hero, logo
 * and header belonging to whichever game had been identified before it: the new
 * cover over the old backdrop. Reported as "not all the artwork sizes update",
 * which is precisely what it was.
 *
 * Applying artwork is a replacement. What is not supplied is cleared, so a
 * shortcut never shows two games at once.
 */
interface Call {
  slot: number;
  data?: string;
}

function install(options: { canClear?: boolean } = {}) {
  const cleared: Call[] = [];
  const set: Call[] = [];
  // The order matters as much as the contents: a write landing before the
  // clear it was supposed to follow is wiped by it.
  const order: string[] = [];

  const apps: Record<string, unknown> = {
    SetCustomArtworkForApp: async (_appId: number, data: string, _kind: string, slot: number) => {
      set.push({ slot, data });
      order.push(`set:${slot}`);
    },
  };

  if (options.canClear !== false) {
    apps.ClearCustomArtworkForApp = async (_appId: number, slot: number) => {
      cleared.push({ slot });
      order.push(`clear:${slot}`);
    };
  }

  (globalThis as any).window = { SteamClient: { Apps: apps } };
  return { cleared, set, order };
}

const IMAGE = { data: "data:image/png;base64,AAAA", kind: "png" } as const;

// Capsule 0, Hero 1, Logo 2, Header 3 -- ELibraryAssetType, as Steam numbers them.
const CAPSULE = 0;
const HERO = 1;
const LOGO = 2;
const HEADER = 3;

afterEach(() => {
  delete (globalThis as any).window;
});

describe("applyArtwork", () => {
  it("clears the slots the new game has nothing for", async () => {
    const steam = install();

    // A libretro pick: a boxart, and that is all there is.
    await applyArtwork(7, { capsule: IMAGE });

    expect(steam.cleared.map((call) => call.slot).sort()).toEqual([
      CAPSULE, HERO, LOGO, HEADER,
    ].sort());
    expect(steam.set.map((call) => call.slot)).toEqual([CAPSULE]);
  });

  it("clears a slot it is about to overwrite too", async () => {
    // Not redundant: Steam does not reliably refresh a slot that already holds
    // custom art, which is why decky-steamgriddb clears before every write.
    const steam = install();

    await applyArtwork(7, { capsule: IMAGE, hero: IMAGE });

    expect(steam.order.indexOf(`clear:${CAPSULE}`)).toBeLessThan(
      steam.order.indexOf(`set:${CAPSULE}`),
    );
    expect(steam.order.indexOf(`clear:${HERO}`)).toBeLessThan(
      steam.order.indexOf(`set:${HERO}`),
    );
  });

  it("counts the slots that stuck, not the ones it emptied", async () => {
    const steam = install();

    expect(await applyArtwork(7, { capsule: IMAGE, logo: IMAGE })).toBe(2);
    expect(steam.set).toHaveLength(2);
  });

  // An older Steam without the call is not a reason to apply nothing: the
  // artwork we do have is still better than the filename-derived default.
  it("still applies what it has when Steam cannot clear", async () => {
    const steam = install({ canClear: false });

    expect(await applyArtwork(7, { capsule: IMAGE })).toBe(1);
    expect(steam.set.map((call) => call.slot)).toEqual([CAPSULE]);
  });

  it("does nothing at all when Steam is not there", async () => {
    (globalThis as any).window = {};
    expect(await applyArtwork(7, { capsule: IMAGE })).toBe(0);
  });

  // Clearing everything and writing nothing would strip a game's artwork for
  // the sake of a lookup that found none.
  it("leaves a game alone when there is nothing to apply", async () => {
    const steam = install();

    expect(await applyArtwork(7, {})).toBe(0);
    expect(steam.cleared).toHaveLength(0);
  });
});
