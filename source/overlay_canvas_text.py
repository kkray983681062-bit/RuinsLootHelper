"""Cached HUD text layout, with no per-section child windows to resize."""
import bisect

COLORS = {'place': '#e6eef7', 'hit': '#ffe29b', 'name': '#f1e4bd', 'muted': '#cfd9e4'}


def wrap_line(text, font, width):
    while text:
        if font.measure(text) <= width:
            yield text
            return
        low, high = 1, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if font.measure(text[:middle]) <= width:
                low = middle
            else:
                high = middle - 1
        yield text[:low]
        text = text[low:]


class SectionView:
    def __init__(self, pane, key, title):
        self.pane, self.key, self.title = pane, key, title
        self.top, self.height = 0, 0
        self.runs, self.rows, self.row_tops = [], [], []
        self.content_height, self.offset = 1, 0.
        self.cache_key = None
        self.scrollbar = self
        self.wheel_delta = 0

    def set_runs(self, runs):
        if runs == self.runs:
            return
        fraction = self.yview()[0]
        self.runs = list(runs)
        self.cache_key = None
        self.layout()
        self.yview_moveto(fraction)

    def layout(self):
        width = max(20, self.pane.winfo_width() - 30)
        key = width, self.pane.font_size
        if self.cache_key == key:
            return
        self.cache_key = key
        self.rows = []
        y = 4
        for text, tag in self.runs:
            font = self.pane.fonts['hit' if tag == 'hit' else 'normal']
            line_height = font.metrics('linespace')
            if tag == 'place':
                y += 3
            for paragraph in str(text).split('\n'):
                for line in wrap_line(paragraph, font, width):
                    self.rows.append((y, line, tag, line_height))
                    y += line_height
            y += 2 if tag == 'hit' else 0
        self.row_tops = [row[0] for row in self.rows]
        self.content_height = max(1, y + 4)

    @property
    def body_top(self):
        return self.top + self.pane.header_height

    @property
    def viewport(self):
        return max(1, self.height - self.pane.header_height - 4)

    @property
    def shown(self):
        return self.content_height > self.viewport

    def clamp(self):
        self.offset = max(0., min(self.offset, max(0, self.content_height - self.viewport)))

    def yview(self):
        self.layout()
        self.clamp()
        return self.offset / self.content_height, min(1., (self.offset + self.viewport) / self.content_height)

    def yview_moveto(self, fraction):
        self.layout()
        self.offset = float(fraction) * self.content_height
        self.clamp()
        self.pane.request_paint()

    def scroll(self, pixels):
        self.offset += pixels
        self.clamp()
        self.pane.request_paint()

    def visible_rows(self):
        self.layout()
        self.clamp()
        start = max(0, bisect.bisect_right(self.row_tops, self.offset) - 1)
        for index in range(start, len(self.rows)):
            row = self.rows[index]
            if row[0] > self.offset + self.viewport:
                break
            yield index, row

    def thumb(self):
        self.layout()
        self.clamp()
        height = min(self.viewport, max(22, self.viewport * self.viewport / self.content_height))
        travel = max(0, self.viewport - height)
        fraction = self.offset / max(1, self.content_height - self.viewport)
        return self.body_top + fraction * travel, height, travel

    def winfo_y(self):
        return self.top

    def winfo_height(self):
        return self.height

    def event_generate(self, sequence, **kwargs):
        kwargs.setdefault('x', 20)
        kwargs.setdefault('y', int(self.body_top + min(10, self.viewport / 2)))
        return self.pane.event_generate(sequence, **kwargs)
