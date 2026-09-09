"""Public release checks and verified ZIP downloads, independent of game data."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
import zipfile

HOME = 'https://github.com/kkray983681062-bit/RuinsLootHelper'
LATEST = 'https://api.github.com/repos/kkray983681062-bit/RuinsLootHelper/releases/latest'
MAX_PACKAGE = 512 * 1024 * 1024
HEADERS = {'User-Agent': 'RuinsLootHelper', 'Accept': 'application/vnd.github+json',
           'X-GitHub-Api-Version': '2022-11-28'}


def load_links():
    return json.loads(Path(__file__).with_name('project-links.json').read_text(encoding='utf-8-sig'))


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+(?:\.\d+)?', value):
        return None
    parts = tuple(int(x) for x in value.removeprefix('v').split('.'))
    return parts + (0,) * (4-len(parts))


def own_asset(url, filename):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    return (parsed.scheme == 'https' and parsed.netloc == 'github.com'
            and path.startswith('/kkray983681062-bit/RuinsLootHelper/releases/download/')
            and path.rsplit('/', 1)[-1] == filename and not parsed.query and not parsed.fragment)


def release_info(payload, current):
    if not isinstance(payload, dict) or payload.get('draft') or payload.get('prerelease'):
        return {'state': 'unpublished'}
    tag = payload.get('tag_name')
    key = version_key(tag)
    if key is None:
        return {'state': 'unpublished'}
    version = tag.removeprefix('v')
    if key <= (version_key(current) or (0, 0, 0, 0)):
        return {'state': 'current', 'version': version}
    info = {'state': 'pending', 'version': version,
            'release_url': HOME + '/releases/tag/' + quote(tag, safe=''), 'asset': None}
    names = {f'破晓装备助手-{version}-Windows-x64.zip', f'RuinsLootHelper-{version}-Windows-x64.zip'}
    for asset in payload.get('assets', []) or []:
        if not isinstance(asset, dict):
            continue
        name, size = asset.get('name'), asset.get('size')
        if (name not in names or asset.get('state') != 'uploaded' or type(size) is not int
                or not 0 < size <= MAX_PACKAGE or not own_asset(asset.get('browser_download_url'), name)):
            continue
        digest = asset.get('digest') or ''
        sha = digest[7:].lower() if isinstance(digest, str) and re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest) else None
        info.update(state='available', asset={'name': name, 'size': size, 'sha256': sha,
                                             'url': asset['browser_download_url']})
        break
    return info


def fetch_release(current):
    try:
        with urlopen(Request(LATEST, headers=HEADERS), timeout=8) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('版本信息过大')
            return release_info(json.loads(raw), current)
    except HTTPError as error:
        if error.code == 404:
            return {'state': 'unpublished'}
        raise


def download_release(info, directory, cancelled, progress=lambda done, total: None):
    asset = info.get('asset') or {}
    digest = asset.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('发布包尚未提供校验值，请使用下载页')
    name, size = asset.get('name'), asset.get('size')
    if (not isinstance(name, str) or '/' in name or '\\' in name or not own_asset(asset.get('url'), name)
            or type(size) is not int or not 0 < size <= MAX_PACKAGE):
        raise ValueError('下载信息不完整')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / name
    temporary = None
    try:
        request = Request(quote(asset['url'], safe=':/%?=&'), headers={'User-Agent': HEADERS['User-Agent']})
        with urlopen(request, timeout=10) as response:
            destination = urlsplit(response.geturl())
            if destination.scheme != 'https' or not (destination.hostname == 'github.com'
                    or (destination.hostname or '').endswith('.githubusercontent.com')):
                raise ValueError('下载地址发生了异常跳转')
            with tempfile.NamedTemporaryFile(dir=directory, suffix='.part', delete=False) as output:
                temporary = Path(output.name)
                hasher, received, last_progress = hashlib.sha256(), 0, 0.
                deadline = time.monotonic() + 15 * 60
                while True:
                    if cancelled.is_set():
                        raise InterruptedError('下载已取消')
                    if time.monotonic() > deadline:
                        raise TimeoutError('下载超时')
                    block = response.read(128 * 1024)
                    if not block:
                        break
                    received += len(block)
                    if received > size:
                        raise ValueError('下载大小与发布信息不一致')
                    output.write(block)
                    hasher.update(block)
                    if time.monotonic()-last_progress >= .2:
                        progress(received, size)
                        last_progress = time.monotonic()
        if received != size or hasher.hexdigest() != digest:
            raise ValueError('下载不完整或校验失败，请重新下载')
        if not zipfile.is_zipfile(temporary):
            raise ValueError('下载内容不是完整 ZIP 包')
        if cancelled.is_set():
            raise InterruptedError('下载已取消')
        temporary.replace(final)
        return final
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class UpdateWorker:
    def __init__(self, version, directory):
        self.version, self.directory = version, Path(directory)
        self.snapshot = {'state': 'idle'}
        self.release = None
        self.closed = threading.Event()
        self.thread = None
        self.last_check = 0.

    def publish(self, result):
        if not self.closed.is_set():
            self.snapshot = result

    def check(self):
        if self.closed.is_set() or (self.thread and self.thread.is_alive()):
            return False
        self.snapshot = {'state': 'checking'}
        self.last_check = time.monotonic()
        self.thread = threading.Thread(target=self._check, name='ReleaseCheck', daemon=True)
        self.thread.start()
        return True

    def _check(self):
        try:
            result = fetch_release(self.version)
            self.release = result if result['state'] in ('available', 'pending') else None
        except Exception:
            result = {'state': 'unavailable', 'message': '暂时无法检查，请到蓝奏云查看。助手仍可正常使用。'}
        self.publish(result)

    def download(self):
        if self.closed.is_set() or not self.release or (self.thread and self.thread.is_alive()):
            return False
        self.snapshot = {'state': 'downloading', 'progress': 0}
        self.thread = threading.Thread(target=self._download, name='ReleaseDownload', daemon=True)
        self.thread.start()
        return True

    def _download(self):
        try:
            path = download_release(self.release, self.directory, self.closed,
                                    lambda done, total: self.publish({'state': 'downloading', 'progress': int(done*100/total)}))
            self.publish({'state': 'downloaded', 'path': str(path)})
        except Exception as error:
            self.publish({'state': 'download_error', 'message': '下载未完成：' + str(error)[:100]})

    def close(self):
        self.closed.set()
