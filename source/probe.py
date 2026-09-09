"""Bounded, read-only inspection of this user's running Ruins of Dawn.

Uses PROCESS_QUERY_INFORMATION | PROCESS_VM_READ only. No game writes,
injection, debugger attachment, privilege changes, network, or persistence.
Outputs selected metadata, never a process-memory dump.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
import pathlib
import struct
import time
import traceback

EXPECTED = r"D:\steam\steamapps\common\Ruins of Dawn\RuinsOfDawn\Binaries\Win64\RuinsOfDawn-Win64-Shipping.exe"
OUTPUT_ROOT = pathlib.Path(__file__).resolve().parent


def configure_runtime(expected_image, output_root):
    """The release launcher pins the verified installation and user data folder."""
    global EXPECTED, OUTPUT_ROOT
    from game_install import resolve_game
    verified = resolve_game(expected_image)
    if verified is None:
        raise ValueError('Invalid Ruins of Dawn installation')
    EXPECTED = str(verified)
    OUTPUT_ROOT = pathlib.Path(output_root).resolve()


k = c.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]
k.CloseHandle.restype = w.BOOL
k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
k.ReadProcessMemory.restype = w.BOOL
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
k.QueryFullProcessImageNameW.restype = w.BOOL
k.K32EnumProcessModulesEx.argtypes = [w.HANDLE, c.POINTER(w.HMODULE), w.DWORD, c.POINTER(w.DWORD), w.DWORD]
k.K32EnumProcessModulesEx.restype = w.BOOL


def ptr(x):
    return 0x10000 < x < 0x0000800000000000 and x % 8 == 0


def u32(b, off=0):
    return struct.unpack_from("<I", b, off)[0]


def u64(b, off=0):
    return struct.unpack_from("<Q", b, off)[0]


class Probe:
    def __init__(self, pid, output, seconds):
        self.pid = pid
        self.output = pathlib.Path(output).resolve()
        if self.output.parent != OUTPUT_ROOT:
            raise ValueError("Output must remain in the configured runtime folder")
        self.started = time.monotonic()
        self.deadline = self.started + min(seconds, 45)
        self.handle = None
        self.read_bytes = 0
        self.read_calls = 0
        self.names = {}
        self.blocks = []
        self.next_stop_check = 0.0
        self.result = {"pid": pid, "expected_image": EXPECTED, "mode": "read_only", "stage": "starting", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def check(self):
        now = time.monotonic()
        if now > self.deadline:
            raise TimeoutError("Bounded probe time limit reached")
        if now >= self.next_stop_check:
            self.next_stop_check = now + 0.25
            if (self.output.parent / "stop.flag").exists():
                raise InterruptedError("Stopped by user request")

    def save(self, stage):
        self.result.update(stage=stage, elapsed_seconds=round(time.monotonic() - self.started, 3), bytes_read=self.read_bytes, read_calls=self.read_calls)
        temp = self.output.with_suffix(".tmp")
        temp.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.output)

    def read(self, address, size):
        self.check()
        if not 0x10000 < address < 0x0000800000000000 or not 0 < size <= 32 * 1024 * 1024:
            return b""
        buffer = c.create_string_buffer(size)
        n = c.c_size_t()
        k.ReadProcessMemory(self.handle, address, buffer, size, c.byref(n))
        self.read_bytes += n.value
        self.read_calls += 1
        return buffer.raw[:n.value]

    def name(self, index):
        if index in self.names:
            return self.names[index]
        block, offset = index >> 16, (index & 0xFFFF) * 2
        if block >= len(self.blocks):
            return ""
        b = self.read(self.blocks[block] + offset, 2)
        if len(b) != 2:
            return ""
        head = struct.unpack("<H", b)[0]
        length, wide = head >> 6, head & 1
        if not 0 < length <= 1023:
            return ""
        b = self.read(self.blocks[block] + offset + 2, length * (2 if wide else 1))
        try:
            value = b.decode("utf-16le" if wide else "utf-8")
            if any(ord(ch) < 32 for ch in value):
                return ""
        except UnicodeError:
            return ""
        self.names[index] = value
        return value

    def object_info(self, address):
        if not ptr(address):
            return None
        b = self.read(address, 40)
        if len(b) != 40 or not ptr(u64(b, 16)):
            return None
        name = self.name(u32(b, 24))
        if not name:
            return None
        return {"address": address, "name": name, "number": u32(b, 28), "index": u32(b, 12), "flags": u32(b, 8), "class_address": u64(b, 16), "outer_address": u64(b, 32)}

    def open(self, load_sections=True):
        self.handle = k.OpenProcess(0x0410, False, self.pid)
        if not self.handle:
            raise OSError(c.get_last_error(), "OpenProcess query/read access denied")
        size = w.DWORD(32768)
        path = c.create_unicode_buffer(size.value)
        if not k.QueryFullProcessImageNameW(self.handle, 0, path, c.byref(size)):
            raise OSError(c.get_last_error(), "Cannot verify process image")
        if path.value.casefold() != EXPECTED.casefold():
            raise ValueError("Process identity changed; refusing to inspect")
        self.result["verified_image"] = path.value
        self.result["read_handle_opened"] = True
        modules = (w.HMODULE * 1024)()
        needed = w.DWORD()
        if not k.K32EnumProcessModulesEx(self.handle, modules, c.sizeof(modules), c.byref(needed), 3):
            raise OSError(c.get_last_error(), "Cannot enumerate game modules")
        self.base = modules[0]
        header = self.read(self.base, 4096)
        if header[:2] != b"MZ":
            raise ValueError("Game image header could not be verified")
        pe = u32(header, 0x3C)
        if header[pe:pe + 4] != b"PE\x00\x00":
            raise ValueError("Invalid PE header")
        count = struct.unpack_from("<H", header, pe + 6)[0]
        optsize = struct.unpack_from("<H", header, pe + 20)[0]
        table = pe + 24 + optsize
        self.sections = []
        self.result["module_base"] = self.base
        self.result["memory_header_verified"] = True
        for index in range(count):
            off = table + index * 40
            name = header[off:off + 8].split(b"\x00")[0].decode("ascii", "replace")
            size, rva = struct.unpack_from("<II", header, off + 8)
            flags = u32(header, off + 36)
            if load_sections and flags & 0x80000000 and 0 < size <= 32 * 1024 * 1024:
                content = self.read(self.base + rva, size)
                self.sections.append((self.base + rva, content))
            self.result.setdefault("sections", []).append({"name": name, "rva": rva, "size": size, "writable": bool(flags & 0x80000000)})
        self.save("game_read_access_verified")

    def load_writable_sections(self):
        self.sections = [(self.base + section['rva'], self.read(self.base + section['rva'], section['size']))
                         for section in self.result['sections'] if section['writable'] and 0 < section['size'] <= 32 * 1024 * 1024]

    def find_names(self):
        attempts = 0
        for base, data in self.sections:
            for off in range(0, len(data) - 32, 8):
                if off % 65536 == 0:
                    self.check()
                block, cursor = struct.unpack_from("<II", data, off + 8)
                p0 = u64(data, off + 16)
                if not (0 <= block < 512 and 2 <= cursor <= 131072 and cursor % 2 == 0 and ptr(p0)):
                    continue
                attempts += 1
                b = self.read(p0, 16)
                if len(b) < 6 or b[2:6] != b"None" or struct.unpack_from("<H", b)[0] >> 6 != 4:
                    continue
                addresses = self.read(base + off + 16, (block + 1) * 8)
                if len(addresses) != (block + 1) * 8:
                    continue
                blocks = list(struct.unpack("<" + "Q" * (block + 1), addresses))
                if not all(ptr(p) for p in blocks):
                    continue
                self.blocks = blocks
                self.result["name_pool"] = {"address": base + off, "blocks": block + 1, "cursor": cursor, "candidates_checked": attempts, "none_name_verified": self.name(0) == "None"}
                self.save("runtime_name_pool_found")
                return
        raise ValueError("No validated runtime name pool found")

    def find_objects(self):
        candidates = []
        for base, data in self.sections:
            for off in range(0, len(data) - 32, 8):
                if off % 65536 == 0:
                    self.check()
                chunks, pre, maximum, used, maxchunks, numchunks = struct.unpack_from("<QQiiii", data, off)
                if not (ptr(chunks) and pre == 0 and 1000 <= used <= maximum <= 8000000 and maximum % 65536 == 0 and 1 <= numchunks <= maxchunks <= 8192 and used <= numchunks * 65536):
                    continue
                first = self.read(chunks, 8)
                if len(first) != 8 or not ptr(u64(first)):
                    continue
                items = self.read(u64(first), 512)
                for stride in (24, 32, 16):
                    checked = []
                    for index in range(1, 8):
                        if index * stride + 8 > len(items):
                            continue
                        info = self.object_info(u64(items, index * stride))
                        if info and info["index"] == index:
                            checked.append(info["name"])
                    if len(checked) >= 4:
                        candidates.append({"address": base + off, "chunks_address": chunks, "used": used, "maximum": maximum, "chunk_count": numchunks, "stride": stride, "validated_samples": checked})
                        break
        if not candidates:
            raise ValueError("No validated runtime object array found")
        self.objects = candidates[0]
        self.result["object_array"] = self.objects
        self.result["object_array_candidate_count"] = len(candidates)
        self.save("runtime_object_array_found")

    def field_info(self, address, nameoff):
        if not ptr(address):
            return None
        b = self.read(address, 128)
        if len(b) != 128:
            return None
        name = self.name(u32(b, nameoff))
        cls = u64(b, 8)
        clsdata = self.read(cls, 8) if ptr(cls) else b""
        kind = self.name(u32(clsdata)) if len(clsdata) == 8 else ""
        if not name or not kind.endswith("Property"):
            return None
        dim, size = struct.unpack_from("<ii", b, nameoff + 16)
        offset = struct.unpack_from("<i", b, nameoff + 36)[0]
        if not (1 <= dim <= 4096 and 0 < size < 1000000 and 0 <= offset < 10000000):
            return None
        return {"address": address, "name": name, "kind": kind, "offset": offset, "element_size": size, "array_dim": dim, "next": u64(b, nameoff - 8), "name_offset": nameoff}

    def fields(self, address):
        header = self.read(address, 144)
        if len(header) != 144:
            return []
        for childoff in (80, 88, 72, 96):
            child = u64(header, childoff)
            for nameoff in (40, 32, 48):
                current = self.field_info(child, nameoff)
                if not current:
                    continue
                items = []
                seen = set()
                while current and current["address"] not in seen and len(items) < 512:
                    seen.add(current["address"])
                    items.append(current)
                    current = self.field_info(current["next"], nameoff)
                if len(items) >= 2:
                    return items
        return []

    def scan_objects(self):
        info = self.objects
        chunks = self.read(info["chunks_address"], info["chunk_count"] * 8)
        classcache = {}
        examples = []
        metadata = {}
        count = 0
        interesting = ("格子", "背包", "物品", "掉落", "拾取", "TopDownCharacter", "PlayerController", "SAVE_C", "装备")
        self.result["interesting_objects"] = examples
        self.result["reflected_types"] = metadata
        for chunkindex in range(info["chunk_count"]):
            num = min(65536, info["used"] - chunkindex * 65536)
            if num <= 0:
                break
            chunk = self.read(u64(chunks, chunkindex * 8), num * info["stride"])
            for index in range(num):
                self.check()
                at = index * info["stride"]
                if at + 8 > len(chunk):
                    break
                obj = self.object_info(u64(chunk, at))
                if not obj or obj["flags"] & 0x10:
                    continue
                count += 1
                cl = obj["class_address"]
                if cl not in classcache:
                    classcache[cl] = self.object_info(cl)
                cls = classcache[cl]
                if not cls:
                    continue
                cname = cls["name"]
                if any(term in cname or term in obj["name"] for term in interesting):
                    if len(examples) < 400:
                        examples.append(dict(obj, class_name=cname))
                    if cname not in metadata and any(term in cname for term in interesting):
                        metadata[cname] = {"class_address": cl, "fields": self.fields(cl)}
                    if cname in ("ScriptStruct", "UserDefinedStruct") and any(term in obj["name"] for term in ("物品属性", "格子属性", "装备", "简化")):
                        metadata[obj["name"]] = {"struct_address": obj["address"], "fields": self.fields(obj["address"])}
                if count % 5000 == 0:
                    self.result["objects_checked"] = count
                    self.save("examining_live_objects")
        self.result["objects_checked"] = count
        self.result["class_count"] = len(classcache)

    def run(self):
        self.save("starting")
        try:
            self.open()
            self.find_names()
            self.find_objects()
            self.scan_objects()
            self.result["status"] = "inspection_completed"
        except Exception as exc:
            self.result["status"] = "stopped" if isinstance(exc, InterruptedError) else "time_limit" if isinstance(exc, TimeoutError) else "inspection_failed"
            self.result["error"] = str(exc)
            self.result["error_type"] = type(exc).__name__
            self.result["traceback"] = traceback.format_exc(limit=3)
        finally:
            if self.handle:
                k.CloseHandle(self.handle)
                self.handle = None
            self.result["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.save("finished")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--seconds", type=float, default=45)
    args = ap.parse_args()
    Probe(args.pid, args.output, args.seconds).run()
