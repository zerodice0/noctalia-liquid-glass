#!/usr/bin/env python3
"""Check actual xdg windows, generic opacity and game exemptions off-screen."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from PIL import Image, ImageChops
from render import ROOT, BINARY, CLIENT, ARTIFACTS, pixels


def run_case(content_type):
    with tempfile.TemporaryDirectory(prefix="glass-window-") as directory:
        temp = Path(directory)
        env = dict(os.environ)
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DBUS_SESSION_BUS_ADDRESS", "UMBRIEL_SOCKET"):
            env.pop(key, None)
        env.update(XDG_RUNTIME_DIR=str(temp), WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1", WLR_LIBINPUT_NO_DEVICES="1")
        conf = temp / "config.toml"
        config_text = subprocess.check_output([str(ROOT / ".venv/bin/python"), "-c",
            'import sys,tomlkit; sys.path.insert(0,sys.argv[1]); from theme import profile; '
            'p=profile("desktop"); c=p["umbriel"]; '
            'c["general"]={"autostart":[],"xwayland":False,"show_cheatsheet":False}; '
            'c["animation"]={"enabled":False}; '
            'c["appearance"]["blur"]["noise"]=0.0; '
            'c["window_rule"]=[dict(p["window_defaults"],default_floating=True,default_size=[600,340])]+c["window_rule"]; '
            'print(tomlkit.dumps(c))', str(ROOT / "scripts")], text=True)
        conf.write_text(config_text)
        processes, handles = [], []
        def spawn(command, name, extra=None):
            handle = (temp / f"{name}.log").open("w")
            handles.append(handle)
            proc = subprocess.Popen(command, env=env | (extra or {}), stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(proc)
            return proc
        try:
            server = spawn([str(BINARY), "-c", str(conf)], "compositor")
            for _ in range(150):
                if (temp / "wayland-0").exists():
                    break
                assert server.poll() is None
                time.sleep(0.03)
            env.update(WAYLAND_DISPLAY="wayland-0", UMBRIEL_SOCKET=str(temp / "umbriel-wayland-0.sock"))
            spawn([str(CLIENT), "HEADLESS-1", "0"], "background")
            spawn([str(ROOT / ".build/umbriel/build/tests/unmap-client"), "glass-window", "600", "340"], "window",
                  {"APP_ID": "glass.test.ordinary", "CONTENT_TYPE": content_type})
            for _ in range(100):
                windows = subprocess.check_output([str(BINARY), "windows"], env=env, text=True)
                if "glass-window" in windows:
                    break
                time.sleep(0.03)
            assert "glass-window" in windows, "No mapped test window"
            time.sleep(0.3)
            def capture(label, strength):
                conf.write_text(config_text.replace("glass_strength = 38.0", f"glass_strength = {strength:.1f}"))
                subprocess.run([str(BINARY), "msg", "config-reload"], env=env, check=True, capture_output=True)
                time.sleep(0.3)
                path = ARTIFACTS / f"window-{content_type}-{label}.png"
                subprocess.run(["grim", str(path)], env=env, check=True)
                return Image.open(path).convert("RGB")
            off = capture("off", 0)
            on = capture("on", 38)
            restored = capture("restored", 0)
            changed = sum(any(pixel) for pixel in pixels(ImageChops.difference(off, on)))
            assert ImageChops.difference(off, restored).getbbox() is None
            if content_type == "game":
                assert changed == 0, changed
            else:
                assert changed > 100, changed
            log = (temp / "compositor.log").read_text()
            assert "GL_INVALID" not in log and "Could not link" not in log
            print(f"PASS xdg window content={content_type}: {changed} refracted pixels; exact restoration")
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
            for path in temp.glob("*.log"):
                (ARTIFACTS / f"window-{content_type}-{path.name}").write_text(path.read_text())


if __name__ == "__main__":
    run_case("none")
    run_case("game")
