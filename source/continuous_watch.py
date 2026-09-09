"""Keep a read-only handle open for this game session; publish current gear only."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
import msvcrt
import os
import pathlib
import struct
import time

from loot_current import CurrentInventory, occupied_main_slots
from probe import k, ptr, u32, u64
from watch_state import Watch

k.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
k.GetExitCodeProcess.restype = w.BOOL


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic_text(path, text):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    for attempt in range(5):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.01)


def fields_text(data):
    fields = []
    for key, value in data.items():
        if isinstance(value, dict):
            child = fields_text(value)
            if child:
                fields.append(child)
        elif value not in (0, False, "", None):
            label = "暴击几率" if key == "暴击" else key
            fields.append(f"{label} {value:+g}" if isinstance(value, (int, float)) else f"{label} {value}")
    return "；".join(fields) or "—"


class ContinuousWatch(Watch):
    def __init__(self, pid, directory, seed, instances, interval=0.05):
        directory = pathlib.Path(directory).resolve()
        super().__init__(pid, directory / "continuous-status.json", seed, instances)
        self.deadline = float("inf")
        self.interval = min(max(interval, 0.025), 0.5)
        self.state = CurrentInventory()
        self.source = None
        self.player_link = None
        self.phase = "starting"
        self.error = None
        self.current_path = directory / "current-loot.json"
        self.text_path = directory / "当前装备.md"
        self.last_sample = None
        self.sample_total = 0
        self.invalid_samples = 0
        self.loop_overruns = 0
        self.loop_time = 0.0
        self.max_loop_time = 0.0
        self.next_publish = 0.0
        self.last_good = 0.0
        self.last_setup = 0.0
        self.occupied = None

    def save(self, stage):
        # Parent discovery calls this. Never write its old, historical event model.
        self.phase = stage
        self.publish()

    def publish(self):
        now = utcnow()
        items = self.state.export()
        status = {
            "status": self.phase, "worker_pid": os.getpid(), "game_pid": self.pid,
            "started_utc": self.result["started_utc"], "heartbeat_utc": now,
            "last_sample_utc": self.last_sample, "target_interval_seconds": self.interval,
            "sample_count": self.sample_total, "current_equipment_count": len(items),
            "invalid_samples": self.invalid_samples, "loop_overruns": self.loop_overruns,
            "mean_loop_ms": round(1000 * self.loop_time / max(self.sample_total, 1), 3),
            "max_loop_ms": round(1000 * self.max_loop_time, 3),
            "bytes_read": self.read_bytes, "read_calls": self.read_calls,
            "source": self.source["label"] if self.source else None,
            "retains_removed_items": False, "red_affixes_evaluated": False,
            "error": self.error,
        }
        payload = {"status": self.phase, "sampled_utc": self.last_sample,
                   "source": status["source"], "count": len(items), "items": items,
                   "backpack_occupied_indices": self.occupied if self.phase == "watching" else None,
                   "backpack_free_slots": 60 - len(self.occupied) if self.phase == "watching" and self.occupied is not None else None,
                   "note": "只保留当前背包；离开背包即移除。属性为读取到的原始数值，红色判定尚未接入。"}
        atomic_text(self.current_path, json.dumps(payload, ensure_ascii=False, indent=2))
        rows = ["# 当前装备", "", f"状态：{self.phase} · 当前 {len(items)} 件 · 更新 {now}", "",
                "仅保留当前背包，离开背包即从本页移除。数值来自游戏内存；未核准的百分号和红色词条不作推断。格子索引是内部索引。", "",
                "| 格子索引 | 装备内部名 | 锁定 | 附加属性 |", "|---|---|---|---|"]
        for entry in items:
            item = entry["item"]
            name = str(item.get("名字", item.get("名称", ""))).replace("|", "\\|")
            affixes = fields_text(item.get("极品属性", item.get("装备极品属性", {}))).replace("|", "\\|")
            rows.append(f"| {entry['index']} | {name} | {'是' if item.get('锁定') else '否'} | {affixes} |")
        rows.extend(["", "## 完整当前属性", "", "```json", json.dumps(items, ensure_ascii=False, indent=2), "```", ""])
        atomic_text(self.text_path, "\n".join(rows))
        atomic_text(self.output, json.dumps(status, ensure_ascii=False, indent=2))
        self.next_publish = time.monotonic() + 1.0

    def take(self, source):
        owner = self.object_info(source['owner']['address'])
        if not owner or owner['index'] != source['owner']['index'] or owner['class_address'] != source['owner']['class_address']:
            return None
        header = self.read(source['header_address'], 16)
        if len(header) != 16:
            return None
        address, count, capacity = struct.unpack('<Qii', header)
        if not (60 <= count <= capacity <= 10000) or not ptr(address):
            return None
        raw = self.read(address, count * source['stride'])
        if len(raw) != count * source['stride'] or header != self.read(source['header_address'], 16):
            return None
        if raw != self.read(address, len(raw)):
            return None
        decoded = [self.decode(raw[i * source['stride']:(i + 1) * source['stride']], source['type_name']) for i in range(count)]
        self.occupied = occupied_main_slots(decoded)
        return {i: self.compact(item) for i, item in enumerate(decoded)
                if item.get('物品类型', item.get('种类')) == 1 and item.get('名字', item.get('名称')) not in (None, '', 'None')}

    def setup_source(self):
        self.state.clear()
        self.source = None
        self.player_link = None
        if self.handle:
            k.CloseHandle(self.handle)
            self.handle = None
        self.sources = []
        self.result.pop("sections", None)
        self.phase = "locating_current_backpack"
        self.publish()
        Watch.prepare(self)
        candidates = [s for s in self.sources if s["label"].endswith(".背包物品简化")]
        if len(candidates) != 1:
            raise ValueError(f"Expected one current backpack, found {len(candidates)}")
        self.source = candidates[0]
        owner = self.source["owner"]
        cls = self.object_info(owner["class_address"])
        if not cls or cls["name"] != "BP_mypawn_C":
            raise ValueError("Backpack does not belong to the validated player class")
        for report in self.result["container_discovery"]:
            if report["class_name"] == "主UI_C":
                for field in report["fields"]:
                    if field["name"] == "对应玩家" and field["kind"] == "ObjectProperty":
                        self.player_link = report["object"]["address"] + field["offset"]
        self.last_setup = time.monotonic()
        self.last_good = self.last_setup
        self.error = None
        self.phase = "watching"

    def game_alive(self):
        code = w.DWORD()
        return bool(self.handle and k.GetExitCodeProcess(self.handle, c.byref(code)) and code.value == 259)

    def player_changed(self):
        if not self.player_link:
            return False
        raw = self.read(self.player_link, 8)
        return len(raw) == 8 and ptr(u64(raw)) and u64(raw) != self.source["owner"]["address"]

    def refresh_names(self):
        pool = self.seed["name_pool"]["address"]
        head = self.read(pool + 8, 8)
        if len(head) != 8:
            return
        block = u32(head)
        if 0 <= block < 512 and block + 1 > len(self.blocks):
            raw = self.read(pool + 16, (block + 1) * 8)
            if len(raw) == (block + 1) * 8:
                self.blocks = list(struct.unpack("<" + "Q" * (block + 1), raw))

    def observe(self):
        next_identity_check = 0.0
        while True:
            begin = time.monotonic()
            self.check()
            if begin >= next_identity_check:
                if not self.game_alive():
                    self.phase = "game_exited"
                    return
                if self.player_changed() or (begin - self.last_good > 3 and begin - self.last_setup > 10):
                    self.setup_source()
                self.refresh_names()
                next_identity_check = begin + 1.0
            owner = self.object_info(self.source["owner"]["address"])
            current = None if not owner or owner["flags"] & 0x18010 else self.take(self.source)
            changed = False
            if current is None:
                self.invalid_samples += 1
                if begin - self.last_good > 0.5:
                    changed = bool(self.state.export())
                    self.state.clear()
                    self.phase = "waiting_for_valid_backpack"
            else:
                changed = self.state.replace(current)
                self.last_sample = utcnow()
                self.last_good = time.monotonic()
                self.phase = "watching"
            self.sample_total += 1
            if changed or time.monotonic() >= self.next_publish:
                self.publish()
            duration = time.monotonic() - begin
            self.loop_time += duration
            self.max_loop_time = max(self.max_loop_time, duration)
            if duration > self.interval:
                self.loop_overruns += 1
            time.sleep(max(0.001, self.interval - duration))

    def run(self):
        lock = open(self.output.parent / "continuous.lock", "a+b")
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock.close()
            raise RuntimeError("A continuous monitor is already running")
        try:
            self.setup_source()
            self.observe()
        except InterruptedError:
            self.phase = "stopped"
        except Exception as exc:
            self.phase = "monitor_failed"
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if self.handle:
                k.CloseHandle(self.handle)
                self.handle = None
            self.state.clear()
            self.publish()
            lock.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--instances", required=True)
    ap.add_argument("--interval", type=float, default=0.05)
    args = ap.parse_args()
    ContinuousWatch(args.pid, pathlib.Path(__file__).resolve().parent, args.seed, args.instances, args.interval).run()
