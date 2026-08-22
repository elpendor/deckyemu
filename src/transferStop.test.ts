import { describe, expect, it } from "vitest";

import { shouldStopServer } from "./transferStop";

/**
 * Whether dismissing the transfer dialog takes the file server down with it.
 *
 * The costly half is not "stop when idle" -- it is every case that must *not*
 * stop, because getting one of those wrong kills a send from another device
 * that has no idea a dialog was dismissed here. A paused transfer is the one
 * that reads as idle and is not: between two attempts there is nothing in
 * flight, for as long as the sender's backoff lasts.
 *
 * Tested apart from the dialog because two different dismissals reach it -- the
 * dialog's own close, and `closeOpenModals` from outside when the Quick Access
 * panel opens. Those disagreed until this was one function.
 */

const status = (over: Record<string, unknown> = {}) =>
  ({ running: true, uploading: 0, paused: 0, ...over }) as never;

describe("shouldStopServer", () => {
  it("stops a server that is running with nothing arriving", () => {
    expect(shouldStopServer(status())).toBe(true);
  });

  it("leaves a server up while a file is uploading", () => {
    expect(shouldStopServer(status({ uploading: 1 }))).toBe(false);
  });

  // The one that looks idle and is not.
  it("leaves a server up while a transfer is paused between attempts", () => {
    expect(shouldStopServer(status({ paused: 1 }))).toBe(false);
  });

  it("leaves it up when something is uploading and something else is paused", () => {
    expect(shouldStopServer(status({ uploading: 1, paused: 2 }))).toBe(false);
  });

  it("has nothing to stop when the server is not running", () => {
    expect(shouldStopServer(status({ running: false }))).toBe(false);
  });

  // A dismissal can land before the first status poll has answered, and asking
  // to stop a server we know nothing about would race whatever started it.
  it("does not stop on a status it has not read yet", () => {
    expect(shouldStopServer(null)).toBe(false);
    expect(shouldStopServer(undefined)).toBe(false);
  });

  // The backend omits these entirely when nothing is in flight, so treating a
  // missing count as anything but zero would leave every idle server standing.
  it("reads absent counts as nothing in flight", () => {
    expect(shouldStopServer({ running: true } as never)).toBe(true);
  });
});
