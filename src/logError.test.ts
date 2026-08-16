import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Reporting a frontend failure somewhere it can be read.
 *
 * The two halves of this plugin fail into different places and only one of them
 * is reachable: a backend exception lands in the plugin log, while a frontend
 * one goes to a CEF console that needs a second machine to open. So in Game
 * Mode nobody sees it, including the person reporting the bug.
 *
 * What matters here is that reporting a failure cannot itself become one.
 */

const logFrontendError = vi.fn(async (..._args: unknown[]) => ({ ok: true }));
vi.mock("./backend", () => ({
  logFrontendError: (...args: unknown[]) => logFrontendError(...args),
}));

const { logError } = await import("./logError");

let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  logFrontendError.mockClear();
  logFrontendError.mockResolvedValue({ ok: true });
  consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  consoleError.mockRestore();
});

describe("logError", () => {
  it("writes to both places", () => {
    logError("adding a game", new Error("nope"));

    // The console is where a developer with a debugger attached looks.
    expect(consoleError).toHaveBeenCalled();
    // The log is what a diagnostic report carries, and therefore what reaches a
    // bug report from somebody who has neither a debugger nor a keyboard.
    expect(logFrontendError).toHaveBeenCalledWith("adding a game", "Error: nope", "");
  });

  it("carries the detail when there is one", () => {
    logError("the panel failed to render", new Error("x"), "at Foo\n  at Bar");
    expect(logFrontendError.mock.calls[0][2]).toBe("at Foo\n  at Bar");
  });

  /*
   * Anything can be thrown, and a log entry reading "[object Object]" is worth
   * less than none: a rejected `callable` comes back as a string, and decky
   * hands a Python traceback over as one.
   */
  it.each([
    [new Error("boom"), "Error: boom"],
    ["a plain string", "a plain string"],
    [{ code: 42 }, '{"code":42}'],
  ])("describes %o as text", (thrown, expected) => {
    logError("somewhere", thrown);
    expect(logFrontendError.mock.calls[0][1]).toBe(expected);
  });

  /*
   * The backend being unreachable is one of the reasons a frontend call fails
   * in the first place -- decky drops every in-flight call when the plugin
   * reloads. Throwing here would turn a logged problem into an unlogged one, on
   * the path taken *because* something already went wrong.
   */
  it("does not throw when the backend refuses", () => {
    logFrontendError.mockRejectedValueOnce(new Error("plugin reloading"));
    expect(() => logError("somewhere", new Error("original"))).not.toThrow();
  });

  it("nor when the binding is not there at all", () => {
    logFrontendError.mockImplementationOnce(() => {
      throw new Error("no such method");
    });
    expect(() => logError("somewhere", new Error("original"))).not.toThrow();
    // And the original still reached the console, which is the point of doing
    // that first.
    expect(consoleError).toHaveBeenCalled();
  });
});
