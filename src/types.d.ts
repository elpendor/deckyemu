/**
 * Build stamps, substituted into the source by rollup. See rollup.config.js.
 *
 * Declared here rather than beside their use in version.ts: the substitution
 * happens before parsing, so a `declare const` in a real module would itself be
 * rewritten. Ambient declarations never reach the transform.
 */
declare const __DECKYEMU_VERSION__: string;
/** The commit CI built from, or "dev" for a build from source. */
declare const __DECKYEMU_BUILD__: string;

declare module "*.svg" {
  const content: string;
  export default content;
}

declare module "*.png" {
  const content: string;
  export default content;
}

declare module "*.jpg" {
  const content: string;
  export default content;
}
