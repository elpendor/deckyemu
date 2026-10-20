import { readFileSync } from "fs";

import commonjs from "@rollup/plugin-commonjs";
import { nodeResolve } from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";

const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

/*
 * The version is stamped into the bundle at build time.
 *
 * package.json is the single source of truth. CI passes the commit through
 * DECKYEMU_BUILD and writes a matching build.json for the backend to read, so the
 * two halves can each be asked what they are and compared -- a frontend left
 * behind by an update is otherwise indistinguishable from a bug.
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
 * than merely unreachable. scripts/check_release_build.py asserts exactly that,
 * because this is the kind of guarantee that quietly stops being true.
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

const plugins = () => [
  stamp,
  typescript({ tsconfig: "./tsconfig.json", noEmitOnError: true }),
  nodeResolve({ browser: true }),
  commonjs(),
];

export default [
  /*
   * The preload: the script Steam's UI runs before its own code. Nothing
   * outside it is loaded yet when it runs, so it imports nothing at runtime.
   */
  {
    input: "src/preload/index.ts",
    plugins: plugins(),
    treeshake: { moduleSideEffects: true },
    output: { file: "dist/preload.js", format: "iife", sourcemap: false },
  },
  /*
   * The panel. React comes from Steam -- one React per page, or its hooks
   * throw -- through the globals the preload sets from Steam's own modules.
   */
  {
    input: "src/main.tsx",
    plugins: plugins(),
    external: ["react", "react-dom", "react/jsx-runtime"],
    output: {
      file: "dist/deckyemu.js",
      format: "iife",
      sourcemap: false,
      globals: {
        react: "DECKYEMU_REACT",
        "react-dom": "DECKYEMU_REACTDOM",
        "react/jsx-runtime": "DECKYEMU_JSX",
      },
    },
  },
];
