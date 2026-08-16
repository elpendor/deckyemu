/**
 * Getting text off the clipboard, on a device with no keyboard worth using.
 *
 * Every hard part of this was learned once, painfully, for the SteamGridDB key,
 * and is needed again for a Vita licence key. Both are long random strings that
 * nobody will type on an on-screen keyboard.
 *
 * Two facts it rests on:
 *
 * `navigator.clipboard.readText()` is refused outright in SharedJSContext --
 * `NotAllowedError: Document is not focused`, with the `clipboard-read`
 * permission stuck at "prompt". The text off a `paste` event needs no
 * permission and no focus.
 *
 * And each Steam window is a separate browser with its own clipboard. Plugin
 * code is *evaluated* in SharedJSContext but *renders* into the Big Picture
 * window, so pasting through this module's `window` fires a real paste event
 * carrying zero characters -- which looks exactly like an empty clipboard. The
 * tell is that the on-screen keyboard's own paste key works while yours does
 * not. Steam's own context menu does what this does: focus the element, then
 * call Paste on the element's own window.
 */

/** How long to wait for the event. It lands within a frame or two, or never. */
const PASTE_TIMEOUT_MS = 1000;

/**
 * Paste into `input` and return what arrived, or "" if nothing did.
 *
 * The default is prevented, so the text never reaches the DOM: these inputs are
 * React-controlled and the next render would throw away anything the browser
 * inserted. The caller gets the string and decides what to do with it.
 */
export function pasteInto(input: HTMLInputElement): Promise<string> {
  const arrived = new Promise<string>((resolve) => {
    const onPaste = (event: ClipboardEvent) => {
      event.preventDefault();
      window.clearTimeout(timer);
      resolve(event.clipboardData?.getData("text") ?? "");
    };
    const timer = window.setTimeout(() => {
      input.removeEventListener("paste", onPaste);
      resolve("");
    }, PASTE_TIMEOUT_MS);
    input.addEventListener("paste", onPaste, { once: true });
  });

  input.focus();
  try {
    const view = input.ownerDocument.defaultView as
      /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
      (Window & { SteamClient?: any }) | null;
    view?.SteamClient?.Browser?.Paste?.();
  } catch (error) {
    // Reported by the caller, which knows what the user was trying to paste.
    console.error("[deckyemu] Steam paste failed", error);
  }

  return arrived;
}
