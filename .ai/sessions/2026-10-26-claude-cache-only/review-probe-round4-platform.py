from typing import Any
from types import SimpleNamespace
import pytest
from helab.io_ops import stores
from helab.utils import cache_paths, data_roots
from helab.utils.cache_paths import Mount, UnresolvedRemotePath
from helab.utils.data_roots import LocalVolumes

class Hints:
    def __init__(self, hints):
        self.hints = hints
    def mount_hints(self):
        return self.hints

def key_for(hints, mounts, path):
    paths, _ = stores._offline_mounts(Hints(hints), mounts, LocalVolumes([]))
    return paths.key(path)

@pytest.mark.parametrize('prefix', ['/Volumes/review-share', '/System/Volumes/Data/Volumes/review-share', '/Users/review/mount', '/System/Volumes/Data/Users/review/mount'])
def test_mac_system_data_and_firmlink_spellings_keep_unmounted_share_hints(prefix):
    mounts = [Mount('/dev/disk3s1s1', '/', 'apfs'), Mount('devfs', '/dev', 'devfs'),
              Mount('/dev/disk3s5', '/System/Volumes/Data', 'apfs'),
              Mount('/dev/disk3s6', '/System/Volumes/VM', 'apfs'),
              Mount('/dev/disk3s2', '/System/Volumes/Preboot', 'apfs'),
              Mount('/dev/disk3s4', '/System/Volumes/Update', 'apfs'),
              Mount('map auto_home', '/System/Volumes/Data/home', 'autofs')]
    assert key_for({prefix: 'smb://old-server/share'}, mounts, prefix + '/run') == 'smb://old-server/share/run'
    assert stores._transparent_mount(mounts[0])
    assert stores._transparent_mount(mounts[1])
    assert stores._transparent_mount(mounts[2])

@pytest.mark.parametrize('prefix', ['/System/Volumes/Data/home', '/srv/lab'])
def test_mac_autofs_map_blocks_stale_nested_hint(prefix):
    mounts = [Mount('/dev/disk3s1s1', '/', 'apfs'), Mount('/dev/disk3s5', '/System/Volumes/Data', 'apfs'),
              Mount('map auto_home', prefix, 'autofs')]
    assert not stores._transparent_mount(mounts[-1])
    key = key_for({prefix + '/nested': 'smb://old-server/share'}, mounts, prefix + '/nested/run')
    assert not key.startswith('smb://old-server')

@pytest.mark.parametrize('system_drive', ['C:', 'D:'])
def test_windows_system_volume_preserves_hints_but_current_drive_and_directory_mount_win(monkeypatch, system_drive):
    windows = SimpleNamespace(platform='win32')
    monkeypatch.setattr(cache_paths, 'sys', windows)
    monkeypatch.setattr(data_roots, 'sys', windows)
    monkeypatch.setenv('SystemDrive', system_drive)
    system = Mount(system_drive + '\\', system_drive + '\\', 'local')
    assert stores._transparent_mount(system)
    prefix = system_drive + '\\mounts\\old'
    hint = {prefix: 'smb://old-server/share', 'Z:\\nested': 'smb://old-server/share'}
    assert key_for(hint, [system], prefix.lower() + '\\run') == 'smb://old-server/share/run'
    mapped = Mount('\\\\new-server\\share', 'Z:\\', 'smb', True)
    assert key_for(hint, [system, mapped], 'z:\\nested\\run') == 'smb://new-server/share/nested/run'
    directory = Mount('new-disk', system_drive + '\\mounts', 'local')
    assert not stores._transparent_mount(directory)
    assert not key_for(hint, [system, directory], prefix + '\\run').startswith('smb://old-server')

@pytest.mark.parametrize('fstype', ['nfs4', 'fuse.sshfs', 'cifs', 'autofs', 'new-unknown-fs'])
def test_unknown_and_network_mounts_never_inherit_an_old_share(fstype):
    try:
        key = key_for({'/srv/lab/nested': 'smb://old-server/share'},
                      [Mount('/dev/system', '/', 'ext4'), Mount('new-source', '/srv/lab', fstype)],
                      '/srv/lab/nested/run')
    except UnresolvedRemotePath:
        return
    assert not key.startswith('smb://old-server')
