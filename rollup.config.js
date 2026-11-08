import { readFileSync } from "fs";
import { resolve } from "path";

import commonjs from "@rollup/plugin-commonjs";
import { nodeResolve } from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";
import externalGlobals from "rollup-plugin-external-globals";

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

const plugins = (tsconfig = "./tsconfig.json") => [
  stamp,
  typescript({ tsconfig, noEmitOnError: true }),
  nodeResolve({ browser: true }),
  commonjs(),
];

/*
 * The plugin build's host: these three shared modules are replaced by the
 * plugin's own wherever the shared panel imports them. Everything else is the
 * same file in both builds.
 */
const SWAPS = new Map([
  ["src/host/index.ts", "plugin/src/host.ts"],
  ["src/steamui/index.ts", "plugin/src/steamui.ts"],
  ["src/steamui/base.ts", "plugin/src/steamuiBase.ts"],
  ["src/steam/contextMenu.ts", "plugin/src/contextMenu.ts"],
].map(([from, to]) => [resolve(from), resolve(to)]));

const manifest = JSON.parse(readFileSync("./plugin/plugin.json", "utf-8"));

const pluginHost = {
  name: "deckyemu-plugin-host",
  async resolveId(source, importer, options) {
    if (!importer || !source.startsWith(".")) return null;
    const found = await this.resolve(source, importer, { ...options, skipSelf: true });
    return (found && SWAPS.get(resolve(found.id))) ?? null;
  },
};

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
  /*
   * The plugin, for the loader: an ES module whose default export is the
   * plugin definition. React and the loader's UI library come from the
   * loader's globals. Into plugin/dist, never dist/: the zip puts it at
   * dist/index.js, beside nothing of the service's.
   */
  {
    input: "plugin/src/index.tsx",
    plugins: [
      pluginHost,
      ...plugins("./plugin/tsconfig.json"),
      externalGlobals({
        react: "SP_REACT",
        "react/jsx-runtime": "SP_JSX",
        "react-dom": "SP_REACTDOM",
        "@decky/ui": "DFL",
        // The loader's API reads its plugin's manifest from this import.
        "@decky/manifest": JSON.stringify(manifest),
      }),
    ],
    context: "window",
    external: ["react", "react-dom", "react/jsx-runtime", "@decky/ui", "@decky/manifest"],
    // What the loader's own build preset uses, and what the plugin has always
    // shipped with. Without it the development-only panel's calls survive into
    // a release: the loader's `callable` is not known to be pure.
    treeshake: { pureExternalImports: { pure: ["@decky/ui", "@decky/api"] }, preset: "smallest" },
    output: { file: "plugin/dist/index.js", format: "esm", exports: "default", sourcemap: false },
  },
];
