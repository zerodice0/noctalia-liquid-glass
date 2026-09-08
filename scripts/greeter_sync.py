#!/usr/bin/env python3
"""Explicit, backed-up Noctalia Greeter sync. Never restart greetd."""
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

SCRIPT = Path(__file__).resolve()
PYTHON = SCRIPT.parents[1] / '.venv/bin/python'
STATE = Path('/var/lib/noctalia-greeter')
BACKUPS = Path('/var/backups/noctalia-liquid-glass-greeter')
HELPER = '/usr/bin/noctalia-greeter-apply-appearance'


def read(path):
    return tomllib.loads(path.read_text()) if path.exists() else {}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def icon_property():
    result = subprocess.check_output([
        'gdbus', 'call', '--system', '--dest', 'org.freedesktop.Accounts',
        '--object-path', f'/org/freedesktop/Accounts/User{os.getuid()}',
        '--method', 'org.freedesktop.DBus.Properties.Get',
        'org.freedesktop.Accounts.User', 'IconFile'], text=True).strip()
    match = re.fullmatch(r'\(<(.+)>,\)', result)
    if not match:
        raise ValueError('Unexpected AccountsService IconFile response')
    value = ast.literal_eval(match.group(1))
    if not isinstance(value, str):
        raise ValueError('IconFile is not a string')
    return value


def sync_avatar(local_state):
    from theme import atomic
    old_path = icon_property()
    source = Path(old_path) if old_path else Path.home() / '.face'
    if not source.is_file():
        raise ValueError('No readable current profile image; appearance sync was not started')
    local_state.mkdir(parents=True, exist_ok=True, mode=0o700)
    baseline = local_state / 'avatar-baseline.json'
    if not baseline.exists():
        atomic(baseline, json.dumps({'icon_file': old_path}))
        atomic(local_state / 'avatar-original', source.read_bytes())
    # A fresh source path makes AccountsService copy the image to its shared
    # icon directory, even when IconFile currently points into a 0700 home.
    with tempfile.TemporaryDirectory(prefix='avatar-', dir=local_state) as directory:
        staged = Path(directory) / ('profile' + (source.suffix or '.png'))
        shutil.copyfile(source, staged)
        subprocess.run([
            'gdbus', 'call', '--system', '--dest', 'org.freedesktop.Accounts',
            '--object-path', f'/org/freedesktop/Accounts/User{os.getuid()}',
            '--method', 'org.freedesktop.Accounts.User.SetIconFile', str(staged)], check=True)
        installed = Path(icon_property())
        if not installed.is_file() or digest(installed) != digest(staged):
            raise ValueError('AccountsService profile image verification failed')
    return str(installed)


def snapshot():
    if STATE.is_symlink() or not STATE.is_dir():
        raise ValueError('Expected an existing, non-symlink Greeter state directory')
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    if BACKUPS.is_symlink() or BACKUPS.stat().st_uid != 0:
        raise ValueError('Unsafe backup directory')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    destination = BACKUPS / stamp
    destination.mkdir(mode=0o700)
    subprocess.run(['/usr/bin/cp', '-a', '--', str(STATE), str(destination / 'state')], check=True)
    return destination


def appearance_conflict(config):
    appearance = config.get('appearance', {})
    # Declarative fields take precedence over mutable sync.toml. Do not silently
    # report success when the installed appearance would still be hidden.
    return bool(appearance.get('scheme') not in (None, 'Synced')
                or any(key in appearance for key in
                       ('palette', 'wallpaper', 'wallpapers', 'theme_mode', 'font_family', 'corner_radius_scale')))


def follow_synced_appearance(config):
    """Leave authentication, sessions, input, output and UI choices intact."""
    appearance = config.setdefault('appearance', {})
    for key in ('palette', 'wallpaper', 'wallpapers', 'theme_mode', 'font_family', 'corner_radius_scale'):
        appearance.pop(key, None)
    appearance['scheme'] = 'Synced'
    return config


