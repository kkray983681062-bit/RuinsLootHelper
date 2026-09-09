"""Version-bound relative addresses, always revalidated against this process."""
import hashlib
import json
from pathlib import Path
import struct

from probe import ptr, u32, u64


def fingerprint(game):
    path = Path(game)
    stat = path.stat()
    with path.open('rb') as file:
        header = file.read(65536)
    paks = path.parents[2] / 'Content' / 'Paks'
    content = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in paks.glob('*.utoc'))
    return hashlib.sha256(json.dumps([stat.st_size, stat.st_mtime_ns, hashlib.sha256(header).hexdigest(), content]).encode()).hexdigest()


def inside_module(probe, rva, size):
    return isinstance(rva, int) and any(section['writable'] and section['rva'] <= rva and
        rva + size <= section['rva'] + section['size'] for section in probe.result['sections'])


def restore_globals(probe, cache):
    """No stored absolute or heap pointer is accepted, including chunk pointers."""
    try:
        nrva, orva, stride = cache['name_rva'], cache['objects_rva'], cache['stride']
        if not inside_module(probe, nrva, 32) or not inside_module(probe, orva, 32) or stride not in (16, 24, 32):
            return False
        pool = probe.base + nrva
        head = probe.read(pool + 8, 8)
        block, cursor = struct.unpack('<II', head)
        if not (0 <= block < 512 and 2 <= cursor <= 131072 and cursor % 2 == 0):
            return False
        raw = probe.read(pool + 16, (block + 1) * 8)
        blocks = list(struct.unpack('<' + 'Q' * (block + 1), raw))
        if not all(ptr(p) for p in blocks):
            return False
        probe.blocks, probe.names = blocks, {}
        if probe.name(0) != 'None':
            return False
        address = probe.base + orva
        chunks, pre, maximum, used, maxchunks, count = struct.unpack('<QQiiii', probe.read(address, 32))
        if not (ptr(chunks) and pre == 0 and 1000 <= used <= maximum <= 8000000 and maximum % 65536 == 0
                and 1 <= count <= maxchunks <= 8192 and used <= count * 65536):
            return False
        first = u64(probe.read(chunks, 8))
        items = probe.read(first, stride * 8)
        verified = []
        for index in range(1, 8):
            obj = probe.object_info(u64(items, index * stride))
            if obj and obj['index'] == index:
                verified.append(obj['name'])
        if len(verified) < 4:
            return False
        probe.result['name_pool'] = {'address': pool, 'blocks': block + 1, 'cursor': cursor, 'none_name_verified': True}
        probe.objects = {'address': address, 'chunks_address': chunks, 'used': used, 'maximum': maximum,
            'chunk_count': count, 'stride': stride, 'validated_samples': verified}
        probe.result['object_array'] = probe.objects
        return True
    except (KeyError, TypeError, ValueError, struct.error):
        return False


def cache_value(probe, version, indices=None):
    return {'schema': 1, 'fingerprint': version,
        'name_rva': probe.result['name_pool']['address'] - probe.base,
        'objects_rva': probe.objects['address'] - probe.base,
        'stride': probe.objects['stride'], 'indices': indices or {}}
