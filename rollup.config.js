import { readFileSync } from "fs";

import deckyPlugin from "@decky/rollup";

const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

/*
 * The version is stamped into the bundle at build time.
 *
 * package.json is the single source of truth. CI passes the commit through
 * DECKYEMU_BUILD and writes a matching build.json for the backend to read, so the
 * two halves of the plugin can each be asked what they are and compared -- a
 * frontend Steam cached before an update is otherwise indistinguishable from a bug.
 */
const build = process.env.DECKYEMU_BUILD || "dev";

/*
 * Substituted in the source, not prepended to the output.
 *
 * This was an `intro` string, which reads identically from inside the bundle
 * and was wrong in one way that mattered: `intro` is raw text glued on after
 * tree-shaking has already run, so rollup never learns what the constant is.
 * `IS_DEV_BUILD && <DevPanel/>` therefore survived into a release build with
 * the entire development-only Reset panel behind it -- verified by grepping a
 * release bundle for it and finding it there.
 *
 * Replacing the identifier before rollup parses makes `"a1b2c3d" === "dev"` a
 * constant expression, the branch dead, and the panel genuinely absent rather
 * than merely unreachable. scripts/check_release_build.sh asserts exactly that,
 * because this is the kind of guarantee that quietly stops being true.
 *
 * A hand-rolled transform rather than @rollup/plugin-replace: the two
 * identifiers are ours and unambiguous, and this needs no dependency the decky
 * preset has not already pinned. The declarations live in types.d.ts, which
 * never reaches this hook -- ambient declarations are not modules -- so there
 * is no `declare const "0.5.0"` to worry about.
 */
const stamp = {
  name: "deckyemu-stamp",
  transform(code) {
    if (!code.includes("__DECKYEMU_")) return null;
    return {
      code: code
        .replace(/__DECKYEMU_VERSION__/g, JSON.stringify(pkg.version))
        .replace(/__DECKYEMU_BUILD__/g, JSON.stringify(build)),
      map: null,
    };
  },
};

export default deckyPlugin({ plugins: [stamp] });