def install(helper, directory):
    resolved_helper = shutil.which(helper, path='/usr/bin:/bin')
    if os.geteuid() != 0 or resolved_helper != HELPER:
        raise ValueError('Install must use pkexec and the packaged appearance helper')
    uid = int(os.environ['PKEXEC_UID'])
    staging = Path(directory)
    expected = Path(f'/run/user/{uid}/noctalia-greeter-sync')
    if staging != expected or staging.is_symlink() or staging.stat().st_uid != uid:
        raise ValueError('Unexpected Greeter staging directory')
    report = {}
    try:
        import tomlkit
        from theme import atomic
        backup = snapshot()
        report['backup'] = str(backup)
        previous_session = read(STATE / 'sync.toml').get('session', {})
        config_path = STATE / 'greeter.toml'
        if config_path.is_symlink():
            raise ValueError('Declarative symlinked greeter.toml must be changed in its owning configuration')
        if appearance_conflict(read(config_path)):
            original_stat = config_path.stat()
            config = tomlkit.parse(config_path.read_text())
            follow_synced_appearance(config)
            atomic(config_path, tomlkit.dumps(config), original_stat.st_mode & 0o777)
            os.chown(config_path, original_stat.st_uid, original_stat.st_gid)
        staged = read(staging / 'sync.toml')['appearance']
        # The official helper validates and copies wallpaper data, merges sync
        # preferences, and sets ownership to the configured greetd user.
        subprocess.run([HELPER, str(staging)], check=True,
                       env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        # This operation is appearance-only. The packaged helper also syncs
        # shell power/menu actions; keep the greeter's original actions here.
        sync_path = STATE / 'sync.toml'
        sync_stat = sync_path.stat()
        installed_doc = tomlkit.parse(sync_path.read_text())
        session = installed_doc.setdefault('session', {})
        for key in ('power', 'actions'):
            if key in previous_session:
                session[key] = previous_session[key]
            else:
                session.pop(key, None)
        atomic(sync_path, tomlkit.dumps(installed_doc), sync_stat.st_mode & 0o777)
        os.chown(sync_path, sync_stat.st_uid, sync_stat.st_gid)
        actual = read(STATE / 'sync.toml')['appearance']
        for key in ('scheme', 'theme_mode', 'palette', 'wallpaper', 'wallpapers'):
            if key in staged and actual.get(key) != staged[key]:
                raise ValueError(f'Installed Greeter {key} does not match Noctalia')
        for wallpaper in [actual.get('wallpaper', {}), *actual.get('wallpapers', {}).values()]:
            path = wallpaper.get('path', '')
            if path and not path.startswith('color:'):
                if digest(path) != digest(staging / Path(path).name):
                    raise ValueError('Installed wallpaper bytes differ from staged image')
        report.update(ok=True, theme_mode=actual.get('theme_mode'), palette=actual.get('palette'))
    except Exception as error:
        report.update(ok=False, error=str(error))
    # Atomic replacement, never follow a caller-controlled report symlink.
    fd, temporary = tempfile.mkstemp(prefix='.glass-result-', dir=staging)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2)
    os.chmod(temporary, 0o644)
    os.replace(temporary, staging / 'glass-result.json')
    if not report['ok']:
        raise ValueError(report['error'])


def restore(stamp):
    if os.geteuid() != 0 or not re.fullmatch(r'\d{8}T\d{6}\.\d{6}Z', stamp):
        raise ValueError('Restore needs root and an exact backup timestamp')
    source = BACKUPS / stamp / 'state'
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Backup not found')
    previous = snapshot()
    # Keep the replaced directory recoverable; never recursively delete state.
    STATE.rename(previous / 'replaced-state')
    subprocess.run(['/usr/bin/cp', '-a', '--', str(source), str(STATE)], check=True)
    print(f'Greeter state restored. Previous state retained in {previous}')


