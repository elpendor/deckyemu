import { TAB_KEY } from "../preload/bridge";
import { Navigation } from "../steamui/navigation";

/** Open the Quick Access menu on our tab. */
export function openPanel(): void {
  Navigation.OpenQuickAccessMenu(TAB_KEY);
}
