"""
Analytics AI Engine
-------------------
Handles three capabilities inside the Academic Analytics feature:

  1. PDF/CSV Mark Sheet Parsing (Multi-table aware)
     - Uses existing PDFExtractor to read uploaded PDF
     - Detects multiple tables and their relationships
     - Sends extracted text to local Ollama (llama3.2) to produce structured JSON
     - Writes SubjectResult/EndSemesterResult rows for subjects that already exist
     - Subjects are NEVER auto-created from documents; they must be defined manually
     - Separates internal marks from end semester results into different tables

  2. Natural Language Query (NLPQ)
     - Accepts a free-text question from the user
     - Fetches relevant DB data for context
     - Asks local Ollama to answer + pick the right output format (table / paragraph / chart)
     - Returns a structured response for the frontend to render
     - Supports visualizations: bar charts, pie charts, line charts

  3. Data Visualization
     - Generates chart data (bar, pie, line) for frontend rendering
     - Supports grade distribution, mark trends, comparison charts
"""

import json
import os
import re
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

# ─── Ollama (local) setup ──────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# Import canonical model names from the central LLM client
try:
    from aa.llm_client import MAIN_MODEL as OLLAMA_MODEL
except ImportError:
    OLLAMA_MODEL = os.environ.get("OLLAMA_MAIN_MODEL", "llama3.1:8b")


def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """
    Send a prompt to the local Ollama REST API and return the response text.
    Uses only stdlib – no extra package needed.
    """
    payload = json.dumps({
        "model":   model,
        "prompt":  prompt,
        "stream":  False,
        "options": {
            "num_ctx":     8192,   # context window (prompt + response)
            "num_predict": 4096,   # max tokens the model may generate
            "temperature": 0.0,    # deterministic output for data extraction
        },
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    return data.get("response", "")


# ─── PDF → DB pipeline ────────────────────────────────────────────────────────

# ─── Subject-code pattern used across helpers ─────────────────────────────────

_SUBJ_CODE_RE = re.compile(
    r'\b((?:[A-Z]{2,4}\d{3,4}[A-Z]?\d?)|(?:\d{2}[A-Z]{2,4}\d{3,4}))\b'
)

# ─── PDF coordinate-based table parser ────────────────────────────────────────

def _page_rows(page, y_tol: float = 4.0) -> list:
    """
    Return every row on a fitz page as a sorted list of (x_center, text) tuples.
    Words whose Y-midpoints are within y_tol pts of each other share a row.
    Result: [ [(x, text), ...], ... ]  sorted top-to-bottom.
    """
    words = page.get_text("words")   # (x0,y0,x1,y1,text,blk,ln,wrd)
    if not words:
        return []

    buckets: Dict[int, list] = {}
    for w in words:
        x0, y0, x1, y1, text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])
        y_mid = (y0 + y1) / 2
        key   = round(y_mid / y_tol)
        buckets.setdefault(key, []).append(((x0 + x1) / 2, text))

    return [
        sorted(cells, key=lambda c: c[0])
        for key, cells in sorted(buckets.items())
    ]


def _find_header_row(rows: list) -> tuple:
    """
    Scan rows top-to-bottom and return (row_index, {x_center: subject_code})
    for the row that contains the most subject codes.
    Returns (-1, {}) if none found.
    """
    best_idx, best_map = -1, {}
    for i, row in enumerate(rows):
        col_map = {}
        for x, text in row:
            m = _SUBJ_CODE_RE.match(text.upper().strip())
            if m:
                col_map[x] = m.group(1)
        if len(col_map) > len(best_map):
            best_map = col_map
            best_idx = i
    return best_idx, best_map


def _nearest_x(x: float, col_xs: list, tol: float = 25.0) -> Optional[float]:
    """Return the closest column X within tol points, or None."""
    if not col_xs:
        return None
    closest = min(col_xs, key=lambda cx: abs(cx - x))
    return closest if abs(closest - x) <= tol else None


# Sub-column label sets used to distinguish marks columns from attendance columns.
# PDFs often have per-subject sub-columns:  MAX | MARK | ATT%  (or similar).
# We want to read MARK, not ATT%.
_MARK_SUBCOL_LABELS = {
    'MARK', 'MARKS', 'CIA', 'INT', 'INTERNAL', 'SCORE',
    'OBTAINED', 'SCORED', 'SECURED',
}
_SKIP_SUBCOL_LABELS = {
    # Attendance-related — must NOT be read as marks
    'ATT', 'ATT%', 'ATTENDANCE', 'PRESENT', 'PRESENT%', 'ABSENT', 'ABSENT%',
    'ATTENDED', '%', 'CLASSES', 'CONDUCTED',
    # Aggregate/metadata columns — also not marks
    'MAX', 'MAX.', 'MAXIMUM', 'TOTAL', 'CREDITS', 'CREDIT',
}

# ── End-semester sub-column label sets ─────────────────────────────────────────
# End-semester marksheets have per-subject sub-columns like:
#   21AD101      | 21CS101
#   GR | GP | STS | GR | GP | STS
# We need to locate GRADE, GRADE_POINTS, and RESULT_STATUS columns.
_GRADE_SUBCOL_LABELS = {
    'GR', 'GRD', 'GRADE', 'GDE', 'LG', 'LETTER', 'LETTER GRADE',
    'LETTERGRADE', 'LGR',
}
_GP_SUBCOL_LABELS = {
    'GP', 'GRADEPOINT', 'GRADE POINT', 'GRADEPOINTS', 'GRADE POINTS',
    'PTS', 'POINT', 'POINTS', 'GPA', 'CREDIT POINT', 'CP',
}
_STATUS_SUBCOL_LABELS = {
    'STS', 'STATUS', 'RESULT', 'RES', 'P/F', 'PF', 'PASS/FAIL',
    'OUTCOME', 'REM', 'REMARKS',
}
_MARKS_ENDSEM_SUBCOL_LABELS = {
    'MARK', 'MARKS', 'SCORE', 'OBTAINED', 'SCORED', 'SECURED',
    'TOTAL', 'TOT', 'EXAM', 'END SEM', 'ENDSEM', 'THEORY', 'EXTERNAL',
    'EXT', 'ESE',
}
_CREDIT_SUBCOL_LABELS = {
    'CR', 'CREDIT', 'CREDITS', 'CRD', 'C',
}

# Grade → grade points mapping for end-sem CSVs that provide only letter grades.
_GRADE_POINT_MAP = {
    'O': 10.0,
    'A+': 9.0,
    'A': 8.0,
    'B+': 7.0,
    'B': 6.0,
    'C': 5.0,
    'U': 0.0,
    'AB': 0.0,
}

_GRADE_ALIASES = {
    'ABS': 'AB',
    'ABSENT': 'AB',
    'A/B': 'AB',
    'U-RA*': 'U',
    'U-RA': 'U',
    'RA': 'U',
    'F': 'U',
    'FAIL': 'U',
}


def _normalize_grade_token(token: str) -> Optional[str]:
    """Normalize a grade token to canonical form, or return None."""
    if token is None:
        return None
    t = re.sub(r"\s+", "", str(token).upper())
    t = re.sub(r"[^A-Z+\-]", "", t)
    if not t:
        return None
    if t in _GRADE_ALIASES:
        return _GRADE_ALIASES[t]
    if t in _GRADE_POINT_MAP:
        return t
    return None


