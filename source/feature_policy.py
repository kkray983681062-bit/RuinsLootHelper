"""Coordinate validation for current-inventory markers."""
import math


def slot_rect(index, grid, width, height):
    if not isinstance(index, int) or not 0 <= index < 60 or not isinstance(grid, (list, tuple)) or len(grid) != 4:
        return None
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in grid):
        return None
    x, y, gw, gh = grid
    if min(x, y) < 0 or min(gw, gh) <= 0 or x + gw > 1.001 or y + gh > 1.001:
        return None
    col, row = index % 10, index // 10
    return tuple(round(v) for v in ((x + col * gw / 10) * width, (y + row * gh / 6) * height,
                                    (x + (col + 1) * gw / 10) * width, (y + (row + 1) * gh / 6) * height))


def native_slot_rects(grid, width, height):
    """Accept a complete, current 10x6 grid in client pixels, never a guessed ROI."""
    if not isinstance(grid, dict) or grid.get('viewport') != [width, height]:
        return None
    source = grid.get('slots', {})
    if not isinstance(source, dict) or len(source) != 60:
        return None
    result = {}
    for index in range(60):
        box = source.get(str(index))
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box):
            return None
        left, top, right, bottom = box
        if not (0 <= left < right <= width and 0 <= top < bottom <= height and right-left > 8 and bottom-top > 8):
            return None
        if index % 10 and left < result[index-1][2] - 3:
            return None
        if index >= 10 and top < result[index-10][3] - 3:
            return None
        result[index] = tuple(round(x) for x in box)
    return result
