from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Uses the same isolated app/cache/temp setup and reruns the previous probes.
exec(Path('/private/tmp/helab_review_probe_r2.py').read_text())

from helab.io_ops.stores import _offline_mounts, _volume_mount
from helab.utils.cache_paths import current_mounts, CachePaths, UnresolvedRemotePath
from helab.utils.data_roots import DataRoots, RootLocation

class NFSHints:
    def mount_hints(self):
        return {'/srv/lab/subdir': 'smb://old-server/old-share'}

partition = SimpleNamespace(device='new-server:/export', mountpoint='/srv/lab', fstype='nfs4',
                            opts='rw,relatime,vers=4.2,proto=tcp')
with patch('psutil.disk_partitions', return_value=[partition]):
    current = current_mounts()[0]
volumes = LocalVolumes([])
paths, local = _offline_mounts(NFSHints(), [current], volumes)
resolver = DataRoots(paths, [RootLocation('smb://old-server/old-share', 'old-root')],
                     local_location=local.location)
print('NFS_CURRENT_MOUNT', current)
print('NFS_MOUNT_CLASSIFIED', _volume_mount(current, volumes))
print('NFS_HINTED_ROOT', resolver.key('/srv/lab/subdir/run'))
try:
    CachePaths([current]).key('/srv/lab/subdir/run')
except UnresolvedRemotePath as error:
    print('NFS_WITHOUT_HINT', type(error).__name__, error)
