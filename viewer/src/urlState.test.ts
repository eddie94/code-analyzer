import { describe, expect, it } from "vitest";
import { DEFAULTS, decode, encode } from "./urlState";

describe("urlState", () => {
  it("leaves defaults out of the hash", () => {
    expect(encode(DEFAULTS)).toBe("");
    expect(decode("")).toEqual(DEFAULTS);
  });

  it("round-trips a full state", () => {
    const state = {
      tab: "classes" as const,
      selected: "cls:shop.models.Order",
      expanded: ["pkg:shop", "pkg:plugins"],
      showExternal: true,
      showWeak: false,
      showCycles: true,
      hideTests: true,
    };
    const hash = encode(state);
    expect(hash).toBe("tab=classes&sel=cls:shop.models.Order&exp=pkg:plugins,pkg:shop&ext=1&weak=0&notests=1");
    expect(decode(`#${hash}`)).toEqual({ ...state, expanded: ["pkg:plugins", "pkg:shop"] });
  });

  it("keeps an explicitly empty expansion", () => {
    expect(decode("#exp=").expanded).toEqual([]);
  });

  it("ignores unknown tabs", () => {
    expect(decode("#tab=nope").tab).toBe("deps");
  });
});
