#!/usr/bin/env python3
"""Run real Noctalia in a private compositor, D-Bus, and settings directory."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if "--private-bus" not in sys.argv:
    # The bus activation environment must also be isolated (e.g. dconf).
    with tempfile.TemporaryDirectory(prefix="glass-bus-") as bus_directory:
        bus_env = dict(os.environ)
        for key in ("GNOME_KEYRING_CONTROL", "SSH_AUTH_SOCK", "DBUS_SESSION_BUS_ADDRESS"):
            bus_env.pop(key, None)
        for kind in ("CONFIG", "STATE", "CACHE", "DATA"):
            bus_env[f"XDG_{kind}_HOME"] = str(Path(bus_directory) / kind.lower())
        raise SystemExit(subprocess.call(["dbus-run-session", "--", sys.executable, __file__, "--private-bus"], env=bus_env))

with tempfile.TemporaryDirectory(prefix="glass-shell-") as directory:
    temp = Path(directory)
    env = dict(os.environ)
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "UMBRIEL_SOCKET"):
        env.pop(key, None)
    env.update(XDG_RUNTIME_DIR=str(temp), WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1",
               WLR_LIBINPUT_NO_DEVICES="1", XDG_CONFIG_HOME=str(temp / "config"),
               XDG_STATE_HOME=str(temp / "state"), XDG_CACHE_HOME=str(temp / "cache"),
               NOCTALIA_CONFIG_HOME=str(temp / "config"), NOCTALIA_STATE_HOME=str(temp / "state"),
               DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent-glass-test-bus")
    config = temp / "umbriel.toml"
    config.write_text('''[general]
xwayland = false
show_cheatsheet = false
autostart = []
[animation]
enabled = false
[appearance.blur]
enabled = true
optimized = false
passes = 2
radius = 4
noise = 0.0
brightness = 1.0
contrast = 1.0
saturation = 1.0
glass_strength = 38.0
glass_edge = 52.0
glass_dispersion = 0.09
glass_highlight = 0.22
[[layer_rule]]
match.namespace = "^noctalia-.*$"
blur = true
blur_ignore_alpha = 0.2
blur_optimized = false
''')
    shell_config = Path(env["NOCTALIA_CONFIG_HOME"]) / "noctalia"
    shell_config.mkdir(parents=True)
    (shell_config / "00-base.toml").write_text('''[shell]
offline_mode = true
setup_wizard_enabled = false
polkit_agent = false
clipboard_enabled = false
telemetry_enabled = false
[wallpaper]
enabled = false
[theme]
source = "builtin"
builtin = "Noctalia"
[theme.templates]
enable_builtin_templates = false
enable_community_templates = false
[plugins]
enabled = []
auto_update = "none"
[notification]
enable_daemon = false
[location]
auto_locate = false
''')
    theme = subprocess.check_output([str(ROOT / ".venv/bin/python"), "-c",
        'import tomlkit,sys; print(tomlkit.dumps(tomlkit.load(open(sys.argv[1]))["noctalia"].unwrap()))',
        str(ROOT / "profiles/desktop.toml")], text=True)
    combined = subprocess.check_output([str(ROOT / ".venv/bin/python"), "-c",
        'import sys,tomlkit; sys.path.insert(0,sys.argv[1]); from theme import merge; '
        'base=tomlkit.load(open(sys.argv[2])).unwrap(); '
        'print(tomlkit.dumps(merge(base,tomlkit.parse(sys.stdin.read()).unwrap())))',
        str(ROOT / "scripts"), str(shell_config / "00-base.toml")], input=theme, text=True)
    (shell_config / "00-base.toml").unlink()
    (shell_config / "config.toml").write_text(combined)
    subprocess.run(["noctalia", "config", "validate"], env=env, check=True)
    processes = []
    handles = []
    def spawn(command, name):
        handle = (temp / f"{name}.log").open("w")
        handles.append(handle)
        proc = subprocess.Popen(command, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(proc)
        return proc
    binary = ROOT / ".build/umbriel/build/umbriel"
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    try:
        server = spawn([str(binary), "-c", str(config)], "shell-compositor")
        for _ in range(100):
            if (temp / "wayland-0").exists():
                break
            assert server.poll() is None, "Compositor exited"
            time.sleep(0.05)
        env.update(WAYLAND_DISPLAY="wayland-0", UMBRIEL_SOCKET=str(temp / "umbriel-wayland-0.sock"))
        spawn([str(ROOT / ".build/tests/glass-client"), "HEADLESS-1", "0"], "shell-background")
        shell = spawn(["noctalia"], "noctalia")
        for _ in range(150):
            assert shell.poll() is None, "Noctalia exited"
            status = subprocess.run(["noctalia", "msg", "status"], env=env, text=True, capture_output=True)
            if status.returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Noctalia startup timeout")
        subprocess.run(["noctalia", "msg", "panel-open", "launcher"], env=env, check=True, capture_output=True)
        time.sleep(1.0)
        state = json.loads(subprocess.check_output(["noctalia", "msg", "status"], env=env, text=True))
        assert state["activePanelId"] == "launcher", state
        subprocess.run(["grim", str(artifacts / "noctalia-glass.png")], env=env, check=True)
        # Capture the identical live shell with refraction disabled for comparison.
        config.write_text(config.read_text().replace("glass_strength = 38.0", "glass_strength = 0.0"))
        subprocess.run([str(binary), "msg", "config-reload"], env=env, check=True, capture_output=True)
        time.sleep(0.3)
        subprocess.run(["grim", str(artifacts / "noctalia-frosted.png")], env=env, check=True)
        log = (temp / "shell-compositor.log").read_text()
        assert "Could not link" not in log and "GL_INVALID" not in log, log
        shell_log = (temp / "noctalia.log").read_text()
        assert "no config files found" not in shell_log and "dock disabled in config" not in shell_log, shell_log
        print("PASS: real Noctalia bar, dock and launcher on a private Wayland/D-Bus session")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        for handle in handles:
            handle.close()
        for log in temp.glob("*.log"):
            (artifacts / log.name).write_text(log.read_text())
