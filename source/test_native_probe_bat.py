"""Exercise the standalone probe using isolated files, never a live game."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
BAT = ROOT / "packaging" / "破晓助手功能探针.bat"


class NativeProbeTest(unittest.TestCase):
    def collect(self, scenario):
        with tempfile.TemporaryDirectory(prefix="native-probe-tests-", dir=ROOT) as tmp:
            base = Path(tmp).resolve()
            self.assertTrue(base.is_relative_to(ROOT))
            package = base / "中文 O'Brien & 测试!(目录)"
            package.mkdir()
            copied = package / BAT.name
            copied.write_bytes(BAT.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            data, output = base / "data", base / "output"
            data.mkdir()
            if scenario != "missing":
                now = time.time()
                from datetime import datetime, timezone
                iso = datetime.now(timezone.utc).isoformat()
                files = {
                    "loot-overlay-settings.json": {
                        "native": {"pickup": True, "lock": True, "lock_sections": {"numeric": True}}
                    },
                    "loot-filter-rules.json": [
                        {"key": "cast_speed", "label": "施法速度", "field": "施法速度+",
                         "group": "特殊属性", "enabled": True, "min": 47, "unit": "%"}
                    ],
                    "continuous-status.json": {"status": "watching", "heartbeat_utc": iso, "game_pid": 123},
                    "feature-status.json": {"status": "running", "ui": {"valid": True, "backpack_open": False}},
                    "native-schema.json": {"pid": 123},
                    "native-request.json": {"protocol": 4, "game_pid": 123, "player_address": 555,
                        "session": "sample-session", "expires": now + 1.9, "active": True, "pickup": True,
                        "auto_lock": True, "locks": []},
                    "native-status.json": {"protocol": 4, "game_pid": 123, "player_address": 555,
                        "session": "sample-session", "utc": now, "ready": True, "state": "ready",
                        "pickup_state": "menu", "acks": []},
                    "current-loot.json": {"status": "watching", "items": [{"name": "PRIVATE_INVENTORY_SENTINEL"}],
                        "backpack_free_slots": 15},
                    "matches-current.json": {"live": True, "numeric": [], "legendary": [], "lower": []},
                }
                if scenario == "stale":
                    files["native-status.json"]["utc"] = now - 90
                    files["native-status.json"]["pickup_state"] = "inactive"
                for name, value in files.items():
                    (data / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                (data / "unrelated.txt").write_text("UNRELATED_SECRET_SENTINEL", encoding="utf-8")
                if scenario == "corrupt":
                    (data / "native-status.json").write_text("{bad json", encoding="utf-8")
                (data / "startup-error.txt").write_text(
                    "sample read error " + str(Path.home() / "private-path"), encoding="utf-8"
                )
            before = {p.name: p.read_bytes() for p in data.iterdir()}
            env = dict(os.environ, RLH_PROBE_DATA_DIR=str(data), RLH_PROBE_OUTPUT_DIR=str(output),
                       RLH_PROBE_NO_PAUSE="1", RLH_PROBE_SECONDS="0", RLH_PROBE_SKIP_SYSTEM="1")
            command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{copied}""'
            result = subprocess.run(command, env=env, cwd=package, capture_output=True, timeout=30)
            console = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, console)
            logs = list(output.glob("*.log"))
            self.assertEqual(len(logs), 1, console)
            log = logs[0].read_text("utf-8-sig")
            self.assertIn("诊断结论", log)
            self.assertEqual(before, {p.name: p.read_bytes() for p in data.iterdir()})
            self.assertNotIn("PRIVATE_INVENTORY_SENTINEL", log)
            self.assertNotIn("UNRELATED_SECRET_SENTINEL", log)
            self.assertNotIn(str(Path.home()).casefold(), log.casefold())
            return log

    def test_no_files_still_saves_log(self):
        self.assertIn("没有收到新鲜的游戏组件心跳", self.collect("missing"))

    def test_connected_menu_pause_and_rules(self):
        log = self.collect("ready")
        self.assertIn("通信链路曾正常接通", log)
        self.assertIn("曾因背包、菜单", log)
        self.assertIn("施法速度", log)
        self.assertIn('"min":  47', log)

    def test_corrupt_file_does_not_prevent_report(self):
        self.assertIn("状态文件读取失败：native-status.json", self.collect("corrupt"))

    def test_stale_native_state_is_not_current_pause(self):
        log = self.collect("stale")
        self.assertIn("没有收到新鲜的游戏组件心跳", log)
        self.assertNotIn("曾因游戏不在前台/助手未就绪而暂停拾取", log)


if __name__ == "__main__":
    unittest.main()
