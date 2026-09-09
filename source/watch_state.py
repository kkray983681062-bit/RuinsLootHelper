"""Bounded live inventory observation; reads game memory only, no inputs."""
import argparse
import datetime
import json
import pathlib
import struct
import time
import traceback
from live_items import ItemProbe, clean
from probe import k, ptr, u32, u64


class Watch(ItemProbe):
    def __init__(self, pid, output, seed, instances, seconds=180):
        super().__init__(pid, output, seed)
        seconds = min(max(seconds, 1), 180)
        self.deadline = self.started + seconds
        self.instances = instances if isinstance(instances, dict) else json.loads(pathlib.Path(instances).read_text(encoding="utf-8"))
        self.result["duration_limit_seconds"] = seconds
        self.sources = []
        self.previous = {}
        self.samples = 0
        self.result["events"] = []

    @staticmethod
    def source_key(source):
        return hex(source["header_address"])

    def array_inner(self, f):
        raw = self.read(f["address"] + 88, 96)
        for off in range(0, len(raw) - 7, 8):
            p = u64(raw, off)
            inner = self.field_info(p, 32)
            if not inner or inner["offset"] != 0 or inner["name"] != f["name"]:
                continue
            if inner["kind"] == "StructProperty" and inner["element_size"] in (808, 716):
                tail = self.read(inner["address"] + 88, 96)
                for j in range(0, len(tail) - 7, 8):
                    obj = self.object_info(u64(tail, j))
                    if obj and obj["name"] in ("格子属性", "简化物品属性"):
                        return inner, obj["name"]
        return None, None

    def prepare(self):
        self.open()
        if self.base != self.seed["module_base"]:
            raise ValueError("Game module changed; rediscovery needed")
        pool = self.seed["name_pool"]["address"]
        block = u32(self.read(pool + 8, 8))
        raw = self.read(pool + 16, (block + 1) * 8)
        self.blocks = list(struct.unpack("<" + "Q" * (block + 1), raw))
        if self.name(0) != "None":
            raise ValueError("Name pool identity changed")
        addresses = {}
        for item in self.instances["equipment_candidates"]:
            for outer in item.get("outer_chain", []):
                if outer["name"] in ("全局变量_C", "主UI_C", "仓库UI"):
                    addresses[outer["address"]] = outer["name"]
        queue = [(a, n, 0) for a, n in addresses.items()]
        seen = set()
        reports = []
        while queue and len(seen) < 24:
            address, label, depth = queue.pop(0)
            if address in seen:
                continue
            seen.add(address)
            obj = self.object_info(address)
            if not obj:
                continue
            cls = self.object_info(obj["class_address"])
            if not cls:
                continue
            fields = self.fields(obj["class_address"])
            report = {"label": label, "object": obj, "class_name": cls["name"], "fields": []}
            for f in fields:
                name = clean(f["name"])
                entry = {"name": name, "kind": f["kind"], "offset": f["offset"], "size": f["element_size"]}
                report["fields"].append(entry)
                if f["kind"] == "ArrayProperty":
                    h = self.read(address + f["offset"], 16)
                    if len(h) != 16:
                        continue
                    pointer, count, capacity = struct.unpack("<Qii", h)
                    entry["count"] = count
                    if not (0 <= count <= capacity <= 100000):
                        continue
                    inner, type_name = self.array_inner(f)
                    if inner:
                        entry["inner_type"] = type_name
                        entry["stride"] = inner["element_size"]
                        self.sources.append({"label": label + "." + name, "owner": obj, "header_address": address + f["offset"], "stride": inner["element_size"], "type_name": type_name})
                if f["kind"] == "ObjectProperty" and depth < 2 and any(t in name for t in ("玩家", "主角", "控制", "BP_", "背包", "仓库", "储物", "角色", "Game", "Pawn")):
                    raw = self.read(address + f["offset"], 8)
                    if len(raw) == 8 and ptr(u64(raw)):
                        queue.append((u64(raw), label + "." + name, depth + 1))
            reports.append(report)
        self.result["container_discovery"] = reports
        self.result["sources"] = self.sources
        self.save("live_containers_discovered")

    def take(self, source):
        owner = self.object_info(source["owner"]["address"])
        if not owner or owner["index"] != source["owner"]["index"] or owner["class_address"] != source["owner"]["class_address"]:
            return None
        header = self.read(source["header_address"], 16)
        if len(header) != 16:
            return None
        address, count, capacity = struct.unpack("<Qii", header)
        if not (0 <= count <= capacity <= 10000):
            return None
        if count == 0:
            return {}
        if not ptr(address):
            return None
        raw = self.read(address, count * source["stride"])
        if len(raw) != count * source["stride"] or header != self.read(source["header_address"], 16):
            return None
        if raw != self.read(address, len(raw)):
            return None
        slots = {}
        for index in range(count):
            item = self.decode(raw[index * source["stride"]:(index + 1) * source["stride"]], source["type_name"])
            name = item.get("名称", item.get("名字"))
            kind = item.get("种类", item.get("物品类型"))
            if name and name != "None" and kind == 1:
                slots[index] = self.compact(item)
        return slots

    def observe(self):
        if not self.sources:
            self.result["status"] = "no_validated_live_containers"
            return
        self.result["baseline_targets"] = []
        self.result["latest_counts"] = {}
        while time.monotonic() < self.deadline - 0.5:
            self.check()
            sample_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for source in self.sources:
                current = self.take(source)
                if current is None:
                    self.result.setdefault("unstable_or_invalid_samples", 0)
                    self.result["unstable_or_invalid_samples"] += 1
                    continue
                label = source["label"]
                identity = self.source_key(source)
                self.result["latest_counts"][identity] = {"source": label, "equipment_count": len(current)}
                if identity not in self.previous:
                    for index, item in current.items():
                        if item.get("名称", item.get("名字")) == "追风":
                            self.result["baseline_targets"].append({"source": label, "source_id": identity, "index": index, "item": item})
                else:
                    old = self.previous[identity]
                    for index in sorted(set(old) | set(current)):
                        before, after = old.get(index), current.get(index)
                        if before == after:
                            continue
                        event = "equipment_added" if before is None else "equipment_removed" if after is None else "equipment_changed_or_replaced"
                        self.result["events"].append({"time": sample_time, "source": label, "source_id": identity, "index": index, "event": event, "before": before, "after": after})
                        self.result["events"] = self.result["events"][-120:]
                self.previous[identity] = current
            self.samples += 1
            self.result.update(sample_count=self.samples, last_sample_utc=sample_time)
            self.save("watching_live_container_changes")
            time.sleep(1)
        self.result["status"] = "observation_completed"

    def run(self):
        self.save("starting")
        try:
            self.prepare()
            self.observe()
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
    ap.add_argument("--instances", required=True)
    ap.add_argument("--seconds", type=float, default=180)
    args = ap.parse_args()
    Watch(args.pid, args.output, args.seed, args.instances, args.seconds).run()
