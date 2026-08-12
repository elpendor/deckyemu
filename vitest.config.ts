import { readFileSync } from "fs";

import { defineConfig } from "vitest/config";

const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

/**
 * The frontend suite.
 *
 *     pnpm test:ui            # once
 *     pnpm test:ui --watch    # while working
 *
 * Node environment rather than jsdom: nothing tested here touches the DOM. What
 * it touches is Steam's own globals -- `window.collectionStore` and friends --
 * which no DOM library provides either, so a jsdom dependency would buy the
 * `window` object and nothing else. `src/test.setup.ts` provides that object in
 * three lines instead.
 *
 * The build stamps have to be defined here as well as in rollup.config.js.
 * version.ts reads them as bare identifiers that rollup replaces before it
 * parses, so without this the module cannot be imported at all -- which is how
 * this was discovered. "dev" rather than a commit, because that is what a build
 * from source stamps and what `isStale` is expected to stay quiet about.
 */
export default defineConfig({
  define: {
    __DECKYEMU_VERSION__: JSON.stringify(pkg.version),
    __DECKYEMU_BUILD__: JSON.stringify("dev"),
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    setupFiles: ["src/test.setup.ts"],
  },
});
