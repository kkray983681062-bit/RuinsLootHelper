"""Locate the backpack by its header lock, then fit the visible 10 x 6 grid."""
from pathlib import Path
import threading
import time


class LockDetector:
    def __init__(self):
        import cv2
        import numpy as np
        self.cv, self.np = cv2, np
        cv2.setNumThreads(1)
        self.template = cv2.imdecode(np.fromfile(Path(__file__).with_name('assets') / 'backpack-lock.png', np.uint8), 0)
        if self.template is None:
            raise ValueError('缺少背包锁定位图片')
        self.previous = None

    def locate(self, frame, hint=None):
        cv, np = self.cv, self.np
        gray = cv.cvtColor(frame, cv.COLOR_BGRA2GRAY if frame.shape[2] == 4 else cv.COLOR_BGR2GRAY)
        height, width = gray.shape
        best = None
        if hint:
            hx, hy = hint[0]*width, hint[1]*height
            left, top = max(0, int(hx-140)), max(0, int(hy-140))
            right, bottom = min(width, int(hx+140)), min(height, int(hy+140))
            best = self._match(gray[top:bottom, left:right], range(18, 110))
            if best:
                score, x, y, scale = best
                best = (score, x+left, y+top, scale)
        # Most frames only search a small area around the previous header lock.
        if not best and self.previous:
            x, y, scale = self.previous
            left, top = max(0, int(x - 160)), max(0, int(y - 110))
            right, bottom = min(width, int(x + 200)), min(height, int(y + 160))
            best = self._match(gray[top:bottom, left:right], [round(46 * scale) + d for d in (0, -1, 1)])
            if best:
                score, x, y, scale = best
                best = (score, x + left, y + top, scale)
        if not best:
            # Downsample only the broad search; the grid is fitted at native resolution.
            factor = min(1., 1400 / width)
            small = cv.resize(gray, None, fx=factor, fy=factor) if factor < 1 else gray
            target = max(12, round(46 * height / 1360 * factor))
            sizes = sorted(range(max(10, round(target * .45)), round(target * 2.1) + 1), key=lambda n: abs(n-target))
            best = self._match(small, sizes)
            if best:
                score, x, y, scale = best
                best = (score, x / factor, y / factor, scale / factor)
        if not best:
            self.previous = None
            return None, {'state': 'searching_lock'}
        score, x, y, scale = best
        boxes, count = self._grid(gray, x, y, scale)
        if boxes is None:
            self.previous = None
            return None, {'state': 'searching_cells', 'confidence': round(score, 3), 'cells_seen': count}
        self.previous = (x, y, scale)
        return {'viewport': [width, height], 'slots': boxes, 'source': 'header_lock'}, {
            'state': 'ready', 'confidence': round(score, 3), 'cells_seen': count,
            'lock': [round(x), round(y), round(34*scale), round(46*scale)]}

    def _match(self, gray, heights):
        cv = self.cv
        best = None
        for h in heights:
            w = max(8, round(h * 34 / 46))
            if gray.shape[0] < h or gray.shape[1] < w:
                continue
            template = cv.resize(self.template, (w, h), interpolation=cv.INTER_AREA if h < 46 else cv.INTER_LINEAR)
            _, score, _, pos = cv.minMaxLoc(cv.matchTemplate(gray, template, cv.TM_CCOEFF_NORMED))
            if score >= .86 and (best is None or score > best[0]):
                best = (score, pos[0], pos[1], h / 46)
                if score >= .96:
                    break
        return best

    def _grid(self, gray, x, y, scale):
        cv, np = self.cv, self.np
        # Relative layout from the supplied header/cell image. This is a search
        # seed only: observed borders below determine the final origin/pitches.
        pitch, size = 88.14 * scale, 77 * scale
        gx, gy = x - 409 * scale, y + 79 * scale
        h, w = gray.shape
        left, top = max(0, int(gx-pitch*.5)), max(0, int(gy-pitch*.5))
        right, bottom = min(w, int(gx+pitch*10.5)), min(h, int(gy+pitch*6.5))
        if right <= left or bottom <= top:
            return None, 0
        edges = cv.Canny(gray[top:bottom, left:right], 45, 110)
        contours, _ = cv.findContours(edges, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
        found = {}
        for contour in contours:
            bx, by, bw, bh = cv.boundingRect(contour)
            if not (size*.78 <= bw <= size*1.2 and size*.78 <= bh <= size*1.2 and .86 <= bw/bh <= 1.16):
                continue
            if cv.contourArea(contour) < bw * bh * .78:
                continue
            cx, cy = bx+left+bw/2, by+top+bh/2
            col, row = round((cx-gx-size/2)/pitch), round((cy-gy-size/2)/pitch)
            if not (0 <= col < 10 and 0 <= row < 6):
                continue
            error = abs(cx-(gx+col*pitch+size/2)) + abs(cy-(gy+row*pitch+size/2))
            if error > pitch*.55:
                continue
            quality = abs(bw-size) + abs(bh-size) + error*.2
            key = row*10+col
            if key not in found or quality < found[key][0]:
                found[key] = (quality, col, row, cx, cy)
        if len(found) < 12:
            return None, len(found)
        points = np.array(list(found.values()), dtype=float)
        if len(set(points[:, 1])) < 5 or len(set(points[:, 2])) < 3:
            return None, len(found)
        def fit(points):
            ax = np.column_stack((points[:, 1], np.ones(len(points))))
            ay = np.column_stack((points[:, 2], np.ones(len(points))))
            px, cx = np.linalg.lstsq(ax, points[:, 3], rcond=None)[0]
            py, cy = np.linalg.lstsq(ay, points[:, 4], rcond=None)[0]
            return px, py, cx, cy
        px, py, cx, cy = fit(points)
        good = (np.abs(points[:, 3]-(points[:, 1]*px+cx)) < pitch*.12) & (np.abs(points[:, 4]-(points[:, 2]*py+cy)) < pitch*.12)
        if int(good.sum()) < 12:
            return None, int(good.sum())
        px, py, cx, cy = fit(points[good])
        if not (.9*pitch <= px <= 1.1*pitch and .9*pitch <= py <= 1.1*pitch):
            return None, int(good.sum())
        boxes = {str(i): [round(cx+(i%10)*px-px*.435), round(cy+(i//10)*py-py*.435),
                         round(cx+(i%10)*px+px*.435), round(cy+(i//10)*py+py*.435)] for i in range(60)}
        from feature_policy import native_slot_rects
        grid = {'viewport': [w, h], 'slots': boxes}
        return (boxes if native_slot_rects(grid, w, h) else None), int(good.sum())


class AnchorWorker:
    """Screen reads and CV work stay off Tk; requests/results contain no widgets."""
    def __init__(self):
        self.target = None
        self.result = None
        self.hint = None
        self.error = None
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.run, name='BackpackLockLocator', daemon=True)
        self.thread.start()

    def request(self, hwnd, pid, player, bounds):
        key = (int(hwnd), pid, player, tuple(bounds))
        self.target = (key, time.monotonic())
        result = self.result
        return result if result and result['key'] == key and time.monotonic()-result['at'] < .45 else None

    def suspend(self):
        self.target = self.result = None

    def set_hint(self, point):
        self.hint = tuple(point)

    def close(self):
        self.closed.set()
        self.thread.join(2)

    def run(self):
        try:
            import mss
            import numpy as np
            detector = LockDetector()
            previous_key = None
            with mss.mss() as capture:
                while not self.closed.is_set():
                    target = self.target
                    if target and time.monotonic()-target[1] < .4:
                        key = target[0]
                        if previous_key != key:
                            detector.previous = None
                            previous_key = key
                        from overlay_markers import foreground_matches, game_bounds
                        if foreground_matches(key[0], key[1]) and game_bounds(key[0]) == key[3]:
                            x, y, width, height = key[3]
                            started = time.monotonic()
                            frame = np.asarray(capture.grab({'left': x, 'top': y, 'width': width, 'height': height}))
                            grid, info = detector.locate(frame, self.hint)
                            self.hint = None
                            info['ms'] = round((time.monotonic()-started)*1000, 1)
                            if self.target and self.target[0] == key:
                                self.result = {'key': key, 'at': time.monotonic(), 'grid': grid, 'info': info}
                        else:
                            self.result = None
                    else:
                        detector.previous = None
                        self.result = None
                    self.closed.wait(.1)
        except Exception as exc:
            self.result = None
            self.error = f'{type(exc).__name__}: {exc}'
