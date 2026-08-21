/**
 * Steam's own UI strings, borrowed by token.
 *
 * Only for a dialog that is deliberately a copy of one of Steam's -- the
 * multiple-games warning. Saying it in Steam's words means the user reads the
 * sentence they already know rather than a paraphrase of it, and it arrives in
 * whatever language the client is set to, which nothing else here manages.
 *
 * `LocalizationManager.LocalizeString` returns the raw string and does **not**
 * substitute: the tokens come back containing literal `%1$s`. Steam's own
 * components run them through a formatting helper afterwards, so this does the
 * same, and it is the reason this is a module rather than one call.
 *
 * Every token carries an English fallback, and that is the whole safety story:
 * `LocalizationManager` is an injected global like the rest, so a rename or a
 * retired token costs the translation and nothing else.
 */

const strings = (): any => (window as any).LocalizationManager ?? null;

/**
 * Replace `%1$s`, `%2$s`, ... with `args`.
 *
 * Positional rather than sequential because that is what the format is for:
 * translations reorder the arguments, and "Close %2$s and launch %1$s" is a
 * sentence some language wants.
 */
function format(template: string, args: string[]): string {
  return template.replace(/%(\d+)\$s/g, (whole, index) => {
    const arg = args[Number(index) - 1];
    return arg === undefined ? whole : arg;
  });
}

/**
 * One of Steam's strings, formatted, falling back to `fallback`.
 *
 * `token` is Steam's own, with the leading `#`.
 */
export function steamText(token: string, fallback: string, ...args: string[]): string {
  let template = fallback;
  try {
    const localized = strings()?.LocalizeString?.(token);
    // A missing token comes back as the token itself on some builds and as
    // undefined on others. Neither is a string to show anybody.
    if (typeof localized === "string" && localized && !localized.startsWith("#")) {
      template = localized;
    }
  } catch (error) {
    console.error("[deckyemu] could not localize", token, error);
  }
  return format(template, args);
}
