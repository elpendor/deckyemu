/**
 * Steam's own UI pieces, as the loader's library finds them, plus DeckyEmu's
 * own copies of the ones Steam updates break most (src/ui). The service build
 * has its own; the rest of src/ imports from here on both.
 *
 * Named, never `export *`: the build turns imports of the library into reads
 * of the loader's global, and it cannot rewrite an `export *`, which then
 * reaches Steam as a bare import it fails to resolve.
 */

export {
  afterPatch,
  DialogButton,
  DialogButtonPrimary,
  DialogButtonSecondary,
  fakeRenderComponent,
  findInReactTree,
  findInTree,
  findModuleByExport,
  Focusable,
  GamepadButton,
  getReactRoot,
  MenuGroup,
  MenuItem,
  Navigation,
  QuickAccessTab,
  quickAccessMenuClasses,
  showModal,
  TextField,
  ToggleField,
} from "@decky/ui";
export type { GamepadEvent, Patch, ShowModalResult } from "@decky/ui";
export { playNavSound, type NavSound } from "../../src/steamui/sound";

// DeckyEmu's own copies of the controls Steam updates break most: src/ui.
export {
  ButtonItem,
  ConfirmModal,
  DialogBody,
  DialogBodyText,
  DialogFooter,
  DialogHeader,
  Dropdown,
  DropdownItem,
  Field,
  ModalRoot,
  PanelSection,
  PanelSectionRow,
  SidebarNavigation,
  Spinner,
  Tabs,
} from "../../src/ui";
export type { DropdownOption, SingleDropdownOption } from "../../src/ui";
