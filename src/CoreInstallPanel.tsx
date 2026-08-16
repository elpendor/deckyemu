import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  Spinner,
  type SingleDropdownOption,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  installCore,
  listInstallableCores,
  uninstallCore,
  type InstallableCore,
} from "./backend";
import { callWithRetry } from "./timeout";

interface Props {
  /** Bumped by the parent whenever the installed core set changes. */
  onCoresChanged: () => void;
  /**
   * Changes when something outside this panel deleted cores — the development
   * Reset tab. The catalog cache below is module-level and outlives the panel,
   * so nothing else would ever make it re-read.
   */
  reloadKey?: number;
}

// Steam unmounts Quick Access content whenever a modal opens, so this panel is
// remounted constantly. Caching the catalog at module scope keeps that from
// re-fetching 188 entries every time. Also remembers the user's place in the
// list across remounts.
let cachedCatalog: InstallableCore[] | null = null;
let lastSystem = "";
let lastCoreId = "";

/**
 * A core to open this panel on, set by whoever is about to navigate here.
 *
 * The game editor uses it: a game whose core was uninstalled cannot offer to
 * reinstall it in place -- installing belongs here, and a second install path
 * is the kind of duplication that has already drifted twice in this project --
 * so it sends the user here instead, with the core it needs already chosen.
 *
 * Held rather than applied, because the catalog is very likely not loaded yet:
 * this panel caches it at module scope and the tab may never have been opened.
 * The effect below resolves the name once there is a catalog to resolve it in.
 */
let pendingCoreId = "";

/**
 * Panels waiting to hear about one, because arriving is not always a mount.
 *
 * A route component registered with `routerHook` can stay mounted between
 * visits, so navigating to a tab that is already showing changes nothing: no
 * remount, no new catalog, and an effect keyed to either never runs again. The
 * request would sit here unread and the button would look broken -- which is
 * how an auto-start effect on the transfer page failed once, and it looked
 * correct while doing it.
 *
 * So the request is announced as well as stored. Whichever of the two arrives
 * second does the work; `take` makes sure only one of them does.
 */
const arrivals = new Set<() => void>();

export function preselectCore(coreId: string) {
  pendingCoreId = coreId;
  for (const listener of [...arrivals]) listener();
}

/** The pending core id, exactly once. "" for every reader after the first. */
function take() {
  const wanted = pendingCoreId;
  pendingCoreId = "";
  return wanted;
}

/**
 * The nearest ancestor that actually scrolls, or null.
 *
 * Steam's page is a stack of `overflow: visible` divs with one `DialogContent`
 * doing the scrolling several levels up, so "the scroll container" has to be
 * found rather than assumed.
 */
function scrollableAncestor(node: HTMLElement): HTMLElement | null {
  let parent = node.parentElement;
  while (parent) {
    const style = getComputedStyle(parent);
    // The height test matters: a container can be `auto` and have nothing to
    // scroll, and scrolling that one does nothing while looking like success.
    if (/(auto|scroll)/.test(style.overflowY) && parent.scrollHeight > parent.clientHeight + 4) {
      return parent;
    }
    parent = parent.parentElement;
  }
  return null;
}

