import { describe, expect, it } from "vitest";

import { callWithRetry } from "./timeout";

describe("retrying a backend call", () => {
  it("asks again after a failure", async () => {
    let calls = 0;
    const call = async () => {
      calls += 1;
      if (calls < 2) throw new Error("dropped");
      return "ok";
    };
    expect(await callWithRetry(call, { delay: 1 })).toBe("ok");
    expect(calls).toBe(2);
  });

  it("does not ask a backend that stays off again", async () => {
    let calls = 0;
    const call = async () => {
      calls += 1;
      throw new Error("get_settings is not available: {'reason': 'switched'}");
    };
    await expect(callWithRetry(call, { delay: 1 })).rejects.toThrow("is not available");
    expect(calls).toBe(1);
  });

  it("knows the refusal when only a traceback carries it", async () => {
    let calls = 0;
    const call = async () => {
      calls += 1;
      throw Object.assign(new Error(""), {
        name: "Python Exception",
        pythonTraceback: "Traceback...\nException: list_added is not available: {}\n",
      });
    };
    await expect(callWithRetry(call, { delay: 1 })).rejects.toMatchObject({ name: "Python Exception" });
    expect(calls).toBe(1);
  });
});