def _detect_mark_subcolumns(
    rows: list, hdr_idx: int, col_map: Dict[float, str]
) -> Dict[str, float]:
    """
    Detect per-subject sub-column headers in the row(s) immediately below the
    subject-code header row.

    Many Indian college mark sheets look like:

        21AD101        21CS101        21EN101
        Max  Mark Att% Max  Mark Att% Max  Mark Att%
        50   45   92   50   48   88   50   38   75

    Without sub-column awareness, _nearest_x(col_x, ..., tol=30) will return
    whatever data cell happens to be closest — often the Att% value.

    This function scans up to 2 rows below the code row for sub-column labels.
    Returns: {subject_code: best_mark_x}  mapping each code to the X position
    of its MARK sub-column.  Returns {} if no sub-column structure is found
    (caller uses the subject-code X position directly, as before).
    """
    if hdr_idx < 0 or not col_map:
        return {}

    col_xs    = sorted(col_map.keys())
    n_cols    = len(col_xs)
    if n_cols < 1:
        return {}

    # Estimate per-subject column width (average gap between adjacent codes).
    if n_cols > 1:
        col_width = (col_xs[-1] - col_xs[0]) / (n_cols - 1)
    else:
        col_width = 60.0
    half_w = max(col_width / 2.0, 15.0)

    found: Dict[str, float] = {}

    for scan_row_i in range(hdr_idx + 1, min(len(rows), hdr_idx + 3)):
        sub_row = rows[scan_row_i]
        row_texts_up = {t.upper().strip('.%') for _, t in sub_row}

        # Only treat this as a sub-column row if it contains recognisable labels
        has_mark = bool(row_texts_up & _MARK_SUBCOL_LABELS)
        has_att  = bool(row_texts_up & _SKIP_SUBCOL_LABELS)
        if not (has_mark or has_att):
            continue  # Not a sub-column label row — look at next candidate

        # For each subject code, bucket the sub-row cells within ±half_w
        for code_x, code in col_map.items():
            nearby = [(x, t) for x, t in sub_row if abs(x - code_x) <= half_w]
            if not nearby:
                continue

            mark_xs:  list = []
            skip_xs:  set  = set()

            for x, t in nearby:
                tu = t.upper().strip('.%')
                if tu in _MARK_SUBCOL_LABELS:
                    mark_xs.append(x)
                elif tu in _SKIP_SUBCOL_LABELS:
                    skip_xs.add(x)

            if mark_xs:
                # Explicit "MARK" label found — use leftmost one
                found[code] = min(mark_xs)
            elif skip_xs:
                # Present skip columns but no explicit mark label.
                # Pick the leftmost cell that is NOT a skip column.
                non_skip = [(x, t) for x, t in nearby if x not in skip_xs]
                if non_skip:
                    found[code] = min(non_skip, key=lambda c: c[0])[0]
                # else: all nearby cells are skippable — leave found[code] unset

        # If we found sub-column info for at least half the subjects, trust it
        if len(found) >= max(1, n_cols // 2):
            return found
        # Otherwise, clear partial results and try the next candidate row
        found = {}

    return {}


def _detect_end_sem_subcolumns(
    rows: list, hdr_idx: int, col_map: Dict[float, str]
) -> Dict[str, Dict[str, float]]:
    """
    Detect per-subject sub-column X positions for end-semester marksheets.

    End-semester PDFs typically have sub-columns like:
        21AD101          | 21CS101
        Marks GR GP STS  | Marks GR GP STS
        85    A+ 9  P    | 72    A  8  P

    Returns: {subject_code: {"marks": x, "grade": x, "gp": x, "status": x, "credits": x}}
    Only populated fields are present in the inner dict.
    Returns {} if no sub-column structure is detected.
    """
    if hdr_idx < 0 or not col_map:
        return {}

    col_xs = sorted(col_map.keys())
    n_cols = len(col_xs)
    if n_cols < 1:
        return {}

    if n_cols > 1:
        col_width = (col_xs[-1] - col_xs[0]) / (n_cols - 1)
    else:
        col_width = 80.0
    half_w = max(col_width / 2.0, 20.0)

    result: Dict[str, Dict[str, float]] = {}

    # Scan up to 3 rows below the header for sub-column labels
    for scan_row_i in range(hdr_idx + 1, min(len(rows), hdr_idx + 4)):
        sub_row = rows[scan_row_i]
        row_texts_up = {t.upper().strip('.%') for _, t in sub_row}

        # Check if this row has any end-sem relevant labels
        has_grade  = bool(row_texts_up & _GRADE_SUBCOL_LABELS)
        has_gp     = bool(row_texts_up & _GP_SUBCOL_LABELS)
        has_status = bool(row_texts_up & _STATUS_SUBCOL_LABELS)
        has_marks  = bool(row_texts_up & _MARKS_ENDSEM_SUBCOL_LABELS)
        has_credit = bool(row_texts_up & _CREDIT_SUBCOL_LABELS)

        if not (has_grade or has_gp or has_status):
            continue  # Not an end-sem sub-column row

        for code_x, code in col_map.items():
            nearby = [(x, t) for x, t in sub_row if abs(x - code_x) <= half_w]
            if not nearby:
                continue

            code_result = result.setdefault(code, {})
            for x, t in nearby:
                tu = t.upper().strip('.%')
                if tu in _GRADE_SUBCOL_LABELS:
                    code_result['grade'] = x
                elif tu in _GP_SUBCOL_LABELS:
                    code_result['gp'] = x
                elif tu in _STATUS_SUBCOL_LABELS:
                    code_result['status'] = x
                elif tu in _MARKS_ENDSEM_SUBCOL_LABELS:
                    code_result['marks'] = x
                elif tu in _CREDIT_SUBCOL_LABELS:
                    code_result['credits'] = x

        # If we found sub-column info for at least a third of the subjects, trust it
        if len(result) >= max(1, n_cols // 3):
            return result
        result = {}

    return {}


def _parse_end_sem_vertical(file_bytes: bytes) -> Optional[Dict]:
    """
    Parse end-semester marksheets that use a VERTICAL (row-per-subject)
    layout instead of horizontal (subject-per-column).

    Layout B format (one student per section/page):
      -----------------------------------------------------------------
      STUDENT: 24AD001  Name: John Doe
      Reg No: 71402424301
      -----------------------------------------------------------------
      S.No | Subject Code | Subject Name  | Grade | GP | Credits | Status
      1    | 21AD101      | FAID          | A+    | 9  | 4       | PASS
      2    | 21CS101      | CTPS          | O     | 10 | 3       | PASS
      SGPA: 8.5    Total Credits: 22    Arrears: 0
      -----------------------------------------------------------------

    Returns the same schema as _parse_pdf_table, or None if this doesn't
    look like a vertical layout.
    """
    import fitz
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return None

    full_text = ""
    for page in doc:
        full_text += page.get_text()

    # Detect vertical layout: look for patterns like "Subject Code" as a column header
    # AND NO wide subject-code header row (which would indicate horizontal layout)
    text_up = full_text.upper()

    # Check for vertical layout indicators
    has_vertical_headers = bool(re.search(
        r'SUBJECT\s*CODE.*(?:SUBJECT\s*NAME|GRADE|GP|CREDIT|STATUS)',
        text_up
    )) or bool(re.search(
        r'COURSE\s*CODE.*(?:COURSE\s*NAME|GRADE|GP|CREDIT)',
        text_up
    ))

    if not has_vertical_headers:
        doc.close()
        return None

    # Detect mark type
    if re.search(r'END\s*SEM|SEMESTER\s*EXAM|FINAL\s*EXAM|UNIVERSITY\s*EXAM', text_up):
        mark_type = "end_semester"
    else:
        mark_type = "internal"

    # Parse page by page
    all_records = []
    subject_map: Dict[str, Dict] = {}  # code -> {name, credits}
    pages_parsed = 0

    for page in doc:
        rows = _page_rows(page, y_tol=5.0)
        if not rows:
            continue

        # Find the vertical header row (Subject Code, Subject Name, Grade, etc.)
        vert_hdr_idx = -1
        col_indices: Dict[str, int] = {}  # field_name -> cell_index_in_row

        for row_i, row in enumerate(rows):
            row_texts_up = [t.upper().strip() for _, t in row]
            row_text_joined = ' '.join(row_texts_up)

            # Look for the row that has "Subject Code" or "Course Code" AND "Grade"
            has_code_col = any(
                re.search(r'SUB.*CODE|COURSE.*CODE|CODE', tt) for tt in row_texts_up
            )
            has_grade_or_gp = any(
                tt in ('GRADE', 'GR', 'GRD', 'GP', 'GRADE POINT', 'GRADEPOINT')
                for tt in row_texts_up
            )
            if has_code_col and has_grade_or_gp:
                vert_hdr_idx = row_i
                # Map column positions by their headers
                for ci, (_, t) in enumerate(row):
                    tu = t.upper().strip()
                    if re.search(r'SUB.*CODE|COURSE.*CODE', tu) or tu == 'CODE':
                        col_indices['code'] = ci
                    elif re.search(r'SUB.*NAME|COURSE.*NAME|TITLE', tu) or tu == 'NAME':
                        col_indices['name'] = ci
                    elif tu in _GRADE_SUBCOL_LABELS:
                        col_indices['grade'] = ci
                    elif tu in _GP_SUBCOL_LABELS or re.search(r'GRADE\s*P', tu):
                        col_indices['gp'] = ci
                    elif tu in _STATUS_SUBCOL_LABELS or tu in ('RESULT', 'RES', 'REMARKS'):
                        col_indices['status'] = ci
                    elif tu in ('CREDIT', 'CREDITS', 'CR', 'CRD'):
                        col_indices['credits'] = ci
                    elif re.search(r'MARK|SCORE|TOTAL', tu):
                        col_indices['marks'] = ci
                break

        if vert_hdr_idx < 0 or 'code' not in col_indices:
            # Try to find student sections and look for subject codes in rows
            continue

        # Find current student ID (look in rows BEFORE the header)
        current_student = None
        for row_i in range(vert_hdr_idx):
            for _, t in rows[row_i]:
                t_stripped = t.strip()
                if _is_student_id(t_stripped) and not _SUBJ_CODE_RE.match(t_stripped.upper()):
                    current_student = t_stripped
                    break
            if current_student:
                break

        # If no student found above header, look in data rows
        # (some formats put the student ID in the first data row column)

        # Parse data rows below the vertical header
        for row_i in range(vert_hdr_idx + 1, len(rows)):
            row = rows[row_i]
            if len(row) < 2:
                continue

            # Extract subject code from this row
            code_ci = col_indices.get('code', 0)
            if code_ci >= len(row):
                continue
            raw_code = row[code_ci][1].strip().upper()
            code_match = _SUBJ_CODE_RE.match(raw_code)
            if not code_match:
                # Check if this row has a student ID (next student section)
                for _, t in row:
                    t_stripped = t.strip()
                    if _is_student_id(t_stripped) and not _SUBJ_CODE_RE.match(t_stripped.upper()):
                        current_student = t_stripped
                        break
                continue

            subj_code = code_match.group(1)

            if not current_student:
                # Still no student — look for ID in this row itself
                for ci, (_, t) in enumerate(row):
                    if ci == code_ci:
                        continue
                    t_stripped = t.strip()
                    if _is_student_id(t_stripped) and not _SUBJ_CODE_RE.match(t_stripped.upper()):
                        current_student = t_stripped
                        break
                if not current_student:
                    continue

            # Extract fields
            def _get_cell(ci_name):
                ci = col_indices.get(ci_name)
                if ci is not None and ci < len(row):
                    return row[ci][1].strip()
                return ""

            subj_name = _get_cell('name') or subj_code
            grade     = _get_cell('grade')
            gp_raw    = _get_cell('gp')
            status    = _get_cell('status')
            marks_raw = _get_cell('marks')
            credits_r = _get_cell('credits')

            # Parse marks
            marks = None
            is_absent = False
            if marks_raw:
                clean = marks_raw.replace(',', '.')
                if clean.upper() in ('AB', 'A/B', 'ABS', 'ABSENT'):
                    is_absent = True
                elif re.fullmatch(r'\d{1,3}(\.\d{1,2})?', clean):
                    try:
                        marks = float(clean)
                    except ValueError:
                        pass

            # Parse grade points
            gp = None
            if gp_raw:
                try:
                    gp = float(gp_raw.replace(',', '.'))
                except ValueError:
                    pass

            # Parse credits
            credits = 3
            if credits_r:
                try:
                    credits = int(credits_r)
                except ValueError:
                    pass

            # Store subject info
            if subj_code not in subject_map:
                clean_name = _clean_subject_name(subj_name) or subj_name
                subject_map[subj_code] = {"code": subj_code, "name": clean_name, "credits": credits}

            # Determine status
            result_status = ""
            if status:
                su = status.upper()
                if su in ('P', 'PASS', 'PASSED'):
                    result_status = 'PASS'
                elif su in ('F', 'FAIL', 'FAILED'):
                    result_status = 'FAIL'
                elif su in ('AB', 'ABS', 'ABSENT'):
                    result_status = 'AB'
                    is_absent = True
                elif su in ('WH', 'WITHHELD'):
                    result_status = 'WH'
                else:
                    result_status = su

            # Determine result_status from grade if not explicitly set
            if not result_status and grade:
                if grade.upper() in ('U', 'F'):
                    result_status = 'FAIL'
                elif grade.upper() in ('AB', 'ABS'):
                    result_status = 'AB'
                    is_absent = True
                elif grade.upper() not in ('', '-', '—'):
                    result_status = 'PASS'

            all_records.append({
                "roll_number":     current_student,
                "subject_code":    subj_code,
                "internal_number": 1,
                "marks":           marks,
                "is_absent":       is_absent,
                "type":            mark_type,
                "grade":           grade if grade and grade.upper() not in ('', '-', '—') else None,
                "grade_points":    gp,
                "result_status":   result_status,
            })

        pages_parsed += 1

    doc.close()

    if not all_records:
        return None

    subjects = list(subject_map.values())
    return {
        "subjects":        subjects,
        "records":         all_records,
        "mark_type":       mark_type,
        "internal_number": 1,
        "pages_parsed":    pages_parsed,
        "header_codes":    list(subject_map.keys()),
    }

_BUCKET_PTS = 6.0  # X-coordinate bucket size (PDF points) for grouping nearby cells


def _find_best_mark_xs(
    rows: list, hdr_idx: int, col_map: Dict[float, str]
) -> tuple:
    """
    Multi-pass statistical approach to identify which X position holds the real
    CIA/internal mark for each subject, separating it from Max-Marks and Att%
    columns that appear in the same horizontal band.

    Strategy overview
    -----------------
    Many Indian college PDF mark-sheets have per-subject sub-columns:
        21EN101        21CS101
        Max  CIA  Att%  Max  CIA  Att%
        50   45   92    50   48   88

    Without explicit text labels the following structural invariants are used:

    Pass A – Dedicated max-marks row detection
        The row(s) between the code header and the first student row often
        contain ONLY the max-marks values (e.g. all 50s / 25s) with NO student
        ID.  Collect those values as our max-marks ceiling.

    Pass B – Per-student row collection
        Scan every student data row; for each subject, bucket all numeric
        values within ±half_w of code_x by their X coordinate.

    Pass C – Classify X buckets
        Constant buckets (≥80 % same value)  → Max-Marks column (skip it)
        Variable buckets with values ≤ max   → Real marks column  ✓
        Variable buckets with values >  max  → Attendance % column (skip it)

    Fallback heuristics (when max cannot be determined)
        • Any bucket whose median > 75 is treated as attendance % (mark out of
          100 is possible, but att% is usually in 70-100 range universally).
        • Among remaining candidates, pick the leftmost variable bucket
          (marks column almost always precedes att% column in Indian PDFs).

    Returns (mark_xs, max_marks_by_code):
      mark_xs:           {subject_code: best_mark_x_float}
      max_marks_by_code: {subject_code: detected_max_marks}
    Both may be partial; ({}, {}) when insufficient data.
    """
    from collections import defaultdict
    import statistics as _stats

    if hdr_idx < 0 or not col_map:
        return {}, {}

    col_xs = sorted(col_map.keys())
    n_cols = len(col_xs)
    if n_cols < 1:
        return {}, {}

    col_width = (col_xs[-1] - col_xs[0]) / (n_cols - 1) if n_cols > 1 else 60.0
    # Use a tighter window (40% of spacing) so we don't bleed into adjacent subjects
    half_w    = max(col_width * 0.4, 18.0)

    # ── Pass A: Scan non-student rows between header and first student row ────
    # These rows typically carry only the Max-Marks (e.g., all "50") with no ID.
    # Collect per-subject max from the FIRST non-student numeric row after header.
    max_from_dedicated_row: Dict[str, float] = {}

    first_student_row_i = len(rows)
    for row_i, row in enumerate(rows):
        if row_i <= hdr_idx:
            continue
        if any(_is_student_id(t) for _, t in row):
            first_student_row_i = row_i
            break

    # Scan rows between header+1 and first student row for a "max marks" row:
    # accept a row if it has ≥ 1 numeric cell near each code column AND no ID.
    _VALID_MAX_VALUES = {10, 15, 20, 25, 30, 40, 50, 60, 75, 80, 100}
    for row_i in range(hdr_idx + 1, min(first_student_row_i, hdr_idx + 6)):
        row = rows[row_i]
        if not row:
            continue
        candidate: Dict[str, float] = {}
        for code_x, code in col_map.items():
            for x, t in row:
                if abs(x - code_x) > half_w:
                    continue
                clean = t.strip().replace(',', '.')
                if not re.fullmatch(r'\d{1,3}', clean):
                    continue
                try:
                    v = float(clean)
                except ValueError:
                    continue
                if v in _VALID_MAX_VALUES:
                    candidate[code] = v
                    break  # take the first (leftmost) matching value per subject
        # Only trust this row if it matched ≥ half the subjects
        if len(candidate) >= max(1, n_cols // 2):
            max_from_dedicated_row.update(candidate)
            break  # stop at first matching dedicated row

    # ── Pass B: Collect numeric values per (subject_code, x_bucket) ───────────
    # val_map[code][bucket_x] = list of float values seen in student rows
    val_map: Dict[str, Dict[float, list]] = defaultdict(lambda: defaultdict(list))
    raw_x_map: Dict[str, Dict[float, list]] = defaultdict(lambda: defaultdict(list))

    for row_i, row in enumerate(rows):
        if row_i <= hdr_idx:
            continue
        if not any(_is_student_id(t) for _, t in row):
            continue
        for code_x, code in col_map.items():
            for x, t in row:
                if abs(x - code_x) > half_w:
                    continue
                clean = t.strip().replace(',', '.')
                if not re.fullmatch(r'\d{1,3}(\.\d{1,2})?', clean):
                    continue
                try:
                    v = float(clean)
                except ValueError:
                    continue
                bx = round(x / _BUCKET_PTS) * _BUCKET_PTS
                val_map[code][bx].append(v)
                raw_x_map[code][bx].append(x)

    if not val_map:
        return {}, {}

    # ── Pass C: For each subject, classify buckets and pick best mark X ────────
    result: Dict[str, float]        = {}
    max_marks_ret: Dict[str, float] = {}

    for code, bx_vals in val_map.items():
        buckets = {bx: vs for bx, vs in bx_vals.items() if len(vs) >= 2}
        if not buckets:
            continue

        # ------------------------------------------------------------------
        # Determine max_marks ceiling for this subject (multiple sources):
        # Source 1: dedicated max-marks row (most reliable)
        # Source 2: constant-value bucket among student rows
        # ------------------------------------------------------------------
        max_marks_val: Optional[float] = max_from_dedicated_row.get(code)

        def _is_constant(vs: list) -> bool:
            top_val = max(set(vs), key=vs.count)
            return vs.count(top_val) / len(vs) >= 0.75

        constant_bxs = {bx for bx, vs in buckets.items() if _is_constant(vs)}

        if max_marks_val is None:
            # Fallback: smallest constant-bucket value
            for bx in sorted(constant_bxs):
                top_v = max(set(buckets[bx]), key=buckets[bx].count)
                if max_marks_val is None or top_v < max_marks_val:
                    max_marks_val = top_v

        if max_marks_val is not None:
            max_marks_ret[code] = max_marks_val

        # Non-constant buckets are candidates for actual marks or attendance %
        variable_bxs = [(bx, vs) for bx, vs in buckets.items()
                        if bx not in constant_bxs]

        if not variable_bxs:
            continue

        # ------------------------------------------------------------------
        # Filter out attendance % candidates
        # Rule 1: if max_marks known → reject buckets where > 50% exceed it
        # Rule 2: regardless of max_marks → reject buckets whose median > 75
        #         (attendance % is almost always ≥ 60; marks out of 50 rarely
        #          have median above 45; even out of 100 the median is usually
        #          below 75 for CIA exams)
        # ------------------------------------------------------------------
        def _is_attendance_bucket(vs: list, max_m: Optional[float]) -> bool:
            med = _stats.median(vs)
            if max_m is not None and sum(1 for v in vs if v > max_m) / len(vs) > 0.50:
                return True
            # Heuristic: if median > 75 AND max_marks is unknown or ≥ 100,
            # treat as attendance %
            if max_m is None or max_m >= 100:
                if med > 75:
                    return True
            return False

        valid_bxs = [(bx, vs) for bx, vs in variable_bxs
                     if not _is_attendance_bucket(vs, max_marks_val)]

        if not valid_bxs:
            # All filtered — likely end-semester (marks out of 100).
            # Attendance % still typically clustered higher than marks.
            # Pick the bucket with the LOWER median.
            valid_bxs = sorted(
                variable_bxs,
                key=lambda t: _stats.median(t[1])
            )[:1]

        if not valid_bxs:
            continue

        # Pick leftmost among valid candidates
        best_bx  = min(valid_bxs, key=lambda t: t[0])[0]
        raw_xs   = raw_x_map[code].get(best_bx, [best_bx])
        result[code] = sum(raw_xs) / len(raw_xs)

    return result, max_marks_ret



def _is_student_id(text: str) -> bool:
    """Return True if text looks like a registration number or roll number.
    
    Note: This can also match subject codes like 21AD101.
    Callers should check against known subject codes first.
    """
    t = text.strip()
    if not t:
        return False
    # 12- or 13-digit reg number: 714024243001
    if re.fullmatch(r'7\d{11,12}', t):
        return True
    # Any long digit sequence (≥8 digits) — likely a registration/enrolment number
    if re.fullmatch(r'\d{8,}', t):
        return True
    # roll number: 24AD001, 21CS023 etc.
    # But exclude likely subject codes: subject codes typically have a 3-digit
    # suffix ≥ 100 (e.g., 21AD101, 21CS201). Roll numbers are usually 001-099.
    m = re.fullmatch(r'(\d{2})([A-Z]{2,5})(\d{3,4})', t, re.IGNORECASE)
    if m:
        suffix = int(m.group(3))
        # Subject codes: suffix is typically 101, 102, 201, 301 etc. (≥100)
        # Roll numbers: suffix is typically 001–099
        # We still return True but callers should use _known_codes to disambiguate
        return True
    return False


def _normalize_student_key(text: str) -> str:
    """Normalize roll/reg numbers for matching (strip spaces/punctuation)."""
    if text is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(text)).upper()


_SUBJ_NAME_SKIP = {
    'MAX', 'MIN', 'TOTAL', 'GRADE', 'CREDITS', 'CREDIT', 'PASS', 'FAIL',
    'MARKS', 'MARK', 'S.NO', 'S.N', 'SNO', 'SL.NO', 'ROLL', 'REG', 'NAME',
    'RESULT', 'SEM', 'SEMESTER', 'INT', 'EXT', 'THEORY', 'PRACTICAL',
    'INTERNAL', 'EXTERNAL', 'CIA', 'NO', 'AVERAGE', 'AVG',
    # Attendance-related noise words — these appear in the same rows as marks
    # and must never be misidentified as subject names.
    'ATTENDANCE', 'ATTEN', 'ABSENT', 'PRESENT', 'PERCENTAGE', 'PERCENT',
    'ABSENT%', 'PRESENT%', 'ATT', 'ATTENDED', 'CLASSES', 'CONDUCTED',
}

# Tokens anywhere in a candidate subject name that disqualify the entire name.
# Used in _extract_subject_names to silently drop attendance/noise rows.
_SUBJ_NAME_DISQUALIFY = {
    'ATTENDANCE', 'ATTEN', 'ABSENT', 'PRESENT', 'PERCENTAGE', 'PERCENT',
    'ATT%', 'MARK', 'MARKS',
}

# Words that identify an entire ROW as a document title / institution header.
# If ANY word in the row matches, the ENTIRE ROW is skipped.
# These words never appear as part of academic course names.
_TITLE_ROW_MARKERS = {
    'DEPARTMENT', 'DEPT', 'COLLEGE', 'UNIVERSITY', 'INSTITUTE', 'INSTITUTION',
    'AUTONOMOUS', 'AFFILIATED', 'REGULATION', 'CAMPUS', 'FACULTY', 'SCHOOL',
    'ACCREDITED', 'NAAC', 'DEEMED', 'POLYTECHNIC',
    # Exam-title words that span the full page width
    'CONTINUOUS', 'ASSESSMENT', 'EXAMINATION', 'EXAMINATIONS',
}

# ── Honorifics that signal the start of a teacher / staff name ────────────────
_HONORIFICS = frozenset({
    'MRS', 'MR', 'MS', 'DR', 'PROF', 'SMT', 'SHRI', 'SRI',
})

# ── Faculty designation abbreviations (never subject name words) ──────────────
_STAFF_DESIGNATIONS = frozenset({
    'AP', 'ASP', 'HOD', 'ASST', 'ASSO', 'ASSOC',
})

# ── Words characteristic of student-info tables ──────────────────────────────
# If ≥2 of these appear in a candidate row, that row is student data, not a
# subject name.  Used as a row-level guard and as a name-level rejector.
_STUDENT_INFO_INDICATORS = frozenset({
    'REGISTER', 'REGISTRATION', 'GENDER', 'FEMALE', 'MALE',
    'HOSTELLER', 'DAYSCHOLAR', 'SGPA', 'CGPA', 'ARREAR', 'ARREARS',
    'RANK', 'H/D', 'SCHOLAR',
})

# ── Keywords for detecting legend-table column headers ────────────────────────
_LEGEND_NAME_HDR_KW = frozenset({
    'SUBJECT', 'COURSE', 'TITLE', 'PAPER',
})
_LEGEND_AFTER_NAME_KW = frozenset({
    'STAFF', 'TEACHER', 'FACULTY', 'INSTRUCTOR', 'HANDLED', 'LECTURER',
    'DESIGNATION', 'DESIG', 'DEPARTMENT', 'DEPT',
    'TYPE', 'CATEGORY', 'NATURE',
})


def _clean_subject_name(name: str) -> str:
    """
    Aggressively clean a candidate subject name extracted from PDF text.

    Strips:
      - Teacher / staff names  (everything after Mrs. / Mr. / Dr. / etc.)
      - Trailing designation codes  (AP, HOD, ASP …)
      - Entire strings that look like student-info table data
        ("Register Number AARTHI Female Gender …")
    """
    if not name:
        return ""

    words = name.split()

    # Phase 1 — reject if this looks like student-info data (≥35 % indicator words)
    indicator_hits = sum(
        1 for w in words if w.upper().rstrip('.,:-') in _STUDENT_INFO_INDICATORS
    )
    if len(words) > 2 and indicator_hits / len(words) > 0.30:
        return ""

    # Phase 2 — truncate at first honorific (beginning of teacher name)
    clean: list = []
    for w in words:
        wu = w.upper().rstrip('.,:-')
        if wu in _HONORIFICS:
            break
        clean.append(w)

    if not clean:
        return ""

    # Phase 3 — strip trailing designation codes (AP, HOD, etc.)
    while clean:
        last_up = clean[-1].upper().rstrip('.,:-')
        if last_up in _STAFF_DESIGNATIONS:
            clean.pop()
        else:
            break

    # Phase 4 — strip trailing 2-letter uppercase-only words that look like
    # department abbreviations (EE, AI, DS, IT, CE …) but protect real words
    # like "II" (Roman numeral) and words < 2 chars.
    while len(clean) > 1:
        last = clean[-1].rstrip('.,:-')
        if (len(last) == 2 and last.isalpha() and last.isupper()
                and last not in ('II', 'IV', 'VI')):
            clean.pop()
        else:
            break

    # Phase 5 — drop any remaining student-info noise words
    clean = [w for w in clean
             if w.upper().rstrip('.,:-') not in _STUDENT_INFO_INDICATORS]

    result = ' '.join(clean).strip()
    return result if len(result) >= 4 else ""


def _extract_subject_names(rows: list, hdr_idx: int, col_map: Dict[float, str]) -> Dict[str, str]:
    """
    Scan rows adjacent to the subject-code header row for full subject names.

    PDF mark sheets typically have a row just above or just below the code row
    that contains the human-readable subject names.  Words that x-align with a
    code column (but are not codes / numbers / common header words) are joined
    into the subject name for that column.
    """
    if hdr_idx < 0 or not col_map:
        return {}

    col_xs  = sorted(col_map.keys())
    n_cols  = len(col_xs)

    def col_index(x: float) -> int:
        """Return the index of the col_xs entry nearest to x."""
        return min(range(n_cols), key=lambda i: abs(col_xs[i] - x))

    best_names: Dict[str, str] = {}
    best_count = 0

    # Check up to 2 rows above and 2 rows below the header row.
    # A narrow window avoids picking up title/institution rows that sit
    # far above the header.
    candidates = (
        list(range(max(0, hdr_idx - 2), hdr_idx)) +
        list(range(hdr_idx + 1, min(len(rows), hdr_idx + 3)))
    )

    for row_i in candidates:
        row = rows[row_i]

        # ── Row-level guard 1: skip DATA rows (contain student IDs) ─────────
        row_texts = [text for _, text in row]
        if any(_is_student_id(t) for t in row_texts):
            continue

        # ── Row-level guard 2: skip TITLE / INSTITUTION rows ───────────────
        # Rows like "Department of Artificial Intelligence and Data Science"
        # or "Continuous Internal Assessment - 1" span the full page width.
        # Their words get bucketed into subject columns, producing garbage
        # names like "Department of", "Artifical Intelligence and".
        row_tokens_up = {t.upper().strip('.,:=-') for t in row_texts}
        if row_tokens_up & _TITLE_ROW_MARKERS:
            continue

        # ── Row-level guard 3: skip STUDENT-INFO table rows ─────────────────
        # Rows like "Register Number  Name  Gender  H/D  SGPA  Arrear  Rank"
        # appear near subject-code headers in multi-table PDFs.
        student_info_hits = len(row_tokens_up & _STUDENT_INFO_INDICATORS)
        if student_info_hits >= 2:
            continue

        # Bucket each word into the column whose centroid it is nearest
        col_words: Dict[int, list] = {i: [] for i in range(n_cols)}
        for x, text in row:
            col_words[col_index(x)].append((x, text))

        row_names: Dict[str, str] = {}
        for col_i, col_x in enumerate(col_xs):
            code  = col_map[col_x]
            # Join all words in this column bucket, left-to-right
            joined = ' '.join(t for _, t in sorted(col_words[col_i])).strip()

            if not joined:
                continue

            tokens = joined.split()

            # Skip cells where ALL tokens are numbers / decimals.
            # Handles space-separated marks like "98 100", "72 97 59",
            # "100 82 419 98.83" that the old single-regex missed.
            if all(re.fullmatch(r'[\d.,/\-]+', tok) for tok in tokens):
                continue

            # Skip cells where MORE THAN HALF the tokens are numeric.
            # Catches mixed data cells like "AARTHI 100" from data rows.
            numeric_tokens = sum(1 for tok in tokens if re.fullmatch(r'[\d.,/\-]+', tok))
            if numeric_tokens > len(tokens) / 2:
                continue

            # A valid subject name must contain at least one word with ≥3
            # alphabetic characters. Single letters ("V", "G") and 2-char
            # tokens are initials or noise, not subject names.
            alpha_words = [tok for tok in tokens if len(re.sub(r'[^A-Za-z]', '', tok)) >= 3]
            if not alpha_words:
                continue

            # Guard against title-row fragments that slipped through the
            # row-level check (edge cases with multi-line merging).
            if {w.upper() for w in alpha_words} & _TITLE_ROW_MARKERS:
                continue

            # Guard against preposition-only fragments like "of", "and",
            # "Department of" — a real subject name needs a noun.
            _FILLER = {'OF', 'AND', 'THE', 'IN', 'FOR', 'TO', 'A', 'AN', 'WITH', 'ON', 'AT', 'BY'}
            if all(tok.upper() in _FILLER for tok in alpha_words):
                continue

            # Skip subject-code patterns
            if _SUBJ_CODE_RE.fullmatch(joined.upper().strip()):
                continue
            # Skip common non-name header words (whole cell or every token)
            tokens_up = {tok.upper().strip('.') for tok in tokens}
            if tokens_up <= _SUBJ_NAME_SKIP:
                continue

            # Final guard: if any disqualifier token appears in the name,
            # this whole cell is attendance/noise — skip it.
            name_tokens_up = {tok.upper().strip('%.') for tok in tokens}
            if name_tokens_up & _SUBJ_NAME_DISQUALIFY:
                continue

            row_names[code] = joined

        # Keep the row that gives us names for the most columns
        if len(row_names) > best_count:
            best_count = len(row_names)
            best_names = row_names

    # Only trust if we got names for at least half the subject columns
    if best_count < max(1, n_cols // 2):
        return {}

    # Apply aggressive cleaning to strip teacher names, designations, etc.
    cleaned: Dict[str, str] = {}
    for code, raw_name in best_names.items():
        cn = _clean_subject_name(raw_name)
        if cn:
            cleaned[code] = cn
    return cleaned


def _scan_all_pages_for_subject_names(doc, known_codes: set) -> Dict[str, str]:
    """
    Whole-document scan for subject names.

    Many Indian college PDFs have a "subjects offered" table on the first page
    (separate from the marks data table) that lists  code → name → credits.
    `_extract_subject_names` only looks ±2 rows around the marks header, so it
    misses names that live in a completely different table.

    This function scans EVERY row on EVERY page looking for rows that contain
    a known subject code alongside plain-text that qualifies as a name.

    Layout types handled:
      Type A — code left, name right (subject list table):
          21AD101  Design Thinking & Innovation  3
      Type B — name above/same row as code in a wide header:
          Engineering Mathematics  Data Structures ...
          21MA130               21CS112 ...

    Returns {code: best_name_found}.  Bare-code entries are only used to fill
    gaps — caller should prefer _extract_subject_names results when available.
    """
    names: Dict[str, str] = {}
    if not known_codes or doc is None:
        return names

    for page in doc:
        rows = _page_rows(page)
        for row in rows:
            # Locate all known subject codes in this row
            codes_in_row: Dict[float, str] = {}          # x → code
            for x, t in row:
                m = _SUBJ_CODE_RE.match(t.strip().upper())
                if m and m.group(1) in known_codes:
                    codes_in_row[x] = m.group(1)

            if not codes_in_row:
                continue

            # ── Row-level guard: skip student-info table rows ───────────────
            row_words_up = {t.strip().upper().rstrip('.,:-')
                            for _, t in row}
            if len(row_words_up & _STUDENT_INFO_INDICATORS) >= 2:
                continue

            # For each code found, harvest candidate name text from the same row
            for code_x, code in codes_in_row.items():
                candidates: list = []
                for x, t in row:
                    # Skip the code cell itself
                    if abs(x - code_x) < 5:
                        continue
                    ts = t.strip()
                    if not ts:
                        continue
                    # Skip other codes
                    if _SUBJ_CODE_RE.fullmatch(ts.upper()):
                        continue
                    # Skip pure numbers / marks / percentages
                    if re.fullmatch(r'[\d.,/\-\s%()]+', ts):
                        continue
                    ts_up = ts.upper().strip('.,:-')
                    if ts_up in _SUBJ_NAME_SKIP:
                        continue
                    if ts_up in _SUBJ_NAME_DISQUALIFY:
                        continue
                    if ts_up in _TITLE_ROW_MARKERS:
                        continue
                    # Need at least one word with ≥3 alpha characters
                    alpha_words = [w for w in ts.split()
                                   if len(re.sub(r'[^A-Za-z]', '', w)) >= 3]
                    if not alpha_words:
                        continue
                    candidates.append((x, ts))

                if not candidates:
                    continue

                # Prefer text that appears to the RIGHT of the code (Type A layout)
                right = [(x, n) for x, n in candidates if x > code_x]
                chosen = max(right, key=lambda c: len(c[1]))[1] if right else \
                         max(candidates, key=lambda c: len(c[1]))[1]

                # Aggressive clean — strip teacher names, designations, etc.
                chosen = _clean_subject_name(chosen)
                if chosen and len(chosen) >= 5:
                    existing = names.get(code, code)
                    # Accept if: no name yet, or new name is longer (more informative)
                    if existing == code or len(chosen) > len(existing):
                        names[code] = chosen

    return names


# ── Full-document pre-scan ("understand before you parse") ────────────────────

def _extract_subject_legend_tables(doc, known_codes: set = None) -> Dict[str, Dict]:
    """
    Column-aware legend table parser.

    Indian university PDFs contain a legend table mapping codes to names:

        S.No │ Code    │ Subject Name                   │ Staff Name       │ Desig │ Dept
        ─────┼─────────┼────────────────────────────────┼──────────────────┼───────┼──────
         1   │ 21AD101 │ Design Thinking and Innovation │ Mrs. Shakthi ...│ AP    │ AI DS

    Previous parsers grabbed ALL text from a row, producing garbage names
    like "Design Thinking and Innovation Mrs. Shakthi Priya AP AI DS".

    This implementation:
      1. Finds the legend table **header row** (contains column labels like
         "Subject", "Staff", "Department").
      2. Uses X-positions of those header keywords to compute **column
         boundaries** — the subject-name column ends where the staff column
         begins.
      3. For data rows, extracts ONLY words whose X-center falls inside the
         subject-name column.
      4. Falls back to aggressive cleaning when no header is detected.

    Returns: {code: {"name": str, "credits": int}}
    """
    import fitz

    legend: Dict[str, Dict] = {}
    if doc is None:
        return legend

    for page in doc:
        rows = _page_rows(page, y_tol=5.0)
        if not rows:
            continue

        # ── Phase 1: detect legend-table header row ──────────────────────────
        hdr_row_idx = -1
        name_col_left  = 0.0           # left X boundary of subject-name column
        name_col_right = float('inf')  # right X boundary
        credits_col_x: Optional[float] = None

        for ri, row in enumerate(rows):
            word_ups = [(x, t.upper().strip('.,:-()')) for x, t in row]
            word_set = {w for _, w in word_ups}

            # A legend header should have BOTH:
            #   ≥1 name keyword  (SUBJECT, COURSE, TITLE …)  AND
            #   ≥1 "after-name" keyword  (STAFF, DEPARTMENT, DESIGNATION …)
            has_name_kw  = bool(word_set & _LEGEND_NAME_HDR_KW)
            has_after_kw = bool(word_set & _LEGEND_AFTER_NAME_KW)

            if not (has_name_kw and has_after_kw):
                continue

            # ── Compute column boundaries from header word positions ────────
            name_kw_xs  = [x for x, w in word_ups if w in _LEGEND_NAME_HDR_KW]
            after_kw_xs = [x for x, w in word_ups if w in _LEGEND_AFTER_NAME_KW]
            code_kw_xs  = [x for x, w in word_ups if w in {'CODE', 'NO', 'S'}]
            cred_kw_xs  = [x for x, w in word_ups
                           if w in {'CREDITS', 'CREDIT', 'CR'}]

            if name_kw_xs and after_kw_xs:
                # Name column LEFT edge: just before the leftmost name keyword,
                # or just after the code keyword if we found one.
                if code_kw_xs:
                    name_col_left = max(code_kw_xs) + 15
                else:
                    name_col_left = min(name_kw_xs) - 30

                # Name column RIGHT edge: just before the leftmost staff /
                # dept / designation keyword.
                name_col_right = min(after_kw_xs) - 10

                if cred_kw_xs:
                    credits_col_x = min(cred_kw_xs)

                hdr_row_idx = ri
                break          # found the header, no need to keep looking

        # ── Phase 2: extract data from rows below the header ─────────────────
        if hdr_row_idx >= 0:
            consecutive_empty = 0
            for row in rows[hdr_row_idx + 1:]:
                # Find subject code in this row
                code_found: Optional[str] = None
                code_x: Optional[float] = None
                for x, t in row:
                    m = _SUBJ_CODE_RE.match(t.strip().upper())
                    if m:
                        c = m.group(1)
                        if known_codes is None or c in known_codes:
                            code_found = c
                            code_x = x
                            break

                if not code_found:
                    consecutive_empty += 1
                    if consecutive_empty >= 4:
                        break               # table ended
                    continue
                consecutive_empty = 0

                # Skip data rows (contain student IDs)
                has_student_id = False
                for x, t in row:
                    if code_x is not None and abs(x - code_x) < 5:
                        continue
                    if (_is_student_id(t.strip())
                            and t.strip().upper() != code_found):
                        has_student_id = True
                        break
                if has_student_id:
                    continue

                # Collect words ONLY within the subject-name column boundaries
                name_parts: list = []
                credits_val: Optional[int] = None
                for x, t in sorted(row, key=lambda c: c[0]):
                    ts = t.strip()
                    if not ts:
                        continue
                    tu = ts.upper().rstrip('.,:-')

                    # ── Credits column ───────────────────────────────────────
                    if credits_col_x is not None and abs(x - credits_col_x) < 30:
                        try:
                            v = int(ts)
                            if 1 <= v <= 6:
                                credits_val = v
                        except ValueError:
                            pass
                        continue

                    # ── Name column check ────────────────────────────────────
                    if not (name_col_left <= x <= name_col_right):
                        continue       # outside the name column

                    if _SUBJ_CODE_RE.match(tu):
                        continue
                    if re.fullmatch(r'[\d.,/\-]+', ts):
                        continue
                    if len(re.sub(r'[^A-Za-z]', '', ts)) < 2:
                        continue

                    name_parts.append(ts)

                if name_parts:
                    raw = ' '.join(name_parts).strip()
                    clean = _clean_subject_name(raw)
                    if clean and len(clean) >= 4:
                        existing = legend.get(code_found, {}).get("name", "")
                        if not existing or len(clean) > len(existing):
                            legend[code_found] = {
                                "name": clean,
                                "credits": credits_val or 3,
                            }

        # ── Phase 3 (fallback): no header found — consecutive-row heuristic ─
        # Still applies _clean_subject_name to strip teacher / dept garbage.
        if hdr_row_idx < 0:
            consecutive_legend_rows: list = []

            for row in rows:
                codes_in_row: list = []  # [(x, code)]
                all_texts: list = []     # [(x, text)]
                for x, t in row:
                    ts = t.strip()
                    all_texts.append((x, ts))
                    m = _SUBJ_CODE_RE.match(ts.upper())
                    if m:
                        c = m.group(1)
                        if known_codes is None or c in known_codes:
                            codes_in_row.append((x, c))

                if not codes_in_row:
                    if len(consecutive_legend_rows) >= 2:
                        for entry in consecutive_legend_rows:
                            c = entry["code"]
                            if (c not in legend
                                    or len(entry["name"]) > len(legend.get(c, {}).get("name", ""))):
                                legend[c] = {"name": entry["name"],
                                             "credits": entry.get("credits", 3)}
                    consecutive_legend_rows = []
                    continue

                for code_x, code in codes_in_row:
                    # Skip data rows
                    has_sid = False
                    for x, t in all_texts:
                        if abs(x - code_x) < 5:
                            continue
                        if (_is_student_id(t)
                                and t.upper() != code
                                and not _SUBJ_CODE_RE.match(t.upper())):
                            has_sid = True
                            break
                    if has_sid:
                        continue

                    # Gather text, but apply cleaning
                    name_parts: list = []
                    credits_found: Optional[int] = None
                    for x, t in sorted(all_texts, key=lambda c: c[0]):
                        if abs(x - code_x) < 5:
                            continue
                        tu = t.upper().strip('.,:-')
                        if _SUBJ_CODE_RE.match(tu):
                            continue
                        if re.fullmatch(r'\d{1,2}', t.strip()):
                            v = int(t.strip())
                            if 1 <= v <= 6 and credits_found is None:
                                credits_found = v
                            continue
                        if re.fullmatch(r'[\d.,/\-\s%()]+', t.strip()):
                            continue
                        if tu in _SUBJ_NAME_SKIP or tu in _SUBJ_NAME_DISQUALIFY:
                            continue
                        if len(re.sub(r'[^A-Za-z]', '', t)) < 2:
                            continue
                        name_parts.append(t)

                    if name_parts:
                        raw = ' '.join(name_parts).strip()
                        clean = _clean_subject_name(raw)
                        if clean and len(clean) >= 4:
                            consecutive_legend_rows.append({
                                "code": code,
                                "name": clean,
                                "credits": credits_found or 3,
                            })

            # Flush final streak
            if len(consecutive_legend_rows) >= 2:
                for entry in consecutive_legend_rows:
                    c = entry["code"]
                    if (c not in legend
                            or len(entry["name"]) > len(legend.get(c, {}).get("name", ""))):
                        legend[c] = {"name": entry["name"],
                                     "credits": entry.get("credits", 3)}

    return legend


# ── Hallucination guard for LLM subject names ────────────────────────────────

# Common fragments that LLMs hallucinate as subject names when they don't know
# the real name. These are institution / department / exam title words.
_HALLUCINATION_MARKERS = {
    'DEPARTMENT', 'COLLEGE', 'UNIVERSITY', 'INSTITUTE', 'INSTITUTION',
    'ENGINEERING', 'TECHNOLOGY', 'SCIENCE', 'ARTS', 'CAMPUS',
    'AUTONOMOUS', 'AFFILIATED', 'ASSESSMENT', 'EXAMINATION',
    'CONTINUOUS', 'INTERNAL', 'SEMESTER', 'ACADEMIC', 'BATCH',
    'ARTIFICIAL', 'INTELLIGENCE', 'DATA', 'COMPUTER',
}


def _is_hallucinated_name(name: str) -> bool:
    """
    Return True if the LLM-suggested subject name looks like a hallucinated
    fragment from the institution/department/exam title, a teacher name,
    or student-data noise rather than a real course title.

    Examples of hallucinated / garbage names:
      - "Department of Artificial Intelligence"   (institution row)
      - "Continuous Internal Assessment"          (exam title row)
      - "Mrs. Shakthi Priya AP AI DS"            (teacher + designation)
      - "Register Number AARTHI Female Gender"   (student info row)

    Examples of REAL subject names (should return False):
      - "Engineering Mathematics"
      - "Design Thinking and Innovation"
      - "Technical English"
      - "Problem Solving using C"
    """
    if not name or name == name.upper():
        # All-caps codes (21AD101) — not hallucinated, just bare codes
        return False

    words = name.upper().split()
    if len(words) < 2:
        return False

    # ── Teacher / staff name detection ────────────────────────────────────
    for w in words:
        if w.rstrip('.,:-') in _HONORIFICS:
            return True

    # ── Student-info row detection ────────────────────────────────────────
    student_hits = sum(
        1 for w in words if w.rstrip('.,:-') in _STUDENT_INFO_INDICATORS
    )
    if student_hits >= 2:
        return True

    # Count how many words are hallucination markers
    marker_count = sum(1 for w in words if w.strip('.,:-') in _HALLUCINATION_MARKERS)

    # If more than half the words are markers, it's likely hallucinated
    if marker_count > len(words) / 2:
        return True

    # Specific patterns that are always hallucinated
    name_up = name.upper()
    if re.search(r'DEPARTMENT\s+OF', name_up):
        return True
    if re.search(r'COLLEGE\s+OF', name_up):
        return True
    if re.search(r'INSTITUTE\s+OF', name_up):
        return True
    if re.search(r'CONTINUOUS\s+INTERNAL', name_up):
        return True

    return False


def _full_document_prescan(file_bytes: bytes) -> Dict:
    """
    AI Architecture: "Understand the ENTIRE document before extracting data."

    This function performs a comprehensive pre-scan of the PDF to build a
    full understanding of its structure BEFORE any data extraction begins.

    Returns:
      {
        "full_text":      str,        # Complete text of all pages
        "page_count":     int,
        "mark_type":      str,        # "internal" | "end_semester"
        "legend_names":   {code: {"name": str, "credits": int}},
        "legend_text":    str,        # The raw text of legend table sections
        "header_text":    str,        # First 2000 chars for LLM
        "has_legend":     bool,
        "detected_codes": set,        # All subject codes found anywhere
      }
    """
    import fitz

    result = {
        "full_text":      "",
        "page_count":     0,
        "mark_type":      "internal",
        "legend_names":   {},
        "legend_text":    "",
        "header_text":    "",
        "has_legend":     False,
        "detected_codes": set(),
    }

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return result

    result["page_count"] = doc.page_count

    # ── Pass 1: Extract full text and detect all subject codes ────────────────
    page_texts: list = []
    for page in doc:
        text = page.get_text("text")
        page_texts.append(text)

    result["full_text"] = "\n".join(page_texts)
    result["header_text"] = page_texts[0][:2000] if page_texts else ""

    # Detect mark type from full text
    text_up = result["full_text"].upper()
    if re.search(r'END\s*SEM|SEMESTER\s*EXAM|FINAL\s*EXAM|UNIVERSITY\s*EXAM', text_up):
        result["mark_type"] = "end_semester"

    # Find all subject codes across entire document
    for m in _SUBJ_CODE_RE.finditer(text_up):
        result["detected_codes"].add(m.group(1))

    # ── Pass 2: Find subject legend/mapping tables ────────────────────────────
    legend = _extract_subject_legend_tables(doc, result["detected_codes"] or None)
    result["legend_names"] = legend
    result["has_legend"] = bool(legend)

    # ── Pass 3: Build legend text for LLM context ─────────────────────────────
    # Find the actual text sections that contain the legend table so the LLM
    # can see them and be less likely to hallucinate.
    if legend:
        legend_codes = set(legend.keys())
        legend_lines: list = []
        for pt in page_texts:
            for line in pt.split('\n'):
                line_up = line.upper().strip()
                for code in legend_codes:
                    if code in line_up:
                        legend_lines.append(line.strip())
                        break
        result["legend_text"] = '\n'.join(legend_lines[:50])  # cap at 50 lines

    doc.close()
    return result


def _extract_end_sem_fields(
    cell: Dict[float, str],
    subj_code: str,
    global_endsem_xs: Dict[str, Dict[str, float]],
) -> Dict:
    """
    Given a row's cell map, extract grade / GP / status / credits
    for an end-semester subject if sub-column positions are known.
    Returns a dict with only the keys that were found.
    """
    positions = global_endsem_xs.get(subj_code)
    if not positions:
        return {}

    result = {}
    cell_xs = list(cell.keys())

    # Grade (A+, O, U, …)
    gx = positions.get('grade')
    if gx is not None:
        nx = _nearest_x(gx, cell_xs, tol=20.0)
        if nx is not None:
            val = cell[nx].strip()
            if val and val.upper() not in ('', '-', '—'):
                result['grade'] = val

    # Grade Points (0–10)
    gpx = positions.get('gp')
    if gpx is not None:
        nx = _nearest_x(gpx, cell_xs, tol=20.0)
        if nx is not None:
            val = cell[nx].strip()
            try:
                result['grade_points'] = float(val.replace(',', '.'))
            except (ValueError, AttributeError):
                pass

    # Result Status (PASS / FAIL / AB)
    sx = positions.get('status')
    if sx is not None:
        nx = _nearest_x(sx, cell_xs, tol=20.0)
        if nx is not None:
            val = cell[nx].strip().upper()
            if val in ('P', 'PASS', 'PASSED'):
                result['result_status'] = 'PASS'
            elif val in ('F', 'FAIL', 'FAILED'):
                result['result_status'] = 'FAIL'
            elif val in ('AB', 'ABS', 'ABSENT'):
                result['result_status'] = 'AB'
            elif val in ('WH', 'WITHHELD'):
                result['result_status'] = 'WH'
            elif val and val not in ('', '-', '—'):
                result['result_status'] = val

    # Credits
    cx = positions.get('credits')
    if cx is not None:
        nx = _nearest_x(cx, cell_xs, tol=20.0)
        if nx is not None:
            val = cell[nx].strip()
            try:
                result['credits'] = int(val)
            except (ValueError, AttributeError):
                pass

    # Infer result_status from grade if not found explicitly
    if 'result_status' not in result and 'grade' in result:
        g = result['grade'].upper()
        if g in ('U', 'F'):
            result['result_status'] = 'FAIL'
        elif g in ('AB', 'ABS'):
            result['result_status'] = 'AB'
        elif g not in ('', '-', '—'):
            result['result_status'] = 'PASS'

    return result


def _parse_pdf_table(file_bytes: bytes) -> Dict:
    """
    Full pipeline: open PDF → find header row → map columns → extract all rows.

    Returns:
      {
        "subjects":  [{"code": ..., "name": ..., "credits": 3}],
        "records":   [{"roll_number": ..., "subject_code": ...,
                       "internal_number": 1, "marks": float|null,
                       "type": "internal"}],
        "mark_type": "internal" | "end_semester",
        "internal_number": 1|2|3,
        "pages_parsed": int,
        "header_codes": [...],
      }
    """
    import fitz

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        return {"error": f"Cannot open PDF: {e}"}

    # ── Detect mark type + internal number from full-text of page 1 ──────────
    full_p1 = doc[0].get_text() if doc.page_count > 0 else ""
    text_up = full_p1.upper()

    if re.search(r'END\s*SEM|SEMESTER\s*EXAM|FINAL\s*EXAM|UNIVERSITY\s*EXAM', text_up):
        mark_type = "end_semester"
    else:
        mark_type = "internal"

    # Detect internal number — try patterns from most-specific to least-specific.
    # IMPORTANT: patterns use \b word boundaries AND require at least one separator
    # character (space, dash, colon …) between the keyword and the digit so that
    # subject codes such as 21ECT201 or 21CIA301 do NOT falsely match.
    internal_number = 1
    _ia_patterns = [
        # Full spellings  ("Continuous Internal Assessment - 2", "CIA Test 3" …)
        r'CONTINUOUS\s+INTERNAL\s+ASSESSMENT\s*[-\u2013:]*\s*([123])\b',
        # Dotted abbreviation  ("C.I.A 2", "C.I.A.-3" …)
        r'\bC\.I\.A\.?\s*[-\u2013:]*\s*([123])\b',
        # Short tokens — \b on both sides AND ≥1 separator so "ECT201" won't match
        r'\b(?:INTERNAL|TEST|CIA|CT|IA)\b[\s\-\u2013:/]+([123])\b',
    ]
    for _pat in _ia_patterns:
        _m = re.search(_pat, text_up)
        if _m:
            internal_number = int(_m.group(1))
            break

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: collect all subject codes + names from every page.
    # We do a full pre-pass so that:
    #  a) global_col_map is complete before we start reading data rows.
    #  b) subject names found in OTHER tables (subject-index page) are captured.
    # ─────────────────────────────────────────────────────────────────────────
    global_col_map:  Dict[float, str]   = {}  # x → subject_code
    global_mark_xs:  Dict[str, float]   = {}  # subject_code → best mark-column X
    global_max_marks: Dict[str, float]  = {}  # subject_code → detected max marks
    # End-sem sub-column X positions: {subj_code: {"grade": x, "gp": x, ...}}
    global_endsem_xs: Dict[str, Dict[str, float]] = {}
    subject_names:   Dict[str, str]     = {}
    all_records: list = []
    pages_parsed = 0

    # page_data caches (rows, hdr_idx, col_map) so Phase 2 avoids re-parsing
    page_cache: list = []

    for page in doc:
        rows = _page_rows(page)
        hdr_idx, col_map = _find_header_row(rows) if rows else (-1, {})
        page_cache.append((rows, hdr_idx, col_map))

        if not col_map:
            continue

        global_col_map.update(col_map)

        # Detect which X column is the real marks column (statistical + label)
        stat_mark_xs, stat_max_marks = _find_best_mark_xs(rows, hdr_idx, col_map)
        global_mark_xs.update(stat_mark_xs)
        global_max_marks.update(stat_max_marks)
        label_mark_xs = _detect_mark_subcolumns(rows, hdr_idx, col_map)
        global_mark_xs.update(label_mark_xs)

        # Detect end-semester sub-columns (grade, GP, status …)
        if mark_type == "end_semester":
            endsem_xs = _detect_end_sem_subcolumns(rows, hdr_idx, col_map)
            for code, positions in endsem_xs.items():
                global_endsem_xs.setdefault(code, {}).update(positions)

        # Collect nearby subject names (±2 rows around the marks header)
        found_names = _extract_subject_names(rows, hdr_idx, col_map)
        for code, name in found_names.items():
            subject_names[code] = name
        for code in col_map.values():
            subject_names.setdefault(code, code)

    # ── After phase 1: do a FULL document scan for names in OTHER tables ──────
    # Fills gaps for codes whose names weren't in the ±2 rows around the header.
    if global_col_map:
        known_codes = set(global_col_map.values())
        doc_wide_names = _scan_all_pages_for_subject_names(doc, known_codes)
        for code, name in doc_wide_names.items():
            # Only use doc-wide name if we still have the bare code as a name
            if subject_names.get(code, code) == code and name != code:
                subject_names[code] = name

    if not global_col_map:
        doc.close()
        return {"error": "No subject-code header row found in any page of the PDF."}

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: data extraction — iterate student rows on all pages.
    # Key guard: subject codes (21AD101) look like roll numbers to _is_student_id.
    # We explicitly exclude any text that matches a known subject code.
    # ─────────────────────────────────────────────────────────────────────────
    _known_codes: set = set(global_col_map.values())  # e.g. {"21AD101", "21CS101", …}

    for rows, hdr_idx, col_map in page_cache:
        if not rows:
            continue

        # Iterate data rows (skip the header row itself)
        for row_i, row in enumerate(rows):
            if row_i == hdr_idx:
                continue

            # Collect text cells as a flat dict: x → text
            cell: Dict[float, str] = {x: t for x, t in row}

            # Find student ID in this row.
            # IMPORTANT: skip cells that are known subject codes — both patterns
            # \d{2}[A-Z]+\d{3} match roll numbers (24AD001) AND subject codes
            # (21AD101), so without this guard subject codes are treated as IDs.
            student_id = None
            for x, text in sorted(cell.items()):
                if text.strip().upper() in _known_codes:
                    continue    # definitely a subject code, not a student ID
                if _is_student_id(text):
                    student_id = text.strip()
                    break
            if not student_id:
                continue

            # For each subject column, read the value at the best mark-column X.
            for col_x, subj_code in global_col_map.items():
                target_x = global_mark_xs.get(subj_code, col_x)
                tol = 15.0 if subj_code in global_mark_xs else 30.0
                nearest  = _nearest_x(target_x, list(cell.keys()), tol=tol)
                raw_val  = cell.get(nearest, "") if nearest is not None else ""

                # Parse the marks value
                marks     = None
                is_absent = False
                if raw_val:
                    clean = raw_val.strip().replace(',', '.')
                    if clean.upper() in ('AB', 'A/B', 'ABS', 'ABSENT'):
                        is_absent = True
                    elif re.fullmatch(r'\d{1,3}\.\d{2,}', clean):
                        marks = None   # 2+ decimal places → attendance %
                    elif re.fullmatch(r'\d{1,3}(\.\d)?' , clean):
                        try:
                            marks = float(clean)
                            _ceil = global_max_marks.get(subj_code)
                            if _ceil is not None and marks > _ceil:
                                marks = None   # exceeds max → attendance %
                        except ValueError:
                            marks = None

                all_records.append({
                    "roll_number":     student_id,
                    "subject_code":    subj_code,
                    "internal_number": internal_number,
                    "marks":           marks,
                    "is_absent":       is_absent,
                    "type":            mark_type,
                    **_extract_end_sem_fields(cell, subj_code, global_endsem_xs),
                })

        pages_parsed += 1

    doc.close()

    subjects = []
    for code in global_col_map.values():
        # Try to pick up credits from end-sem sub-columns parsed from data rows
        cr = 3
        endsem_pos = global_endsem_xs.get(code, {})
        # Also check records themselves for credits
        for rec in all_records:
            if rec.get("subject_code") == code and rec.get("credits"):
                cr = rec["credits"]
                break
        subjects.append({
            "code": code,
            "name": subject_names.get(code, code),
            "credits": cr,
        })

    return {
        "subjects":        subjects,
        "records":         all_records,
        "mark_type":       mark_type,
        "internal_number": internal_number,
        "pages_parsed":    pages_parsed,
        "header_codes":    list(global_col_map.values()),
    }


def _detect_structure(first_page_text: str) -> Dict:
    """Legacy helper kept for backward compat — no longer used in main path."""
    text_upper = first_page_text.upper()
    mark_type = "end_semester" if re.search(
        r'END\s*SEM|SEMESTER\s*EXAM|FINAL\s*EXAM|UNIVERSITY', text_upper
    ) else "internal"
    internal_num = 1
    for _pat in [
        r'CONTINUOUS\s+INTERNAL\s+ASSESSMENT\s*[-\u2013:]*\s*([123])\b',
        r'\bC\.I\.A\.?\s*[-\u2013:]*\s*([123])\b',
        r'\b(?:INTERNAL|TEST|CIA|CT|IA)\b[\s\-\u2013:/]+([123])\b',
    ]:
        _m = re.search(_pat, text_upper)
        if _m:
            internal_num = int(_m.group(1))
            break
    return {"mark_type": mark_type, "internal_number": internal_num}


# ─── CSV mark-sheet parser ────────────────────────────────────────────────────

def _parse_csv_table(file_bytes: bytes) -> Dict:
    """
    Parse a CSV mark sheet and return the same structure as _parse_pdf_table().

    Typical CSV formats handled:

      Format A — single-row header with codes:
        S.No, Roll No, Reg No, Student Name, 21AD101, 21CS101, ...
        1,    24AD001, 7140..., Aarthi V G,  98,      100, ...

      Format B — two-row header (name row + code row):
        ,,,, Engineering Mathematics, Data Science, ...
        S.No, Roll No, Reg No, Student Name, 21AD101, 21CS101, ...
        1,   24AD001, 7140..., Aarthi V G, 98, 100, ...

    Returns the same dict schema as _parse_pdf_table:
      { "subjects", "records", "mark_type", "internal_number",
        "pages_parsed", "header_codes" }
    """
    import csv
    import io

    # Decode bytes — UTF-8 with BOM first, latin-1 fallback
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader  = csv.reader(io.StringIO(text))
    raw_rows = [row for row in reader]
    if not raw_rows:
        return {"error": "CSV file is empty."}

    # ── Detect mark type + internal number from first 10 rows ────────────────
    header_sample = "\n".join(",".join(r) for r in raw_rows[:10]).upper()

    if re.search(r'END\s*SEM|SEMESTER\s*EXAM|FINAL\s*EXAM|UNIVERSITY\s*EXAM', header_sample):
        mark_type = "end_semester"
    else:
        mark_type = "internal"

    internal_number = 1
    for _pat in [
        r'CONTINUOUS\s+INTERNAL\s+ASSESSMENT\s*[-\u2013:]*\s*([123])\b',
        r'\bC\.I\.A\.?\s*[-\u2013:]*\s*([123])\b',
        r'\b(?:INTERNAL|TEST|CIA|CT|IA)\b[\s\-\u2013:/]+([123])\b',
    ]:
        _m = re.search(_pat, header_sample)
        if _m:
            internal_number = int(_m.group(1))
            break

    # ── Find header row: row with the most subject codes ─────────────────────
    best_hdr_idx          = -1
    best_col_map: Dict[int, str] = {}   # column-index → subject_code

    for row_i, row in enumerate(raw_rows):
        col_map: Dict[int, str] = {}
        for col_i, cell in enumerate(row):
            m = _SUBJ_CODE_RE.match(cell.strip().upper())
            if m:
                col_map[col_i] = m.group(1)
        if len(col_map) > len(best_col_map):
            best_col_map = col_map
            best_hdr_idx = row_i

    if best_hdr_idx == -1 or not best_col_map:
        return {"error": (
            "Could not find a subject-code header row in the CSV. "
            "Ensure a row contains subject codes like 21EN101."
        )}

    # ── Extract subject names from the ±2 adjacent rows ──────────────────────
    subject_names: Dict[str, str] = {code: code for code in best_col_map.values()}

    for cand_i in range(max(0, best_hdr_idx - 2), min(len(raw_rows), best_hdr_idx + 3)):
        if cand_i == best_hdr_idx:
            continue
        row = raw_rows[cand_i]

        # Skip title/institution rows
        row_tokens_up = {c.strip().upper() for c in row if c.strip()}
        if row_tokens_up & _TITLE_ROW_MARKERS:
            continue
        # Skip student info rows
        if len(row_tokens_up & _STUDENT_INFO_INDICATORS) >= 2:
            continue
        # Skip data rows
        if any(_is_student_id(c.strip()) for c in row):
            continue

        names_found: Dict[str, str] = {}
        for col_i, code in best_col_map.items():
            if col_i >= len(row):
                continue
            cell_val = row[col_i].strip()
            if not cell_val:
                continue
            tokens = cell_val.split()
            if all(re.fullmatch(r'[\d.,/\-]+', t) for t in tokens):
                continue
            alpha_words = [t for t in tokens if len(re.sub(r'[^A-Za-z]', '', t)) >= 3]
            if not alpha_words:
                continue
            if {w.upper() for w in alpha_words} & _TITLE_ROW_MARKERS:
                continue
            tokens_up = {t.upper().strip('.') for t in tokens}
            if tokens_up <= _SUBJ_NAME_SKIP:
                continue
            name_tokens_up = {t.upper().strip('%.') for t in tokens}
            if name_tokens_up & _SUBJ_NAME_DISQUALIFY:
                continue
            names_found[code] = cell_val

        if len(names_found) >= max(1, len(best_col_map) // 2):
            subject_names.update(names_found)
            break

    # ── Detect student-identifier columns from header row tokens ─────────────
    hdr_row  = raw_rows[best_hdr_idx]
    roll_col: Optional[int] = None
    reg_col:  Optional[int] = None

    for col_i, cell in enumerate(hdr_row):
        tok = cell.strip().upper()
        if roll_col is None and re.search(r'\bROLL\b', tok):
            roll_col = col_i
        if reg_col is None and re.search(r'\bREG\b|\bREGISTRATION\b', tok):
            reg_col = col_i

    # ── Detect sub-column offsets (Max | Mark | Att%) via two-pass stats ──────
    # Some CSVs have per-subject sub-columns; the subject code lands in the
    # "Max" column while marks are one or two columns to the right.
    # Strategy: collect numeric values for col_i..col_i+3 across student rows,
    # then pick the non-constant column whose values fall within max_marks.
    _MAX_SUBCOL_SCAN = 4  # how many columns right of the code header to check

    # Pre-collect student-row values: {col_i: {offset: [values]}}
    from collections import defaultdict as _dd
    _offset_vals: Dict[int, Dict[int, list]] = {ci: _dd(list) for ci in best_col_map}

    for _row_i, _row in enumerate(raw_rows):
        if _row_i == best_hdr_idx:
            continue
        # Only student data rows
        _sid = None
        for _col in (roll_col, reg_col):
            if _col is not None and _col < len(_row):
                _val = _row[_col].strip()
                if _val and re.search(r"\d", _val):
                    _sid = _val
                    break
        if not _sid:
            for _c in _row:
                if _is_student_id(_c.strip()):
                    _sid = _c.strip()
                    break
        if not _sid:
            continue
        for ci in best_col_map:
            for off in range(_MAX_SUBCOL_SCAN):
                idx = ci + off
                if idx >= len(_row):
                    break
                _raw = _row[idx].strip().replace(',', '.')
                if not re.fullmatch(r'\d{1,3}(\.\d{1,2})?', _raw):
                    continue
                try:
                    _offset_vals[ci][off].append(float(_raw))
                except ValueError:
                    pass

    # Per-subject: find best offset using constant/variable classification
    _mark_col_offset: Dict[int, int]   = {}  # col_i → best offset (default 0)
    _max_marks_csv:   Dict[int, float] = {}  # col_i → detected max marks ceiling

    for ci, off_vals in _offset_vals.items():
        # Require ≥2 student rows for reliability
        buckets = {off: vs for off, vs in off_vals.items() if len(vs) >= 2}
        if not buckets:
            _mark_col_offset[ci] = 0
            continue

        def _is_const(vs: list) -> bool:
            top = max(set(vs), key=vs.count)
            return vs.count(top) / len(vs) >= 0.80

        const_offs = {o for o, vs in buckets.items() if _is_const(vs)}
        max_m: Optional[float] = None
        for o in const_offs:
            vs   = buckets[o]
            top  = max(set(vs), key=vs.count)
            if max_m is None or top < max_m:
                max_m = top

        if max_m is not None:
            _max_marks_csv[ci] = max_m

        var_offs = [(o, vs) for o, vs in buckets.items() if o not in const_offs]

        if not var_offs:
            _mark_col_offset[ci] = 0
            continue

        # Prefer variable offsets with values ≤ max_m
        def _within_max(vs, mx):
            if mx is None:
                return True
            return sum(1 for v in vs if v > mx) / len(vs) <= 0.50

        valid = [(o, vs) for o, vs in var_offs if _within_max(vs, max_m)]
        if not valid:
            valid = sorted(var_offs, key=lambda t: t[0])[:1]

        _mark_col_offset[ci] = min(valid, key=lambda t: t[0])[0]

    # ── Extract data rows ─────────────────────────────────────────────────────
    # Known subject codes — used to prevent them being matched as student IDs
    _known_csv_codes: set = {c.upper() for c in best_col_map.values()}

    all_records: list = []

    for row_i, row in enumerate(raw_rows):
        if row_i == best_hdr_idx:
            continue
        if not row:
            continue

        # Locate student identifier
        student_id: Optional[str] = None

        # 1. Try labelled columns first
        for _col in (roll_col, reg_col):
            if _col is not None and _col < len(row):
                val = row[_col].strip()
                if val.upper() in _known_csv_codes:
                    continue    # subject code cell — skip
                if val and re.search(r"\d", val):
                    student_id = val
                    break

        # 2. Scan all cells for a student ID
        if student_id is None:
            for cell in row:
                cs = cell.strip()
                if cs.upper() in _known_csv_codes:
                    continue    # subject code — skip
                if _is_student_id(cs):
                    student_id = cs
                    break

        if not student_id:
            continue

        # Extract marks for every subject column
        for col_i, subj_code in best_col_map.items():
            # Apply sub-column offset: if PDF-style sub-columns exist in the CSV
            # (Max | Mark | Att%), use the statistically-determined offset.
            mark_col = col_i + _mark_col_offset.get(col_i, 0)
            raw_val = row[mark_col].strip() if mark_col < len(row) else ""

            marks:    Optional[float] = None
            is_absent = False
            grade: Optional[str] = None
            grade_points: Optional[float] = None
            result_status: Optional[str] = None
            max_marks = _max_marks_csv.get(col_i)

            if raw_val:
                clean = raw_val.replace(",", ".").strip()
                clean_up = clean.upper()

                grade = _normalize_grade_token(clean_up)
                if grade:
                    if grade == "AB":
                        is_absent = True
                        result_status = "AB"
                    elif grade == "U":
                        result_status = "FAIL"
                    else:
                        result_status = "PASS"
                    grade_points = _GRADE_POINT_MAP.get(grade)
                else:
                    if clean_up in ("AB", "A/B", "ABS", "ABSENT"):
                        is_absent = True
                    elif clean_up in ("NA", "N/A", "-", "--", "—"):
                        marks = None
                    else:
                        num_m = re.search(r"(\d{1,3}(?:\.\d+)?)", clean)
                        if num_m:
                            num_str = num_m.group(1)
                            if (re.fullmatch(r"\d{1,3}\.\d{2,}", num_str)
                                    and "/" not in clean and "%" not in clean):
                                marks = None
                            else:
                                try:
                                    marks = float(num_str)
                                    # If we have a reliable max_marks ceiling and the value
                                    # clearly exceeds it, it is attendance %, not a mark.
                                    _ceil = _max_marks_csv.get(col_i)
                                    if _ceil is not None and marks > _ceil:
                                        marks = None
                                except ValueError:
                                    marks = None

            record = {
                "roll_number":     student_id,
                "subject_code":    subj_code,
                "internal_number": internal_number,
                "marks":           marks,
                "is_absent":       is_absent,
                "type":            mark_type,
            }

            if grade is not None:
                record["grade"] = grade
            if grade_points is not None:
                record["grade_points"] = grade_points
            if result_status is not None:
                record["result_status"] = result_status
            if max_marks is not None:
                record["max_marks"] = max_marks

            all_records.append(record)

    subjects = [
        {"code": code, "name": subject_names.get(code, code), "credits": 3}
        for code in best_col_map.values()
    ]

    return {
        "subjects":        subjects,
        "records":         all_records,
        "mark_type":       mark_type,
        "internal_number": internal_number,
        "pages_parsed":    1,
        "header_codes":    list(best_col_map.values()),
    }


# ─── LLM-powered PDF metadata extractor ──────────────────────────────────────────────────
#
# Strategy: the coordinate parser (_parse_pdf_table) reads EVERY student row
# with zero token-limit constraints.  The LLM only reads the compact header /
# title section (≤2 000 chars) to answer three small questions:
#   1. What type of exam is this?  (internal / end_semester)
#   2. Which internal number?      (1 / 2 / 3)
#   3. What are the full subject names for each code?
#
# Splitting responsibilities this way means 60, 120, or 200 students all work
# correctly — the LLM never sees the data rows.

_PDF_META_PROMPT = """\
You are a college mark-sheet header parser.
I will give you the HEADER SECTION of an academic PDF (title rows + subject rows only).
The text may also include a SUBJECT LEGEND TABLE section that maps subject codes
to their full names and credits — this is the MOST RELIABLE source of subject names.

Return ONLY one JSON object — no markdown, no explanation.

JSON schema:
{{
  "mark_type": "internal",
  "internal_number": 1,
  "subjects": [
    {{"code": "21AD101", "name": "Engineering Mathematics", "credits": 4}}
  ]
}}

Rules:
- mark_type: "end_semester" for university/semester-end exam, otherwise "internal".
- internal_number: the CIA / CT / Test number (1, 2, or 3).
  Look for "CIA 1", "CT-2", "Test 3", "Continuous Internal Assessment 2" etc.
  Default to 1 only if genuinely not mentioned.
  NEVER read digits from inside subject codes (21ECT201 is NOT internal-2).

- subjects: list every subject that a marks column exists for.
  A SUBJECT NAME is the academic course title — e.g. "Engineering Mathematics",
  "Basic Civil Engineering", "Physics", "Programming in C", "Technical English".

  PRIORITY for finding subject names:
    1. SUBJECT LEGEND TABLE: If a section labelled "SUBJECT LEGEND TABLE" is 
       present, use those names — they are extracted directly from the PDF and
       are the most reliable source. Map each code to its name from this table.
    2. SUBJECT NAME ROW: A row just below the subject code row may contain
       full course titles aligned under each code.
    3. If neither is available, use the code itself as the name.

  IMPORTANT: The PDF header typically contains these types of rows:
    1. INSTITUTION ROWS: college name, department name
       e.g. "Department of Artificial Intelligence and Data Science"
       → These are NOT subject names! Never use words from these rows.
    2. EXAM TITLE ROW: "Continuous Internal Assessment 1" etc.
       → Not subject names.
    3. SUBJECT CODE ROW: "21AD101  21CS101  21EN101  21HS201  21MA130  21TA101"
       → These are subject codes.

  NEVER hallucinate or guess subject names from the department/institution name.
  If you cannot find a clear subject name, use the code itself as the name.

  DO NOT include any of the following as subject names:
    • Institution/department words: "Department of", "College", "Engineering"
    • Attendance data: "Attendance Mark", "Attendance %", "Present", "Absent"
    • Aggregate columns: "Total", "Average", "Grand Total", "Result", "Grade"
    • Admin columns: "S.No", "Roll No", "Reg No", "Name"

  Use credits from the sheet if shown, else default to 3.

- Marks rows may contain "AB" or "ABS" meaning absent. These are valid.
- Return ONLY valid JSON. No markdown, no prose.

Header text:
{header_text}

JSON:"""


def _extract_header_text(doc, max_chars: int = 2000) -> str:
    """
    Return the first `max_chars` characters of page-1 text — enough to see
    the exam title and subject header rows without sending data rows to the LLM.
    """
    if doc.page_count == 0:
        return ""
    return doc[0].get_text("text")[:max_chars]


def _llm_parse_pdf(pdf_text: str) -> Dict:
    """
    LEGACY path: ask Ollama to parse the FULL marked sheet.
    Only used when _parse_pdf_table returns no header_codes at all.
    Kept as last-resort fallback but no longer the primary path.
    Raises ValueError if the response is unusable.
    """
    prompt = _PDF_PARSE_PROMPT.format(pdf_text=pdf_text[:10000])
    raw    = _ollama_generate(prompt)
    data   = _safe_parse_json(_clean_json(raw))

    if not isinstance(data.get("subjects"), list) or not isinstance(data.get("records"), list):
        raise ValueError(f"LLM returned unexpected structure: {str(data)[:300]}")
    if not data["subjects"] or not data["records"]:
        raise ValueError("LLM found no subjects or records in the PDF")

    mark_type       = str(data.get("mark_type", "internal")).lower()
    internal_number = int(data.get("internal_number", 1) or 1)
    if internal_number not in (1, 2, 3):
        internal_number = 1

    clean_subjects: list = []
    seen_codes: set = set()
    for s in data["subjects"]:
        code = str(s.get("code", "")).strip().upper()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        try:
            credits = int(s.get("credits") or 3)
        except (ValueError, TypeError):
            credits = 3
        clean_subjects.append({
            "code":    code,
            "name":    str(s.get("name", code)).strip() or code,
            "credits": credits,
        })

    clean_records: list = []
    for r in data["records"]:
        roll = str(r.get("roll_number", "")).strip()
        code = str(r.get("subject_code", "")).strip().upper()
        if not roll or not code:
            continue
        clean_records.append({
            "roll_number":     roll,
            "subject_code":    code,
            "marks":           r.get("marks"),
            "type":            mark_type,
            "internal_number": internal_number,
        })

    return {
        "subjects":        clean_subjects,
        "records":         clean_records,
        "mark_type":       mark_type,
        "internal_number": internal_number,
        "pages_parsed":    pdf_text.count("\f") + 1,
        "header_codes":    [s["code"] for s in clean_subjects],
    }


def _llm_extract_metadata(header_text: str) -> Dict:
    """
    Ask Ollama for mark_type, internal_number, and subject name/credits only.
    Returns a dict: {mark_type, internal_number, subjects: [{code, name, credits}]}
    Returns an empty dict on any failure (caller falls back to regex).
    """
    try:
        prompt = _PDF_META_PROMPT.format(header_text=header_text)
        raw    = _ollama_generate(prompt)
        data   = _safe_parse_json(_clean_json(raw))
    except Exception:
        return {}

    if not isinstance(data.get("subjects"), list):
        return {}

    mark_type = str(data.get("mark_type", "internal")).lower()
    try:
        internal_number = int(data.get("internal_number", 1) or 1)
    except (ValueError, TypeError):
        internal_number = 1
    if internal_number not in (1, 2, 3):
        internal_number = 1

    clean_subjects: list = []
    seen: set = set()
    for s in data.get("subjects", []):
        code = str(s.get("code", "")).strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        try:
            credits = int(s.get("credits") or 3)
        except (ValueError, TypeError):
            credits = 3
        clean_subjects.append({
            "code":    code,
            "name":    str(s.get("name", code)).strip() or code,
            "credits": credits,
        })

    return {
        "mark_type":       mark_type,
        "internal_number": internal_number,
        "subjects":        clean_subjects,
    }


NLPQ_SYSTEM_PROMPT = """
You are an academic data analyst assistant embedded in a college management system.
You answer questions about student marks, subjects, and semester summaries.

When the answer is best shown as a TABLE, respond with this JSON:
{{
  "format": "table",
  "title": "...",
  "columns": ["Col1", "Col2", ...],
  "rows": [["val1", "val2", ...], ...]
}}

When the answer is best as a PARAGRAPH, respond with:
{{
  "format": "paragraph",
  "text": "..."
}}

When the answer requests a CHART/GRAPH/VISUALIZATION, respond with:
{{
  "format": "chart",
  "chart_type": "bar" | "pie" | "line" | "doughnut",
  "title": "...",
  "labels": ["Label1", "Label2", ...],
  "datasets": [
    {{
      "label": "Dataset Name",
      "data": [10, 20, 30, ...]
    }}
  ]
}}

Use ONLY the data provided below. If the answer isn't in the data, say so clearly.
Do not fabricate numbers.
Respond with ONLY the JSON – no markdown, no explanation outside the JSON.

Context — {department} | Batch {batch_year} | {semester_name}
{context_data}
"""

# ─── Code-generation prompt (for _compute_query) ──────────────────────────────

CODE_GEN_PROMPT = """You are a Python analytics expert helping analyse academic data.

You have a list called `data`. Each item is a dict with:
  roll_number   (str)        – student roll number, e.g. "24AD001"
  student_name  (str)        – full student name
  subject_code  (str)        – e.g. "21MA130"
  subject_name  (str)        – e.g. "Engineering Mathematics"
  internal1     (float|None) – CIA 1 marks
  internal2     (float|None) – CIA 2 marks
  internal3     (float|None) – CIA 3 marks
  end_sem_marks (float|None) – End semester exam marks (from SubjectResult, legacy)
  grade         (str|None)   – Letter grade; 'U' = failed

You also have `end_sem_data` — a list of dicts with end semester results (separate table):
  roll_number   (str)
  student_name  (str)
  subject_code  (str)
  subject_name  (str)
  marks         (float|None) – End semester marks
  max_marks     (float|None) – Maximum marks
  grade         (str|None)   – Letter grade
  grade_points  (float|None)
  result_status (str)        – 'PASS', 'FAIL', 'AB', 'WH'

Context: {department} | Batch {batch_year} | {semester_name}
Total internal records: {record_count}
Total end semester records: {end_sem_count}

Important routing rule:
- `data` contains CIA/internal marks only.
- `end_sem_data` contains end semester / university exam results only.
- If the user's query mentions end semester, semester-end, final exam, university exam,
  pass percentage, grade distribution, result status, or "each subject" in the end-semester context,
  use `end_sem_data` and do NOT answer from CIA/internal marks.
- For end-semester chart requests, prefer pass/fail or pass-percentage logic from `end_sem_data`.

Query: "{query}"

Write Python code that processes `data` and/or `end_sem_data` and sets `result` to EXACTLY one of:

  For a TABLE answer:
    result = {{
      "format": "table",
      "title": "...",
      "columns": ["Col1", "Col2"],
      "rows": [["val1", "val2"], ...]
    }}

  For a TEXT answer:
    result = {{
      "format": "paragraph",
      "text": "..."
    }}

  For a CHART/GRAPH/VISUALIZATION answer:
    result = {{
      "format": "chart",
      "chart_type": "bar" | "pie" | "line" | "doughnut",
      "title": "...",
      "labels": ["Label1", "Label2", ...],
      "datasets": [
        {{
          "label": "Dataset Name",
          "data": [10, 20, 30, ...]
        }}
      ]
    }}

STRICT RULES:
- Use ONLY: len, sum, min, max, sorted, enumerate, zip, round, abs, int, float,
  str, list, dict, set, filter, map, range, isinstance, any, all, bool, type
- Do NOT use: import, open, __import__, eval, exec, getattr, setattr, globals, locals
- Always convert row cell values to str (e.g. str(round(v, 2)))
- Skip None values with: if x is not None
- Output ONLY the Python code — no markdown fences, no explanations
- If the query asks for a graph/chart/visualization/plot, use "chart" format
- If the query mentions "graph", "chart", "plot", "visualize", "visualization",
  always use the chart format with the best chart_type for the data
""".strip()


# ─── Core class ───────────────────────────────────────────────────────────────

class AnalyticsAI:
    """
    Singleton-style helper; instantiate once per request.
    Requires Django to be set up before import (import inside view functions is fine).
    """

    def __init__(self, department_id, batch_year: str, semester_number: int, section: Optional[str] = None):
        self.department_id = department_id
        self.batch_year = batch_year
        self.semester_number = semester_number
        self.section = section.strip().upper() if section else None
        self._active_section = self.section

    # ── PDF Parsing ───────────────────────────────────────────────────────────

    def process_pdf(
        self,
        file_bytes: bytes,
        filename: str,
        internal_override: int = None,
        mark_type_override: str = None,
    ) -> Dict:
        """
        Main entry point for PDF uploads.

        Architecture — "Understand First, Extract Second":

          0. FULL DOCUMENT PRE-SCAN — read the ENTIRE PDF to understand
             its structure before extracting any data. Finds subject
             legend/mapping tables (Code → Name → Credits), detects mark
             type, and collects all subject codes from every page.

          1. Run parsers to extract all student records.

          2. Send header + legend text to Ollama for metadata enrichment.

          3. SMART MERGE with priority chain for subject names:
               P1: Document legend tables (highest trust)
               P2: Coordinate parser names (inline header rows)
               P3: LLM names (only fills gaps; guardrailed)

          4. Apply optional mark_type_override, then internal_override.
        """
        import fitz

        # ── Step 0: Full Document Pre-Scan ────────────────────────────────────
        prescan = _full_document_prescan(file_bytes)

        # ── Step 1: Parse student data ────────────────────────────────────────
        vert_parsed = _parse_end_sem_vertical(file_bytes)
        if vert_parsed and vert_parsed.get("records"):
            parsed = vert_parsed
        else:
            parsed = _parse_pdf_table(file_bytes)

        if "error" in parsed:
            return parsed
        if not parsed.get("header_codes"):
            return {"error": (
                "Could not find a subject-code header row in the PDF. "
                "Ensure the PDF contains a row with subject codes like 21EN101."
            )}

        # ── Step 2: LLM metadata enrichment ──────────────────────────────────
        # Send both the header text AND the legend table text to the LLM
        # so it has full context and doesn't need to guess names.
        try:
            llm_context = prescan["header_text"]
            if prescan["legend_text"]:
                llm_context += "\n\n--- SUBJECT LEGEND TABLE ---\n" + prescan["legend_text"]
            meta = _llm_extract_metadata(llm_context)
        except Exception:
            meta = {}

        # ── Step 3: Smart Merge with Priority Chain ───────────────────────────
        # 3a. Use LLM for mark_type and internal_number (good at this)
        if meta:
            parsed["mark_type"]       = meta.get("mark_type",       parsed.get("mark_type",       "internal"))
            parsed["internal_number"] = meta.get("internal_number", parsed.get("internal_number", 1))

        # Also trust prescan's mark_type if it found end_semester indicators
        if prescan["mark_type"] == "end_semester":
            parsed["mark_type"] = "end_semester"

        # 3b. PRIORITY CHAIN for subject names and credits
        #     P1: legend_names (from document's own legend table)
        #     P2: parser_names (from coordinate parser's extraction)
        #     P3: llm_names   (from LLM — only fills gaps)
        legend_names = prescan.get("legend_names", {})
        llm_subject_map = {}
        if meta:
            llm_subject_map = {s["code"]: s for s in meta.get("subjects", [])}

        enriched_subjects = []
        for subj in parsed.get("subjects", []):
            code = subj["code"]
            parser_name = subj.get("name", code)

            # Priority 1: Document legend table — highest trust
            if code in legend_names:
                subj["name"]    = legend_names[code]["name"]
                subj["credits"] = legend_names[code].get("credits", subj.get("credits", 3))
            # Priority 2: Keep parser name if it's a real, clean name
            elif parser_name != code and len(parser_name) >= 4:
                # Even parser names need cleaning (may contain teacher/noise)
                cleaned_parser = _clean_subject_name(parser_name)
                if cleaned_parser and not _is_hallucinated_name(cleaned_parser):
                    subj["name"] = cleaned_parser
                else:
                    subj["name"] = code  # demote to bare code so P3 can try
            # Priority 3: LLM name — only if parser had no name
            if subj.get("name", code) == code and code in llm_subject_map:
                llm_name = llm_subject_map[code].get("name", code)
                llm_clean = _clean_subject_name(llm_name)
                if llm_clean and not _is_hallucinated_name(llm_clean):
                    subj["name"]    = llm_clean
                    subj["credits"] = llm_subject_map[code].get("credits", subj.get("credits", 3))

            enriched_subjects.append(subj)
        parsed["subjects"] = enriched_subjects

        # 3c. Optional UI override for mark type (authoritative)
        if mark_type_override:
            override = str(mark_type_override).strip().lower()
            if override in ("internal", "end_semester"):
                parsed["mark_type"] = override

        # Stamp every record with the determined mark metadata
        int_num   = parsed["internal_number"]
        mark_type = parsed["mark_type"]
        for rec in parsed.get("records", []):
            rec["type"]            = mark_type
            rec["internal_number"] = int_num

        # ── Step 4: user-supplied override wins over everything ──────────────
        if internal_override is not None and int(internal_override) in (1, 2, 3):
            override_int = int(internal_override)
            parsed["internal_number"] = override_int
            for rec in parsed.get("records", []):
                if rec.get("type") != "end_semester":
                    rec["internal_number"] = override_int

        result = self._commit_parsed_data(parsed)
        result["mark_type"]       = parsed.get("mark_type", "internal")
        result["internal_number"] = parsed.get("internal_number", 1)
        result["pages_parsed"]    = parsed.get("pages_parsed", 0)
        if prescan["has_legend"]:
            result["legend_detected"] = True
            result["legend_subjects"] = len(legend_names)
        return result

    # ── CSV import ────────────────────────────────────────────────────────────

    def process_csv(
        self,
        file_bytes: bytes,
        filename: str,
        internal_override: int = None,
        mark_type_override: str = None,
    ) -> Dict:
        """
        Main entry point for CSV mark-sheet uploads.

        Pipeline (mirrors process_pdf hybrid architecture):
          1. Parse the entire CSV with _parse_csv_table — no token limits.
          2. Feed the first 2000 characters to the LLM for smart metadata
             (mark_type, internal_number, full subject names).
          3. Merge LLM metadata into the coordinate parser's result.
          4. Apply user-supplied internal_override on top.
        """
        # ── Step 1: structural CSV parse ──────────────────────────────────────
        parsed = _parse_csv_table(file_bytes)
        if "error" in parsed:
            return parsed
        if not parsed.get("header_codes"):
            return {"error": (
                "Could not find a subject-code header row in the CSV. "
                "Ensure a row contains subject codes like 21EN101."
            )}

        # ── Step 2: LLM metadata from the CSV header text ────────────────────
        try:
            # Decode just enough of the CSV for the LLM
            try:
                header_text = file_bytes.decode("utf-8-sig")[:2000]
            except UnicodeDecodeError:
                header_text = file_bytes.decode("latin-1")[:2000]
            meta = _llm_extract_metadata(header_text)
        except Exception:
            meta = {}

        # ── Step 3: merge LLM metadata ────────────────────────────────────────
        if meta:
            parsed["mark_type"]       = meta.get("mark_type",       parsed.get("mark_type",       "internal"))
            parsed["internal_number"] = meta.get("internal_number", parsed.get("internal_number", 1))

            llm_subject_map = {s["code"]: s for s in meta.get("subjects", [])}
            enriched = []
            for subj in parsed.get("subjects", []):
                code = subj["code"]
                if code in llm_subject_map:
                    subj["name"]    = llm_subject_map[code]["name"]
                    subj["credits"] = llm_subject_map[code]["credits"]
                enriched.append(subj)
            parsed["subjects"] = enriched

            int_num   = parsed["internal_number"]
            mark_type = parsed["mark_type"]
            for rec in parsed.get("records", []):
                rec["type"]            = mark_type
                rec["internal_number"] = int_num

        # ── Step 4: optional mark-type override (wins), then internal override ─
        if mark_type_override:
            override = str(mark_type_override).strip().lower()
            if override in ("internal", "end_semester"):
                parsed["mark_type"] = override
                int_num = parsed.get("internal_number", 1) or 1
                for rec in parsed.get("records", []):
                    rec["type"] = override
                    rec["internal_number"] = int_num

        if internal_override is not None and int(internal_override) in (1, 2, 3):
            override_int = int(internal_override)
            parsed["internal_number"] = override_int
            for rec in parsed.get("records", []):
                if rec.get("type") != "end_semester":
                    rec["internal_number"] = override_int

        result = self._commit_parsed_data(parsed)
        result["mark_type"]       = parsed.get("mark_type", "internal")
        result["internal_number"] = parsed.get("internal_number", 1)
        result["pages_parsed"]    = parsed.get("pages_parsed", 1)
        return result

    def _commit_parsed_data(self, parsed: Dict) -> Dict:
        """Write subjects and results to the database."""
        from students.models import Department, Semester, Subject, SubjectResult, Student, EndSemesterResult

        try:
            department = Department.objects.get(id=self.department_id, is_active=True)
            semester = Semester.objects.get(number=self.semester_number)
        except Exception as e:
            return {"error": f"Department or semester not found: {e}"}

        subjects_existed = []
        subjects_not_found = []  # codes present in document but not in subjects table
        rows_inserted = 0
        rows_skipped = 0
        skip_reasons: Dict[str, int] = {}

        # Pre-load students for THIS department AND THIS batch only.
        # Filtering by batch (academic_year_joining starts with batch_year) is
        # critical — without it, roll numbers from other batches can collide.
        batch_year_str = str(self.batch_year)
        student_pool: Dict[str, Any] = {}
        batch_students = Student.objects.filter(
            department_id=department.id,
            is_active=True,
            academic_year_joining__startswith=batch_year_str,
        )
        for s in batch_students:
            rn = s.roll_number.strip().upper() if s.roll_number else None
            reg = str(s.registration_number).strip().upper() if s.registration_number else None
            if rn:
                student_pool[rn] = s
                student_pool[_normalize_student_key(rn)] = s
            if reg and reg not in ('NONE', 'NULL', ''):
                student_pool[reg] = s
                student_pool[_normalize_student_key(reg)] = s

        # ── Look up subjects (READ-ONLY — subjects must be defined manually) ──
        # The AI engine NEVER creates or modifies subjects from uploaded documents.
        # Subjects must be added by the user via the Subjects tab before uploading
        # mark sheets.  Any subject code present in the document that is not already
        # in the subjects table is recorded in subjects_not_found; all its mark rows
        # are skipped during import.
        subject_map: Dict[str, Subject] = {}

        # Collect every subject code referenced in this document (from the
        # subjects list AND directly from individual records).
        _doc_codes: list = []
        for s in parsed.get("subjects", []):
            code = str(s.get("code", "")).strip().upper()
            if code:
                _doc_codes.append(code)
        for rec in parsed.get("records", []):
            code = str(rec.get("subject_code", "")).strip().upper()
            if code and code not in _doc_codes:
                _doc_codes.append(code)

        # Deduplicate while preserving order, then look each one up.
        for code in dict.fromkeys(_doc_codes):
            obj = Subject.objects.filter(
                code=code, department=department, semester=semester
            ).first()
            if obj:
                subjects_existed.append(code)
                subject_map[code] = obj
            else:
                subjects_not_found.append(code)

        # ── Write marks ────────────────────────────────────────────────────────
        for rec in parsed.get("records", []):
            roll_raw = str(rec.get("roll_number", "")).strip()
            roll = roll_raw.upper()
            code = str(rec.get("subject_code", "")).strip().upper()
            marks_raw = rec.get("marks")

            if not roll or not code:
                skip_reasons["missing roll/code"] = skip_reasons.get("missing roll/code", 0) + 1
                rows_skipped += 1
                continue

            # Determine internal number + type
            rec_type = str(rec.get("type", "internal")).lower()
            try:
                internal_num = int(rec.get("internal_number", 1) or 1)
            except (ValueError, TypeError):
                internal_num = 1

            # Subject lookup
            subject = subject_map.get(code) or Subject.objects.filter(
                code=code, department=department, semester=semester
            ).first()
            if not subject:
                skip_reasons[f"subject {code} not found"] = skip_reasons.get(f"subject {code} not found", 0) + 1
                rows_skipped += 1
                continue

            # Student lookup — EXACT matching only.
            # Tier 1: exact roll number or registration number (upper-cased).
            # Tier 2: roll number stripped of all spaces (handles "24 AD 001" → "24AD001").
            # We do NOT do name-based fuzzy matching — mark sheets always carry
            # numeric identifiers and fuzzy name matching causes silent wrong assignments.
            roll_norm = _normalize_student_key(roll_raw)

            # Sanity-check: reject pure serial numbers (1, 2, 3 … 99) that the
            # LLM mistakenly extracted from the S.No column.
            if re.fullmatch(r'\d{1,3}', roll_norm):
                skip_reasons["serial number ignored"] = skip_reasons.get("serial number ignored", 0) + 1
                rows_skipped += 1
                continue

            student = student_pool.get(roll)                  # exact
            if student is None:
                student = student_pool.get(roll_norm)         # spaces stripped
            if student is None:
                skip_reasons[f"{roll_raw} not found in batch {batch_year_str}"] = (
                    skip_reasons.get(f"{roll_raw} not found in batch {batch_year_str}", 0) + 1
                )
                rows_skipped += 1
                continue

            # Parse marks value
            # is_absent can come from the parser (is_absent key) or be inferred
            # from marks_raw itself when the LLM / CSV path passes the raw string
            # (e.g. "AB", "ab", "ABS", "ABSENT", "A/B").
            _marks_str = str(marks_raw).strip().upper() if marks_raw is not None else ''
            is_absent = bool(rec.get("is_absent")) or _marks_str in ('AB', 'A/B', 'ABS', 'ABSENT')
            try:
                marks = Decimal(str(marks_raw)) if (marks_raw is not None and not is_absent) else None
            except InvalidOperation:
                marks = None

            # Skip records that have neither a numeric mark nor an AB flag
            # AND no grade/GP (for end-sem records that may only have grade info).
            has_grade_info = bool(rec.get("grade") or rec.get("grade_points") or rec.get("result_status"))
            if marks is None and not is_absent and not has_grade_info:
                skip_reasons["no mark (empty cell)"] = skip_reasons.get("no mark (empty cell)", 0) + 1
                rows_skipped += 1
                continue

            if rec_type == "end_semester":
                # ── Route end-semester marks to the dedicated EndSemesterResult table ──
                end_result, _ = EndSemesterResult.objects.get_or_create(
                    student=student, subject=subject
                )
                if marks is not None:
                    end_result.marks = marks
                elif is_absent:
                    end_result.marks = None
                # Try to get max_marks from the record if available
                max_marks_raw = rec.get("max_marks")
                if max_marks_raw is not None:
                    try:
                        end_result.max_marks = Decimal(str(max_marks_raw))
                    except (InvalidOperation, ValueError):
                        pass
                # Set grade if available
                grade_raw = rec.get("grade")
                if grade_raw:
                    end_result.grade = str(grade_raw).strip()
                # Set grade points if available
                gp_raw = rec.get("grade_points")
                if gp_raw is not None:
                    try:
                        end_result.grade_points = Decimal(str(gp_raw))
                    except (InvalidOperation, ValueError):
                        pass
                # Set result status
                result_status_raw = rec.get("result_status", "")
                if result_status_raw:
                    end_result.result_status = str(result_status_raw).strip().upper()
                elif is_absent:
                    end_result.result_status = "AB"
                elif end_result.grade and end_result.grade.upper() == "U":
                    end_result.result_status = "FAIL"
                elif marks is not None:
                    end_result.result_status = "PASS"
                end_result.save()
                rows_inserted += 1
            else:
                result, _ = SubjectResult.objects.get_or_create(
                    student=student, subject=subject
                )

                if internal_num == 1:
                    result.internal1 = marks
                    result.internal1_absent = is_absent
                elif internal_num == 2:
                    result.internal2 = marks
                    result.internal2_absent = is_absent
                elif internal_num == 3:
                    result.internal3 = marks
                    result.internal3_absent = is_absent
                else:
                    result.internal1 = marks
                    result.internal1_absent = is_absent

                result.save()
                rows_inserted += 1

        # Build summary
        summary_parts = []
        if subjects_not_found:
            summary_parts.append(
                f"{len(subjects_not_found)} subject code(s) from the document were not found "
                f"in the subjects table and were skipped: {', '.join(subjects_not_found)}. "
                f"Please add them manually via the Subjects tab first."
            )
        if subjects_existed:
            summary_parts.append(f"{len(subjects_existed)} subject(s) already existed")
        summary_parts.append(f"Inserted/updated {rows_inserted} mark record(s)")
        if rows_skipped:
            reasons_str = "; ".join(f"{v}× {k}" for k, v in skip_reasons.items())
            summary_parts.append(f"{rows_skipped} skipped ({reasons_str})")

        # Debug: show first 8 LLM-extracted rolls and a DB sample for this batch
        llm_rolls = list(dict.fromkeys(
            str(r.get("roll_number", "")).strip() for r in parsed.get("records", [])
        ))[:8]
        db_sample = list(dict.fromkeys(
            f"{s.roll_number}|{s.registration_number}"
            for s in batch_students[:5]
        ))

        # ── Auto-update ProgramSemester status based on what was uploaded ──────
        if rows_inserted > 0:
            self._update_semester_status(
                mark_type=parsed.get("mark_type", "internal"),
                semester_number=self.semester_number,
                batch_year=self.batch_year,
            )

        return {
            "subjects_created": [],          # always empty — AI never creates subjects
            "subjects_not_found": subjects_not_found,
            "subjects_existed": subjects_existed,
            "rows_inserted": rows_inserted,
            "rows_skipped": rows_skipped,
            "skip_reasons": skip_reasons,
            "summary": ". ".join(summary_parts) + ".",
            "_debug": {
                "llm_extracted_rolls": llm_rolls,
                "db_sample": db_sample,
                "student_pool_size": len(student_pool),
                "records_count": len(parsed.get("records", [])),
            },
        }

    # ── Semester status management ──────────────────────────────────────────

    @staticmethod
    def _update_semester_status(mark_type: str, semester_number: int, batch_year: str) -> None:
        """
        Automatically advance ProgramSemester status flags after a successful upload.

        Rules
        -----
        Internal marks uploaded (CIA 1/2/3)
          • Current semester's ProgramSemester: 'upcoming' → 'active'
          • All higher semesters: stay 'upcoming'

        End-semester results uploaded
          • Current semester's ProgramSemester: any → 'completed'
          • Next semester (N+1) for the same batch: 'upcoming' → 'active'
          • All still-higher semesters: stay 'upcoming'
        """
        from students.models import ProgramSemester

        try:
            current_ps = ProgramSemester.objects.get(
                semester_id=semester_number,
                batch_year=batch_year,
            )
        except ProgramSemester.DoesNotExist:
            return  # No ProgramSemester entry yet — nothing to update

        if mark_type == "end_semester":
            # Mark this semester as completed
            if current_ps.status != 'completed':
                current_ps.status = 'completed'
                current_ps.save(update_fields=['status'])

            # Activate the next semester for this batch (if it exists + upcoming)
            next_ps = ProgramSemester.objects.filter(
                semester_id=semester_number + 1,
                batch_year=batch_year,
            ).first()
            if next_ps and next_ps.status == 'upcoming':
                next_ps.status = 'active'
                next_ps.save(update_fields=['status'])

        else:
            # Internal marks — just activate the current semester if still upcoming
            if current_ps.status == 'upcoming':
                current_ps.status = 'active'
                current_ps.save(update_fields=['status'])

    # ── Marks Mutation (chatbot-driven) ──────────────────────────────────────

    # Field aliases understood in natural language
    _FIELD_ALIASES = {
        'internal1': ['internal 1', 'internal1', 'cia1', 'cia 1', 'ia1', 'ia 1', 'test 1', 'ct1', 'ct 1', 'i1'],
        'internal2': ['internal 2', 'internal2', 'cia2', 'cia 2', 'ia2', 'ia 2', 'test 2', 'ct2', 'ct 2', 'i2'],
        'internal3': ['internal 3', 'internal3', 'cia3', 'cia 3', 'ia3', 'ia 3', 'test 3', 'ct3', 'ct 3', 'i3'],
        'end_sem_marks': ['end sem', 'end semester', 'endsem', 'university', 'final', 'sem exam', 'ese'],
        'grade': ['grade'],
        'grade_points': ['grade points', 'grade point', 'gp'],
    }

    def _resolve_field(self, text: str) -> Optional[str]:
        """Return DB field name for a human-readable mark field description."""
        t = text.lower().strip()
        for field, aliases in self._FIELD_ALIASES.items():
            for alias in aliases:
                if alias in t:
                    return field
        return None

    def mutate_marks(self, query: str) -> Dict:
        """
        Parse a natural-language mutation command and execute it.

        Supported patterns (case-insensitive):
          • Update <student_id> <subject_code> internal <N> to <value>
          • Set <field> of <student_id> for <subject> to <value>
          • Delete marks of <student_id> for <subject>
          • Clear internal <N> marks for <subject> → applies to ALL students
          • Set grade of <student_id> <subject> to A+

        Returns { "action": str, "affected": int, "detail": str }
        """
        from students.models import Department, Semester, Subject, SubjectResult, Student
        from decimal import Decimal, InvalidOperation

        try:
            department = Department.objects.get(id=self.department_id, is_active=True)
            semester   = Semester.objects.get(number=self.semester_number)
        except Exception as e:
            return {"error": f"Department/semester not found: {e}"}

        # ── Build pools ───────────────────────────────────────────────────────
        student_pool: Dict[str, Any] = {}
        for s in Student.objects.filter(department_id=department.id, is_active=True):
            if s.roll_number:
                student_pool[s.roll_number.strip().upper()] = s
            if s.registration_number:
                student_pool[str(s.registration_number).strip().upper()] = s
            if s.student_name:
                name_key = re.sub(r'[^a-z0-9]', '', s.student_name.lower())
                student_pool[name_key] = s

        subjects = {
            sub.code: sub
            for sub in Subject.objects.filter(
                department=department, semester=semester
            )
        }

        # ── Use LLM to extract intent + entities ──────────────────────────────
        entity_prompt = f"""Extract the intent and entities from this marks database command.
Available subjects: {', '.join(subjects.keys())}

OUTPUT ONLY JSON. Format:
{{"action":"update"|"delete","student_id":"<id or ALL>","subject_code":"<code or ALL>","field":"<internal1|internal2|internal3|end_sem_marks|grade|grade_points or null>","value":"<new value or null>"}}

- "student_id": the registration number, roll number, or student name mentioned. Use "ALL" if command applies to all students.
- "subject_code": subject code from the list. Use "ALL" if all subjects.
- "field": which mark column to change.
- "value": the new value (string). null for delete actions.

Command: {query}
JSON:"""

        try:
            raw = _ollama_generate(entity_prompt)
            entities = _safe_parse_json(_clean_json(raw))
        except Exception:
            # Fallback: pure regex parsing
            entities = self._regex_parse_mutation(query, subjects)

        action       = str(entities.get('action', 'update')).lower()
        student_id   = str(entities.get('student_id', '')).strip()
        subject_code = str(entities.get('subject_code', '')).strip().upper()
        field_raw    = str(entities.get('field', '') or '')
        new_value    = entities.get('value')

        # ── Resolve field name ────────────────────────────────────────────────
        field = field_raw if field_raw in (
            'internal1', 'internal2', 'internal3',
            'end_sem_marks', 'grade', 'grade_points'
        ) else self._resolve_field(field_raw)

        # Override: if action is delete and no field, delete the whole row
        delete_row = (action == 'delete' and not field)

        # ── Resolve student(s) ────────────────────────────────────────────────
        target_students: list = []
        if student_id.upper() == 'ALL':
            target_students = list(Student.objects.filter(
                department_id=department.id, is_active=True
            ))
        else:
            s = student_pool.get(student_id.upper())
            if s is None:
                # try normalised name lookup
                nk = re.sub(r'[^a-z0-9]', '', student_id.lower())
                s  = student_pool.get(nk)
            if s:
                target_students = [s]
            else:
                return {"error": f"Student '{student_id}' not found in {department.name}."}

        # ── Resolve subject(s) ────────────────────────────────────────────────
        target_subjects: list = []
        if subject_code == 'ALL' or not subject_code:
            target_subjects = list(subjects.values())
        else:
            sub = subjects.get(subject_code)
            if not sub:
                # fuzzy: partial match
                matches = [s for c, s in subjects.items() if subject_code in c]
                if matches:
                    target_subjects = matches[:1]
                else:
                    return {"error": f"Subject '{subject_code}' not found for semester {self.semester_number}."}
            else:
                target_subjects = [sub]

        # ── Execute ───────────────────────────────────────────────────────────
        affected = 0
        detail_rows: list[str] = []

        for student in target_students:
            for subject in target_subjects:
                try:
                    result_obj = SubjectResult.objects.get(
                        student=student, subject=subject
                    )
                except SubjectResult.DoesNotExist:
                    if action == 'delete':
                        continue
                    result_obj = SubjectResult(student=student, subject=subject)

                if delete_row:
                    result_obj.delete()
                    detail_rows.append(
                        f"{student.roll_number} / {subject.code} → deleted"
                    )
                    affected += 1
                elif field:
                    old_val = getattr(result_obj, field, None)
                    if field in ('internal1', 'internal2', 'internal3',
                                 'end_sem_marks', 'grade_points'):
                        if new_value in ('', None, 'null', 'none'):
                            setattr(result_obj, field, None)
                        else:
                            try:
                                setattr(result_obj, field, Decimal(str(new_value)))
                            except InvalidOperation:
                                return {"error": f"'{new_value}' is not a valid number."}
                        if field in ('internal1', 'internal2', 'internal3'):
                            absent_field = f"{field}_absent"
                            val_up = str(new_value).strip().upper() if new_value is not None else ''
                            if val_up in ('AB', 'A/B', 'ABS', 'ABSENT'):
                                setattr(result_obj, field, None)
                                setattr(result_obj, absent_field, True)
                            else:
                                setattr(result_obj, absent_field, False)
                    elif field == 'grade':
                        setattr(result_obj, field,
                                str(new_value).strip().upper() if new_value else None)
                    result_obj.save()
                    new_display = getattr(result_obj, field, None)
                    detail_rows.append(
                        f"{student.roll_number} / {subject.code} "
                        f"{field}: {old_val} → {new_display}"
                    )
                    affected += 1
                else:
                    return {"error": "Could not determine which field to update. "
                            "Try: 'set internal 1 of <student> for <subject> to <value>'"}

        if affected == 0:
            return {"error": "No matching records found to modify."}

        summary = (
            f"{'Deleted' if delete_row else 'Updated'} {affected} record(s).\n"
            + "\n".join(detail_rows[:10])
            + ("\n…and more." if len(detail_rows) > 10 else "")
        )
        return {"action": action, "affected": affected, "detail": summary}

    def _regex_parse_mutation(self, query: str, subjects: dict) -> dict:
        """Pure-regex fallback when LLM entity extraction fails."""
        q = query.lower()
        action = 'delete' if re.search(r'\bdelete\b|\bclear\b|\bremove\b', q) else 'update'

        # Extract subject code
        subject_code = 'ALL'
        for code in subjects:
            if code.lower() in q:
                subject_code = code
                break

        # Extract student ID (12-digit reg or roll like 24AD001)
        m = re.search(r'\b(7\d{11}|\d{2}[a-z]{2,5}\d{3,4})\b', q, re.IGNORECASE)
        student_id = m.group(1).upper() if m else 'ALL'

        # Extract field
        field = None
        for f, aliases in self._FIELD_ALIASES.items():
            if any(a in q for a in aliases):
                field = f
                break

        # Extract value
        m_val = re.search(r'\bto\s+([\d.]+|[oabcua][+]?)\b', q, re.IGNORECASE)
        value = m_val.group(1) if m_val else None

        return {
            'action': action, 'student_id': student_id,
            'subject_code': subject_code, 'field': field, 'value': value,
        }

    # ── NLPQ ──────────────────────────────────────────────────────────────────

    def answer_query(self, query: str, history: list = None) -> Dict:
        """
        Answer any natural language question about the current semester/batch.

        Architecture (priority order):
          0. _resolve_references — expand pronouns/refs using conversation history
          1. _try_direct_query   — 15 deterministic ORM handlers (100% accurate)
          2. _compute_query      — LLM writes Python code → executed against real DB data
                                    (LLM generates logic NOT data; always accurate)
        """
        self._history = history or []

        # ── Resolve references from conversation history ──────────────────────
        resolved = self._resolve_references(query)

        # Apply section context from query or UI filter
        self._active_section = (
            self._resolve_section_from_query(resolved)
            or self.section
        )

        # ── Fast path: deterministic direct handlers ──────────────────────────
        direct = self._try_direct_query(resolved)
        if direct is not None:
            return direct

        # ── Compute engine: code-gen + safe exec ─────────────────────────────
        return self._compute_query(resolved)

    def _resolve_references(self, query: str) -> str:
        """
        Expand vague references ("it", "them", "those students", "that subject",
        "the same", "previous", "more details") using recent conversation history.

        If the query is self-contained (has specific subjects/names/actions),
        return it unchanged.  Otherwise, ask the LLM to rewrite the query
        using conversation context.
        """
        if not self._history:
            return query

        ql = query.lower().strip()

        # Preserve chart intent; don't rewrite visual requests
        if re.search(
            r"\bgraph\b|\bgraphical\b|\bchart\b|\bplot\b|\bvisual\b|\bvisuali[sz]e?\b"
            r"|\bvisuali[sz]ation\b|\bpictorial\b",
            ql,
        ):
            return query

        # Check if query contains vague references that need resolution
        _REFERENCE_PATTERNS = re.compile(
            r'\b(it|its|they|them|their|those|that|these|this|the same|same)\b'
            r'|\b(previous|above|before|earlier|last|again)\b'
            r'|\b(more|details|elaborate|explain|why|how come|what about)\b'
            r'|\b(also|too|as well|similarly|and what)\b'
            r'|^(yes|no|ok|sure|yeah|now|but|so|and)\b',
            re.IGNORECASE
        )

        # If query is explicit enough (has subject codes, roll numbers, specific
        # action verbs with objects), skip resolution
        has_subject_code = self._SUBJECT_CODE_RE.search(query)
        is_long_enough   = len(ql.split()) > 8
        has_reference    = _REFERENCE_PATTERNS.search(ql)

        if not has_reference and (has_subject_code or is_long_enough):
            return query

        # Build compact history context (last 6 entries max)
        recent = self._history[-6:]
        history_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content'][:300]}"
            for h in recent if h.get('content')
        )

        if not history_text.strip():
            return query

        resolve_prompt = (
            "You are a query rewriter for an academic analytics chatbot.\n"
            "Given the conversation history and the user's latest message, "
            "rewrite the latest message as a COMPLETE, SELF-CONTAINED query "
            "that includes all necessary context (subject names, student names, "
            "actions, etc.) from the conversation history.\n\n"
            "RULES:\n"
            "- If the message is already self-contained, return it as-is\n"
            "- Replace pronouns (it, them, those, etc.) with the actual entities\n"
            "- Keep the same intent and tone\n"
            "- Output ONLY the rewritten query, nothing else\n"
            "- Do NOT add explanations or prefixes\n\n"
            f"Conversation history:\n{history_text}\n\n"
            f"Latest message: {query}\n\n"
            "Rewritten query:"
        )

        try:
            resolved = _ollama_generate(resolve_prompt).strip()
            # Sanity: if LLM returned something too long or empty, keep original
            if resolved and len(resolved) < len(query) * 5 and len(resolved) > 2:
                # Strip quotes if LLM wrapped the output
                resolved = resolved.strip('"\' ')
                return resolved
        except Exception:
            pass  # LLM unavailable — use original query

        return query

    # ── Direct query engine ───────────────────────────────────────────────────

    _SUBJECT_CODE_RE = re.compile(r'\b(\d{0,2}[A-Z]{2,4}\d{3,}[A-Z0-9]*)\b', re.IGNORECASE)
    _THRESHOLD_RE    = re.compile(
        r'(?P<op>less\s+than|below|under|more\s+than|above|over|equal\s+to|equals?|scoring\s+below|scoring\s+above|scored\s+below|scored\s+above|at\s+least|at\s+most)\s+(?P<val>\d+(?:\.\d+)?)',
        re.IGNORECASE,
    )
    _INTERNAL_RE     = re.compile(
        r'(?P<ord>[123])(?:st|nd|rd)\s+(?:cia|internal|ia|ct|test)'  # "2nd CIA", "1st internal"
        r'|internal\s*(?P<n>[123])'                                    # "internal 2"
        r'|cia\s*(?P<n2>[123])'                                        # "cia2"
        r'|ia\s*(?P<n3>[123])'                                         # "ia2"
        r'|(?:cia|internal|ia|ct|test)\s+(?P<n5>[123])'               # "CIA 2", "test 3"
        r'|i(?P<n4>[123])\b',                                          # "i2"
        re.IGNORECASE,
    )
    _END_SEM_RE      = re.compile(r'end\s*sem|end\s*semester|endsem|university\s*exam|final\s*exam', re.IGNORECASE)

    @classmethod
    def _dq_prefers_end_semester(cls, query: str) -> bool:
        """Return True when the query is explicitly about end-semester results."""
        ql = query.lower()
        return bool(
            cls._END_SEM_RE.search(query)
            or re.search(r'\bsemester\s*end\b|\bsemester-end\b|\bresult\s+status\b', ql)
            or re.search(r'\bpass\s+percentage\b|\bpass\s+rate\b', ql)
        )

    # ── Direct query engine ── shared helpers ─────────────────────────────────

    def _dq_load_context(self):
        """Load department + semester ORM objects; returns (dept, sem) or raises."""
        from students.models import Department, Semester
        department = Department.objects.get(id=self.department_id, is_active=True)
        semester   = Semester.objects.get(number=self.semester_number)
        return department, semester

    def _dq_resolve_subject(self, q: str, department, semester):
        """
        Resolve a subject from a query string.
        Returns (subject_or_None, error_str_or_None).
        None subject means "all subjects in this semester".
        """
        from students.models import Subject
        code_match = self._SUBJECT_CODE_RE.search(q)
        if code_match:
            code = code_match.group(1).upper()
            sub = Subject.objects.filter(
                code__iexact=code, department=department, semester=semester
            ).first()
            if sub is not None:
                return sub, None
            # Not a known subject — check if this token is actually a student roll number.
            from students.models import Student
            if Student.objects.filter(roll_number__iexact=code).exists():
                return None, None   # it's a roll number; fall through to student lookup
            return None, f"Subject '{code}' not found in {department.name} Semester {semester.number}."
        # Keyword match against subject names
        all_subs = list(Subject.objects.filter(department=department, semester=semester))
        ql = q.lower()
        best, best_len = None, 0
        for sub in all_subs:
            stems = set(re.findall(r'[a-z]+', sub.name.lower()))
            stems |= {w[:4] for w in stems}
            for stem in stems:
                if len(stem) >= 3 and stem in ql and len(stem) > best_len:
                    best, best_len = sub, len(stem)
        return best, None  # best may be None → all subjects

    def _dq_parse_field(self, q: str) -> str:
        """Parse mark field from query text. Returns DB field name."""
        ql = q.lower()
        int_m = self._INTERNAL_RE.search(q)
        if int_m:
            n = (int_m.group('ord') or int_m.group('n') or int_m.group('n2')
                 or int_m.group('n3') or int_m.group('n4') or int_m.group('n5'))
            return f"internal{n}"
        word_m = re.search(
            r"\b(first|second|third)\b\s*(?:cia|internal|ia|ct|test)\b"
            r"|\b(?:cia|internal|ia|ct|test)\s*(first|second|third)\b",
            ql,
        )
        if word_m:
            word = (word_m.group(1) or word_m.group(2) or "").lower()
            return {"first": "internal1", "second": "internal2", "third": "internal3"}.get(word, "internal1")
        if self._END_SEM_RE.search(q):
            return "end_sem_marks"
        return "internal1"

    @staticmethod
    def _dq_field_label(field: str) -> str:
        return f"Internal {field[-1]}" if field.startswith("internal") else "End Sem Marks"

    @staticmethod
    def _resolve_section_from_query(query: str) -> Optional[str]:
        ql = query.lower()
        m = re.search(r"\bsection\s*([a-z])\b", ql)
        if not m:
            m = re.search(r"\b([a-z])\s*section\b", ql)
        if not m:
            m = re.search(r"\bsec\s*([a-z])\b", ql)
        return m.group(1).upper() if m else None

    def _dq_base_qs(self, department, semester, subject=None):
        """Base SubjectResult queryset for this batch/dept/semester."""
        from students.models import SubjectResult
        qs = SubjectResult.objects.filter(
            student__academic_year_joining=self.batch_year,
            student__department_id=department.id,
            student__is_active=True,
            subject__semester=semester,
        )
        if self._active_section:
            qs = qs.filter(student__section=self._active_section)
        if subject:
            qs = qs.filter(subject=subject)
        return qs

    def _dq_no_data_msg(self, department) -> str:
        from students.models import SubjectResult, EndSemesterResult
        has_internals = SubjectResult.objects.filter(
            student__academic_year_joining=self.batch_year,
            student__department_id=department.id,
        ).exists()
        has_end_sem = EndSemesterResult.objects.filter(
            student__academic_year_joining=self.batch_year,
            student__department_id=department.id,
        ).exists()
        if not has_internals and not has_end_sem:
            return " No marks have been uploaded yet."
        return ""

    # ── Intent router ─────────────────────────────────────────────────────────

    def _try_direct_query(self, query: str) -> Optional[Dict]:
        """
        Route query to the right deterministic ORM handler (no LLM, 100% accurate).
        Returns a result dict, or None to fall through to _compute_query.

        Handled intents:
          1.  failed / arrears / grade U
          2.  top N / bottom N / class topper / highest / lowest
          3.  average / mean
          4.  how many / count
          5.  pass rate / fail rate / pass percentage
          6.  chart / graph / visualization  ← checked BEFORE generic show/list
          7.  all marks for a subject (list/show)
          8.  marks of a specific student
          9.  stats / statistics / summary / overview
         10.  threshold filter: below/above X
         11.  grade distribution
         12.  improvement / drop between CIA rounds
         13.  percentile / quartile
         14.  at-risk students (failing in multiple subjects)
         15.  distribution stats: median / std deviation / variance
        """
        q  = query.strip()
        ql = q.lower()

        # 0. Chart / graph / visualization requests
        #    Must come BEFORE other handlers so visual requests always render charts
        if re.search(
            r'\bgraph\b|\bgraphical\b|\bchart\b|\bplot\b|\bvisual\b|\bvisuali[sz]e?\b|\bvisuali[sz]ation\b'
            r'|\bpictorial\b|\bvisual\s+analytics\b'
            r'|\bbar\s*(?:chart|graph)\b|\bpie\s*(?:chart|graph)\b'
            r'|\bline\s*(?:chart|graph)\b|\bdoughnut\b',
            ql
        ):
            if self._dq_prefers_end_semester(q):
                return None
            result = self._dq_chart(q)
            if result is not None:
                return result  # chart resolved; else fall through

        # 1. Failed / arrears
        if re.search(r'\bfailed\b|\barrears?\b|\bu\s*grade\b|\bflunked\b', ql):
            return self._dq_failed(q)

        # 2. Top / bottom / rank / topper / highest / lowest
        # Note: "top N%" is a percentile query → handled by check #12; exclude it here
        if re.search(
            r'\btop\s+\d+\b(?!\s*%)|\bbottom\s+\d+\b(?!\s*%)|\bclass\s+topper\b|\btopper\b'
            r'|\brank\b|\bhighest\s+scor|\blowest\s+scor|\bbest\s+student'
            r'|\bwho\s+scored\s+(?:the\s+)?(?:highest|most|lowest|least)\b',
            ql
        ):
            return self._dq_top_n(q)

        # 3. Average / mean
        if re.search(r'\baverage\b|\bmean\b|\bavg\b', ql):
            return self._dq_average(q)

        # 4. How many / count
        if re.search(r'\bhow\s+many\b|\bcount\s+of\b|\bnumber\s+of\s+students\b', ql):
            return self._dq_count(q)

        # 5. Pass / fail rate
        if re.search(
            r'\bpass\s*(?:rate|percent|%|count|ing|ed)\b'
            r'|\bfail\s*(?:rate|percent|%|count)\b'
            r'|\bpass\s+percentage\b|\bpassing\s+rate\b',
            ql
        ):
            return self._dq_pass_fail_stats(q)

        # 7. All marks for a subject (must come before student-marks check)
        #    "show marks for 21MA130" / "list all marks for maths"
        if re.search(r'\blist\b|\bshow\b|\bdisplay\b|\ball\s+marks\b|\bfull\s+marks\b'
                     r'|\bmarks?\s+for\b|\bmarks?\s+of\b', ql):
            if re.search(r'\bmark|\bscore|\bresult', ql) and not self._THRESHOLD_RE.search(ql):
                result = self._dq_all_marks(q)
                if result is not None:
                    return result  # subject resolved → return; else fall to student lookup

        # 8. Marks of a specific student
        if re.search(
            r'\bmarks?\s+(?:of|for)\b|\bscores?\s+(?:of|for)\b'
            r'|\bshow\s+marks\b|\bmark\s*sheet\b|\bresult\s+of\b',
            ql
        ) or (
            re.search(r'\broll\s*number\b|\breg(?:istration)?\s*number\b|\bstudent\b', ql)
            and re.search(r'\b7\d{11,12}\b|\b\d{2,4}[a-z]{2,5}\d{3,4}\b', ql)
        ):
            return self._dq_student_marks(q)

        # 9. Stats / summary / overview
        if re.search(
            r'\bstats?\b|\bstatistics\b|\bsummary\b|\bsummarise\b|\bsummarize\b'
            r'|\boverview\b|\bperformance\s+(?:of|in|summary)\b',
            ql
        ):
            return self._dq_subject_stats(q)

        # 10. Threshold filter — students below/above X
        # 10a. Compound multi-field: "less than 50 in BOTH CIA 1 and CIA 2"
        if self._MULTI_FIELD_BOTH_RE.search(ql) and self._THRESHOLD_RE.search(ql):
            result = self._dq_filter_multi(q)
            if result is not None:
                return result

        # 10b. Single-field threshold — skip compound "and" queries (fall to compute engine)
        threshold_matches = self._THRESHOLD_RE.findall(ql)
        if len(threshold_matches) == 1 and not re.search(r'\band\b.*\b(?:below|above|less|more|under|over)\b', ql):
            return self._dq_filter(q)

        # 11. Grade distribution
        if re.search(
            r'\bgrade\s+(?:distribution|breakdown|split|count)\b'
            r'|\bdistribution\s+of\s+grades?\b'
            r'|\bhow\s+many.*(?:got|scored|have)\s+(?:grade\s+)?[oabcdu][+]?\b'
            r'|\bgrade\s+wise\b|\bgradewise\b',
            ql
        ):
            return self._dq_grade_distribution(q)

        # 12. CIA improvement / drop / performance change
        if re.search(
            r'\bimproved?\b|\bdrop(?:ped)?\b|\bdecline[d]?\b'
            r'|\bperformance\s+change\b|\bcia\s*[123]\s*(?:to|vs|and)\s*cia\s*[123]\b'
            r'|\binternal\s*[123]\s*(?:to|vs|and)\s*internal\s*[123]\b'
            r'|\bbetter\s+in\s+cia\b|\bworse\s+in\s+cia\b',
            ql
        ):
            return self._dq_improvement(q)

        # 13. Percentile / quartile
        if re.search(
            r'\bpercentile\b|\bquartile\b|\btop\s+\d+\s*%\b|\bbottom\s+\d+\s*%\b',
            ql
        ):
            return self._dq_percentile(q)

        # 14. At-risk students (failing in multiple subjects)
        if re.search(
            r'\bat.?risk\b|\bfailing\s+(?:in\s+)?multiple\b|\bmultiple\s+(?:subjects?|fail)\b'
            r'|\bback\s+log\b|\bbacklog\b|\bdetained\b',
            ql
        ):
            return self._dq_at_risk(q)

        # 15. Distribution stats: median / std dev / variance
        if re.search(
            r'\bmedian\b|\bstd\.?\s*dev|\bstandard\s+deviation\b'
            r'|\bvariance\b|\bdispersion\b|\bspread\b|\bskew',
            ql
        ):
            return self._dq_distribution_stats(q)

        return None  # fall through to _compute_query

    # ── Handler 1b: multi-field filter (both CIA 1 and 2) ────────────────────

    # Detects CIA/internal numbers in a query — used by _dq_filter_multi
    _MULTI_FIELD_BOTH_RE = re.compile(
        # "both CIA 1 and CIA 2" / "both internal 1 and 2" / "both 1 and 2 CIA"
        r'both\s+(?:cia|internal|ia)?\s*([123])\s+(?:and|&|nd|n)\s+(?:cia|internal|ia)?\s*([123])'
        # "both [N] nd/and [N] CIA" — numbers BEFORE the word CIA/internal
        r'|both\s+([123])\s+(?:and|&|nd|n)\s+([123])\s+(?:cia|internal|ia)'
        # "CIA 1 and CIA 2" (without 'both')
        r'|(?:cia|internal|ia)\s*([123])\s+(?:and|&)\s+(?:cia|internal|ia)?\s*([123])'
        # "all three CIA/internals"
        r'|all\s+(?:three\s+)?(?:cia|internal|ia)s?',
        re.IGNORECASE
    )

    def _dq_filter_multi(self, query: str) -> Optional[Dict]:
        """
        Handle queries like:
          'students who scored less than 50 in BOTH CIA 1 and CIA 2'
          'who got below 40 in all three internals'
        Applies the threshold to ALL specified fields simultaneously (AND logic).
        """
        q   = query
        ql  = q.lower()
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        threshold_match = self._THRESHOLD_RE.search(q)
        if not threshold_match:
            return None
        op_raw   = threshold_match.group('op').lower()
        val      = float(threshold_match.group('val'))
        operator = ('lt' if re.search(r'less|below|under|at\s+most',   op_raw) else
                    'gt' if re.search(r'more|above|over|at\s+least',    op_raw) else 'lt')
        op_label = 'below' if operator == 'lt' else 'above'

        # Determine which fields to AND-filter
        m = self._MULTI_FIELD_BOTH_RE.search(ql)
        if m and 'all' in (m.group(0) or '').lower():
            fields = ['internal1', 'internal2', 'internal3']
        elif m:
            n1 = m.group(1) or m.group(3) or m.group(5)
            n2 = m.group(2) or m.group(4) or m.group(6)
            fields = [f'internal{n1}', f'internal{n2}']
        else:
            return None  # safety — should not reach here

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {'format': 'paragraph', 'text': err}

        # Build AND query across all specified fields
        qs = self._dq_base_qs(department, semester, subject).select_related('student', 'subject')
        for f in fields:
            qs = qs.filter(**{f'{f}__isnull': False})
            qs = qs.filter(**{f'{f}__{operator}': val})
        qs = qs.order_by('student__roll_number')

        field_labels  = [self._dq_field_label(f) for f in fields]
        field_str     = ' & '.join(field_labels)
        subj_label    = subject.name if subject else 'All Subjects'

        if not qs.exists():
            return {
                'format': 'paragraph',
                'text': (
                    f'No students scored {op_label} {val:.0f} in '
                    f'ALL of {field_str} in {subj_label}.'
                ),
            }

        columns = ['Roll No', 'Student Name']
        if not subject:
            columns.append('Subject')
        columns += field_labels

        rows = []
        for r in qs:
            row = [r.student.roll_number, r.student.student_name]
            if not subject:
                row.append(r.subject.code)
            for f in fields:
                v = getattr(r, f)
                row.append(str(v) if v is not None else '\u2014')
            rows.append(row)

        return {
            'format':  'table',
            'title':   f'Students {op_label} {val:.0f} in {field_str} \u2014 {subj_label}',
            'columns': columns,
            'rows':    rows,
        }

    # ── Handler 1: filter by threshold ────────────────────────────────────────

    def _dq_filter(self, query: str) -> Optional[Dict]:
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        threshold_match = self._THRESHOLD_RE.search(q)
        if not threshold_match:
            return None
        op_raw = threshold_match.group('op').lower()
        val    = float(threshold_match.group('val'))
        operator = ('lt' if re.search(r'less|below|under|at\s+most', op_raw)
                    else 'gt' if re.search(r'more|above|over|at\s+least', op_raw)
                    else 'eq')

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field       = self._dq_parse_field(q)
        field_label = self._dq_field_label(field)
        op_label    = "below" if operator == "lt" else ("above" if operator == "gt" else "equal to")

        qs = (self._dq_base_qs(department, semester, subject)
              .filter(**{f"{field}__isnull": False})
              .filter(**{f"{field}__{operator if operator != 'eq' else 'exact'}": val})
              .select_related("student", "subject")
              .order_by("student__roll_number"))

        subj_label = subject.name if subject else "All Subjects"
        if not qs.exists():
            return {
                "format": "paragraph",
                "text": (
                    f"No students found with {field_label} {op_label} {val} in {subj_label}."
                    + self._dq_no_data_msg(department)
                ),
            }

        columns = ["Roll No", "Student Name"]
        if not subject:
            columns.append("Subject")
        columns.append(field_label)

        rows = []
        for r in qs:
            row = [r.student.roll_number, r.student.student_name]
            if not subject:
                row.append(r.subject.code)
            row.append(str(getattr(r, field)))
            rows.append(row)

        return {
            "format":  "table",
            "title":   f"Students with {field_label} {op_label} {val} — {subj_label}",
            "columns": columns,
            "rows":    rows,
        }

    # ── Handler 2: top / bottom N ──────────────────────────────────────────────

    def _dq_top_n(self, query: str) -> Optional[Dict]:
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        ql = q.lower()
        # Parse N
        n = 5
        m = re.search(r'\btop\s+(\d+)\b|\bbottom\s+(\d+)\b|\bhighest\s+(\d+)\b|\blowest\s+(\d+)\b', ql)
        if m:
            n = int(next(v for v in m.groups() if v is not None))
        ascending = bool(re.search(r'\bbottom\b|\blowest\b|\bworst\b|\bweak', ql))

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field       = self._dq_parse_field(q)
        field_label = self._dq_field_label(field)

        # ── Aggregate mode: "in total" / "overall" / "combined" / no subject ──
        # When no specific subject is resolved AND query implies total/overall,
        # rank by SUM of marks across all subjects — one row per student.
        aggregate_mode = (
            subject is None and
            re.search(
                r'\bin\s+total\b|\bover\s*all\b|\bcombined\b|\baggregate\b'
                r'|\bacross\s+(?:all\s+)?subjects?\b|\btotal\s+marks?\b'
                r'|\boverall\s+rank\b|\boverall\s+performance\b',
                ql
            )
        )

        if aggregate_mode:
            from django.db.models import Sum
            qs_agg = (
                self._dq_base_qs(department, semester, None)
                .filter(**{f"{field}__isnull": False})
                .values('student__roll_number', 'student__student_name')
                .annotate(total=Sum(field))
                .order_by('total' if ascending else '-total')
            )[:n]

            if not qs_agg:
                return {
                    "format": "paragraph",
                    "text": f"No marks recorded for {field_label}."
                            + self._dq_no_data_msg(department),
                }

            direction = "Bottom" if ascending else "Top"
            rows = [
                [str(i), r['student__roll_number'], r['student__student_name'],
                 f"{float(r['total']):.2f}"]
                for i, r in enumerate(qs_agg, 1)
            ]
            return {
                "format":  "table",
                "title":   f"{direction} {n} Students — Total {field_label} (All Subjects)",
                "columns": ["Rank", "Roll No", "Student Name", f"Total {field_label}"],
                "rows":    rows,
            }

        # ── Per-subject mode (original behaviour) ─────────────────────────────
        qs = (self._dq_base_qs(department, semester, subject)
              .filter(**{f"{field}__isnull": False})
              .select_related("student", "subject")
              .order_by(field if ascending else f"-{field}"))[:n]

        subj_label = subject.name if subject else "All Subjects"
        direction  = "Bottom" if ascending else "Top"

        if not qs:
            return {
                "format": "paragraph",
                "text": f"No marks recorded for {field_label} in {subj_label}."
                        + self._dq_no_data_msg(department),
            }

        columns = ["Rank", "Roll No", "Student Name"]
        if not subject:
            columns.append("Subject")
        columns.append(field_label)

        rows = []
        for i, r in enumerate(qs, 1):
            row = [str(i), r.student.roll_number, r.student.student_name]
            if not subject:
                row.append(r.subject.code)
            row.append(str(getattr(r, field)))
            rows.append(row)

        return {
            "format":  "table",
            "title":   f"{direction} {n} Students — {field_label} — {subj_label}",
            "columns": columns,
            "rows":    rows,
        }

    # ── Handler 3: average / mean ──────────────────────────────────────────────

    def _dq_average(self, query: str) -> Optional[Dict]:
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        from students.models import Subject as SubjectModel
        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field       = self._dq_parse_field(q)
        field_label = self._dq_field_label(field)

        # If a single subject is resolved, return detailed stats for it;
        # otherwise, return per-subject averages as a comparison table.
        if subject:
            vals = [
                float(getattr(r, field))
                for r in self._dq_base_qs(department, semester, subject)
                .filter(**{f"{field}__isnull": False})
            ]
            if not vals:
                return {"format": "paragraph",
                        "text": f"No {field_label} marks recorded for {subject.name}."}
            avg = sum(vals) / len(vals)
            return {
                "format": "table",
                "title":  f"{field_label} Statistics — {subject.name}",
                "columns": ["Metric", "Value"],
                "rows": [
                    ["Average",  f"{avg:.2f}"],
                    ["Highest",  f"{max(vals):.2f}"],
                    ["Lowest",   f"{min(vals):.2f}"],
                    ["Students", str(len(vals))],
                    ["Above avg", str(sum(1 for v in vals if v >= avg))],
                    ["Below avg", str(sum(1 for v in vals if v < avg))],
                ],
            }
        else:
            # Multi-subject comparison
            subjects = SubjectModel.objects.filter(department=department, semester=semester)
            rows = []
            for sub in subjects:
                vals = [
                    float(getattr(r, field))
                    for r in self._dq_base_qs(department, semester, sub)
                    .filter(**{f"{field}__isnull": False})
                ]
                if vals:
                    rows.append([
                        sub.code, sub.name,
                        f"{sum(vals)/len(vals):.2f}",
                        f"{max(vals):.2f}", f"{min(vals):.2f}",
                        str(len(vals)),
                    ])
            if not rows:
                return {"format": "paragraph",
                        "text": f"No {field_label} marks uploaded yet."
                                + self._dq_no_data_msg(department)}
            return {
                "format":  "table",
                "title":   f"Average {field_label} — All Subjects",
                "columns": ["Code", "Subject", "Average", "Highest", "Lowest", "Count"],
                "rows":    rows,
            }

    # ── Handler 4: how many / count ────────────────────────────────────────────

    def _dq_count(self, query: str) -> Optional[Dict]:
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field    = self._dq_parse_field(q)
        fl_label = self._dq_field_label(field)

        threshold_match = self._THRESHOLD_RE.search(q)
        if threshold_match:
            op_raw = threshold_match.group('op').lower()
            val    = float(threshold_match.group('val'))
            operator = ('lt' if re.search(r'less|below|under|at\s+most', op_raw)
                        else 'gt' if re.search(r'more|above|over|at\s+least', op_raw)
                        else 'eq')
            op_label = "below" if operator == "lt" else ("above" if operator == "gt" else "equal to")
            qs = (self._dq_base_qs(department, semester, subject)
                  .filter(**{f"{field}__isnull": False})
                  .filter(**{f"{field}__{operator if operator != 'eq' else 'exact'}": val}))
            count = qs.count()
            total = self._dq_base_qs(department, semester, subject).filter(
                **{f"{field}__isnull": False}).count()
            pct   = f"{count/total*100:.1f}%" if total else "N/A"
            subj_label = subject.name if subject else "All Subjects"
            return {
                "format": "paragraph",
                "text": (
                    f"{count} student(s) scored {fl_label} {op_label} {val} in {subj_label} "
                    f"({pct} of {total} with marks recorded)."
                ),
            }
        else:
            # Count of students with any marks
            total = self._dq_base_qs(department, semester, subject).filter(
                **{f"{field}__isnull": False}).count()
            subj_label = subject.name if subject else "this semester"
            return {
                "format": "paragraph",
                "text": f"{total} student(s) have {fl_label} marks recorded in {subj_label}.",
            }

    # ── Handler 5: pass / fail stats ───────────────────────────────────────────

    def _dq_pass_fail_stats(self, query: str) -> Optional[Dict]:
        from django.db.models import Q
        from students.models import Subject as SubjectModel, Student
        q = query
        ql = q.lower()
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field = self._dq_parse_field(q)
        wants_breakdown = bool(re.search(r"per\s+subject|subject[-\s]*wise|each\s+subject", ql))

        # ── Internal pass/fail (based on marks, not grades) ─────────────────
        if field.startswith("internal"):
            absent_field = f"{field}_absent"
            pass_threshold = 50.0
            field_label = self._dq_field_label(field)

            if subject:
                qs = (self._dq_base_qs(department, semester, subject)
                    .filter(Q(**{f"{field}__isnull": False}) | Q(**{f"{absent_field}": True})))
                total = qs.count()
                if not total:
                    return {"format": "paragraph",
                            "text": f"No {field_label} marks uploaded for {subject.name} yet."}
                passed = (qs.exclude(**{f"{absent_field}": True})
                      .filter(**{f"{field}__gte": pass_threshold})
                      .count())
                failed = total - passed
                return {
                    "format":  "table",
                    "title":   f"Pass / Fail Summary — {subject.name}",
                    "columns": ["Metric", "Count", "Percentage"],
                    "rows": [
                        ["Total",  str(total),  "100%"],
                        ["Passed", str(passed), f"{passed/total*100:.1f}%"],
                        ["Failed", str(failed), f"{failed/total*100:.1f}%"],
                    ],
                }

            if not wants_breakdown:
                from collections import defaultdict
                students_qs = Student.objects.filter(
                    department_id=department.id,
                    academic_year_joining=self.batch_year,
                    is_active=True,
                )
                if self._active_section:
                    students_qs = students_qs.filter(section=self._active_section)

                sr_qs = (self._dq_base_qs(department, semester, None)
                         .only("student_id", field, absent_field))

                student_appeared = defaultdict(int)
                student_passed = defaultdict(int)
                for sr in sr_qs:
                    mark = getattr(sr, field)
                    is_absent = getattr(sr, absent_field, False)
                    if mark is not None or is_absent:
                        student_appeared[sr.student_id] += 1
                        if mark is not None and not is_absent and float(mark) >= pass_threshold:
                            student_passed[sr.student_id] += 1

                appeared_count = len(student_appeared)
                if appeared_count == 0:
                    return {"format": "paragraph",
                            "text": "No internal marks uploaded for this semester yet."}

                passed_count = sum(
                    1 for sid in student_appeared
                    if student_passed[sid] == student_appeared[sid]
                )
                failed_count = appeared_count - passed_count
                pass_pct = round(passed_count / appeared_count * 100, 1)

                title = f"Overall Pass % — {field_label}"
                if self._active_section:
                    title += f" — Section {self._active_section}"

                return {
                    "format":  "table",
                    "title":   title,
                    "columns": ["Metric", "Count"],
                    "rows": [
                        ["Class Strength", str(students_qs.count())],
                        ["Appeared", str(appeared_count)],
                        ["Passed", str(passed_count)],
                        ["Failed", str(failed_count)],
                        ["Pass %", f"{pass_pct:.1f}%"],
                    ],
                }

            # Subject-wise breakdown (all subjects)
            subjects = SubjectModel.objects.filter(department=department, semester=semester)
            rows = []
            for sub in subjects:
                qs = (self._dq_base_qs(department, semester, sub)
                      .filter(Q(**{f"{field}__isnull": False}) | Q(**{f"{absent_field}": True})))
                total = qs.count()
                if total:
                    passed = (qs.exclude(**{f"{absent_field}": True})
                              .filter(**{f"{field}__gte": pass_threshold})
                              .count())
                    failed = total - passed
                    rows.append([
                        sub.code, sub.name, str(total),
                        str(passed), str(failed),
                        f"{passed/total*100:.1f}%",
                    ])
            if not rows:
                return {"format": "paragraph",
                        "text": "No internal marks uploaded for this semester yet."}
            return {
                "format":  "table",
                "title":   "Pass / Fail Summary — All Subjects",
                "columns": ["Code", "Subject", "Total", "Passed", "Failed", "Pass %"],
                "rows":    rows,
            }

        # ── End-semester / grade-based fallback ─────────────────────────────
        def _stats(sub):
            qs = self._dq_base_qs(department, semester, sub).filter(grade__isnull=False)
            total = qs.count()
            if not total:
                return None
            failed = qs.filter(grade='U').count()
            passed = total - failed
            return {
                "code":   sub.code,
                "name":   sub.name,
                "total":  total,
                "passed": passed,
                "failed": failed,
                "pass_pct": f"{passed/total*100:.1f}%",
                "fail_pct": f"{failed/total*100:.1f}%",
            }

        if subject:
            s = _stats(subject)
            if s is None:
                return {"format": "paragraph",
                        "text": f"No grade data uploaded for {subject.name} yet."}
            return {
                "format":  "table",
                "title":   f"Pass / Fail Summary — {subject.name}",
                "columns": ["Metric", "Count", "Percentage"],
                "rows": [
                    ["Total",  str(s["total"]),  "100%"],
                    ["Passed", str(s["passed"]), s["pass_pct"]],
                    ["Failed", str(s["failed"]), s["fail_pct"]],
                ],
            }
        else:
            subjects = SubjectModel.objects.filter(department=department, semester=semester)
            rows = []
            for sub in subjects:
                s = _stats(sub)
                if s:
                    rows.append([s["code"], s["name"], str(s["total"]),
                                 str(s["passed"]), str(s["failed"]),
                                 s["pass_pct"], s["fail_pct"]])
            if not rows:
                return {"format": "paragraph",
                        "text": "No grade data uploaded for this semester yet."}
            return {
                "format":  "table",
                "title":   "Pass / Fail Summary — All Subjects",
                "columns": ["Code", "Subject", "Total", "Passed", "Failed",
                            "Pass %", "Fail %"],
                "rows":    rows,
            }

    # ── Handler 6: marks of a specific student ─────────────────────────────────

    def _dq_student_marks(self, query: str) -> Optional[Dict]:
        from students.models import Department, Semester, Subject, SubjectResult, Student
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        # Try to extract a roll number or registration number
        student = None
        # Roll number pattern: e.g. 24AD001, 711721CS001
        roll_m = re.search(r'\b(\d{2,4}[A-Z]{2,5}\d{3,})\b', q, re.IGNORECASE)
        if roll_m:
            roll = roll_m.group(1).upper()
            student = Student.objects.filter(
                roll_number__iexact=roll,
                department_id=department.id,
                is_active=True,
            ).first()

        # Fallback: try matching a name fragment
        if student is None:
            # Extract words that likely are a name (not keywords)
            stop = {'marks', 'of', 'for', 'show', 'display', 'get', 'fetch',
                    'student', 'result', 'score', 'sheet', 'internal', 'subject',
                    'the', 'a', 'an', 'in', 'and', 'what', 'is', 'are'}
            words = [w for w in re.findall(r'[a-z]+', q.lower()) if w not in stop and len(w) > 2]
            for w in words:
                student = Student.objects.filter(
                    student_name__icontains=w,
                    department_id=department.id,
                    academic_year_joining=self.batch_year,
                    is_active=True,
                ).first()
                if student:
                    break

        if student is None:
            return {
                "format": "paragraph",
                "text": "Could not identify the student from your query. "
                        "Please include the roll number (e.g. 24AD001).",
            }

        results = (SubjectResult.objects
                   .filter(student=student, subject__semester=semester)
                   .select_related("subject")
                   .order_by("subject__code"))

        if not results.exists():
            return {
                "format": "paragraph",
                "text": f"No marks found for {student.student_name} ({student.roll_number}) "
                        f"in Semester {self.semester_number}.",
            }

        rows = []
        for r in results:
            rows.append([
                r.subject.code, r.subject.name,
                str(r.internal1 or "—"),
                str(r.internal2 or "—"),
                str(r.internal3 or "—"),
                str(r.end_sem_marks or "—"),
                r.grade or "—",
            ])

        return {
            "format":  "table",
            "title":   f"Marks — {student.student_name} ({student.roll_number})",
            "columns": ["Code", "Subject", "CIA 1", "CIA 2", "CIA 3", "End Sem", "Grade"],
            "rows":    rows,
        }

    # ── Handler 7: subject stats / overview ────────────────────────────────────

    def _dq_subject_stats(self, query: str) -> Optional[Dict]:
        from students.models import Subject as SubjectModel
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        def _subject_row(sub):
            qs = self._dq_base_qs(department, semester, sub)
            row = [sub.code, sub.name]
            for field in ("internal1", "internal2", "internal3", "end_sem_marks"):
                vals = [float(getattr(r, field)) for r in qs if getattr(r, field) is not None]
                row.append(f"{sum(vals)/len(vals):.1f}" if vals else "—")
            # pass%
            graded = qs.filter(grade__isnull=False)
            total  = graded.count()
            passed = graded.exclude(grade='U').count()
            row.append(f"{passed/total*100:.0f}%" if total else "—")
            return row

        subjects = ([subject] if subject
                    else list(SubjectModel.objects.filter(department=department, semester=semester)))
        rows = [_subject_row(s) for s in subjects]
        if not any(r[2] != "—" for r in rows):
            return {"format": "paragraph",
                    "text": "No marks have been uploaded for this semester yet."}

        return {
            "format":  "table",
            "title":   f"Subject Statistics — Semester {self.semester_number}",
            "columns": ["Code", "Subject", "CIA 1 Avg", "CIA 2 Avg", "CIA 3 Avg",
                        "End Sem Avg", "Pass %"],
            "rows":    rows,
        }

    # ── Handler 8: list all marks for a subject ────────────────────────────────

    def _dq_all_marks(self, query: str) -> Optional[Dict]:
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}
        if subject is None:
            return None  # too broad — fall through to LLM

        qs = (self._dq_base_qs(department, semester, subject)
              .select_related("student")
              .order_by("student__roll_number"))
        if not qs.exists():
            return {"format": "paragraph",
                    "text": f"No marks recorded for {subject.name} yet."}

        rows = [
            [r.student.roll_number, r.student.student_name,
             str(r.internal1 or "—"), str(r.internal2 or "—"),
             str(r.internal3 or "—"), str(r.end_sem_marks or "—"),
             r.grade or "—"]
            for r in qs
        ]
        return {
            "format":  "table",
            "title":   f"All Marks — {subject.name} ({subject.code})",
            "columns": ["Roll No", "Student Name", "CIA 1", "CIA 2", "CIA 3",
                        "End Sem", "Grade"],
            "rows":    rows,
        }

    # ── Handler 9: failed / arrears ────────────────────────────────────────────

    def _dq_failed(self, query: str) -> Dict:
        q = query
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return {"format": "paragraph", "text": "Context not found."}

        subject, err = self._dq_resolve_subject(q, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        qs = (self._dq_base_qs(department, semester, subject)
              .filter(grade='U')
              .select_related("student", "subject")
              .order_by("student__roll_number"))

        if qs.exists():
            columns = ["Roll No", "Student Name"]
            if not subject:
                columns.append("Subject")
            columns += ["End Sem", "Grade"]
            rows = []
            for r in qs:
                row = [r.student.roll_number, r.student.student_name]
                if not subject:
                    row.append(r.subject.code)
                row += [str(r.end_sem_marks or "—"), r.grade or "U"]
                rows.append(row)
            subj_label = subject.name if subject else "All Subjects"
            return {
                "format":  "table",
                "title":   f"Students who Failed (Grade U) — {subj_label}",
                "columns": columns,
                "rows":    rows,
            }

        return {
            "format": "paragraph",
            "text": "No failed students found for this semester, "
                    "or end-semester results have not been uploaded yet.",
        }

    # Legacy alias kept for any external call-sites
    def _direct_query_failed(self, query: str) -> Dict:
        return self._dq_failed(query)

    # ── Handler 10: grade distribution ────────────────────────────────────────

    def _dq_grade_distribution(self, query: str) -> Optional[Dict]:
        """Grade breakdown: how many A / B / C / U etc."""
        from django.db.models import Count
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(query, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        qs = (self._dq_base_qs(department, semester, subject)
              .exclude(grade__isnull=True).exclude(grade__exact=''))
        graded = qs.values('grade').annotate(count=Count('id')).order_by('grade')

        if not graded.exists():
            subj_name = subject.name if subject else "this semester"
            return {"format": "paragraph",
                    "text": f"No grade data uploaded for {subj_name} yet."}

        total = sum(g['count'] for g in graded)
        rows = [
            [g['grade'], str(g['count']), f"{g['count'] * 100 / total:.1f}%"]
            for g in graded
        ]
        title = (f"Grade Distribution — {subject.name}"
                 if subject else
                 f"Grade Distribution — All Subjects (Semester {semester.number})")
        return {
            "format":  "table",
            "title":   title,
            "columns": ["Grade", "Count", "Percentage"],
            "rows":    rows,
        }

    # ── Handler 11: CIA improvement / drop ────────────────────────────────────

    def _dq_improvement(self, query: str) -> Optional[Dict]:
        """Students who improved or dropped between CIA rounds."""
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(query, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        ql = query.lower()
        if re.search(r'cia\s*2.*cia\s*3|internal\s*2.*internal\s*3|2\s*to\s*3', ql):
            f1, f2, l1, l2 = 'internal2', 'internal3', 'CIA 2', 'CIA 3'
        else:
            f1, f2, l1, l2 = 'internal1', 'internal2', 'CIA 1', 'CIA 2'

        is_drop = bool(re.search(r'\bdrop(?:ped)?\b|\bdecline[d]?\b|\bworse\b|\bfell\b|\bdecrease[d]?\b', ql))

        qs = (self._dq_base_qs(department, semester, subject)
              .exclude(**{f"{f1}__isnull": True})
              .exclude(**{f"{f2}__isnull": True})
              .select_related("student", "subject"))

        if not qs.exists():
            return {"format": "paragraph",
                    "text": f"No data available for both {l1} and {l2} yet."}

        rows = []
        for r in qs:
            v1   = float(getattr(r, f1))
            v2   = float(getattr(r, f2))
            diff = v2 - v1
            if is_drop and diff < 0:
                rows.append([r.student.roll_number, r.student.student_name,
                              f"{v1:.1f}", f"{v2:.1f}", f"{diff:+.1f}"])
            elif not is_drop and diff > 0:
                rows.append([r.student.roll_number, r.student.student_name,
                              f"{v1:.1f}", f"{v2:.1f}", f"{diff:+.1f}"])

        if not rows:
            direction = "drop" if is_drop else "improvement"
            return {"format": "paragraph",
                    "text": f"No students showed a {direction} from {l1} to {l2}."}

        rows.sort(key=lambda x: float(x[4]), reverse=(not is_drop))
        direction_label = "Drop" if is_drop else "Improvement"
        subj_name = subject.name if subject else "All Subjects"
        return {
            "format":  "table",
            "title":   f"Performance {direction_label}: {l1} → {l2} — {subj_name}",
            "columns": ["Roll No", "Student Name", l1, l2, "Change"],
            "rows":    rows,
        }

    # ── Handler 12: top-percentile ────────────────────────────────────────────

    def _dq_percentile(self, query: str) -> Optional[Dict]:
        """Students in top/bottom X percentile or quartile."""
        import math
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(query, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field       = self._dq_parse_field(query)
        field_label = self._dq_field_label(field)
        ql          = query.lower()

        pct_m = re.search(
            r'top\s+(\d+(?:\.\d+)?)\s*%'
            r'|(\d+(?:\.\d+)?)\s*(?:th|st|nd|rd)?\s*percentile'
            r'|top\s+quartile|bottom\s+quartile|first\s+quartile|fourth\s+quartile',
            ql
        )
        if pct_m:
            if 'quartile' in ql and ('top' in ql or 'fourth' in ql):
                pct = 25.0
            elif 'quartile' in ql:
                pct = 25.0
            else:
                pct = float(pct_m.group(1) or pct_m.group(2) or 25)
        else:
            pct = 25.0

        qs = (self._dq_base_qs(department, semester, subject)
              .exclude(**{f"{field}__isnull": True})
              .select_related("student")
              .order_by(f"-{field}"))

        total = qs.count()
        if total == 0:
            return {"format": "paragraph", "text": "No marks data available."}

        cutoff = max(1, math.ceil(total * pct / 100))
        rows = []
        for i, r in enumerate(qs[:cutoff], 1):
            val = getattr(r, field)
            rows.append([str(i), r.student.roll_number, r.student.student_name,
                         f"{float(val):.2f}"])

        subj_name = subject.name if subject else "All Subjects"
        return {
            "format":  "table",
            "title":   f"Top {pct:.0f}% Students — {field_label} — {subj_name}",
            "columns": ["Rank", "Roll No", "Student Name", field_label],
            "rows":    rows,
        }

    # ── Handler 13: at-risk students ──────────────────────────────────────────

    def _dq_at_risk(self, query: str) -> Optional[Dict]:
        """Students failing (below threshold) in 2+ subjects simultaneously."""
        from django.db.models import Count
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        threshold_m = self._THRESHOLD_RE.search(query)
        threshold   = float(threshold_m.group('val')) if threshold_m else 40.0
        field       = self._dq_parse_field(query)
        field_label = self._dq_field_label(field)

        fail_qs = (self._dq_base_qs(department, semester, None)
                   .filter(**{f"{field}__lt": threshold}))

        at_risk = (fail_qs
                   .values('student__roll_number', 'student__student_name')
                   .annotate(fail_count=Count('id'))
                   .filter(fail_count__gte=2)
                   .order_by('-fail_count', 'student__roll_number'))

        if not at_risk.exists():
            return {
                "format": "paragraph",
                "text": (f"No students are failing in 2 or more subjects "
                         f"({field_label} below {threshold:.0f})."),
            }

        rows = [
            [s['student__roll_number'], s['student__student_name'], str(s['fail_count'])]
            for s in at_risk
        ]
        return {
            "format":  "table",
            "title":   f"At-Risk Students ({field_label} < {threshold:.0f} in ≥2 Subjects)",
            "columns": ["Roll No", "Student Name", "Subjects Below Threshold"],
            "rows":    rows,
        }

    # ── Handler 14: distribution stats (median / std-dev / variance) ──────────

    def _dq_distribution_stats(self, query: str) -> Optional[Dict]:
        """Statistical distribution: mean, median, std dev, variance, percentiles."""
        import math
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        subject, err = self._dq_resolve_subject(query, department, semester)
        if err:
            return {"format": "paragraph", "text": err}

        field       = self._dq_parse_field(query)
        field_label = self._dq_field_label(field)

        values = list(
            self._dq_base_qs(department, semester, subject)
            .exclude(**{f"{field}__isnull": True})
            .values_list(field, flat=True)
        )
        if not values:
            return {"format": "paragraph", "text": "No marks data available."}

        values = sorted(float(v) for v in values)
        n      = len(values)
        mean   = sum(values) / n
        var    = sum((x - mean) ** 2 for x in values) / n
        std    = math.sqrt(var)
        mid    = n // 2
        median = values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
        p25    = values[max(0, math.ceil(n * 0.25) - 1)]
        p75    = values[min(n - 1, math.ceil(n * 0.75) - 1)]

        subj_name = subject.name if subject else f"All Subjects"
        return {
            "format":  "table",
            "title":   f"Distribution Statistics — {field_label} — {subj_name}",
            "columns": ["Metric", "Value"],
            "rows": [
                ["Count",          str(n)],
                ["Mean (Average)", f"{mean:.2f}"],
                ["Median",         f"{median:.2f}"],
                ["Std Deviation",  f"{std:.2f}"],
                ["Variance",       f"{var:.2f}"],
                ["Min",            f"{values[0]:.2f}"],
                ["Max",            f"{values[-1]:.2f}"],
                ["Range",          f"{values[-1] - values[0]:.2f}"],
                ["25th Percentile",f"{p25:.2f}"],
                ["75th Percentile",f"{p75:.2f}"],
            ],
        }

    # ── Compute engine: LLM code-gen + safe exec ──────────────────────────────

    def _dq_chart(self, query: str) -> Optional[Dict]:
        """
        Generate chart/visualization data for common requests like:
          - 'show a bar chart of average marks per subject'
          - 'pie chart of pass/fail distribution'
          - 'graph of CIA 1 vs CIA 2 averages'
          - 'visualize grade distribution'

        For complex chart requests, falls through to _compute_query (which
        also supports the chart format now).
        """
        ql = query.lower()
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return None

        from students.models import SubjectResult, Subject, EndSemesterResult

        # Detect chart type preference
        chart_type = "bar"
        if re.search(r'\bpie\b', ql):
            chart_type = "pie"
        elif re.search(r'\bline\b', ql):
            chart_type = "line"
        elif re.search(r'\bdoughnut\b', ql):
            chart_type = "doughnut"

        field       = self._dq_parse_field(query)
        field_label = self._dq_field_label(field)

        # ── Grade distribution chart ──────────────────────────────────────────
        if re.search(r'\bgrade\b', ql):
            from django.db.models import Count
            subject, err = self._dq_resolve_subject(query, department, semester)
            if err:
                return {"format": "paragraph", "text": err}

            if self._dq_prefers_end_semester(query):
                base_qs = (EndSemesterResult.objects
                           .filter(
                               student__academic_year_joining=self.batch_year,
                               student__department_id=department.id,
                               student__is_active=True,
                               subject__semester=semester,
                           ))
                if self._active_section:
                    base_qs = base_qs.filter(student__section=self._active_section)
                if subject:
                    base_qs = base_qs.filter(subject=subject)
            else:
                base_qs = self._dq_base_qs(department, semester, subject)
            dist = (base_qs
                    .exclude(grade__isnull=True)
                    .exclude(grade='')
                    .values('grade')
                    .annotate(cnt=Count('id'))
                    .order_by('grade'))
            if not dist:
                return {"format": "paragraph", "text": "No grade data available for charting."}

            labels = [d['grade'] for d in dist]
            data   = [d['cnt'] for d in dist]
            subj_name = subject.name if subject else "All Subjects"
            return {
                "format":     "chart",
                "chart_type": chart_type if chart_type != "bar" else "pie",
                "title":      f"Grade Distribution — {subj_name}",
                "labels":     labels,
                "datasets":   [{"label": "Students", "data": data}],
            }

        # ── Pass/fail chart ───────────────────────────────────────────────────
        if re.search(r'\bpass\b.*\bfail\b|\bfail\b.*\bpass\b|\bresult\s+status\b|\bpass\s+percentage\b|\bpass\s+rate\b', ql):
            subject, _ = self._dq_resolve_subject(query, department, semester)
            if self._dq_prefers_end_semester(query):
                base_qs = (EndSemesterResult.objects
                           .filter(
                               student__academic_year_joining=self.batch_year,
                               student__department_id=department.id,
                               student__is_active=True,
                               subject__semester=semester,
                           ))
                if self._active_section:
                    base_qs = base_qs.filter(student__section=self._active_section)
                if subject:
                    base_qs = base_qs.filter(subject=subject)
                total  = base_qs.exclude(grade__isnull=True).exclude(grade='').count()
                failed = base_qs.filter(grade__in=['U', 'u']).count()
            else:
                base_qs = self._dq_base_qs(department, semester, subject)
                total   = base_qs.exclude(grade__isnull=True).exclude(grade='').count()
                failed  = base_qs.filter(grade__in=['U', 'u']).count()
            passed  = total - failed
            subj_name = subject.name if subject else "All Subjects"
            return {
                "format":     "chart",
                "chart_type": chart_type if chart_type != "bar" else "doughnut",
                "title":      f"Pass/Fail — {subj_name}",
                "labels":     ["Passed", "Failed"],
                "datasets":   [{"label": "Students", "data": [passed, failed]}],
            }

        # ── Average marks per subject chart ───────────────────────────────────
        if re.search(r'\baverage\b|\bmean\b|\bsubject\s*wise\b|\bper\s+subject\b|\bcompar', ql):
            from django.db.models import Avg
            subjects = Subject.objects.filter(department=department, semester=semester)
            labels = []
            data   = []
            for sub in subjects:
                if self._dq_prefers_end_semester(query):
                    avg = (EndSemesterResult.objects
                           .filter(
                               student__academic_year_joining=self.batch_year,
                               student__department_id=department.id,
                               student__is_active=True,
                               subject=sub,
                           )
                           .exclude(marks__isnull=True)
                           .aggregate(avg=Avg('marks'))['avg'])
                else:
                    avg = (SubjectResult.objects
                           .filter(
                               student__academic_year_joining=self.batch_year,
                               student__department_id=department.id,
                               student__is_active=True,
                               subject=sub,
                           )
                           .exclude(**{f"{field}__isnull": True})
                           .aggregate(avg=Avg(field))['avg'])
                if avg is not None:
                    labels.append(sub.code)
                    data.append(round(float(avg), 2))
            if not labels:
                return {"format": "paragraph", "text": "No marks data available for chart."}
            return {
                "format":     "chart",
                "chart_type": chart_type,
                "title":      f"Average {field_label} per Subject",
                "labels":     labels,
                "datasets":   [{"label": f"Avg {field_label}", "data": data}],
            }

        # ── CIA comparison chart (CIA 1 vs 2 vs 3) ────────────────────────────
        if re.search(r'\bcia\b|\binternals?\b|\bvs\b|\bcompare\b', ql):
            from django.db.models import Avg
            subjects = Subject.objects.filter(department=department, semester=semester)
            labels   = [s.code for s in subjects]
            datasets = []
            for n in [1, 2, 3]:
                f_name = f"internal{n}"
                vals = []
                for sub in subjects:
                    avg = (SubjectResult.objects
                           .filter(
                               student__academic_year_joining=self.batch_year,
                               student__department_id=department.id,
                               student__is_active=True,
                               subject=sub,
                           )
                           .exclude(**{f"{f_name}__isnull": True})
                           .aggregate(avg=Avg(f_name))['avg'])
                    vals.append(round(float(avg), 2) if avg is not None else 0)
                datasets.append({"label": f"CIA {n}", "data": vals})
            if not labels:
                return {"format": "paragraph", "text": "No subjects found for charting."}
            return {
                "format":     "chart",
                "chart_type": "bar",
                "title":      "CIA Comparison — Average Marks per Subject",
                "labels":     labels,
                "datasets":   datasets,
            }

        # ── Default: subject-wise performance overview ─────────────────────
        #    Catch-all for general "show me a graph" / "visualize results" queries
        from django.db.models import Avg
        subjects = Subject.objects.filter(department=department, semester=semester)
        if not subjects.exists():
            return {"format": "paragraph",
                    "text": "No subjects found in this semester for charting."}

        labels   = [s.code for s in subjects]
        datasets = []
        end_sem_context = self._dq_prefers_end_semester(query)

        if end_sem_context and re.search(r'\bpass\s+percentage\b|\bpass\s+rate\b|\bpass\b', ql):
            pass_pct_vals = []
            pass_labels = []
            for sub in subjects:
                base_qs = (EndSemesterResult.objects
                           .filter(
                               student__academic_year_joining=self.batch_year,
                               student__department_id=department.id,
                               student__is_active=True,
                               subject=sub,
                           ))
                if self._active_section:
                    base_qs = base_qs.filter(student__section=self._active_section)
                total = base_qs.exclude(grade__isnull=True).exclude(grade='').count()
                if total == 0:
                    continue
                failed = base_qs.filter(grade__in=['U', 'u']).count()
                passed = total - failed
                pass_labels.append(sub.code)
                pass_pct_vals.append(round((passed / total) * 100, 2))
            if pass_pct_vals:
                return {
                    "format":     "chart",
                    "chart_type": chart_type if chart_type != "bar" else "bar",
                    "title":      "End Semester Pass Percentage by Subject",
                    "labels":     pass_labels,
                    "datasets":   [{"label": "Pass %", "data": pass_pct_vals}],
                }

        if end_sem_context:
            end_vals = []
            for sub in subjects:
                avg = (EndSemesterResult.objects
                       .filter(
                           student__academic_year_joining=self.batch_year,
                           student__department_id=department.id,
                           student__is_active=True,
                           subject=sub,
                       )
                       .exclude(marks__isnull=True)
                       .aggregate(avg=Avg('marks'))['avg'])
                end_vals.append(round(float(avg), 2) if avg is not None else 0)
            if any(v > 0 for v in end_vals):
                return {
                    "format":     "chart",
                    "chart_type": chart_type,
                    "title":      "End Semester Performance Overview",
                    "labels":     labels,
                    "datasets":   [{"label": "End Sem Avg", "data": end_vals}],
                }

        # CIA 1, CIA 2, CIA 3 averages
        for f_name, f_label in [("internal1", "CIA 1"),
                                 ("internal2", "CIA 2"),
                                 ("internal3", "CIA 3")]:
            vals = []
            for sub in subjects:
                avg = (SubjectResult.objects
                       .filter(
                           student__academic_year_joining=self.batch_year,
                           student__department_id=department.id,
                           student__is_active=True,
                           subject=sub,
                       )
                       .exclude(**{f"{f_name}__isnull": True})
                       .aggregate(avg=Avg(f_name))['avg'])
                vals.append(round(float(avg), 2) if avg is not None else 0)
            if any(v > 0 for v in vals):
                datasets.append({"label": f_label, "data": vals})

        # End Semester average (check SubjectResult first, fall back to EndSemesterResult)
        end_vals = []
        for sub in subjects:
            avg = (SubjectResult.objects
                   .filter(
                       student__academic_year_joining=self.batch_year,
                       student__department_id=department.id,
                       student__is_active=True,
                       subject=sub,
                   )
                   .exclude(end_sem_marks__isnull=True)
                   .aggregate(avg=Avg('end_sem_marks'))['avg'])
            if avg is None:
                avg = (EndSemesterResult.objects
                       .filter(
                           student__academic_year_joining=self.batch_year,
                           student__department_id=department.id,
                           student__is_active=True,
                           subject=sub,
                       )
                       .exclude(marks__isnull=True)
                       .aggregate(avg=Avg('marks'))['avg'])
            end_vals.append(round(float(avg), 2) if avg is not None else 0)
        if any(v > 0 for v in end_vals):
            datasets.append({"label": "End Sem", "data": end_vals})

        if not datasets:
            return {"format": "paragraph",
                    "text": "No marks data available yet to generate a chart."}

        return {
            "format":     "chart",
            "chart_type": chart_type,
            "title":      "Subject-wise Performance Overview",
            "labels":     labels,
            "datasets":   datasets,
        }

    def _compute_query(self, query: str) -> Dict:
        """
        For queries that don't match any direct handler:

        1. Load all SubjectResult records for this context into Python dicts.
        2. Ask Ollama to write a Python snippet that computes the answer.
        3. Execute the snippet in a restricted sandbox against the real data.
        4. Return the result — which is always computed from REAL data (no hallucination).

        Retry once if the generated code raises an exception.
        """
        try:
            department, semester = self._dq_load_context()
        except Exception:
            return {"format": "paragraph", "text": "Could not load semester context."}

        # Guard: no data at all
        no_data = self._dq_no_data_msg(department)
        if no_data:
            return {"format": "paragraph",
                    "text": "No marks have been uploaded for this semester yet. "
                            "Please upload a mark sheet first."}

        from students.models import SubjectResult, Semester, EndSemesterResult
        qs = (SubjectResult.objects
              .filter(
                  student__academic_year_joining=self.batch_year,
                  student__department_id=department.id,
                  student__is_active=True,
                  subject__semester=semester,
              )
              .select_related("student", "subject"))
        if self._active_section:
            qs = qs.filter(student__section=self._active_section)

        records = [
            {
                "roll_number":   r.student.roll_number,
                "student_name":  r.student.student_name,
                "subject_code":  r.subject.code,
                "subject_name":  r.subject.name,
                "internal1":     float(r.internal1)     if r.internal1     is not None else None,
                "internal2":     float(r.internal2)     if r.internal2     is not None else None,
                "internal3":     float(r.internal3)     if r.internal3     is not None else None,
                "end_sem_marks": float(r.end_sem_marks) if r.end_sem_marks is not None else None,
                "grade":         r.grade or None,
            }
            for r in qs
        ]

        # Load end semester results from the dedicated table
        end_qs = (EndSemesterResult.objects
                  .filter(
                      student__academic_year_joining=self.batch_year,
                      student__department_id=department.id,
                      student__is_active=True,
                      subject__semester=semester,
                  )
                  .select_related("student", "subject"))
        if self._active_section:
            end_qs = end_qs.filter(student__section=self._active_section)

        end_sem_records = [
            {
                "roll_number":   r.student.roll_number,
                "student_name":  r.student.student_name,
                "subject_code":  r.subject.code,
                "subject_name":  r.subject.name,
                "marks":         float(r.marks)         if r.marks         is not None else None,
                "max_marks":     float(r.max_marks)     if r.max_marks     is not None else None,
                "grade":         r.grade or None,
                "grade_points":  float(r.grade_points)  if r.grade_points  is not None else None,
                "result_status": r.result_status or None,
            }
            for r in end_qs
        ]

        if not records and not end_sem_records:
            return {"format": "paragraph",
                    "text": "No marks have been uploaded for this semester yet."}

        try:
            sem_obj  = Semester.objects.get(number=self.semester_number)
            sem_name = sem_obj.name
        except Exception:
            sem_name = f"Semester {self.semester_number}"

        prompt = CODE_GEN_PROMPT.format(
            department=department.name,
            batch_year=self.batch_year,
            semester_name=sem_name,
            record_count=len(records),
            end_sem_count=len(end_sem_records),
            query=query,
        )

        if self._dq_prefers_end_semester(query):
            prompt += (
                "\n\nThe current question is specifically about end-semester results. "
                "Use end_sem_data as the primary source and ignore CIA/internal marks unless the user explicitly asks for them."
            )

        # Append conversation history to prompt if available
        if getattr(self, '_history', None):
            recent = self._history[-6:]
            history_text = "\n".join(
                f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content'][:300]}"
                for h in recent if h.get('content')
            )
            if history_text.strip():
                prompt += (
                    "\n\nConversation history (for context — the current query may "
                    "reference previous exchanges):\n" + history_text
                )

        # Safe builtins — no imports, no I/O, no reflection
        _SAFE_BUILTINS = {
            'len': len, 'sum': sum, 'min': min, 'max': max,
            'sorted': sorted, 'enumerate': enumerate, 'zip': zip,
            'round': round, 'abs': abs, 'int': int, 'float': float,
            'str': str, 'list': list, 'dict': dict, 'set': set,
            'filter': filter, 'map': map, 'range': range,
            'isinstance': isinstance, 'any': any, 'all': all,
            'bool': bool, 'type': type,
            'None': None, 'True': True, 'False': False,
            'print': lambda *a, **kw: None,   # silenced
        }

        last_error = None
        for attempt in range(2):
            try:
                raw_code = _ollama_generate(prompt)
                code     = _extract_python_code(raw_code)

                namespace = {
                    'data':          records,
                    'end_sem_data':  end_sem_records,
                    'result':        None,
                    '__builtins__':  _SAFE_BUILTINS,
                }
                exec(compile(code, '<compute_query>', 'exec'), namespace)  # noqa: S102
                result = namespace.get('result')

                if isinstance(result, dict):
                    fmt = result.get('format')
                    if fmt == 'table':
                        # Normalise: all cell values → str
                        result['rows'] = [
                            [str(c) if c is not None else '—' for c in row]
                            for row in result.get('rows', [])
                        ]
                        return result
                    if fmt == 'chart' and result.get('labels') and result.get('datasets'):
                        # Validate chart structure
                        result.setdefault('chart_type', 'bar')
                        result.setdefault('title', 'Chart')
                        # Ensure data values are numbers
                        for ds in result.get('datasets', []):
                            ds['data'] = [
                                float(v) if v is not None else 0
                                for v in ds.get('data', [])
                            ]
                        return result
                    if fmt == 'paragraph' and result.get('text'):
                        return result

                # If result isn't well-formed, wrap as paragraph
                if result is not None:
                    return {"format": "paragraph", "text": str(result)}

            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    # Tell the LLM about the error and ask it to fix the code
                    prompt += (
                        f"\n\n[Error on previous attempt: "
                        f"{type(exc).__name__}: {exc}. Please fix the code.]"
                    )
                    continue

        return {
            "format": "paragraph",
            "text": (
                f"I couldn't compute an answer for that query. "
                f"({type(last_error).__name__}: {last_error})"
                if last_error else
                "Unable to compute an answer. Please try rephrasing your question."
            ),
        }


# ─── helpers ──────────────────────────────────────────────────────────────────

def _clean_json(text: str) -> str:
    """Strip markdown fences and leading/trailing whitespace from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Extract the first {...} block in case the model added commentary around it
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    return text.strip()


def _extract_python_code(text: str) -> str:
    """
    Extract clean Python code from an LLM response.
    Strips ```python … ``` fences and any leading prose.
    """
    # Remove fenced code blocks
    text = re.sub(r"```python\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    # Drop any leading lines that look like English prose (no = or : or indent)
    lines = text.splitlines()
    code_lines = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if not in_code and stripped and not stripped.startswith('#'):
            # Heuristic: Python code lines often start with keywords or have = / ( / [
            if re.match(r'^(result\s*=|data|for|if|def|import|#|[a-zA-Z_].*=)', stripped):
                in_code = True
        if in_code:
            code_lines.append(line)
    return "\n".join(code_lines).strip() if code_lines else text.strip()


def _safe_parse_json(text: str) -> dict:
    """
    Try to parse JSON from LLM output.
    Falls back to a best-effort repair for common llama quirks:
      - trailing commas before ] or }
      - truncated output (adds missing closing brackets)
    """
    # First try: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Second try: remove trailing commas
    cleaned = re.sub(r",\s*([\]}])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Third try: truncated JSON — count brackets and close them
    repaired = cleaned
    open_braces   = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    repaired += "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    return json.loads(repaired)  # let this raise if still broken
