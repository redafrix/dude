#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command="bash -lc 'systemctl --user start dude.service && \"$repo_dir/.venv/bin/dude\" --config \"$repo_dir/configs/default.yaml\" arm'"
base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
slot="$base/dude/"
current="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"
bindings="$(python3 - <<'PY' "$current" "$slot"
import ast
import sys

current = ast.literal_eval(sys.argv[1])
slot = sys.argv[2]
if slot not in current:
    current.append(slot)
print(current)
PY
)"

gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$bindings"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$slot name "Dude Arm"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$slot command "$command"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$slot binding "<Alt>a"

printf 'Installed GNOME hotkey Alt+A for Dude.\n'
