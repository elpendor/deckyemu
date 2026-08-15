import { readFileSync, readdirSync } from "fs";
import { join } from "path";

import { describe, expect, it } from "vitest";

/**
 * The two rules that make this package a package.
 *
 * Neither is checked by anything else. The typecheck is happy with a backend
 * import here, and happy with any file reaching into `steam/client` -- both
 * would simply work, right up until the thing they break.
 *
 * They are cheap to state and expensive to rediscover, which is the whole
 * argument for a test over a comment.
 */

const DIR = join(__dirname);
const SRC = join(__dirname, "..");

const read = (path: string) => readFileSync(path, "utf-8");
const sources = (dir: string) =>
  readdirSync(dir)
    .filter((name) => name.endsWith(".ts") || name.endsWith(".tsx"))
    .filter((name) => !name.endsWith(".test.ts"));

describe("the steam package's boundaries", () => {
  /*
   * `@decky/api` will not load under Node, so a backend import anywhere in here
   * takes every test that touches Steam down with it -- including the ones
   * covering the calls that delete somebody's games, which are the tests least
   * worth losing. That is why `reuseShortcut.ts`, `addGame.ts` and
   * `src/collections.ts` exist outside this directory: each is a piece of work
   * that needs both halves, kept where it cannot cost this one its tests.
   */
  it("brings no value in from the backend", () => {
    // A *type* import is erased before anything runs, so it costs nothing --
    // `artwork.ts` has always taken `ArtImage` that way. A value import is the
    // one that pulls @decky/api in behind it. The rule is that distinction, not
    // the word "backend", and stating it loosely would have banned a line that
    // was always fine.
    const fromBackend = /import\s+(type\s+)?\{([^}]*)\}\s*from\s*"\.\.?\/backend"/g;

    for (const name of sources(DIR)) {
      const body = read(join(DIR, name));
      for (const [statement, typeOnly, specifiers] of body.matchAll(fromBackend)) {
        const values = specifiers
          .split(",")
          .map((specifier) => specifier.trim())
          .filter((specifier) => specifier && !specifier.startsWith("type "));
        expect(
          Boolean(typeOnly) || values.length === 0,
          `${name} imports ${values.join(", ")} from the backend as a value ` +
            `(${statement.trim()}); put the work in src/collections.ts instead`,
        ).toBe(true);
      }
      // The import, not the name: these files explain in prose why they do not
      // import it, and a substring match reads that explanation as the offence.
      expect(
        /from\s*"@decky\/api"/.test(body),
        `${name} imports @decky/api, which will not load under Node`,
      ).toBe(false);
    }
  });

  /*
   * `client.ts` holds the globals Steam injects. Everything that touches one
   * goes through a function in this directory that knows how to call it
   * defensively -- checking the method exists, tolerating a Map where an array
   * was expected, waiting for an overview that has not appeared yet. A caller
   * that reaches past all of that gets none of it, and the failure shows up as
   * a blank Quick Access panel rather than as a missing feature.
   *
   * It is left out of `index.ts` for the same reason, so the ordinary import
   * cannot reach it by accident. This catches the deliberate one.
   */
  it("keeps the injected globals to itself", () => {
    const offenders: string[] = [];
    for (const name of sources(SRC)) {
      const body = read(join(SRC, name));
      if (body.includes('from "./steam/client"')) offenders.push(name);
      // The globals themselves, reached for directly rather than through here.
      if (/\bwindow\s+as\s+any\s*\)\s*\.(SteamClient|appStore|collectionStore)/.test(body)) {
        offenders.push(`${name} (reads a Steam global directly)`);
      }
    }
    expect(offenders).toEqual([]);
  });

  /*
   * The index is the package's public face, and a module missing from it is a
   * module nobody can import -- which is how a subject file gets written,
   * passes its own tests, and turns out to be unreachable.
   */
  it("re-exports every subject module", () => {
    const index = read(join(DIR, "index.ts"));
    for (const name of sources(DIR)) {
      const stem = name.replace(/\.ts$/, "");
      if (stem === "index" || stem === "client") continue;
      expect(index, `steam/index.ts does not re-export ${name}`).toContain(
        `export * from "./${stem}"`,
      );
    }
  });
});
