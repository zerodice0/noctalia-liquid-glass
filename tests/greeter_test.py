#!/usr/bin/env python3
import copy
from pathlib import Path
import sys
import unittest

import tomlkit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from greeter_sync import appearance_conflict, follow_synced_appearance


class GreeterTests(unittest.TestCase):
    def test_only_fixed_appearance_is_released(self):
        config = {'appearance': {'scheme': 'Noctalia', 'theme_mode': 'light',
                                 'palette': {'primary': '#123456'},
                                 'wallpaper': {'path': '/private/old.png'},
                                 'password_style': 'random', 'hide_logo': True},
                  'auth': {'allow_empty_password': False},
                  'session': {'default': 'Umbriel'}, 'user': {'default': 'test'},
                  'keyboard': {'layout': 'us'}, 'output': {'scale': 1.5}}
        original = copy.deepcopy(config)
        self.assertTrue(appearance_conflict(config))
        result = follow_synced_appearance(config)
        self.assertFalse(appearance_conflict(result))
        self.assertEqual(result['appearance'], {'scheme': 'Synced', 'password_style': 'random', 'hide_logo': True})
        for key in ('auth', 'session', 'user', 'keyboard', 'output'):
            self.assertEqual(result[key], original[key])

    def test_toml_roundtrip_preserves_unrelated_comments(self):
        config = tomlkit.parse('# keep\n[appearance]\nscheme = "Noctalia"\ntheme_mode = "dark"\n'
                               '[auth]\n# fingerprint choice\nallow_empty_password = false\n')
        follow_synced_appearance(config)
        text = tomlkit.dumps(config)
        self.assertIn('# fingerprint choice', text)
        self.assertFalse(tomlkit.parse(text)['auth']['allow_empty_password'])
        self.assertEqual(tomlkit.parse(text)['appearance']['scheme'], 'Synced')


if __name__ == '__main__':
    unittest.main()
