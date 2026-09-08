"""Install portable app colors without exporting or replacing personal settings."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import tomlkit

from theme import REPO, atomic, get, leaves, put, read_toml, snapshot

BEGIN = "# BEGIN noctalia-liquid-glass managed colors"
END = "# END noctalia-liquid-glass managed colors"
RELOAD_GHOSTTY = ["gdbus", "call", "--session", "--dest", "com.mitchellh.ghostty",
                  "--object-path", "/com/mitchellh/ghostty", "--method",
                  "org.gtk.Actions.Activate", "reload-config", "[]", "{}"]


def unmanaged(text):
    if BEGIN not in text and END not in text:
        return text
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("Malformed Ghostty managed colors block")
    result, count = re.subn(re.escape(BEGIN) + r"\n.*?" + re.escape(END) + r"\n?", "", text, flags=re.S)
    if count != 1:
        raise ValueError("Malformed Ghostty managed colors block")
    return result


def ghostty_path(path):
    value = str(path)
    if "\n" in value or "\r" in value:
        raise ValueError("Newlines are not supported in Ghostty include paths")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def seed_colors(palette, mode):
    terminal = palette[mode]["terminal"]
    colors = {}
    for group in ("normal", "bright"):
        for name, value in terminal[group].items():
            colors[f"terminal_{group}_{name}"] = value
    for token, key in {"background": "background", "foreground": "foreground",
                       "cursor": "cursor", "cursor_text": "cursorText",
                       "selection_bg": "selectionBg", "selection_fg": "selectionFg"}.items():
        colors[f"terminal_{token}"] = terminal[key]
    template = (REPO / "themes/glass-slate/ghostty.template").read_text()
    return re.sub(r"\{\{colors\.(\w+)\.default\.hex\}\}", lambda m: colors[m[1]], template)


class AppTheme:
    def __init__(self, theme):
        self.theme = theme
        self.baseline = theme.state / "apps-baseline.json"
        self.assets = REPO / "themes/glass-slate"
        self.palette = theme.config / "noctalia/palettes/glass-slate.json"
        self.template = theme.config / "noctalia-liquid-glass/ghostty.template"
        self.colors = theme.config / "noctalia-liquid-glass/ghostty.colors"
        self.herdr = Path(os.environ.get("HERDR_CONFIG_PATH", theme.config / "herdr/config.toml"))

    def candidates(self):
        palette_text = (self.assets / "palette.json").read_text()
        palette = json.loads(palette_text)
        settings = read_toml(self.theme.settings)
        mode = "light" if settings.get("theme", {}).get("mode") == "light" else "dark"
        updates = {
            self.theme.settings: {"theme": {"source": "custom", "custom_palette": "glass-slate",
                "templates": {"user": {"liquid_glass_ghostty": {
                    "enabled": True, "input_path": str(self.template), "output_path": str(self.colors),
                    # GTK action only: SIGUSR2 can terminate a starting Ghostty.
                    "post_hook": "gdbus call --session --dest com.mitchellh.ghostty "
                                 "--object-path /com/mitchellh/ghostty --method org.gtk.Actions.Activate "
                                 "reload-config '[]' '{}' >/dev/null 2>&1 || true",
                }}}}},
            self.herdr: read_toml(self.assets / "herdr.toml").unwrap(),
        }
        writes = {self.palette: palette_text, self.template: (self.assets / "ghostty.template").read_text(),
                  self.colors: seed_colors(palette, mode)}
        for path, values in updates.items():
            doc = read_toml(path)
            for key, value in leaves(values):
                put(doc, key, {"exists": True, "value": value})
            writes[path] = tomlkit.dumps(doc)
        original = self.theme.ghostty.read_text() if self.theme.ghostty.exists() else ""
        content = unmanaged(original)
        # Keep the entire existing config, including the independent opacity block.
        if content and not content.endswith("\n"):
            content += "\n"
        writes[self.theme.ghostty] = (content + BEGIN + "\nconfig-file = " + ghostty_path(self.colors)
                                     + "\n" + END + "\n")
        return writes, updates

    def validate(self, writes):
        for path in (self.theme.settings, self.herdr):
            tomlkit.parse(writes[path])
        with tempfile.TemporaryDirectory(prefix="glass-apps-validate-") as directory:
            temp = Path(directory)
            if self.theme.shell_binary.exists():
                config = temp / "noctalia.toml"
                config.write_text(writes[self.theme.settings])
                subprocess.run([str(self.theme.shell_binary), "config", "validate", str(config)], check=True)
            if shutil.which("ghostty"):
                color_file = temp / "colors"
                color_file.write_text(writes[self.colors])
                # Validate the generated include independently. Existing user
                # relative includes must retain their original directory.
                config = temp / "ghostty"
                config.write_text("config-file = " + ghostty_path(color_file) + "\n")
                subprocess.run(["ghostty", "+validate-config", f"--config-file={config}"], check=True)

    def apply(self):
        writes, updates = self.candidates()
        self.validate(writes)
        folder, records = self.theme.backup([*writes, self.baseline])
        baseline = json.loads(self.baseline.read_text()) if self.baseline.exists() else {
            "documents": {}, "files": {}, "ghostty": str(self.theme.ghostty),
            "ghostty_existed": self.theme.ghostty.exists(),
        }
        for path, values in updates.items():
            entry = baseline["documents"].setdefault(str(path), {"existed": path.exists(), "keys": []})
            known = {tuple(item["path"]) for item in entry["keys"]}
            original = read_toml(path)
            for key, _ in leaves(values):
                if key not in known:
                    entry["keys"].append({"path": list(key), "before": get(original, key)})
        for path in (self.palette, self.template, self.colors):
            baseline["files"].setdefault(str(path), records[str(path)])
        try:
            # Resources exist before the shell sees the template registration.
            for path, content in writes.items():
                atomic(path, content)
            atomic(self.baseline, json.dumps(baseline, indent=2))
        except Exception:
            self.theme.restore_files(records)
            raise
        print(f"Glass Slate app colors installed. Backup: {folder}")
        self.reload()

    def restore(self):
        if not self.baseline.exists():
            raise ValueError("No app theme baseline to restore")
        baseline = json.loads(self.baseline.read_text())
        ghostty = Path(baseline["ghostty"])
        paths = [*map(Path, baseline["documents"]), *map(Path, baseline["files"]), ghostty, self.baseline]
        folder, records = self.theme.backup(paths)
        try:
            for name, entry in baseline["documents"].items():
                path = Path(name)
                # Do not recreate a config the user has since removed.
                if not path.exists():
                    continue
                doc = read_toml(path)
                for item in entry["keys"]:
                    key = tuple(item["path"])
                    put(doc, key, item["before"])
                    if not item["before"]["exists"]:
                        # Remove newly emptied template/theme tables too.
                        for length in range(len(key) - 1, 0, -1):
                            parent = get(doc, key[:length])
                            if parent.get("value") == {}:
                                put(doc, key[:length], {"exists": False})
                if not entry["existed"] and not list(leaves(doc)):
                    path.unlink()
                else:
                    atomic(path, tomlkit.dumps(doc))
            if ghostty.exists():
                text = unmanaged(ghostty.read_text())
                if not text and not baseline["ghostty_existed"]:
                    ghostty.unlink()
                else:
                    atomic(ghostty, text)
            self.theme.restore_files(baseline["files"])
            self.baseline.unlink()
        except Exception:
            self.theme.restore_files(records)
            raise
        print(f"Original app colors restored; other settings preserved. Backup: {folder}")
        self.reload()

    def reload(self):
        if os.environ.get("GLASS_NO_RELOAD") == "1":
            return
        commands = [[str(self.theme.shell_binary), "msg", "config-reload"],
                    [str(self.theme.shell_binary), "msg", "templates-apply"],
                    RELOAD_GHOSTTY, ["herdr", "server", "reload-config"]]
        for command in commands:
            if not shutil.which(command[0]):
                continue
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                if result.returncode:
                    print(f"Could not reload {command[0]}; colors will apply when it next starts.")
            except subprocess.TimeoutExpired:
                print(f"Reload timed out: {command[0]}; configuration is saved.")
