#!/bin/sh
# Run once on a development Deck: lets this user restart Decky's plugin_loader
# without a password, and nothing else, so scripts/deploy-plugin.sh can finish
# on its own. Undo with: sudo rm /etc/sudoers.d/deckyemu-dev
set -e
RULE="$(id -un) ALL=(root) NOPASSWD: /usr/bin/systemctl restart plugin_loader"
TMP="$(mktemp)"
echo "$RULE" > "$TMP"
sudo visudo -cf "$TMP" >/dev/null
sudo install -m 0440 -o root -g root "$TMP" /etc/sudoers.d/deckyemu-dev
rm -f "$TMP"
echo "Done. Deploys now restart plugin_loader without asking."
