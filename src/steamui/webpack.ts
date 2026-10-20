/**
 * Finding Steam's own modules and exports at runtime.
 *
 * Steam's UI is one webpack build, and its runtime hands its `require` to
 * anything that pushes a chunk into `webpackChunksteamui`. Every factory's
 * source is then readable, which is what an anchor is matched against: a string
 * literal, a localization key or a prop name, never a minified identifier.
 *
 * Every lookup is recorded, found or not, so a Steam update that moves
 * something shows up as a named entry in `report()` rather than as a blank
 * panel. A missing component never throws here; the caller decides how to
 * degrade.
 */

type Require = ((id: string) => Record<string, unknown>) & { m: Record<string, unknown> };

let require: Require | null = null;
const sources = new Map<string, string>();
const results = new Map<string, boolean>();

function webpackRequire(): Require | null {
  if (require) return require;
  const chunks = (window as unknown as { webpackChunksteamui?: unknown[] }).webpackChunksteamui;
  if (!chunks) return null;
  chunks.push([[Symbol("deckyemu")], {}, (r: Require) => (require = r)]);
  return require;
}

function factorySource(id: string, factory: unknown): string {
  let src = sources.get(id);
  if (src === undefined) {
    src = typeof factory === "function" ? Function.prototype.toString.call(factory) : "";
    sources.set(id, src);
  }
  return src;
}

/** The source of an export, looking through forwardRef, memo and observer. */
export function sourceOf(value: unknown): string {
  try {
    if (typeof value === "function") return Function.prototype.toString.call(value);
    const v = value as { render?: unknown; type?: unknown } | null;
    if (v && typeof v === "object") {
      if (typeof v.render === "function") return Function.prototype.toString.call(v.render);
      if (v.type) return sourceOf(v.type);
    }
  } catch {
    // An exotic export. Not what we are looking for.
  }
  return "";
}

/** The exports of the first module whose factory contains every needle. */
export function findModule(name: string, needles: string[]): Record<string, unknown> | null {
  const r = webpackRequire();
  if (r) {
    for (const [id, factory] of Object.entries(r.m)) {
      const src = factorySource(id, factory);
      if (!needles.every((needle) => src.includes(needle))) continue;
      try {
        const exported = r(id);
        results.set(name, true);
        return exported;
      } catch {
        break;
      }
    }
  }
  results.set(name, false);
  return null;
}

/**

 * The first export of `module` that `test` accepts, given it and its source.

 */
export function findExport<T = unknown>(
  name: string,
  module: Record<string, unknown> | null,
  test: (value: unknown, source: string) => boolean,
): T | null {
  if (module) {
    for (const value of Object.values(module)) {
      try {
        if (test(value, sourceOf(value))) {
          results.set(name, true);
          return value as T;
        }
      } catch {
        // Keep looking.
      }
    }
  }
  results.set(name, false);
  return null;
}

/** Note the outcome of a lookup made some other way. */
export function noteLookup(name: string, found: boolean) {
  results.set(name, found);
}

/** Everything looked up so far, and whether it was found. */
export function report(): Record<string, boolean> {
  return Object.fromEntries(results);
}

/** Cached once found; looked up again next time if it was not. */
export function once<T>(lookup: () => T | null): () => T | null {
  let found: T | null = null;
  return () => (found ??= lookup());
}
