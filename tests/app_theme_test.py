#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import app_theme
from theme import Theme, atomic, read_toml
import tomlkit


class AppThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glass apps test ")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        env = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config"),
                                    "XDG_STATE_HOME": str(root / "state"),
                                    "NOCTALIA_STATE_HOME": str(root / "state"),
                                    "HERDR_CONFIG_PATH": str(root / "custom herdr/config.toml"),
                                    "GLASS_NO_RELOAD": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.theme = Theme()
        self.apps = app_theme.AppTheme(self.theme)

    def test_apply_reapply_restore_preserves_personal_edits(self):
        original_ghostty = '# personal\nfont-size = 11\ntheme = Nord\nbackground-opacity = 0.38\n'
        atomic(self.theme.ghostty, original_ghostty)
        atomic(self.apps.herdr, '[theme]\nname = "tokyo-night"\n[theme.custom]\nred = "#ff0000"\n[keys]\nprefix = "ctrl+p"\n')
        atomic(self.theme.settings, '[theme]\nsource = "builtin"\nbuiltin = "Nord"\nmode = "dark"\n[dock]\nmargin_edge = 0\nradius = 15\n')
        atomic(self.apps.palette, '{"previous": true}\n')
        with patch.object(self.apps, "validate"):
            self.apps.apply()
            first = self.apps.baseline.read_text()
            self.apps.apply()
            self.assertEqual(self.apps.baseline.read_text(), first)
        ghostty = self.theme.ghostty.read_text()
        self.assertEqual(ghostty.count(app_theme.BEGIN), 1)
        self.assertIn('background = #2B333E', self.apps.colors.read_text())
        self.assertEqual(app_theme.unmanaged(ghostty), original_ghostty)
        self.assertEqual(read_toml(self.apps.herdr)['theme']['custom']['panel_bg'], 'reset')
        self.assertFalse(read_toml(self.apps.herdr)['theme']['auto_switch'])
        self.assertEqual(read_toml(self.theme.settings)['dock']['radius'], 15)
        atomic(self.theme.ghostty, ghostty.replace('font-size = 11', 'font-size = 13'))
        herdr = read_toml(self.apps.herdr)
        herdr['keys']['prefix'] = 'ctrl+a'
        herdr['theme']['custom']['blue'] = '#abcdef'
        atomic(self.apps.herdr, tomlkit.dumps(herdr))
        self.apps.restore()
        self.assertEqual(self.theme.ghostty.read_text(), original_ghostty.replace('11', '13'))
        restored = read_toml(self.apps.herdr)
        self.assertEqual(restored['keys']['prefix'], 'ctrl+a')
        self.assertEqual(restored['theme']['name'], 'tokyo-night')
        self.assertEqual(restored['theme']['custom'], {'red': '#ff0000', 'blue': '#abcdef'})
        self.assertEqual(read_toml(self.theme.settings)['theme'], {'source': 'builtin', 'builtin': 'Nord', 'mode': 'dark'})
        self.assertEqual(json.loads(self.apps.palette.read_text()), {'previous': True})
        self.assertFalse(self.apps.template.exists())
        self.assertFalse(self.apps.colors.exists())
        self.assertFalse(self.apps.baseline.exists())

    def test_fresh_install_and_generated_ghostty_config(self):
        writes, _ = self.apps.candidates()
        self.apps.validate(writes)
        with patch.object(self.apps, 'validate'):
            self.apps.apply()
        self.assertTrue(self.theme.ghostty.exists())
        self.apps.restore()
        for path in (self.theme.ghostty, self.apps.herdr, self.theme.settings,
                     self.apps.palette, self.apps.template, self.apps.colors):
            self.assertFalse(path.exists(), path)

    def test_light_seed_and_malformed_block(self):
        palette = json.loads((self.apps.assets / 'palette.json').read_text())
        text = app_theme.seed_colors(palette, 'light')
        self.assertIn('background = #EFF3F5', text)
        self.assertNotIn('{{', text)
        with self.assertRaises(ValueError):
            app_theme.unmanaged(app_theme.BEGIN + '\nfont-size = 2\n')

    def test_failed_write_rolls_back_resources_and_settings(self):
        atomic(self.apps.herdr, '[keys]\nprefix = "ctrl+p"\n')
        original = self.apps.herdr.read_bytes()
        def fail(path, *args, **kwargs):
            if path == self.apps.herdr:
                raise OSError('simulated write failure')
            return atomic(path, *args, **kwargs)
        with patch.object(self.apps, 'validate'), patch.object(app_theme, 'atomic', side_effect=fail):
            with self.assertRaises(OSError):
                self.apps.apply()
        self.assertEqual(self.apps.herdr.read_bytes(), original)
        self.assertFalse(self.apps.palette.exists())
        self.assertFalse(self.apps.baseline.exists())
        self.assertFalse(self.theme.settings.exists())


if __name__ == '__main__':
    unittest.main()
