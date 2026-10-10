"""Bounded silent H.264/MP4 export using the existing PyAV dependency.

The caller stages/atomically commits the destination. This encoder only writes
its supplied staging path and never changes FrameStore pixels or timestamps.
"""
from fractions import Fraction
import math

from PIL import Image


class Mp4Cancelled(Exception):
    pass


def encoder_available():
    try:
        import av
        return av.codec.Codec("libx264", "w").is_encoder
    except (ImportError, OSError, ValueError, RuntimeError):
        return False


def output_geometry(store, width=0):
    if type(width) is not int or width < 0 or store.width <= 0 or store.height <= 0:
        raise ValueError("Invalid MP4 dimensions")
    content_w = width or store.width
    content_h = max(1, int(store.height * content_w / store.width + .5))
    w, h = content_w + content_w % 2, content_h + content_h % 2
    if max(w, h) > 8192 or w * h > 16_000_000 or content_w > store.width * 16:
        raise ValueError("MP4 exceeds 16 megapixels, 8192 pixels per edge or 16x enlargement")
    return content_w, content_h, w, h


def frame_timeline(store, start=0, end=None, speed=1.0):
    times = store.frame_timestamps
    end = len(times) - 1 if end is None else end
    if type(start) is not int or type(end) is not int or not 0 <= start <= end < len(times):
        raise ValueError("Invalid inclusive MP4 frame range")
    if not math.isfinite(speed) or not .1 <= speed <= 16:
        raise ValueError("Invalid MP4 speed")
    if any(type(t) is not int or t < 0 for t in times) or any(b < a for a, b in zip(times, times[1:])):
        raise ValueError("Frame timestamps must be nonnegative and monotonic")
    if end + 1 < len(times):
        following = times[end + 1]
    elif end and times[end] > times[end - 1]:
        following = times[end] * 2 - times[end - 1]
    else:
        following = times[end] + 1000 / max(1, store.fps)
    total = max(1, round((following - times[start]) / speed))
    retained = [(start, 0)]
    for index in range(start + 1, end + 1):
        pts = round((times[index] - times[start]) / speed)
        # MP4 uses millisecond timestamps here. Equal boundaries are not given
        # duplicate PTS: retain the earlier frame and preserve the overall time.
        if retained[-1][1] < pts < total:
            retained.append((index, pts))
    return [(index, pts, (retained[i + 1][1] if i + 1 < len(retained) else total) - pts)
            for i, (index, pts) in enumerate(retained)]


def export_mp4(path, store, *, width=0, frame_start=0, frame_end=None, speed=1.0,
               cursor_sprites=None, cursor_infos=None, cancelled=None, progress=None):
    import av
    def check():
        if cancelled and cancelled():
            raise Mp4Cancelled()
    check()
    cw, ch, w, h = output_geometry(store, width)
    timeline = frame_timeline(store, frame_start, frame_end, speed)
    sprites = {}
    if cursor_sprites and cursor_infos:
        for name, (data, sw, sh) in cursor_sprites.items():
            if not 1 <= sw <= 2048 or not 1 <= sh <= 2048 or len(data) != sw * sh * 4:
                raise ValueError("Invalid cursor sprite")
            sprites[name] = Image.frombytes("RGBA", (sw, sh), data)
    if progress:
        progress(0, len(timeline))
    check()
    time_base = Fraction(1, 1000)
    # One decoded frame at a time. No NumPy, full recording decode or audio stream.
    with av.open(str(path), "w", format="mp4", options={"movflags": "+faststart"}) as container:
        stream = container.add_stream("libx264", rate=max(1, min(60, round(store.fps * speed))))
        stream.width, stream.height = w, h
        stream.pix_fmt = "yuv420p"
        stream.options = {"preset": "veryfast", "crf": "20", "tune": "zerolatency"}
        stream.codec_context.time_base = time_base
        stream.codec_context.max_b_frames = 0
        stream.codec_context.thread_count = 2
        durations = {}
        def mux(packet):
            check()
            packet.duration = durations.pop(packet.pts)
            container.mux(packet)
        for done, (index, pts, duration) in enumerate(timeline, 1):
            check()
            rgb = store.get_frame_rgb(index, cw, ch)
            content = Image.frombytes("RGB", (cw, ch), rgb)
            del rgb
            image = content
            if sprites and index < len(cursor_infos) and cursor_infos[index] is not None:
                x, y, _press, scroll, burst_frame, burst_side = cursor_infos[index]
                def paste(name, left, top, image=image):
                    sprite = sprites[name]
                    image.paste(sprite, (left, top), sprite)
                if 1 <= burst_frame <= 3:
                    name = f"burst_{'left' if burst_side == 1 else 'right'}_{burst_frame}"
                    sprite = sprites[name]
                    paste(name, x - sprite.width // 2 + round(6 * cw / store.width),
                          y - sprite.height // 2 + round(6 * ch / store.height))
                if scroll:
                    name = "scroll_up" if scroll > 0 else "scroll_down"
                    sprite = sprites[name]
                    paste(name, x + sprites["cursor"].width + round(10 * cw / store.width) - sprite.width // 2,
                          y + sprites["cursor"].height // 2 - sprite.height // 2)
                paste("cursor", x, y)
            # Apply padding after cursor composition so the new edge stays black.
            if (cw, ch) != (w, h):
                padded_image = Image.new("RGB", (w, h), "black")
                padded_image.paste(image, (0, 0))
                image.close()
                image = padded_image
            check()
            frame = av.VideoFrame(w, h, "rgb24")
            plane = frame.planes[0]
            raw = image.tobytes()
            image.close()
            if plane.line_size == w * 3:
                plane.update(raw)
            else:
                padded = bytearray(plane.buffer_size)
                for row in range(h):
                    padded[row * plane.line_size:row * plane.line_size + w * 3] = raw[row * w * 3:(row + 1) * w * 3]
                plane.update(padded)
                del padded
            del raw
            frame.pts, frame.time_base = pts, time_base
            durations[pts] = duration
            for packet in stream.encode(frame):
                mux(packet)
            if progress:
                progress(done, len(timeline))
        check()
        for packet in stream.encode():
            mux(packet)
        if durations:
            raise RuntimeError("Encoder did not emit all frames")
    check()
    return True
