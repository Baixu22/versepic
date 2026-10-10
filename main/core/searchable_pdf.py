"""Fresh-pixel OCR text under an opaque PDF image: searchable, not visibly redrawn.

No caller-provided/cached OCR is accepted. Each page is OCRed from its exact
rotated, flattened export pixels. Hidden strings can never come from a stale
history index, editable project or pre-redaction OCR result.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import unicodedata

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QPageLayout,
    QPageSize, QPainter, QPdfWriter, QTextLayout, QTextOption)

from core.image_layout import ImageLayoutError, check_cancel, validate_images

MAX_OCR_LINES = 5000
MAX_PDF_TEXT = 500_000


@dataclass
class PdfTextReport:
    pages: list = field(default_factory=list)

    @property
    def lines(self):
        return sum(page['embedded_lines'] for page in self.pages)


def opaque_page(image):
    # Source Composition + fresh storage: drop metadata/DPR and put transparency
    # on white before both recognition and PDF rendering, never after OCR.
    page = QImage(image.size(), QImage.Format.Format_RGB32)
    if page.isNull(): raise ImageLayoutError("Could not allocate PDF page")
    page.fill(Qt.GlobalColor.white)
    painter = QPainter(page)
    painter.drawImage(QRectF(page.rect()), image, QRectF(0, 0, image.width(), image.height()))
    painter.end()
    return page


def positioned_lines(result, image):
    """Validate line quads, retain OCR read order by row, report skipped data."""
    if not isinstance(result, dict) or result.get('code') != 100:
        return [], {'ocr_failed': 1}
    data = result.get('data')
    if not isinstance(data, list) or len(data) > MAX_OCR_LINES:
        return [], {'invalid_result': 1}
    lines, warnings, chars = [], {}, 0
    def skipped(reason): warnings[reason] = warnings.get(reason, 0) + 1
    for block in data:
        try:
            text = block['text']
            if not isinstance(text, str): raise ValueError()
            # Control characters never act as PDF commands, markup or separators.
            text = ' '.join(text.split())
            if not text: continue
            if any(unicodedata.category(c) == 'Cs' for c in text): raise ValueError()
            chars += len(text)
            if chars > MAX_PDF_TEXT: return [], {'text_limit': 1}
            points = block['box']
            if len(points) != 4 or any(len(p) != 2 for p in points): raise ValueError()
            if any(type(v) not in (int, float) or not math.isfinite(v) for p in points for v in p): raise ValueError()
            # Do not clip glyph strings to hide a partially invalid OCR box.
            if any(not 0 <= x <= image.width() or not 0 <= y <= image.height() for x, y in points): raise ValueError()
            p0, p1, p2, p3 = points
            ux, uy = p1[0]-p0[0], p1[1]-p0[1]
            vx, vy = p3[0]-p0[0], p3[1]-p0[1]
            width, height = math.hypot(ux,uy), math.hypot(vx,vy)
            if min(width,height) < 1 or ux*vy-uy*vx <= 0: raise ValueError()
            # A rotated rectangle is supported. Perspective/irregular quads are
            # skipped rather than silently placing searchable text elsewhere.
            if abs(ux*vx+uy*vy)/(width*height) > .25: raise ValueError()
            if math.hypot(p2[0]-(p1[0]+vx),p2[1]-(p1[1]+vy)) > max(3,height*.25): raise ValueError()
            score = block.get('score', 1.0)
            if not isinstance(score,(int,float)) or not math.isfinite(score) or score < .8: skipped('low_confidence')
            lines.append((text, p0[0], p0[1], width, height, math.degrees(math.atan2(uy,ux))))
        except (TypeError,KeyError,ValueError):
            skipped('invalid_box')
    # Top-to-bottom row groups, left-to-right within a row. Never claim semantic
    # reading order for vertical typesetting, multiple columns or merged tables.
    lines.sort(key=lambda b:(b[2]+b[4]/2,b[1]))
    rows=[]
    for line in lines:
        if rows and abs(line[2]-rows[-1][0][2]) <= min(line[4],rows[-1][0][4])*.45:
            rows[-1].append(line)
        else: rows.append([line])
    return [line for row in rows for line in sorted(row,key=lambda b:b[1])], warnings


def text_layout(text):
    # Qt offscreen may have a dummy box font even when QRawFont.isValid is true.
    # Require an installed/loaded family and nonzero glyphs for every shaped run.
    families = QFontDatabase.families()
    if not families: return None
    preferred = ['Microsoft YaHei', 'Microsoft YaHei UI', 'Noto Sans CJK SC', 'Arial']
    family = next((name for name in preferred if name in families), families[0])
    font = QFont(family); font.setPixelSize(40)
    layout = QTextLayout(text, font)
    option = QTextOption(); option.setWrapMode(QTextOption.WrapMode.NoWrap)
    layout.setTextOption(option)
    layout.beginLayout(); line=layout.createLine(); line.setLineWidth(10_000_000); layout.endLayout()
    runs = layout.glyphRuns()
    if not runs or any(not run.rawFont().isValid() or 0 in run.glyphIndexes() for run in runs): return None
    fonts = [run.rawFont() for run in runs]
    if any(not c.isspace() and unicodedata.category(c) != "Cf"
           and not any(font.supportsCharacter(ord(c)) for font in fonts) for c in text):
        return None
    if line.naturalTextWidth() <= 0 or line.height() <= 0: return None
    return layout, line.naturalTextWidth(), line.height()


@contextmanager
def painter_state(painter):
    painter.save()
    try: yield
    finally: painter.restore()


def write_searchable_pdf(images, destination, options, *, cancelled=None, progress=None, report=None):
    """Write fresh-OCR searchable pages. Caller owns atomic staging and cancellation.

    OCR failure/blank/unsupported glyphs produce an image-only page plus an exact
    report; never import cached text to make a failed page look searchable.
    """
    validate_images(images)
    geometries = [options.geometry(im) for im in images]
    report = report if report is not None else PdfTextReport()
    writer = QPdfWriter(str(destination)); writer.setCreator('VersePic'); writer.setResolution(144)
    def set_page(size):
        page_layout = QPageLayout(QPageSize(size,QPageSize.Unit.Point,'Image',QPageSize.SizeMatchPolicy.ExactMatch),
            QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0),QPageLayout.Unit.Point)
        page_layout.setMode(QPageLayout.Mode.FullPageMode); writer.setPageLayout(page_layout)
    set_page(geometries[0][0])
    painter=QPainter(writer)
    if not painter.isActive(): raise ImageLayoutError('PDF writer could not be started')
    painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
    try:
        for index,(source,(size,target)) in enumerate(zip(images,geometries,strict=True)):
            check_cancel(cancelled)
            page=opaque_page(options.image(source))
            from core.capture_privacy import sensitive_ocr
            token=sensitive_ocr.set(True)  # suppress OCR exception payloads; no raw text in export logs
            try:
                from ocr import recognize_text, is_ocr_available
                result=recognize_text(page,return_format='dict') if is_ocr_available() else None
            except Exception: result=None
            finally: sensitive_ocr.reset(token)
            check_cancel(cancelled)
            lines,warnings=positioned_lines(result,page)
            if index:
                set_page(size)
                if not writer.newPage(): raise ImageLayoutError('PDF page could not be written')
            embedded=0
            with painter_state(painter):
                painter.scale(writer.width()/size.width(),writer.height()/size.height())
                painter.fillRect(QRectF(0,0,size.width(),size.height()),Qt.GlobalColor.white)
                with painter_state(painter):
                    painter.translate(target.topLeft());painter.scale(target.width()/page.width(),target.height()/page.height())
                    for text,x,y,width,height,angle in lines:
                        check_cancel(cancelled)
                        shaped=text_layout(text)
                        if shaped is None:
                            warnings['missing_glyphs']=warnings.get('missing_glyphs',0)+1;continue
                        layout,tw,th=shaped
                        with painter_state(painter):
                            painter.translate(x,y);painter.rotate(angle);painter.scale(width/tw,height/th)
                            painter.setPen(QColor('black'));layout.draw(painter,QPointF(0,0))
                        embedded+=1
                # The opaque exact OCR image hides glyph painting, not selection.
                painter.drawImage(target,page,QRectF(0,0,page.width(),page.height()))
            if not embedded and not warnings:
                warnings['no_text']=1
            report.pages.append({'page':index+1,'embedded_lines':embedded,'warnings':warnings,
                'image_only':embedded==0,'pixel_size':[page.width(),page.height()]})
            del result,lines,page
            if progress: progress(index+1,len(images))
    finally:
        if not painter.end():
            raise ImageLayoutError("PDF painter could not finish")
    check_cancel(cancelled)
    return True
