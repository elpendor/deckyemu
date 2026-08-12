/**
 * A never-empty description of whatever was thrown.
 *
 * Its own module because `ErrorBoundary` uses the result as the "am I in the
 * fallback" flag, and an empty string there renders the children that just
 * threw, which throws again -- a render loop is a worse failure than the one
 * being contained. JavaScript lets anything be thrown, including `undefined`,
 * and `String(undefined)` is not a sentence, so neither the message nor its
 * emptiness can be taken on trust.
 */
export function crashMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim();

  // Not an Error, so there is no contract about what it holds. A string or a
  // number says something; `{}` stringifies to "[object Object]", which says
  // less than admitting there was nothing to read.
  if (typeof error === "string" && error.trim()) return error.trim();
  if (typeof error === "number" || typeof error === "boolean") return String(error);

  return "Something went wrong, and it arrived with no description.";
}
