#!/bin/sh
# Run once on a development Deck: lets this user restart Decky's plugin_loader
# without a password, and nothing else, so scripts/deploy-plugin.sh can finish
# on its own. Undo with: sudo rm /etc/sudoers.d/zz-deckyemu-dev
#
# Named to sort last: sudo applies the last matching rule, and the wheel
# group's password rule would otherwise win.
set -e
RULE="$(id -un) ALL=(root) NOPASSWD: /usr/bin/systemctl restart plugin_loader"
TMP="$(mktemp)"
echo "$RULE" > "$TMP"
sudo visudo -cf "$TMP" >/dev/null
sudo install -m 0440 -o root -g root "$TMP" /etc/sudoers.d/zz-deckyemu-dev
sudo rm -f /etc/sudoers.d/deckyemu-dev
rm -f "$TMP"
echo "Done. Deploys now restart plugin_loader without asking."