def restore_session_menu(stamp):
    """Repair only power/menu actions after an earlier stock-helper sync."""
    import tomlkit
    from theme import atomic
    if os.geteuid() != 0 or not re.fullmatch(r'\d{8}T\d{6}\.\d{6}Z', stamp):
        raise ValueError('Needs root and an exact backup timestamp')
    source = BACKUPS / stamp / 'state'
    if not source.is_dir() or source.is_symlink():
        raise ValueError('Backup not found')
    old = read(source / 'sync.toml').get('session', {})
    path = STATE / 'sync.toml'
    info = path.stat()
    config = tomlkit.parse(path.read_text())
    current = config.setdefault('session', {})
    for key in ('power', 'actions'):
        if key in old:
            current[key] = old[key]
        else:
            current.pop(key, None)
    atomic(path, tomlkit.dumps(config), info.st_mode & 0o777)
    os.chown(path, info.st_uid, info.st_gid)
    original_config = read(source / 'greeter.toml')
    actual_config = read(STATE / 'greeter.toml')
    for key in set(original_config) | set(actual_config):
        if key != 'appearance' and original_config.get(key) != actual_config.get(key):
            raise ValueError(f'Unrelated Greeter setting differs: {key}')
    print('Session menu preserved; authentication/user/session/input/output configuration unchanged.')


def sync():
    from theme import Theme, atomic, get, put, read_toml
    import tomlkit
    theme = Theme()
    local = theme.state / 'greeter'
    avatar = sync_avatar(local)
    print(f'Profile image synchronized through AccountsService: {avatar}', flush=True)
    key = ('shell', 'greeter_sync', 'privilege_command')
    settings = read_toml(theme.settings)
    before = get(settings, key)
    theme.backup([theme.settings])
    prefix = shlex.join(['pkexec', str(PYTHON), str(SCRIPT), 'install'])
    put(settings, key, {'exists': True, 'value': prefix})
    atomic(theme.settings, tomlkit.dumps(settings))
    try:
        subprocess.run([str(theme.shell_binary), 'msg', 'config-reload'], check=True)
        response = subprocess.check_output([str(theme.shell_binary), 'msg', 'greeter-sync'], text=True).strip()
        if response != 'ok':
            raise ValueError(f'Could not launch Greeter sync: {response}')
    finally:
        # Restore only the temporary hook, preserving unrelated concurrent UI changes.
        settings = read_toml(theme.settings)
        put(settings, key, before)
        atomic(theme.settings, tomlkit.dumps(settings))
        subprocess.run([str(theme.shell_binary), 'msg', 'config-reload'], check=True)
    print('Approve the system authentication dialog. Waiting for verified installation...', flush=True)
    result = Path(os.environ['XDG_RUNTIME_DIR']) / 'noctalia-greeter-sync/glass-result.json'
    for _ in range(180):
        if result.exists():
            report = json.loads(result.read_text())
            atomic(local / 'last-sync.json', json.dumps(report, indent=2))
            if not report.get('ok'):
                raise ValueError(report.get('error', 'Greeter sync failed'))
            print(f"Verified Greeter sync ({report['theme_mode']}). Backup: {report['backup']}")
            print('No display manager, compositor, or applications were restarted.')
            return
        time.sleep(1)
    raise ValueError('No installation confirmation. Check authentication; do not assume sync succeeded.')


def status():
    from theme import Theme, atomic
    receipt = Theme().state / 'greeter/last-sync.json'
    runtime = Path(os.environ['XDG_RUNTIME_DIR']) / 'noctalia-greeter-sync/glass-result.json'
    if runtime.is_file() and runtime.stat().st_uid == 0:
        atomic(receipt, runtime.read_bytes())
    if not receipt.exists():
        raise ValueError('No recorded Greeter sync result')
    print('Last installation result (not a live login-screen test):')
    print(receipt.read_text())


if __name__ == '__main__':
    try:
        if len(sys.argv) == 4 and sys.argv[1] == 'install':
            install(sys.argv[2], sys.argv[3])
        elif len(sys.argv) == 3 and sys.argv[1] == 'restore':
            restore(sys.argv[2])
        elif len(sys.argv) == 3 and sys.argv[1] == 'restore-session-menu':
            restore_session_menu(sys.argv[2])
        else:
            raise ValueError('Use ./glass greeter-sync; privileged restore requires an exact backup timestamp')
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
