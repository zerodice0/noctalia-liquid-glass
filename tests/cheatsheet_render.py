#!/usr/bin/env python3
"""Check the compositor-owned guide over a busy background in a private session."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from PIL import Image, ImageChops
from render import ARTIFACTS, BINARY, CLIENT, pixels


def run():
    with tempfile.TemporaryDirectory(prefix="glass-cheatsheet-") as directory:
        temp = Path(directory)
        env = dict(os.environ)
        for key in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "UMBRIEL_SOCKET"):
            env.pop(key, None)
        env.update(XDG_RUNTIME_DIR=str(temp), WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1", WLR_LIBINPUT_NO_DEVICES="1")
        config = temp / "config.toml"
        def configure(blur, strength, optimized=False):
            config.write_text(f'''[general]
xwayland = false
show_cheatsheet = false
autostart = []
[animation]
enabled = false
[appearance]
corner_radius = 24
[appearance.blur]
enabled = {str(blur).lower()}
optimized = {str(optimized).lower()}
passes = 2
radius = 7
noise = 0.0
brightness = 1.0
contrast = 1.0
saturation = 1.0
glass_strength = {strength}
glass_edge = 28.0
glass_dispersion = 0.035
glass_highlight = 0.32
[colors]
background = "#2B333E52"
text_primary = "#50FF80"
[keybinds]
"Super+slash" = "cheatsheet-toggle"
"Super+Q" = "window-close"
"Super+F" = "window-toggle-fullscreen"
''')
        configure(False, 0.0)
        subprocess.run([str(BINARY), 'validate', '-c', str(config)], env=env, check=True, capture_output=True)
        children, logs = [], []
        def spawn(args, label, extra=None):
            handle = (temp / (label + '.log')).open('w')
            logs.append(handle)
            child = subprocess.Popen(args, env=env | (extra or {}), stdout=handle,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            children.append(child)
            return child
        def msg(action):
            subprocess.run([str(BINARY), 'msg', action], env=env, check=True, capture_output=True)
        def shot(label):
            time.sleep(0.4)
            path = ARTIFACTS / ('cheatsheet-' + label + '.png')
            subprocess.run(['grim', str(path)], env=env, check=True)
            return Image.open(path).convert('RGB')
        server = spawn([str(BINARY), '-c', str(config)], 'compositor')
        try:
            for _ in range(200):
                if (temp / 'wayland-0').exists():
                    break
                if server.poll() is not None:
                    raise AssertionError((temp / 'compositor.log').read_text())
                time.sleep(0.05)
            else:
                raise AssertionError('Compositor did not start')
            env.update(WAYLAND_DISPLAY='wayland-0', UMBRIEL_SOCKET=str(temp / 'umbriel-wayland-0.sock'))
            spawn([str(CLIENT), 'HEADLESS-1', '0'], 'background')
            spawn([str(CLIENT), 'HEADLESS-1', '0'], 'card', {'GLASS_CARD': '1'})
            for _ in range(100):
                if all('ready' in (temp / (name + '.log')).read_text() for name in ('background', 'card')):
                    break
                time.sleep(0.03)
            else:
                raise AssertionError('Fixture clients did not map')
            original = shot('hidden')
            msg('cheatsheet-open')
            sharp = shot('sharp')
            configure(True, 0.0)
            msg('config-reload')
            blurred = shot('blurred')
            configure(True, 24.0)
            msg('config-reload')
            glass = shot('glass')
            blur_diff = ImageChops.difference(sharp, blurred)
            glass_diff = ImageChops.difference(blurred, glass)
            blur_count = sum(any(p) for p in pixels(blur_diff))
            glass_count = sum(any(p) for p in pixels(glass_diff))
            assert blur_count > 1000, f'Guide backdrop was not blurred: {blur_count}'
            assert glass_count > 100, f'Guide rim did not refract: {glass_count}'
            text = [(x, y) for y in range(sharp.height) for x in range(sharp.width)
                    if sharp.getpixel((x, y)) == (80, 255, 128)]
            assert len(text) > 50, 'Missing opaque foreground text'
            assert all(glass.getpixel(point) == (80, 255, 128) for point in text), 'Guide text was distorted'
            configure(True, 24.0, optimized=True)
            msg('config-reload')
            cached_config = shot('optimized-config')
            assert ImageChops.difference(glass, cached_config).getbbox() is None, 'Guide stopped using the live backdrop'
            configure(False, 0.0)
            msg('config-reload')
            restored = shot('restored')
            assert ImageChops.difference(sharp, restored).getbbox() is None, 'Blur toggle was not reversible'
            msg('cheatsheet-close')
            hidden = shot('hidden-again')
            assert ImageChops.difference(original, hidden).getbbox() is None, 'Hiding guide left effects behind'
            log = (temp / 'compositor.log').read_text()
            assert 'GL_INVALID' not in log and 'Could not link' not in log, log
            result = {'blur_changed_pixels': blur_count, 'rim_changed_pixels': glass_count,
                      'unchanged_text_pixels': len(text), 'live_backdrop': True, 'reversible': True}
            (ARTIFACTS / 'cheatsheet-results.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result))
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
            for handle in logs:
                handle.close()


if __name__ == '__main__':
    run()
