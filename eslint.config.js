import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/*
 * Lint rules for the frontend.
 *
 * **`react-hooks/exhaustive-deps` is the reason this exists.** Everything else
 * here is either already caught by `tsc --noEmit` or a matter of taste, and this
 * project had neither a config nor the dependency for years -- while carrying
 * three `eslint-disable` comments for a linter that was never installed, which
 * is worse than no linting, because it reads as a rule somebody is enforcing.
 *
 * The panel is dense with hand-written dependency arrays: polling effects that
 * re-arm on a status field, callbacks captured by modals that outlive the render
 * that made them, refs used specifically so an effect can stay dependency-free.
 * A wrong array there is a stale closure, and a stale closure on this project is
 * found by holding a Steam Deck rather than by reading a diff.
 *
 * Deliberately narrow otherwise. There is no formatting rule and no style
 * opinion: the codebase is consistent already, and a linter that reports two
 * hundred things nobody intends to change is one people learn to run with their
 * eyes closed.
 */
export default tseslint.config(
  {
    // Build output and the toolchain's own files. `dist/` is regenerated on
    // every build and is not ours to lint.
    ignores: ["dist/**", "node_modules/**", "*.config.js"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // `configs.flat`, not `configs`: the top-level ones are still eslintrc-shaped
  // and declare `plugins` as an array of strings, which flat config refuses.
  reactHooks.configs.flat["recommended-latest"],
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      /*
       * The whole point. Warn-by-default in the plugin's own preset; an error
       * here, because a dependency array that is wrong is not a style question
       * -- it is a value that will be stale at the moment it is read, and the
       * symptom is a panel that does nothing rather than a panel that throws.
       */
      "react-hooks/exhaustive-deps": "error",

      /*
       * `any` is unavoidable at the Steam boundary: SteamClient, appStore and
       * the collection store are undocumented globals with no types to import,
       * and inventing interfaces for them would be asserting a shape nobody has
       * verified. Reported rather than forbidden, so a new one is visible in the
       * output without failing a build over the boundary this plugin is made of.
       */
      "@typescript-eslint/no-explicit-any": "warn",

      // Handled by `tsc` with better messages, and it understands the project's
      // types; the lint version double-reports every one of them.
      "@typescript-eslint/no-unused-vars": "off",

      /*
       * Off, and not because they are wrong -- because they are advice for a
       * compiler this project does not run.
       *
       * `eslint-plugin-react-hooks` v7 ships the React Compiler's own rules
       * alongside the classic ones. `set-state-in-effect` reports 21 times here
       * and `preserve-manual-memoization` four, and every one of them is the
       * ordinary shape of this codebase: an effect that loads from the backend
       * and calls setState with the answer, which is what a panel reading a
       * device *is*. Adopting React Compiler would make them worth reading;
       * until then they are 25 findings nobody intends to act on, sitting on
       * top of the four that matter -- and a linter whose output is mostly
       * noise is one people stop reading, which costs more than it saves.
       */
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/preserve-manual-memoization": "off",

      /*
       * Off because the toolchain cannot express it. `Error(message, { cause })`
       * is ES2022 and tsconfig targets ES2020, so the two-argument form does not
       * typecheck -- and raising the compile target of the whole bundle to
       * satisfy one lint rule is the wrong way round. The one place this fires,
       * `steam/shortcuts.ts`, logs the original immediately before throwing, so
       * what Steam said is in the log either way.
       */
      "preserve-caught-error": "off",
    },
  },
  {
    // The suite mocks modules and reaches into internals on purpose.
    files: ["src/**/*.test.ts"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
);
