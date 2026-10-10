"""One frozen frame, many independently ordered rectangular crops."""
from PySide6.QtCore import QRect

from core.image_layout import MAX_IMAGES, MAX_SOURCE_PIXELS


class MultiRegionSelection:
    def __init__(self, bounds, max_regions=MAX_IMAGES, max_pixels=MAX_SOURCE_PIXELS):
        self.bounds = QRect(bounds)
        self.max_regions, self.max_pixels = max_regions, max_pixels
        self._regions = []
        self._undo, self._redo = [], []

    @property
    def regions(self):
        return [QRect(r) for r in self._regions]

    @property
    def pixels(self):
        return sum(r.width() * r.height() for r in self._regions)

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def _set(self, regions):
        if regions == self._regions:
            return False
        self._undo.append(self.regions)
        self._undo = self._undo[-100:]
        self._redo.clear()
        self._regions = [QRect(r) for r in regions]
        return True

    def add(self, rect):
        rect = QRect(rect).normalized().intersected(self.bounds)
        if rect.width() < 8 or rect.height() < 8:
            raise ValueError("Region must be at least 8 × 8 pixels")
        if len(self._regions) >= self.max_regions or self.pixels + rect.width() * rect.height() > self.max_pixels:
            raise ValueError("Regions exceed the collection capacity")
        return self._set(self.regions + [rect])

    def remove(self, index):
        if not 0 <= index < len(self._regions):
            return False
        return self._set([r for i, r in enumerate(self.regions) if i != index])

    def move(self, index, delta):
        regions = self.regions
        if not 0 <= index < len(regions) or not 0 <= index + delta < len(regions):
            return False
        regions[index], regions[index + delta] = regions[index + delta], regions[index]
        return self._set(regions)

    def clear(self):
        return self._set([])

    def undo(self):
        if self._undo:
            self._redo.append(self.regions)
            self._regions = self._undo.pop()
            return True
        return False

    def redo(self):
        if self._redo:
            self._undo.append(self.regions)
            self._regions = self._redo.pop()
            return True
        return False
