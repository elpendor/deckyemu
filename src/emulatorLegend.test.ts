import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { EMULATOR_LEGEND } from "./emulatorLegend";

/*
 * The panel cannot be imported here -- it pulls in @decky/ui, which does not
 * load under Node -- so it is read as text instead. Crude, and it earns its
 * place: the failure this guards against is a button added later whose icon
 * nothing explains, and that is invisible until somebody meets it on a Deck in
 * a state they cannot get out of.
 */
const PANEL = readFileSync(join(__dirname, "EmulatorCatalogPanel.tsx"), "utf8");

/*
 * The button that opens the legend. Explaining it inside itself would be
 * circular, and anyone reading the list has already worked out what it does.
 * Named here rather than by loosening the check, so the exception is one icon
 * on purpose instead of a hole the next one slips through.
 */
const EXEMPT = new Set(["FaQuestion"]);

/** Icon components actually rendered, e.g. `<FaLink />`. */
function renderedIcons(source: string): string[] {
  const found = Array.from(source.matchAll(/<(Fa[A-Za-z]+)\s*\/>/g), (m) => m[1]);
  return [...new Set(found)].filter((icon) => !EXEMPT.has(icon)).sort();
}

describe("the legend covers the panel", () => {
  it("explains every icon the panel renders", () => {
    const explained = new Set(EMULATOR_LEGEND.map((entry) => entry.icon));
    const unexplained = renderedIcons(PANEL).filter((icon) => !explained.has(icon));
    expect(unexplained).toEqual([]);
  });

  // The other direction: an icon dropped from the panel leaves an entry
  // describing a button that is not there, which is worse than no legend --
  // it sends someone looking for a control that does not exist.
  it("explains nothing the panel does not render", () => {
    const rendered = new Set(renderedIcons(PANEL));
    const stale = EMULATOR_LEGEND.filter((entry) => !rendered.has(entry.icon));
    expect(stale.map((entry) => entry.icon)).toEqual([]);
  });

  // A guard on the guard. If the regex stopped matching, both checks above
  // would pass against an empty list and prove nothing.
  it("finds the icons at all", () => {
    expect(renderedIcons(PANEL).length).toBeGreaterThan(4);
  });
});

describe("the wording", () => {
  it("gives every entry a label and a detail", () => {
    for (const entry of EMULATOR_LEGEND) {
      expect(entry.label.trim().length).toBeGreaterThan(0);
      expect(entry.detail.trim().length).toBeGreaterThan(0);
    }
  });

  /*
   * Uninstall and Forget are the pair people confuse, and the cost of confusing
   * them is deleting an emulator you meant to keep. Each has to say what happens
   * to what is on disk.
   */
  it("distinguishes uninstalling from forgetting", () => {
    const uninstall = EMULATOR_LEGEND.find((entry) => entry.icon === "FaTrash");
    const forget = EMULATOR_LEGEND.find((entry) => entry.icon === "FaEraser");
    expect(uninstall?.detail).toContain("Removes the emulator from the Deck");
    expect(forget?.detail).toContain("without uninstalling");
  });
});