export function CoreInstallPanel({ onCoresChanged, reloadKey = 0 }: Props) {
  const [catalog, setCatalog] = useState<InstallableCore[] | null>(cachedCatalog);
  const [system, setSystem] = useState(lastSystem);
  const [coreId, setCoreId] = useState(lastCoreId);
  const [busy, setBusy] = useState("");
  // The section wrapper, so a deliberate arrival can scroll to it. A plain
  // div rather than a ref on PanelSection: that is Steam's component and
  // forwards nothing, so there is no node of its own to reach.
  const section = useRef<HTMLDivElement>(null);
  // The install row, when there is one -- see the arrival effect.
  const installRow = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (refresh: boolean) => {
    setError("");
    try {
      const loaded = await callWithRetry(() => listInstallableCores(refresh), {
        attempts: 2,
        ms: 30000,
      });
      cachedCatalog = loaded;
      setCatalog(loaded);
    } catch (loadError) {
      console.error("[deckyemu] could not load core catalog", loadError);
      setError("Could not reach the libretro buildbot.");
      setCatalog([]);
    }
  }, []);

  useEffect(() => {
    // Only hit the backend when we have nothing cached, or after an install
    // changed the installed flags.
    if (cachedCatalog === null) void load(false);
  }, [load]);

  // Something outside this panel changed what is installed — today that is the
  // development Reset tab. The cache is module-level and outlives the panel, so
  // without this it kept offering to remove a core that had been deleted, and
  // only "Refresh catalog" put it right.
  useEffect(() => {
    if (reloadKey) void load(false);
  }, [reloadKey, load]);

  /**
   * Show the core somebody navigated here to install.
   *
   * Consumed rather than remembered: it describes one arrival, and leaving it
   * set would drag the list back to that core every time this tab is opened
   * afterwards.
   */
  const showRequestedCore = useCallback((available: InstallableCore[] | null) => {
    if (!pendingCoreId || !available) return;
    // Taken once, before the search: inside the predicate it would be read per
    // element and cleared by the first, so only a core that happened to be at
    // the front of the catalog would ever match.
    const wantedId = take();
    const wanted = available.find((core) => core.id === wantedId);
    if (!wanted) return;
    setSystem(wanted.system_name);
    lastSystem = wanted.system_name;
    setCoreId(wanted.id);
    lastCoreId = wanted.id;

    // Bring it into view. This section sits below RetroArch's status and its
    // launch settings, so on a Deck it is off-screen when the tab opens --
    // arriving here from "Install this core" would land on a page that looks
    // like it ignored the request. Only on a deliberate arrival: scrolling a
    // tab somebody opened themselves would take it away from the top.
    //
    // Focus first, then scroll, and the order is the point. Steam's gamepad
    // focus manager scrolls whatever is focused into view, and after this
    // navigation that is the sidebar near the top of the page -- so a scroll
    // on its own was performed and then undone, leaving the section halfway
    // down the screen. Measured over CEF: scrollTop moved to 68 and came back
    // to 75 with `document.activeElement` reading "RetroArch".
    //
    // Moving focus into the section makes Steam's scroll agree with this one
    // instead of fighting it, and it is where the gamepad should be anyway --
    // the user came here to pick a core, not to read a heading.
    //
    // `start` rather than `center`, so the heading lands at the top of what
    // was scrolled to. No `smooth`: an animated scroll is still running when
    // Steam settles focus, and the last write wins.
    //
    // After paint, or the section is measured where it has not been drawn yet.
    // Two frames, not one: the state set just above has to render before the
    // install row exists to be focused, and a single frame can run before that
    // commit has painted.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const node = section.current;
      if (!node) return;
      // The install button, which is why anyone arrived. Falling back to the
      // section's first control when the core turns out to be installed
      // already -- the row is absent then, and the alternative is Remove.
      const target = installRow.current ?? node;
      target.querySelector<HTMLElement>(".Focusable, button, [tabindex]")?.focus();

      // Then the scroll position, by hand. `scrollIntoView` does not move this
      // page: measured over CEF, the section sat at y=290 with the scroller at
      // scrollTop 68, and calling it with `block: "start"` left both exactly
      // where they were. Assigning the offset directly puts the heading at the
      // top of the scrollport and it stays there.
      const scroller = scrollableAncestor(node);
      if (scroller) {
        scroller.scrollTop +=
          node.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
      }
    }));
  }, []);

  // Arriving by mount, or by catalog finally loading under a request that was
  // waiting for one.
  useEffect(() => {
    showRequestedCore(catalog);
  }, [catalog, showRequestedCore]);

  // Arriving without a mount, which is what happens when this tab was already
  // the one showing. `cachedCatalog` rather than `catalog`: this closes over
  // the value at subscribe time, and the cache is the current one.
  useEffect(() => {
    const listener = () => showRequestedCore(cachedCatalog);
    arrivals.add(listener);
    return () => {
      arrivals.delete(listener);
    };
  }, [showRequestedCore]);

  const systems = useMemo(() => {
    if (!catalog) return [];
    const names = new Set(catalog.map((core) => core.system_name).filter(Boolean));
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [catalog]);

  const systemOptions: SingleDropdownOption[] = useMemo(
    () => systems.map((name) => ({ data: name, label: name })),
    [systems],
  );

  const coresForSystem = useMemo(
    () => (catalog ?? []).filter((core) => core.system_name === system),
    [catalog, system],
  );

  const coreOptions: SingleDropdownOption[] = useMemo(
    () =>
      coresForSystem.map((core) => ({
        data: core.id,
        label: core.installed ? `${core.display_name} (installed)` : core.display_name,
      })),
    [coresForSystem],
  );

  const selected = coresForSystem.find((core) => core.id === coreId);

  const onSystemChange = useCallback(
    (option: SingleDropdownOption) => {
      const next = String(option.data);
      setSystem(next);
      lastSystem = next;
      const first = (catalog ?? []).find((core) => core.system_name === next);
      setCoreId(first?.id ?? "");
      lastCoreId = first?.id ?? "";
    },
    [catalog],
  );

  const doInstall = useCallback(async () => {
    if (!selected) return;
    setBusy(selected.id);
    setError("");
    try {
      const result = await installCore(selected.id);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      toaster.toast({
        title: `Installed ${selected.display_name}`,
        body: `${result.core_count} core(s) now available`,
      });
      await load(false);
      onCoresChanged();
    } catch (installError) {
      console.error("[deckyemu] core install failed", installError);
      setError("Install failed. Check the plugin log for details.");
    } finally {
      setBusy("");
    }
  }, [selected, load, onCoresChanged]);

  const doUninstall = useCallback(async () => {
    if (!selected) return;
    setBusy(selected.id);
    setError("");
    try {
      const result = await uninstallCore(selected.id);
      if (!result.ok) {
        setError(result.error ?? "Could not remove the core.");
        return;
      }
      toaster.toast({
        title: `Removed ${selected.display_name}`,
        body: `${result.core_count ?? 0} core(s) remaining`,
      });
      await load(false);
      onCoresChanged();
    } finally {
      setBusy("");
    }
  }, [selected, load, onCoresChanged]);

  if (!catalog) {
    return (
      <PanelSection title="Install cores">
        <PanelSectionRow>
          <Field label="Loading core catalog">
            <Spinner style={{ height: "20px" }} />
          </Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <div ref={section}>
    <PanelSection title="Install cores">
      <PanelSectionRow>
        <DropdownItem
          label="System"
          description={`${catalog.length} cores across ${systems.length} systems`}
          rgOptions={systemOptions}
          selectedOption={system}
          onChange={onSystemChange}
          disabled={Boolean(busy)}
        />
      </PanelSectionRow>

      {system && (
        <PanelSectionRow>
          <DropdownItem
            label="Core"
            rgOptions={coreOptions}
            selectedOption={coreId}
            onChange={(option) => {
              setCoreId(String(option.data));
              lastCoreId = String(option.data);
            }}
            disabled={Boolean(busy) || coreOptions.length === 0}
          />
        </PanelSectionRow>
      )}

      {selected && (
        <PanelSectionRow>
          <Field
            label="Handles"
            description={selected.extensions.map((ext) => `.${ext}`).join(" ")}
          />
        </PanelSectionRow>
      )}

      {error && (
        <PanelSectionRow>
          <div style={{ color: "#e35d5d", fontSize: "13px", padding: "4px 0" }}>{error}</div>
        </PanelSectionRow>
      )}

      {selected && !selected.installed && (
        // Wrapped so an arrival can put the gamepad straight on it. Only the
        // install row: focusing "Remove this core" would leave the cursor on a
        // destructive button nobody asked for.
        <div ref={installRow}>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={doInstall} disabled={Boolean(busy)}>
              {busy === selected.id ? "Installing..." : `Install ${selected.display_name}`}
            </ButtonItem>
          </PanelSectionRow>
        </div>
      )}

      {selected?.installed && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={doUninstall} disabled={Boolean(busy)}>
            {busy === selected.id ? "Removing..." : "Remove this core"}
          </ButtonItem>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => void load(true)} disabled={Boolean(busy)}>
          Refresh catalog
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
    </div>
  );
}
