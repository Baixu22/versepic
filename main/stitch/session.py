"""Bounded scroll-capture checkpoints and correctable seams, in screen orientation."""
from dataclasses import dataclass
from io import BytesIO
import hashlib

from PIL import Image


class StitchLimitError(ValueError):
    pass


@dataclass(frozen=True)
class StitchState:
    result: object = None
    last_frame: object = None
    fingerprint: str = ""
    count: int = 0
    direction: object = None
    distances: tuple = ()
    overlap: int = 0


def orient(image, axis, reverse=False):
    result = image.transpose(Image.Transpose.ROTATE_270) if axis == "horizontal" else image
    return result.transpose(Image.Transpose.FLIP_TOP_BOTTOM) if reverse else result


def restore(image, axis, reverse=False):
    result = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM) if reverse else image
    return result.transpose(Image.Transpose.ROTATE_90) if axis == "horizontal" else result


def detect_shift(previous, incoming, axis, locked, ignore_top=0, ignore_right=0):
    """Match cropped *frame* copies with the existing Rust engine; never crop output pixels."""
    import longstitch
    if previous.size != incoming.size:
        raise ValueError("Capture dimensions changed")
    width, height = previous.size
    if not 0 <= ignore_top < height - 7 or not 0 <= ignore_right < width - 7:
        raise ValueError("Ignore area leaves too few matching pixels")
    box = (0, ignore_top, width - ignore_right, height)
    a, b = orient(previous.crop(box), axis, locked == "up"), orient(incoming.crop(box), axis, locked == "up")
    first, second = BytesIO(), BytesIO()
    a.save(first, "PNG")
    b.save(second, "PNG")
    matched = longstitch.stitch(first.getvalue(), second.getvalue(), detect_direction=locked is None,
                                ignore_right_pixels=0, ignore_top_pixels=0)
    if matched is None:
        return None
    with Image.open(BytesIO(matched.png)) as result:
        shift = result.height - a.height
        if result.width != a.width or shift <= 0 or shift >= a.height:
            return None
    direction = locked or ("up" if matched.direction == "reverse" else "down")
    return shift, direction


def join_images(base, frame, axis, direction, overlap, max_pixels=64_000_000, max_length=100_000):
    a, b = orient(base, axis, direction == "up"), orient(frame, axis, direction == "up")
    if a.width != b.width or not 0 <= overlap < min(a.height, b.height):
        raise ValueError("Overlap must leave some new image content")
    height = a.height + b.height - overlap
    if a.width * height > max_pixels or max(a.width, height) > 100_000 or height > max_length:
        raise StitchLimitError("Stitched output exceeds the image limit")
    output = Image.new("RGB", (a.width, height))
    output.paste(a, (0, 0))
    output.paste(b.crop((0, overlap, b.width, b.height)), (0, a.height))
    return restore(output, axis, direction == "up")


class StitchSession:
    def __init__(self, axis="vertical", *, max_checkpoints=3, retained_bytes=96*1024*1024, max_pixels=64_000_000):
        self.axis = axis
        self.max_checkpoints, self.budget, self.max_pixels = max_checkpoints, retained_bytes, max_pixels
        self.state = StitchState()
        self.checkpoints = []
        self.pending = None
        self.pending_distance = 0
        self.ignore_top = self.ignore_right = 0

    @property
    def retained_bytes(self):
        images = {}
        current = {id(self.state.result), id(self.state.last_frame)}
        for state in self.checkpoints:
            for image in (state.result, state.last_frame):
                if image is not None and id(image) not in current:
                    images[id(image)] = image.width * image.height * 4
        if self.pending is not None and id(self.pending) not in current:
            images[id(self.pending)] = self.pending.width * self.pending.height * 4
        return sum(images.values())

    def _trim(self):
        while self.checkpoints and (len(self.checkpoints) > self.max_checkpoints or self.retained_bytes > self.budget):
            self.checkpoints.pop(0)
        if self.retained_bytes > self.budget:
            self.pending = None

    def set_axis(self, axis):
        if axis not in ("vertical", "horizontal"):
            raise ValueError("Invalid scroll axis")
        if self.state.count > 1 and axis != self.axis:
            raise ValueError("Undo all seams before changing direction")
        self.axis = axis
        self.pending = None
        self.checkpoints.clear()

    def set_ignore(self, top, right):
        if self.state.last_frame is not None:
            width, height = self.state.last_frame.size
            if not 0 <= top <= height - 8 or not 0 <= right <= width - 8:
                raise ValueError("Ignore area leaves too few matching pixels")
        elif top < 0 or right < 0:
            raise ValueError("Ignore values must be nonnegative")
        self.ignore_top, self.ignore_right = int(top), int(right)

    def add(self, frame, distance=0, *, max_length=100_000):
        if min(frame.size) < 8 or frame.width*frame.height > 16_000_000 or max(frame.size) > 32768:
            raise StitchLimitError("Capture frame exceeds the frame limit")
        if self.state.last_frame is not None and self.state.last_frame.size != frame.size:
            raise ValueError("Capture dimensions changed")
        frame = frame.convert("RGB")
        fingerprint = hashlib.sha256(frame.tobytes()).hexdigest()
        if fingerprint == self.state.fingerprint:
            self.pending = None
            return "duplicate"
        if self.state.result is None:
            self.state = StitchState(frame, frame, fingerprint, 1, None, (0,), 0)
            self.pending = None
            return "added"
        self.pending, self.pending_distance = frame, distance
        self._trim()
        detected = detect_shift(self.state.last_frame, frame, self.axis, self.state.direction,
                                 self.ignore_top, self.ignore_right)
        if detected is None:
            return "unmatched"
        shift, direction = detected
        length = frame.height if self.axis == "vertical" else frame.width
        result = join_images(self.state.result, frame, self.axis, direction, length-shift, self.max_pixels, max_length)
        self._commit(result, frame, fingerprint, direction, length-shift, distance)
        return "added"

    def _commit(self, result, frame, fingerprint, direction, overlap, distance):
        before = self.state
        self.checkpoints.append(before)
        self.state = StitchState(result, frame, fingerprint, before.count+1, direction,
                                 before.distances+(distance,), overlap)
        self.pending = None
        self._trim()

    def undo(self):
        if not self.checkpoints:
            return False
        self.state = self.checkpoints.pop()
        self.pending = None
        self._trim()
        return True

    def seam(self):
        if self.pending is not None:
            length = self.pending.height if self.axis == "vertical" else self.pending.width
            return self.state, self.pending, max(1, length//2), self.state.direction or "down", True
        if self.checkpoints:
            return self.checkpoints[-1], self.state.last_frame, self.state.overlap, self.state.direction, False
        return None

    def repair(self, overlap, direction):
        pair = self.seam()
        if pair is None:
            raise ValueError("Seam images are no longer retained")
        before, frame, _, _, pending = pair
        if direction not in ("up", "down") or (before.direction is not None and direction != before.direction):
            raise ValueError("Cannot reverse an already stitched capture")
        result = join_images(before.result, frame, self.axis, direction, overlap, self.max_pixels)
        if not pending:
            self.checkpoints.pop()
        distance = self.pending_distance if pending else self.state.distances[-1]
        self.state = before
        self._commit(result, frame, hashlib.sha256(frame.tobytes()).hexdigest(), direction, overlap, distance)

    def clear(self):
        self.state = StitchState()
        self.checkpoints.clear()
        self.pending = None
