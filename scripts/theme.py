#!/usr/bin/env python3
"""Portable appearance profiles; private, local backups; no session restarts."""
import argparse
import base64
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

import tomlkit

REPO = Path(__file__).resolve().parents[1]


def merge(dst, src):
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            merge(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)
    return dst


def leaves(data, prefix=()):
    for key, value in data.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            yield from leaves(value, path)
        else:
            yield path, value


def get(data, path):
    for key in path:
        if key not in data:
            return {"exists": False}
        data = data[key]
    return {"exists": True, "value": data.unwrap() if hasattr(data, "unwrap") else data}


def put(doc, path, record):
    cursor = doc
    for key in path[:-1]:
        if key not in cursor:
            if not record["exists"]:
                return
            cursor[key] = tomlkit.table()
        cursor = cursor[key]
    if record["exists"]:
        cursor[path[-1]] = record["value"]
    elif path[-1] in cursor:
        del cursor[path[-1]]


def read_toml(path):
    return tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()


def profile(name, seen=()):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name) or name in seen:
        raise ValueError("Invalid profile name or inheritance cycle")
    data = read_toml(REPO / "profiles" / f"{name}.toml").unwrap()
    if not data:
        raise ValueError(f"Profile not found: {name}")
    parent = data.pop("extends", None)
    return merge(profile(parent, (*seen, name)) if parent else {}, data)


