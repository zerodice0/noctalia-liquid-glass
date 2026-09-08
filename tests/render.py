#!/usr/bin/env python3
"""Exercise the real compositor/GLSL against synthetic Wayland surfaces."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / ".build/umbriel/build/umbriel"
CLIENT = ROOT / ".build/tests/glass-client"
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


def pixels(image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def run_case(optimized, scale=1, transform="normal"):
    with tempfile.TemporaryDirectory(prefix="glass-render-") as directory:
        temp = Path(directory)
        env = dict(os.environ)
        for key in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "UMBRIEL_SOCKET"):
            env.pop(key, None)
        env.update(XDG_RUNTIME_DIR=str(temp), WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1", WLR_LIBINPUT_NO_DEVICES="1")
        config = temp / "config.toml"
        def configure(strength):
            config.write_text(f'''[general]
xwayland = false
show_cheatsheet = false
autostart = []
[animation]
enabled = false
[output.HEADLESS-1]
scale = {scale}
transform = "{transform}"
[appearance.blur]
enabled = true
optimized = {str(optimized).lower()}
passes = 1
radius = 1
noise = 0.0
brightness = 1.0
contrast = 1.0
saturation = 1.0
glass_strength = {strength:.1f}
glass_edge = 52.0
glass_dispersion = 0.20
glass_highlight = 0.0
[[layer_rule]]
match.namespace = "^glass-test-card$"
blur = true
blur_ignore_alpha = 0.2
blur_optimized = {str(optimized).lower()}
''')
        configure(0)
        processes = []
        handles = []
        def spawn(args, name, extra=None):
            log = (temp / f"{name}.log").open("w")
            handles.append(log)
            child = subprocess.Popen(args, env=env | (extra or {}), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(child)
            return child
        server = spawn([str(BINARY), "-c", str(config)], "compositor")
        try:
            for _ in range(200):
                if (temp / "wayland-0").exists():
                    break
                if server.poll() is not None:
                    raise AssertionError((temp / "compositor.log").read_text())
                time.sleep(0.05)
            else:
                raise AssertionError("Compositor socket timeout")
            env.update(WAYLAND_DISPLAY="wayland-0", UMBRIEL_SOCKET=str(temp / "umbriel-wayland-0.sock"))
            for name, extra in (("background", {}), ("card", {"GLASS_CARD": "1"})):
                spawn([str(CLIENT), "HEADLESS-1", "0"], name, extra)
                for _ in range(100):
                    if "ready" in (temp / f"{name}.log").read_text():
                        break
                    time.sleep(0.03)
                else:
                    raise AssertionError(f"{name}: " + (temp / f"{name}.log").read_text())
            label = f'{"cached" if optimized else "live"}-{scale}-{transform}'
            def capture(name, strength):
                configure(strength)
                subprocess.run([str(BINARY), "msg", "config-reload"], env=env, check=True, capture_output=True)
                time.sleep(0.30)
                file = ARTIFACTS / f"{label}-{name}.png"
                subprocess.run(["grim", str(file)], env=env, check=True)
                return Image.open(file).convert("RGB")
            before = capture("off", 0)
            after = capture("on", 48)
            restored = capture("restored", 0)
            diff = ImageChops.difference(before, after)
            changed = sum(any(p) for p in pixels(diff))
            assert changed > 1500, f"No meaningful refraction: {changed} changed pixels"
            assert ImageChops.difference(before, restored).getbbox() is None, "Disabling refraction did not exactly restore original rendering"
            foreground = [(x, y) for y in range(before.height) for x in range(before.width)
                          if before.getpixel((x, y)) == (255, 255, 255)]
            assert foreground, "Fixture has no foreground pixels"
            assert all(after.getpixel(p) == (255, 255, 255) for p in foreground), "Opaque foreground was distorted"
            color_split = sum(max(p) - min(p) > 12 for p in pixels(after))
            assert color_split > 50, "RGB dispersion did not produce visible channel separation"
            # Padding and regions outside the shell surface must be untouched.
            if scale == 1 and transform == "normal":
                for box in ((0, 0, 1280, 155), (0, 510, 1280, 720), (245, 170, 270, 480)):
                    assert diff.crop(box).getbbox() is None, "Glass leaked outside its alpha mask"
            log = (temp / "compositor.log").read_text()
            assert "Could not link" not in log and "GL_INVALID" not in log, log
            result = {"mode": label, "changed_pixels": changed, "unchanged_foreground_pixels": len(foreground), "chromatic_pixels": color_split}
            print(json.dumps(result), flush=True)
            return result
        except Exception:
            for log in temp.glob("*.log"):
                (ARTIFACTS / log.name).write_text(log.read_text())
            raise
        finally:
            for child in reversed(processes):
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
            for handle in handles:
                handle.close()


if __name__ == "__main__":
    results = [run_case(False), run_case(True), run_case(False, 1.5), run_case(False, 1, "90")]
    (ARTIFACTS / "render-results.json").write_text(json.dumps(results, indent=2))
    print("PASS: live and cached blur, fractional scaling, rotation, masks, foreground, and reversible toggle.")
