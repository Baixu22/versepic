"""Read-only image comparison with explicit alignment and bounded pixel differences."""
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage

MAX_COMPARE_PIXELS = 32_000_000
MAX_COMPARE_EDGE = 100_000


class CompareError(ValueError):
    pass


class CompareCancelled(Exception):
    pass


def validate_pair(first, second=None, alignment="original"):
    if alignment not in ("original", "scale_b"):
        raise CompareError("Unknown comparison alignment")
    images=[image for image in (first,second) if image is not None]
    if not images or any(image.isNull() for image in images):
        raise CompareError("Empty image")
    if sum(image.width()*image.height() for image in images)>MAX_COMPARE_PIXELS:
        raise CompareError("Comparison inputs exceed 32 megapixels")
    if second is None or alignment=="scale_b":
        width,height=first.width(),first.height()
    else:
        width,height=max(first.width(),second.width()),max(first.height(),second.height())
    if width*height>MAX_COMPARE_PIXELS or max(width,height)>MAX_COMPARE_EDGE:
        raise CompareError("Comparison canvas exceeds the limit")
    return QSize(width,height)


@dataclass
class DifferenceResult:
    overlay: QImage
    changed_pixels: int
    compared_pixels: int


def difference_overlay(first,second,alignment="original",threshold=0,*,cancelled=None):
    """Compare premultiplied RGBA; invisible RGB is ignored, missing coverage is not.

    Stripe processing bounds temporary PIL buffers. The overlay is at original
    comparison resolution, not the zoomed display size. This is pixel difference,
    never a semantic or layout-correctness verdict.
    """
    size=validate_pair(first,second,alignment)
    if type(threshold) is not int or not 0<=threshold<=255:
        raise CompareError("Threshold must be an integer from 0 to 255")
    def check():
        if cancelled and cancelled():raise CompareCancelled()
    check()
    if alignment=="scale_b" and second.size()!=first.size():
        second=second.scaled(first.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
        if second.isNull():raise CompareError("Could not resize comparison image")
    width,height=size.width(),size.height()
    output=QImage(width,height,QImage.Format.Format_RGBA8888)
    if output.isNull():raise CompareError("Could not allocate difference overlay")
    output.fill(0)
    changed=0
    # At most about 1M pixels per scratch stripe, including very wide images.
    rows=max(1,min(256,1_000_000//width))
    lookup=[255 if delta>threshold else 0 for delta in range(256)]
    for top in range(0,height,rows):
        check();h=min(rows,height-top)
        parts=[];coverage=[]
        for source in (first,second):
            tile=Image.new("RGBA",(width,h),(0,0,0,0));covered=Image.new("L",(width,h),0)
            available=max(0,min(h,source.height()-top))
            if available:
                rgba=source.copy(0,top,source.width(),available).convertToFormat(QImage.Format.Format_RGBA8888)
                tile.paste(Image.frombytes("RGBA",(rgba.width(),available),bytes(rgba.constBits())),(0,0))
                ImageDraw.Draw(covered).rectangle((0,0,source.width()-1,available-1),fill=255)
            # RGBa is premultiplied in Pillow; compare alpha as well as visible color.
            parts.append(tile.convert("RGBa"));coverage.append(covered)
        bands=ImageChops.difference(parts[0],parts[1]).split()
        maximum=bands[0]
        for band in bands[1:]:maximum=ImageChops.lighter(maximum,band)
        mask=ImageChops.lighter(maximum.point(lookup),ImageChops.difference(*coverage))
        count=mask.histogram()[255];changed+=count
        if count:
            rgba=Image.new("RGBA",(width,h),(236,40,119,0));rgba.putalpha(mask.point([0]+[180]*255))
            data=rgba.tobytes()
            offset=top*output.bytesPerLine()
            output.bits()[offset:offset+len(data)]=data
    check()
    return DifferenceResult(output,changed,width*height)