def resolve_umbriel(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve(strict=True)
    if path in seen:
        return {}
    seen.add(path)
    data = read_toml(path).unwrap()
    merged = {}
    for item in data.pop("include", {}).get("files", []):
        child = Path(os.path.expandvars(os.path.expanduser(item)))
        merge(merged, resolve_umbriel(child if child.is_absolute() else path.parent / child, seen))
    return merge(merged, data)


def atomic(path, data, mode=0o600):
    # Follow an existing symlink deliberately, preserving dotfile-manager links.
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".glass-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data if isinstance(data, bytes) else data.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def snapshot(paths, directory):
    directory.mkdir(parents=True, mode=0o700)
    records = {}
    for path in paths:
        records[str(path)] = ({"data": base64.b64encode(path.read_bytes()).decode(),
                               "mode": path.stat().st_mode & 0o777}
                              if path.exists() else None)
    atomic(directory / "files.json", json.dumps(records, indent=2))
    return records


class Theme:
    def __init__(self):
        home = Path.home()
        self.config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        self.state_root = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
        self.state = self.state_root / "noctalia-liquid-glass"
        self.settings = Path(os.environ.get("NOCTALIA_STATE_HOME", self.state_root)) / "noctalia/settings.toml"
        self.base = self.config / "umbriel/config.toml"
        if not self.base.exists():
            self.base = Path("/usr/share/umbriel/config.toml")
        self.overlay = self.config / "noctalia-liquid-glass/umbriel.toml"
        data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
        self.prefix = Path(os.environ.get("GLASS_PREFIX", data / "noctalia-liquid-glass/runtime"))
        self.binary = self.prefix / "bin/umbriel"
        self.launcher = home / ".local/bin/umbriel-liquid-glass"
        self.service = self.config / "systemd/user/umbriel.service.d/90-liquid-glass.conf"
        self.active = self.state / "active.json"
        self.baseline = self.state / "baseline.json"

    def candidates(self, name):
        selected = profile(name)
        settings = read_toml(self.settings)
        if self.baseline.exists():
            for item in json.loads(self.baseline.read_text())["keys"]:
                put(settings, tuple(item["path"]), item["before"])
        for path, value in leaves(selected["noctalia"]):
            put(settings, path, {"exists": True, "value": value})
        compositor = copy.deepcopy(selected["umbriel"])
        # Umbriel replaces arrays across includes. Preserve ALL existing rules
        # before appending our namespace-specific rule.
        base = resolve_umbriel(self.base)
        for kind in ("layer_rule", "window_rule"):
            if kind in compositor:
                compositor[kind] = base.get(kind, []) + compositor[kind]
        compositor["include"] = {"files": [str(self.base)]}
        launcher = ("#!/bin/sh\n"
                    f"binary={shlex.quote(str(self.binary))}\n"
                    f"config={shlex.quote(str(self.overlay))}\n"
                    'if [ -x "$binary" ] && "$binary" validate -c "$config" >/dev/null 2>&1; then\n'
                    '  exec "$binary" -c "$config" "$@"\n'
                    'fi\n'
                    "echo 'Liquid Glass runtime unavailable; starting packaged Umbriel.' >&2\n"
                    'exec /usr/bin/umbriel "$@"\n')
        service_path = str(self.launcher).replace("%", "%%").replace('"', '\\"')
        service = f'[Service]\nExecStart=\nExecStart="{service_path}"\n'
        return selected, {
            self.settings: tomlkit.dumps(settings),
            self.overlay: tomlkit.dumps(compositor),
            self.launcher: launcher,
            self.service: service,
        }

    def validate(self, writes):
        if not self.binary.exists():
            raise ValueError(f"Install the built runtime first: {self.binary}")
        with tempfile.TemporaryDirectory(prefix="glass-validate-") as temp:
            settings = Path(temp) / "noctalia.toml"
            compositor = Path(temp) / "umbriel.toml"
            settings.write_text(writes[self.settings])
            compositor.write_text(writes[self.overlay])
            subprocess.run(["noctalia", "config", "validate", str(settings)], check=True)
            subprocess.run([str(self.binary), "validate", "-c", str(compositor)], check=True)

    def backup(self, paths):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        folder = self.state / "backups" / stamp
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        records = snapshot(paths, folder)
        print(f"Local backup: {folder}")
        return folder, records

    def apply(self, name, dry_run=False):
        selected, writes = self.candidates(name)
        self.validate(writes)
        print(f"Profile: {name}")
        for path in writes:
            print(f"  {path}")
        if dry_run:
            print("Validation passed; no active configuration changed.")
            return
        folder, records = self.backup(writes)
        if not self.baseline.exists():
            original = read_toml(self.settings)
            # Union of all built-in profile keys makes switching lossless.
            paths = set()
            for standard in ("desktop", "gpd", "frosted", name):
                paths.update(path for path, _ in leaves(profile(standard)["noctalia"]))
            baseline = {"settings": str(self.settings),
                        "keys": [{"path": list(path), "before": get(original, path)} for path in sorted(paths)],
                        "files": {key: value for key, value in records.items() if key != str(self.settings)}}
            atomic(self.baseline, json.dumps(baseline, indent=2))
        else:
            baseline = json.loads(self.baseline.read_text())
            known = {tuple(item["path"]) for item in baseline["keys"]}
            if any(path not in known for path, _ in leaves(selected["noctalia"])):
                raise ValueError("New profile controls additional keys. Restore the baseline first, then apply it.")
        # Roll back all files on a write failure; keep the backup for inspection.
        try:
            for path, content in writes.items():
                atomic(path, content, 0o755 if path == self.launcher else 0o600)
        except Exception:
            self.restore_files(records)
            raise
        atomic(self.active, json.dumps({"profile": name, "backup": str(folder),
                                       "hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in writes}}, indent=2))
        self.reload()
        print("Appearance applied. Patched compositor is selected for the next Umbriel login.")
        print("No running compositor or applications were restarted.")

    @staticmethod
    def restore_files(records):
        for name, record in records.items():
            path = Path(name)
            if record is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, base64.b64decode(record["data"]), record["mode"])

    def restore(self):
        if not self.baseline.exists():
            raise ValueError("No installed theme baseline to restore")
        baseline = json.loads(self.baseline.read_text())
        settings = read_toml(self.settings)
        for item in baseline["keys"]:
            put(settings, tuple(item["path"]), item["before"])
        # Back up the current theme before reverting. Preserve unrelated GUI
        # changes by reverting only the appearance keys we managed.
        self.backup([self.settings, *map(Path, baseline["files"])])
        atomic(self.settings, tomlkit.dumps(settings))
        restored_files = copy.deepcopy(baseline["files"])
        # Keep a valid passthrough config for an already-running patched
        # compositor. Removing its pinned -c file would leave a diagnostics
        # banner and retain the last glass settings until logout.
        if restored_files.get(str(self.overlay)) is None:
            passthrough = tomlkit.dumps({"include": {"files": [str(self.base)]}})
            restored_files[str(self.overlay)] = {"data": base64.b64encode(passthrough.encode()).decode(), "mode": 0o600}
        self.restore_files(restored_files)
        self.active.unlink(missing_ok=True)
        self.baseline.unlink()
        self.reload()
        print("Original appearance and session command restored; backups remain local.")
        print("The packaged compositor will run on your next login.")

    @staticmethod
    def reload():
        # Daemon reload changes the next ExecStart only. Never stop the session.
        if os.environ.get("GLASS_NO_RELOAD") != "1":
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    def save(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
            raise ValueError("Invalid profile name")
        target = REPO / "profiles" / f"{name}.toml"
        if target.exists():
            raise ValueError(f"Profile already exists: {target}")
        # Export appearance allowlist only, never wallpaper paths, accounts,
        # monitor names, shortcuts, clipboard, or complete state directories.
        effective = tomlkit.parse(subprocess.check_output(["noctalia", "config", "export", "full"], text=True)).unwrap()
        allowed = profile("desktop")["noctalia"]
        merge(allowed, profile("gpd")["noctalia"])
        saved = {}
        for path, _ in leaves(allowed):
            record = get(effective, path)
            if record["exists"]:
                put(saved, path, record)
        compositor = resolve_umbriel(self.overlay if self.overlay.exists() else self.base)
        data = {"noctalia": saved, "umbriel": {"appearance": compositor.get("appearance", {})}}
        # A theme saved from stock Umbriel must disable refraction explicitly.
        data["umbriel"]["appearance"].setdefault("blur", {}).setdefault("glass_strength", 0.0)
        atomic(target, tomlkit.dumps(data), 0o644)
        print(f"Portable appearance profile saved: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("apply", "plan", "save"):
        sub = commands.add_parser(command)
        sub.add_argument("profile")
    commands.add_parser("restore")
    commands.add_parser("status")
    args = parser.parse_args()
    theme = Theme()
    if args.command in ("apply", "plan"):
        theme.apply(args.profile, args.command == "plan")
    elif args.command == "restore":
        theme.restore()
    elif args.command == "save":
        theme.save(args.profile)
    else:
        print(theme.active.read_text() if theme.active.exists() else "No managed theme active.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
