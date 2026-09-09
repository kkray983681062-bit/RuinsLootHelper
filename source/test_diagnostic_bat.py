"""Run the shareable BAT against isolated support files, without opening windows."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parent
BAT = ROOT / 'packaging' / '破晓助手一键诊断.bat'


class DiagnosticBatTest(unittest.TestCase):
    def collect(self, with_logs):
        self.assertTrue(BAT.is_file(), 'The standalone diagnostic BAT is missing')
        with tempfile.TemporaryDirectory(prefix='loot-diag-', dir=ROOT) as temporary:
            base = Path(temporary)
            # Quoting must survive Chinese, spaces, apostrophes, &, ! and parentheses.
            package = base / "中文 O'Brien & 测试!(目录)"
            package.mkdir()
            copied = package / BAT.name
            copied.write_bytes(BAT.read_bytes())
            data = base / 'support-data'
            data.mkdir()
            if with_logs:
                (data / 'startup-error.txt').write_text(
                    'ValueError: test diagnostic\n' + str(Path.home() / 'private-path'),
                    encoding='utf-8')
                (data / 'overlay-status.json').write_text(
                    json.dumps({'status': 'display_error', 'error': '测试错误'}, ensure_ascii=False),
                    encoding='utf-8')
                (data / 'continuous-status.json').write_text('{"status":"watching"}', encoding='utf-8')
                (data / 'current-loot.json').write_text('{"items":["PRIVATE_INVENTORY_SENTINEL"]}', encoding='utf-8')
                (data / 'unrelated-secret.txt').write_text('DO_NOT_COLLECT_SENTINEL', encoding='utf-8')
            before = {p.name: p.read_bytes() for p in data.iterdir()}
            output = base / 'output'
            env = dict(os.environ, RLH_DIAG_DATA_DIR=str(data), RLH_DIAG_OUTPUT_DIR=str(output),
                       RLH_DIAG_NO_UI='1', RLH_DIAG_NO_PAUSE='1', RLH_DIAG_SKIP_EVENTS='1')
            command = f'"{os.environ["COMSPEC"]}" /d /s /c ""{copied}""'
            result = subprocess.run(command,
                                    env=env, cwd=package, capture_output=True, timeout=75)
            console = (result.stdout + result.stderr).decode('utf-8', errors='replace')
            self.assertEqual(result.returncode, 0, console)
            archives = list(output.glob('*.zip'))
            self.assertEqual(len(archives), 1, console)
            self.assertEqual(before, {p.name: p.read_bytes() for p in data.iterdir()})
            with zipfile.ZipFile(archives[0]) as archive:
                self.assertIsNone(archive.testzip())
                contents = {name: archive.read(name).decode('utf-8-sig') for name in archive.namelist()}
            text = '\n'.join(contents.values())
            self.assertNotIn('PRIVATE_INVENTORY_SENTINEL', text)
            self.assertNotIn('DO_NOT_COLLECT_SENTINEL', text)
            self.assertNotIn(str(Path.home()).casefold(), text.casefold())
            report = json.loads(contents['report.json'])
            self.assertEqual(report['tool_version'], '1.0')
            if with_logs:
                self.assertIn('ValueError: test diagnostic', contents['startup-error.txt'])
                self.assertIn('测试错误', contents['overlay-status.json'])
                self.assertIn('[USERPROFILE]', contents['startup-error.txt'])
            else:
                self.assertTrue(report['missing_files'])
                self.assertIn('诊断说明.txt', contents)

    def test_existing_logs_and_non_ascii_path(self):
        self.collect(True)

    def test_no_logs_still_produces_report(self):
        self.collect(False)


if __name__ == '__main__':
    unittest.main()
