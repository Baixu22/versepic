"""Conservative geometry-only reconstruction of simple, separated OCR cells.

No inferred formulas or merged-cell semantics. Ambiguity is returned for review;
limits are checked before allocating the editable matrix or encoded export.
"""
from bisect import bisect_right
import csv
from dataclasses import dataclass
from html import escape
import io
import math
from statistics import median

MAX_BLOCKS = 2000
MAX_ROWS = 200
MAX_COLUMNS = 32
MAX_CELLS = 4000
MAX_CHARACTERS = 500_000


class TableError(ValueError):
    pass


@dataclass
class TableResult:
    cells: list
    boxes: list
    uncertain: set
    warnings: set


def reconstruct_table(result, width, height, *, row_tolerance=0.5, confidence=0.8):
    if not isinstance(result, dict) or result.get("code") != 100:
        raise TableError("OCR did not return a successful result")
    if width <= 0 or height <= 0 or not .1 <= row_tolerance <= 1 or not 0 <= confidence <= 1:
        raise TableError("Invalid table geometry")
    blocks = result.get("data", [])
    if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
        raise TableError("Too many OCR blocks")
    parsed, warnings, characters = [], set(), 0
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            warnings.add("invalid_boxes"); continue
        text = block["text"]
        characters += len(text)
        if characters > MAX_CHARACTERS: raise TableError("Table text is too large")
        if not text.strip(): continue
        try:
            points = block["box"]
            if len(points) != 4 or any(len(p) != 2 for p in points): raise ValueError()
            xs, ys = zip(*points)
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (*xs, *ys)): raise ValueError()
            left, right = max(0, min(xs)), min(width, max(xs))
            top, bottom = max(0, min(ys)), min(height, max(ys))
            if left >= right or top >= bottom: raise ValueError()
            score = block.get("score", 0)
            low = not isinstance(score, (int, float)) or not math.isfinite(score) or score < confidence
            rotated = abs(points[0][1] - points[1][1]) > (bottom - top) * .25
            if rotated: warnings.add("rotated")
            parsed.append((left, top, right, bottom, text, low or rotated))
        except (KeyError, TypeError, ValueError):
            warnings.add("invalid_boxes")
    if not parsed: raise TableError("No positioned text to build a table")
    parsed.sort(key=lambda b: ((b[1]+b[3])/2, b[0]))
    line_height = median(b[3]-b[1] for b in parsed)
    rows = []
    for block in parsed:
        center = (block[1]+block[3])/2
        if rows and abs(center-median((b[1]+b[3])/2 for b in rows[-1])) <= line_height * row_tolerance:
            rows[-1].append(block)
        else:
            rows.append([block])
    if len(rows) > MAX_ROWS: raise TableError("Table exceeds 200 rows")
    for row in rows: row.sort(key=lambda b: b[0])
    # The richest row anchors columns. Empty cells in other rows remain empty.
    # Do not split a single OCR line at whitespace: multiword cells must survive.
    anchors = max(rows, key=len)
    if len(anchors) > MAX_COLUMNS or len(anchors) * len(rows) > MAX_CELLS:
        raise TableError("Table exceeds 32 columns or 4000 cells")
    if len(rows) < 2 or len(anchors) < 2: warnings.add("not_grid")
    boundaries = [(a[2]+b[0])/2 for a,b in zip(anchors, anchors[1:])]
    if any(a[2] >= b[0] for a,b in zip(anchors, anchors[1:])): warnings.add("overlap")
    # Sort boundaries so an overlapping malformed anchor row stays deterministic.
    boundaries.sort()
    cells = [["" for _ in anchors] for _ in rows]
    boxes = [[None for _ in anchors] for _ in rows]
    uncertain = set()
    for r, row in enumerate(rows):
        for block in row:
            left, top, right, bottom, text, low = block
            c = bisect_right(boundaries, (left+right)/2)
            if any(left < cut < right for cut in boundaries):
                warnings.add("spanning"); low = True
            if boxes[r][c] is not None:
                warnings.add("collision"); low = True
                cells[r][c] += "\n" + text
                old = boxes[r][c]
                boxes[r][c] = (min(old[0],left),min(old[1],top),max(old[2],right),max(old[3],bottom))
            else:
                cells[r][c], boxes[r][c] = text, (left,top,right,bottom)
            if low: uncertain.add((r,c))
    if any(len(row) != len(anchors) for row in rows): warnings.add("missing_cells")
    if uncertain: warnings.add("review_cells")
    return TableResult(cells, boxes, uncertain, warnings)


def validate_cells(cells):
    if not cells or len(cells) > MAX_ROWS or not cells[0] or len(cells[0]) > MAX_COLUMNS:
        raise TableError("Invalid table dimensions")
    columns = len(cells[0])
    if len(cells)*columns > MAX_CELLS: raise TableError("Table exceeds 4000 cells")
    if any(len(row) != columns or any(not isinstance(v,str) for v in row) for row in cells):
        raise TableError("Table must be a rectangular text matrix")
    if sum(len(v) for row in cells for v in row) > MAX_CHARACTERS:
        raise TableError("Table text is too large")


def spreadsheet_text(value, protect_formulas):
    # Leading whitespace can still precede a spreadsheet formula. Text quoting
    # handles TSV structure, not formula evaluation, so protect independently.
    if protect_formulas and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def to_tsv(cells, *, protect_formulas=True):
    validate_cells(cells)
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter="\t", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerows([[spreadsheet_text(v,protect_formulas) for v in row] for row in cells])
    return out.getvalue()


def to_markdown(cells, *, first_row_header=True):
    validate_cells(cells)
    def cell(value):
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = escape(value, quote=False)
        for character in ("\\", "|", "[", "]", "!", "`", "*", "_", "~"):
            value = value.replace(character, "\\" + character)
        return value.replace("\t", "&#9;").replace("\n", "<br>")
    rows = [[cell(v) for v in row] for row in cells]
    if not first_row_header: rows.insert(0,[f"Column {i+1}" for i in range(len(cells[0]))])
    rows.insert(1,["---"]*len(cells[0]))
    return "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
