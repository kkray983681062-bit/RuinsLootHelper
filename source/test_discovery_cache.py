import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock

from discovery_cache import cache_value, fingerprint, restore_globals


class CacheTests(unittest.TestCase):
    def probe(self, base=0x10000000):
        p = Mock()
        p.base = base
        p.result = {'sections': [{'rva': 0x1000, 'size': 0x10000, 'writable': True}]}
        p.name = lambda index: 'None'
        p.object_info = lambda addr: {'index': (addr-0x700000)//0x100, 'name': 'Object'}
        memory = {
            base+0x2008: struct.pack('<II', 0, 100), base+0x2010: struct.pack('<Q', 0x400000),
            base+0x3000: struct.pack('<QQiiii', 0x500000, 0, 65536, 2000, 1, 1),
            0x500000: struct.pack('<Q', 0x600000),
            0x600000: b''.join(struct.pack('<Q', 0x700000+i*0x100)+bytes(16) for i in range(8)),
        }
        p.read = lambda addr, size: memory.get(addr, b'')[:size]
        return p, memory

    def test_relocation_uses_new_module_and_heap_addresses(self):
        cache = {'name_rva': 0x2000, 'objects_rva': 0x3000, 'stride': 24}
        for base in (0x10000000, 0x20000000):
            p, _ = self.probe(base)
            self.assertTrue(restore_globals(p, cache))
            self.assertEqual(p.result['name_pool']['address'], base+0x2000)
            self.assertEqual(p.objects['chunks_address'], 0x500000)
            saved = cache_value(p, 'version')
            self.assertNotIn('chunks_address', saved)
            self.assertNotIn('module_base', saved)

    def test_invalid_memory_or_outside_rva_rejected(self):
        p, memory = self.probe()
        cache = {'name_rva': 0x2000, 'objects_rva': 0x3000, 'stride': 24}
        p.name = lambda _: 'Wrong'
        self.assertFalse(restore_globals(p, cache))
        p.name = lambda _: 'None'
        self.assertFalse(restore_globals(p, dict(cache, objects_rva=999999)))
        memory[0x500000] = b''
        self.assertFalse(restore_globals(p, cache))

    def test_file_version_change_invalidates_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'Game'/'Binaries'/'Win64'/'game.exe'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'MZ' + bytes(100))
            before = fingerprint(path)
            path.write_bytes(b'MZ' + bytes(150))
            self.assertNotEqual(fingerprint(path), before)


if __name__ == '__main__':
    unittest.main()
