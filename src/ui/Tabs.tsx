import { useEffect, useRef, useState, type ReactNode } from "react";

import { Focusable, GamepadButton, type GamepadEvent } from "../steamui/base";
import { styled } from "./styles";

export interface Tab {
  id: string;
  title: ReactNode;
  content: ReactNode;
}

export interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onShowTab: (id: string) => void;
  autoFocusContents?: boolean;
}

// Steam's numbers, used if its enum ever stops naming them.
const BUMPER_LEFT = () => GamepadButton.BUMPER_LEFT ?? 5;
const BUMPER_RIGHT = () => GamepadButton.BUMPER_RIGHT ?? 6;

/** The shoulder-button glyphs Steam serves for its own tab bars. */
function Bumper({ side }: { side: "l1" | "r1" }) {
  return (
    <div className="dek-bumper">
      <img src={`/steaminputglyphs/sd_${side}.svg`} alt={side.toUpperCase()} />
    </div>
  );
}

/**
 * A row of pill tabs over the active tab's content, switched by tapping a tab
 * or with L1 and R1 from anywhere inside, as Steam's own tab bars are.
 */
export function Tabs({ tabs, activeTab, onShowTab }: TabsProps) {
  const index = Math.max(0, tabs.findIndex((tab) => tab.id === activeTab));
  // Steam's navigation node for each tab pill.
  type NavNode = { current: { TakeFocus?: () => void } | null };
  const [pills] = useState(() => new Map<string, NavNode>());
  const pillRef = (id: string): NavNode => {
    let ref = pills.get(id);
    if (!ref) pills.set(id, (ref = { current: null }));
    return ref;
  };
  const shown = useRef<string | undefined>(undefined);
  const activeId = tabs[index]?.id;
  // Which way the content slides in: from the side of the tab moved to. Kept
  // in state, set while rendering when the tab changes, so the first render
  // of the new tab already carries it.
  const [slide, setSlide] = useState<{ id?: string; index: number; from: "left" | "right" | "" }>(
    { id: activeId, index, from: "" },
  );
  if (slide.id !== activeId) {
    setSlide({ id: activeId, index, from: index < slide.index ? "left" : "right" });
  }
  useEffect(() => {
    // A switch unmounts what had focus, and with nothing focused Steam has
    // nowhere to send the D-pad or the bumpers, so all of them stop. Focus
    // goes to the new tab's pill, as Steam's own tab bars keep it in view.
    // On first show too when the active tab is not the first: the dialog's
    // own focus lands on the first pill, lit beside the one showing.
    const opening = shown.current === undefined && index > 0;
    if (opening || (shown.current !== undefined && shown.current !== activeId)) {
      pills.get(activeId ?? "")?.current?.TakeFocus?.();
    }
    shown.current = activeId;
  }, [activeId, index, pills]);
  // The list scrolls only from here: the active pill, and any pill the D-pad
  // lands on, kept in view between the bumpers.
  const bar = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const list = bar.current?.querySelector<HTMLElement>(".dek-tab-list");
    if (!list) return;
    const reveal = (pill: Element | null | undefined) => {
      if (!(pill instanceof HTMLElement) || !list.contains(pill)) return;
      if (pill.offsetLeft < list.scrollLeft) list.scrollLeft = pill.offsetLeft;
      const end = pill.offsetLeft + pill.offsetWidth;
      if (end > list.scrollLeft + list.clientWidth) list.scrollLeft = end - list.clientWidth;
    };
    reveal(list.querySelector(".dek-tab.dek-active"));
    const onFocus = (event: FocusEvent) => reveal((event.target as Element)?.closest?.(".dek-tab"));
    list.addEventListener("focusin", onFocus);
    return () => list.removeEventListener("focusin", onFocus);
  }, [activeId]);
  const step = (by: number) => {
    const next = tabs[index + by];
    if (next) onShowTab(next.id);
  };
  const onButtonDown = (event: GamepadEvent) => {
    const button = event.detail?.button;
    if (button === BUMPER_LEFT()) step(-1);
    else if (button === BUMPER_RIGHT()) step(1);
  };
  return (
    <Focusable className="dek-tabs" onButtonDown={onButtonDown}>
      <div
        className="dek-tab-bar"
        ref={(node) => {
          bar.current = node;
          styled(node);
        }}
      >
        <Bumper side="l1" />
        <Focusable className="dek-tab-list" flow-children="row" role="tablist">
          {tabs.map((tab) => (
            <Focusable
              key={tab.id}
              role="tab"
              noFocusRing
              navRef={pillRef(tab.id)}
              aria-selected={tab.id === tabs[index]?.id}
              className={tab.id === tabs[index]?.id ? "dek-tab dek-active" : "dek-tab"}
              onActivate={() => onShowTab(tab.id)}
              onClick={() => onShowTab(tab.id)}
            >
              {tab.title}
            </Focusable>
          ))}
        </Focusable>
        <Bumper side="r1" />
      </div>
      <div
        key={activeId}
        className={slide.from ? `dek-tab-content dek-slide-${slide.from}` : "dek-tab-content"}
        role="tabpanel"
      >
        {tabs[index]?.content}
      </div>
    </Focusable>
  );
}
