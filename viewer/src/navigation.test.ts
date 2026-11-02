import { describe, expect, it } from "vitest";
import { extendTrail, samePlace, trailOf } from "./navigation";

describe("navigation", () => {
  it("treats a new flow root or tab as a new place", () => {
    expect(samePlace({ tab: "flow", flowRoot: "fn:a" }, { tab: "flow", flowRoot: "fn:b" })).toBe(false);
    expect(samePlace({ tab: "flow", flowRoot: "fn:a" }, { tab: "deps", flowRoot: "fn:a" })).toBe(false);
    // the flow root only matters on the flow tab
    expect(samePlace({ tab: "deps", flowRoot: "fn:a" }, { tab: "deps", flowRoot: null })).toBe(true);
  });

  it("keeps a bounded trail", () => {
    let trail = trailOf(null);
    for (let i = 0; i < 40; i++) trail = extendTrail(trail, { tab: "flow", flowRoot: `fn:${i}` });
    expect(trail).toHaveLength(30);
    expect(trail[29]).toEqual({ tab: "flow", flowRoot: "fn:39" });
    expect(trailOf({ trail: "junk" })).toEqual([]);
  });
});
