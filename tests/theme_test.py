#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("theme", ROOT / "scripts/theme.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ThemeTests(unittest.TestCase):
    def test_apply_switch_restore_preserves_unrelated_settings_and_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(temp / "config"),
                                         "XDG_STATE_HOME": str(temp / "state"),
                                         "NOCTALIA_STATE_HOME": str(temp / "state"),
                                         "GLASS_NO_RELOAD": "1"}):
                base = temp / "config/umbriel/config.toml"
                base.parent.mkdir(parents=True)
                base_text = '[general]\nautostart = []\nxwayland = false\n[[layer_rule]]\nmatch.namespace = "^existing$"\nblur = false\n'
                base.write_text(base_text)
                theme = module.Theme()
                self.assertEqual(theme.settings, temp / "state/noctalia/settings.toml")
                theme.binary = ROOT / ".build/umbriel/build/umbriel"
                theme.shell_binary = ROOT / ".build/noctalia-diagnose/build/noctalia"
                theme.shell_launcher = temp / "bin/noctalia-liquid-glass"
                theme.launcher = temp / "bin/umbriel-liquid-glass"
                theme.ghostty.parent.mkdir(parents=True)
                ghost_original = '# Preserve Ghostty\nbackground-opacity = 0.8\nfont-size = 10\n'
                theme.ghostty.write_text(ghost_original)
                theme.settings.parent.mkdir(parents=True)
                original = '# Keep this comment\n[shell]\nfont_family = "Original Font"\n[wallpaper.default]\npath = "/private/wallpaper.jpg"\n[dock]\nbackground_opacity = 0.8\n'
                theme.settings.write_text(original)
                theme.apply("desktop", dry_run=True)
                self.assertEqual(theme.settings.read_text(), original)
                self.assertFalse(theme.baseline.exists())
                self.assertEqual(theme.ghostty.read_text(), ghost_original)
                theme.apply("desktop")
                self.assertIn("liquid_glass", module.read_toml(theme.settings)["theme"]["templates"]["user"])
                self.assertTrue(theme.material_template.exists())
                self.assertEqual(module.resolve_umbriel(theme.overlay)["colors"]["background"][-2:], "47")
                self.assertIn("background-opacity = 0.68", theme.ghostty.read_text())
                window_rules = module.resolve_umbriel(theme.overlay)["window_rule"]
                self.assertEqual(window_rules[0]["opacity"], 0.92)
                self.assertEqual(window_rules[1]["match"]["app_id"], r"^com\.mitchellh\.ghostty$")
                data = module.read_toml(theme.settings).unwrap()
                self.assertEqual(data["dock"]["background_opacity"], 0.34)
                rules = module.resolve_umbriel(theme.overlay)["layer_rule"]
                self.assertEqual(len(rules), 2)
                self.assertEqual(rules[0]["match"]["namespace"], "^existing$")
                theme.apply("gpd")
                self.assertIn("background-opacity = 0.76", theme.ghostty.read_text())
                self.assertFalse(module.read_toml(theme.settings)["dock"]["magnification"])
                theme.apply("desktop")
                self.assertNotIn("magnification", module.read_toml(theme.settings)["dock"])
                theme.apply("original")
                self.assertIn("background-opacity-cells = false", theme.ghostty.read_text())
                self.assertNotIn("window_rule", module.resolve_umbriel(theme.overlay))
                self.assertEqual(module.resolve_umbriel(theme.overlay)["appearance"]["blur"]["glass_strength"], 0.0)
                theme.apply("desktop")
                edited = module.read_toml(theme.settings)
                edited["shell"]["font_family"] = "User Changed Font"
                theme.settings.write_text(tomlkit.dumps(edited))
                theme.ghostty.write_text(theme.ghostty.read_text().replace("font-size = 10", "font-size = 12"))
                theme.restore()
                self.assertEqual(theme.ghostty.read_text(), ghost_original.replace("font-size = 10", "font-size = 12"))
                restored = module.read_toml(theme.settings).unwrap()
                self.assertEqual(restored["dock"], {"background_opacity": 0.8})
                self.assertEqual(restored["shell"]["font_family"], "User Changed Font")
                self.assertEqual(restored["wallpaper"]["default"]["path"], "/private/wallpaper.jpg")
                self.assertIn("# Keep this comment", theme.settings.read_text())
                self.assertEqual(base.read_text(), base_text)
                self.assertFalse(theme.launcher.exists())
                self.assertFalse(theme.service.exists())
                self.assertFalse(theme.shell_launcher.exists())
                self.assertFalse(theme.material_colors.exists())
                self.assertFalse(theme.material_template.exists())
                self.assertFalse(theme.baseline.exists())
                self.assertEqual(module.resolve_umbriel(theme.overlay)["layer_rule"], rules[:1])

    def test_atomic_write_preserves_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "actual"
            link = Path(directory) / "link"
            target.write_text("old")
            link.symlink_to(target)
            module.atomic(link, "new")
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), "new")

    def test_profiles_contain_no_machine_configuration(self):
        for file in (ROOT / "profiles").glob("*.toml"):
            name = file.stem
            data = module.profile(name)
            self.assertNotIn("output", data["umbriel"])
            self.assertNotIn("input", data["umbriel"])
            self.assertNotIn("keybinds", data["umbriel"])
            self.assertNotIn("wallpaper", data["noctalia"])
            self.assertNotIn("plugins", data["noctalia"])

    def test_approved_dark_opacity(self):
        data = module.profile("dark")
        self.assertEqual(data["noctalia"]["theme"]["mode"], "dark")
        self.assertEqual(data["noctalia"]["bar"]["default"]["background_opacity"], 0.22)
        self.assertEqual(data["noctalia"]["dock"]["background_opacity"], 0.20)
        self.assertEqual(data["noctalia"]["shell"]["panel"]["glass_background_opacity"], 0.20)
        self.assertEqual(data["noctalia"]["shell"]["panel"]["glass_card_opacity"], 0.16)
        self.assertEqual(data["apps"]["ghostty"]["background_opacity"], 0.55)
        self.assertEqual(data["umbriel"]["window_rule"][0]["opacity"], 1.0)

    def test_follow_mode_preserves_auto_and_stops_when_matched(self):
        with tempfile.TemporaryDirectory() as directory:
            theme = module.Theme()
            theme.active = Path(directory) / "active.json"
            for family, current, target in (("desktop", "light", "dark"),
                                             ("gpd", "gpd-light", "gpd-dark"),
                                             ("frosted", "frosted-light", "frosted-dark")):
                theme.active.write_text(json.dumps({"profile": current}))
                with patch.object(module.subprocess, "check_output", side_effect=["dark\n", '[theme]\nmode = "auto"\n']), patch.object(theme, "apply") as apply:
                    theme.follow_mode()
                    apply.assert_called_once_with(target, configured_mode="auto")
                theme.active.write_text(json.dumps({"profile": target}))
                with patch.object(module.subprocess, "check_output", return_value="dark\n") as command, patch.object(theme, "apply") as apply:
                    theme.follow_mode()
                    command.assert_called_once()
                    apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
