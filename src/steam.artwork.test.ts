import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
// Smaller, so it is the one `republish` picks for its second write.
const SMALL = { data: "data:image/png;base64,AA", kind: "png" } as const;

/** Which slots were written at all, ignoring the republish's repeat. */
const slotsWritten = (set: Call[]) => [...new Set(set.map((call) => call.slot))];

// Capsule 0, Hero 1, Logo 2, Header 3 -- ELibraryAssetType, as Steam numbers them.
const CAPSULE = 0;
const HERO = 1;
const LOGO = 2;
const HEADER = 3;

// Applying ends by waiting for the clock to turn over (see `republish`), which
// is a real second of real time. Fake it, and drive it from `apply` below.
beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as any).window;
});

/** `applyArtwork`, with the wait for the next second run through. */
async function apply(appId: number, art: Parameters<typeof applyArtwork>[1]) {
  const running = applyArtwork(appId, art);
  await vi.advanceTimersByTimeAsync(2000);
  return running;
}

describe("applyArtwork", () => {
  it("clears the slots the new game has nothing for", async () => {
    const steam = install();

    // A libretro pick: a boxart, and that is all there is.
    await apply(7, { capsule: IMAGE });

    expect(steam.cleared.map((call) => call.slot).sort()).toEqual([
      CAPSULE, HERO, LOGO, HEADER,
    ].sort());
    expect(slotsWritten(steam.set)).toEqual([CAPSULE]);
  });

  it("clears a slot it is about to overwrite too", async () => {
    // Not for refreshing -- a write over a slot holding custom art lands fine.
    // It is for the extension: Steam keeps `_hero.jpg` and `_hero.png` as
    // separate files and offers jpg first, so a png written over a jpg would
    // leave the old jpg winning. Clearing drops both.
    const steam = install();

    await apply(7, { capsule: IMAGE, hero: IMAGE });

    expect(steam.order.indexOf(`clear:${CAPSULE}`)).toBeLessThan(
      steam.order.indexOf(`set:${CAPSULE}`),
    );
    expect(steam.order.indexOf(`clear:${HERO}`)).toBeLessThan(
      steam.order.indexOf(`set:${HERO}`),
    );
  });

  /*
   * The blank details page, and the reason this order is not incidental.
   *
   * Every slot cleared up front is an app with no custom artwork at all until
   * the writes land, and a game details page open behind the editor renders that
   * emptiness immediately -- then recovers unevenly, the hero on its own and the
   * logo only when the page is re-opened. Interleaving means the gap per slot is
   * one write long.
   */
  it("clears each slot only immediately before its own write", async () => {
    const steam = install();

    await apply(7, { capsule: IMAGE, hero: IMAGE });

    // The two slots being written, in order. The abandoned pair follows, which
    // the test below is about.
    expect(steam.order.slice(0, 4)).toEqual([
      `clear:${CAPSULE}`,
      `set:${CAPSULE}`,
      `clear:${HERO}`,
      `set:${HERO}`,
    ]);
  });

  it("empties the abandoned slots only after the new art is in place", async () => {
    const steam = install();

    // A libretro pick again: the capsule is replaced, and the other three are
    // the previous game's and have to go.
    await apply(7, { capsule: IMAGE });

    // The first write of the capsule, not the republish's repeat of it -- that
    // one is deliberately last of everything.
    const written = steam.order.indexOf(`set:${CAPSULE}`);
    for (const slot of [HERO, LOGO, HEADER]) {
      expect(steam.order.indexOf(`clear:${slot}`)).toBeGreaterThan(written);
    }
  });

  it("counts the slots that stuck, not the ones it emptied", async () => {
    const steam = install();

    expect(await apply(7, { capsule: IMAGE, logo: IMAGE })).toBe(2);
    expect(slotsWritten(steam.set)).toHaveLength(2);
  });

  /*
   * The stale details page, and why one slot is written twice.
   *
   * The version token in every custom art URL is `rt_custom_image_mtime`, an
   * mtime in **whole seconds**. Four writes inside one second are one token, so a
   * page already on screen re-renders once -- on the first change, when the later
   * slots are still cleared or still the previous game's -- and is never told
   * again. Measured on the device: a backdrop that stayed blank and a logo that
   * stayed the old game's, both with the finished files sitting on disk.
   */
  it("writes one slot again once the clock has turned, so the page re-reads", async () => {
    const steam = install();

    await apply(7, { capsule: IMAGE, logo: SMALL });

    // The very last thing to happen, after every clear, on the cheapest slot.
    expect(steam.order[steam.order.length - 1]).toBe(`set:${LOGO}`);
    expect(steam.set.filter((call) => call.slot === LOGO)).toHaveLength(2);
  });

  it("does not republish in the same second it wrote in", async () => {
    const steam = install();

    const running = applyArtwork(7, { capsule: IMAGE, logo: SMALL });
    // Everything except the republish needs no timer at all.
    await vi.advanceTimersByTimeAsync(0);
    const beforeTheWait = steam.order.filter((call) => call === `set:${LOGO}`);

    await vi.advanceTimersByTimeAsync(2000);
    await running;

    expect(beforeTheWait).toHaveLength(1);
    expect(steam.order.filter((call) => call === `set:${LOGO}`)).toHaveLength(2);
  });

  // An older Steam without the call is not a reason to apply nothing: the
  // artwork we do have is still better than the filename-derived default.
  it("still applies what it has when Steam cannot clear", async () => {
    const steam = install({ canClear: false });

    expect(await apply(7, { capsule: IMAGE })).toBe(1);
    expect(slotsWritten(steam.set)).toEqual([CAPSULE]);
  });

  it("does nothing at all when Steam is not there", async () => {
    (globalThis as any).window = {};
    expect(await apply(7, { capsule: IMAGE })).toBe(0);
  });

  // Clearing everything and writing nothing would strip a game's artwork for
  // the sake of a lookup that found none.
  it("leaves a game alone when there is nothing to apply", async () => {
    const steam = install();

    expect(await apply(7, {})).toBe(0);
    expect(steam.cleared).toHaveLength(0);
  });
});
