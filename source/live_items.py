"""Read only a bounded snapshot of equipment held by live inventory widgets."""
import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import re
import struct
import time
import traceback
from probe import Probe, k, ptr, u32, u64


def clean(name):
    return re.sub(r"_\d+_[0-9A-F]{32}$", "", name)


class ItemProbe(Probe):
    def __init__(self, pid, output, seed):
        super().__init__(pid, output, 45)
        self.seed = seed if isinstance(seed, dict) else json.loads(pathlib.Path(seed).read_text(encoding="utf-8"))
        if self.seed["pid"] != pid:
            raise ValueError("Seed process does not match")
        self.types = self.seed["reflected_types"]

    def decode(self, b, type_name, depth=0):
        if depth > 4:
            return {}
        result = {}
        for f in self.types[type_name]["fields"]:
            name, kind, off = clean(f["name"]), f["kind"], f["offset"]
            size = f["element_size"]
            if off + size > len(b):
                raise ValueError("Reflected structure exceeds snapshot")
            if kind == "IntProperty":
                value = struct.unpack_from("<i", b, off)[0]
            elif kind == "FloatProperty":
                value = struct.unpack_from("<f", b, off)[0]
            elif kind == "DoubleProperty":
                value = struct.unpack_from("<d", b, off)[0]
            elif kind in ("ByteProperty", "BoolProperty"):
                value = bool(b[off]) if kind == "BoolProperty" else b[off]
            elif kind == "NameProperty":
                value = self.name(u32(b, off))
            elif kind == "StructProperty":
                nested = {"基础属性": "装备基础属性", "特殊属性": "装备特殊属性", "装备属性": "装备属性", "装备极品属性": "装备极品属性", "极品属性": "装备极品属性"}.get(name)
                if not nested:
                    continue
                value = self.decode(b[off:off + size], nested, depth + 1)
            else:
                continue
            result[name] = value
        return result

    def compact(self, obj):
        result = {}
        for key, value in obj.items():
            if isinstance(value, dict):
                value = self.compact(value)
            if value not in (0, 0.0, False, "", "None", {}) or key in ("锁定", "品质", "名称"):
                result[key] = value
        return result

    def identify(self, item):
        if item.get("名称") != "追风":
            return None
        equip = item.get("装备属性", {})
        base = equip.get("基础属性", {})
        bonus = item.get("装备极品属性", {}).get("特殊属性", {})
        stats = [base.get(x, 0) for x in ("攻击下限", "攻击上限", "魔法下限", "魔法上限")]
        if stats == [32, 77, 21, 82] and bonus.get("暴击") == 3 and bonus.get("灼烧几率+") == 7:
            return "ordinary_unlocked_screenshot"
        if stats == [52, 101, 31, 125] and bonus.get("幸运") == 1 and bonus.get("暴击伤害") == 19:
            return "perfect_locked_screenshot"
        return "other_same_name_item"

    def snapshot_widget(self, obj):
        fieldmap = {clean(f["name"]): f for f in self.types["格子_C"]["fields"]}
        off = fieldmap["格子属性"]["offset"]
        b = self.read(obj["address"] + off, 808)
        if len(b) != 808:
            return None
        name = self.name(u32(b))
        if name not in ("追风", "幸运护符中", "毒素短杖", "龙纹法杖"):
            return None
        again = self.read(obj["address"] + off, 808)
        if b != again:
            return {"object": obj, "name": name, "stable_read": False}
        item = self.decode(b, "格子属性")
        context = {}
        for key in ("格子ID", "在背包", "在仓库", "在商店", "在购买区", "在售卖区", "拖拽中", "预售"):
            f = fieldmap.get(key)
            if f:
                raw = self.read(obj["address"] + f["offset"], f["element_size"])
                if len(raw) == f["element_size"]:
                    context[key] = struct.unpack("<i", raw)[0] if f["kind"] == "IntProperty" else bool(raw[0])
        outer = []
        pointer = obj["outer_address"]
        for _ in range(4):
            node = self.object_info(pointer)
            if not node:
                break
            outer.append({"name": node["name"], "number": node["number"], "address": node["address"]})
            pointer = node["outer_address"]
        return {"object": obj, "stable_read": True, "read_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "fingerprint": hashlib.sha256(b).hexdigest(), "context": context, "outer_chain": outer, "screenshot_match": self.identify(item), "item": self.compact(item)}

    def inspect(self):
        self.open()
        if self.base != self.seed["module_base"]:
            raise ValueError("Game module relocated; cached metadata is invalid")
        pool = self.seed["name_pool"]["address"]
        head = self.read(pool + 8, 8)
        block = u32(head)
        addresses = self.read(pool + 16, (block + 1) * 8)
        self.blocks = list(struct.unpack("<" + "Q" * (block + 1), addresses))
        if self.name(0) != "None":
            raise ValueError("Name pool no longer validates")
        for name in ("格子_C", "格子属性", "装备基础属性", "装备特殊属性", "装备极品属性", "装备属性"):
            t = self.types[name]
            address = t.get("class_address", t.get("struct_address"))
            obj = self.object_info(address)
            if not obj or obj["name"] != name:
                raise ValueError("Reflected type identity changed: " + name)
        gridclass = self.types["格子_C"]["class_address"]
        layout = self.seed["object_array"]
        current = self.read(layout["address"], 32)
        chunksaddr, _, maximum, used, _, chunkcount = struct.unpack("<QQiiii", current)
        if not (0 < used <= maximum <= 8000000 and ptr(chunksaddr) and 1 <= chunkcount <= 128):
            raise ValueError("Object array changed unexpectedly")
        chunks = self.read(chunksaddr, chunkcount * 8)
        checked = 0
        widgets = 0
        matches = []
        labels = set()
        self.result["equipment_candidates"] = matches
        for chunkindex in reversed(range(chunkcount)):
            num = min(65536, used - chunkindex * 65536)
            if num <= 0:
                continue
            chunk = self.read(u64(chunks, chunkindex * 8), num * layout["stride"])
            for index in reversed(range(num)):
                self.check()
                at = index * layout["stride"]
                if at + 8 > len(chunk):
                    continue
                address = u64(chunk, at)
                if not ptr(address):
                    continue
                header = self.read(address, 40)
                checked += 1
                if len(header) != 40 or u64(header, 16) != gridclass or u32(header, 8) & 0x18010:
                    continue
                obj = {"address": address, "index": u32(header, 12), "flags": u32(header, 8), "name": self.name(u32(header, 24)), "number": u32(header, 28), "class_address": gridclass, "outer_address": u64(header, 32)}
                if obj["index"] != chunkindex * 65536 + index:
                    continue
                widgets += 1
                candidate = self.snapshot_widget(obj)
                if candidate and len(matches) < 80:
                    matches.append(candidate)
                    if candidate.get("screenshot_match") in ("ordinary_unlocked_screenshot", "perfect_locked_screenshot"):
                        labels.add(candidate["screenshot_match"])
                if len(labels) == 2:
                    break
            self.result.update(object_headers_checked=checked, grid_widgets_checked=widgets, found_screenshot_labels=sorted(labels), scanned_to_object_index=chunkindex * 65536)
            self.save("matching_live_equipment")
            if len(labels) == 2:
                break
        self.result["matched_both_screenshots"] = len(labels) == 2
        self.result["repeat_reads"] = []
        for candidate in matches:
            if candidate.get("screenshot_match") in labels:
                follow = self.snapshot_widget(candidate["object"])
                if follow:
                    self.result["repeat_reads"].append(follow)

    def run(self):
        self.save("starting")
        try:
            self.inspect()
            self.result["status"] = "inspection_completed"
        except Exception as exc:
            self.result["status"] = "time_limit" if isinstance(exc, TimeoutError) else "stopped" if isinstance(exc, InterruptedError) else "inspection_failed"
            self.result["error"] = str(exc)
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
    ap.add_argument("--seed", required=True)
    args = ap.parse_args()
    ItemProbe(args.pid, args.output, args.seed).run()
