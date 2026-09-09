import hashlib
import io
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app_update import release_info, version_key, download_release, fetch_release, UpdateWorker, load_links


class UpdateTests(unittest.TestCase):
    def payload(self, version='0.4.0'):
        name = f'破晓装备助手-{version}-Windows-x64.zip'
        home = 'https://github.com/kkray983681062-bit/RuinsLootHelper'
        return {'tag_name': 'v' + version, 'html_url': home + '/releases/tag/v' + version,
                'draft': False, 'prerelease': False,
                'assets': [{'name': name, 'state': 'uploaded', 'size': 123,
                            'browser_download_url': home + '/releases/download/v' + version + '/' + name,
                            'digest': 'sha256:' + '0' * 64}]}

    def test_numeric_version_order_and_nonstable_tags(self):
        self.assertGreater(version_key('v0.10.0'), version_key('0.9.9'))
        self.assertEqual(version_key('0.3.1'), version_key('0.3.1.0'))
        self.assertIsNone(version_key('0.4.0-rc1'))
        for changes in ({'draft': True}, {'prerelease': True}, {'tag_name': 'latest'}):
            self.assertEqual(release_info(self.payload() | changes, '0.3.1')['state'], 'unpublished')
        self.assertEqual(release_info(self.payload('0.3.0'), '0.3.1')['state'], 'current')

    def test_only_own_complete_windows_asset_is_offered(self):
        payload = self.payload()
        self.assertEqual(release_info(payload, '0.3.1')['state'], 'available')
        payload['assets'][0]['browser_download_url'] = 'https://example.com/foreign.zip'
        self.assertEqual(release_info(payload, '0.3.1')['state'], 'pending')
        payload = self.payload()
        payload['assets'][0]['name'] = '../../evil.zip'
        self.assertEqual(release_info(payload, '0.3.1')['state'], 'pending')
        self.assertEqual(release_info(self.payload() | {'assets': []}, '0.3.1')['state'], 'pending')

    def zipped(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('破晓装备助手/使用说明.txt', 'fixture')
        return output.getvalue()

    def response(self, data):
        result = io.BytesIO(data)
        result.geturl = lambda: 'https://release-assets.githubusercontent.com/fixture'
        return result

    def test_download_validates_hash_then_saves_without_executing(self):
        data = self.zipped()
        info = release_info(self.payload(), '0.3.1')
        info['asset'].update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as tmp, patch('app_update.urlopen', return_value=self.response(data)):
            path = download_release(info, Path(tmp), threading.Event())
            self.assertEqual(path.read_bytes(), data)
            self.assertFalse(list(Path(tmp).rglob('*.exe')))
            self.assertFalse(list(Path(tmp).rglob('*.part')))

    def test_bad_or_missing_digest_never_leaves_download(self):
        data = self.zipped()
        info = release_info(self.payload(), '0.3.1')
        info['asset']['size'] = len(data)
        for digest in ('0' * 64, None):
            info['asset']['sha256'] = digest
            with tempfile.TemporaryDirectory() as tmp, patch('app_update.urlopen', return_value=self.response(data)):
                with self.assertRaises(ValueError):
                    download_release(info, Path(tmp), threading.Event())
                self.assertFalse(list(Path(tmp).rglob('*.zip')))
                self.assertFalse(list(Path(tmp).rglob('*.part')))

    def test_background_check_does_not_block_caller_or_read_game(self):
        started, release = threading.Event(), threading.Event()
        def slow_check(*args):
            started.set()
            release.wait(2)
            return {'state': 'current'}
        with tempfile.TemporaryDirectory() as tmp, patch('app_update.fetch_release', side_effect=slow_check):
            worker = UpdateWorker('0.3.1', Path(tmp))
            try:
                worker.check()
                self.assertTrue(started.wait(1))
                self.assertEqual(worker.snapshot['state'], 'checking')
                self.assertFalse(worker.check())
            finally:
                release.set()
                worker.thread.join(2)
                worker.close()

    def test_published_links_match_user_handoff(self):
        links = load_links()
        self.assertEqual(links['lanzou_download_url'], 'https://wwaou.lanzoup.com/b01giaqhvg')
        self.assertEqual(links['lanzou_password'], '71my')


if __name__ == '__main__':
    unittest.main()
