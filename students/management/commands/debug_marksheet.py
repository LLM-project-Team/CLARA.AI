"""
Management command to diagnose why marks / attendance %% are mis-identified.

Usage (from project root, venv activated):

  python manage.py debug_marksheet path/to/marksheet.pdf
  python manage.py debug_marksheet path/to/marksheet.csv

Output shows:
  - Header row index + subject codes found
  - Rows between header and first student row  (max-marks candidates)
  - Per-subject: all numeric X-buckets seen, which were chosen, max_marks ceiling
  - First 5 parsed student records
"""
import os, sys
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Debug mark-sheet parser: show X-bucket analysis for a PDF or CSV file"

    def add_arguments(self, parser):
        parser.add_argument("filepath", help="Path to the PDF or CSV mark-sheet")

    def handle(self, *args, **options):
        path = options["filepath"]
        if not os.path.isfile(path):
            raise CommandError(f"File not found: {path}")

        with open(path, "rb") as fh:
            file_bytes = fh.read()

        if path.lower().endswith(".pdf"):
            self._debug_pdf(file_bytes)
        elif path.lower().endswith(".csv"):
            self._debug_csv(file_bytes)
        else:
            raise CommandError("Only .pdf and .csv files are supported.")

    # ------------------------------------------------------------------
    def _debug_pdf(self, file_bytes):
        try:
            import fitz
        except ImportError:
            raise CommandError("PyMuPDF (fitz) not installed in this venv.")

        import re
        from utils.analytics_ai import (
            _page_rows, _find_header_row, _is_student_id,
            _detect_mark_subcolumns, _BUCKET_PTS,
        )
        import statistics as _stats
        from collections import defaultdict

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        self.stdout.write(f"\n=== PDF has {doc.page_count} page(s) ===\n")

        for page_num, page in enumerate(doc):
            rows = _page_rows(page)
            hdr_idx, col_map = _find_header_row(rows)
            self.stdout.write(f"\n--- Page {page_num + 1} ---")
            self.stdout.write(f"Header row index  : {hdr_idx}")
            if hdr_idx < 0:
                self.stdout.write("  (no subject codes found on this page)")
                continue

            self.stdout.write(f"Subject codes found: {list(col_map.values())}")
            self.stdout.write(f"Header row cells   : {[(round(x,1), t) for x, t in rows[hdr_idx]]}")

            # Show rows between header and first student
            first_sid_row = len(rows)
            for ri, row in enumerate(rows):
                if ri <= hdr_idx:
                    continue
                if any(_is_student_id(t) for _, t in row):
                    first_sid_row = ri
                    break

            self.stdout.write(f"\nRows between header ({hdr_idx}) and first student ({first_sid_row}):")
            for ri in range(hdr_idx + 1, min(first_sid_row, hdr_idx + 8)):
                self.stdout.write(f"  row[{ri}]: {[(round(x, 1), t) for x, t in rows[ri]]}")

            # Reproduce _find_best_mark_xs logic with verbose output
            col_xs   = sorted(col_map.keys())
            n_cols   = len(col_xs)
            col_width = (col_xs[-1] - col_xs[0]) / (n_cols - 1) if n_cols > 1 else 60.0
            half_w   = max(col_width * 0.4, 18.0)
            self.stdout.write(f"\ncol_width={col_width:.1f}  half_w={half_w:.1f}  bucket={_BUCKET_PTS}")

            # Max-marks row detection
            _VALID_MAX = {10, 15, 20, 25, 30, 40, 50, 60, 75, 80, 100}
            for ri in range(hdr_idx + 1, min(first_sid_row, hdr_idx + 6)):
                row = rows[ri]
                cand = {}
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
                        if v in _VALID_MAX:
                            cand[code] = v
                            break
                if len(cand) >= max(1, n_cols // 2):
                    self.stdout.write(f"  Max-marks row detected: row[{ri}] → {cand}")
                    break
            else:
                self.stdout.write("  No dedicated max-marks row detected.")

            # Collect per-student bucket values
            val_map   = defaultdict(lambda: defaultdict(list))
            raw_x_map = defaultdict(lambda: defaultdict(list))
            student_count = 0

            for ri, row in enumerate(rows):
                if ri <= hdr_idx:
                    continue
                if not any(_is_student_id(t) for _, t in row):
                    continue
                student_count += 1
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

            self.stdout.write(f"\n{student_count} student row(s) found.")
            if not val_map:
                self.stdout.write("  WARNING: No numeric values collected near subject code columns!")
                self.stdout.write("  → _is_student_id may not be matching this PDF's ID format.")
                # Show first few rows after header so user can check
                self.stdout.write("  First 5 data rows:")
                shown = 0
                for ri, row in enumerate(rows):
                    if ri <= hdr_idx:
                        continue
                    self.stdout.write(f"    row[{ri}]: {[(round(x,1), t) for x,t in row]}")
                    shown += 1
                    if shown >= 5:
                        break
            else:
                for code in col_map.values():
                    bx_vals = val_map.get(code, {})
                    self.stdout.write(f"\n  Subject {code}:")
                    for bx in sorted(bx_vals):
                        vs      = bx_vals[bx]
                        rx      = raw_x_map[code][bx]
                        avg_rx  = sum(rx) / len(rx)
                        try:
                            med = _stats.median(vs)
                        except Exception:
                            med = 0
                        top_val = max(set(vs), key=vs.count)
                        const_pct = vs.count(top_val) / len(vs)
                        flag = "CONSTANT" if const_pct >= 0.75 else f"variable(med={med:.0f})"
                        self.stdout.write(
                            f"    bucket_x≈{bx:.0f}  raw_x≈{avg_rx:.1f}  "
                            f"n={len(vs)}  vals={sorted(set(vs))[:8]}  {flag}"
                        )

            doc.close()

    # ------------------------------------------------------------------
    def _debug_csv(self, file_bytes):
        import csv, io, re
        from utils.analytics_ai import _is_student_id, _SUBJ_CODE_RE

        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")

        raw_rows = list(csv.reader(io.StringIO(text)))
        self.stdout.write(f"\n=== CSV has {len(raw_rows)} row(s) ===\n")

        best_hdr_idx = -1
        best_col_map = {}
        for ri, row in enumerate(raw_rows):
            cm = {}
            for ci, cell in enumerate(row):
                m = _SUBJ_CODE_RE.match(cell.strip().upper())
                if m:
                    cm[ci] = m.group(1)
            if len(cm) > len(best_col_map):
                best_col_map, best_hdr_idx = cm, ri

        if best_hdr_idx < 0:
            self.stdout.write("No subject-code header row found!")
            return

        self.stdout.write(f"Header row: {best_hdr_idx}   codes: {list(best_col_map.values())}")
        self.stdout.write(f"Header row content: {raw_rows[best_hdr_idx]}")

        # Show ±2 rows
        for ri in range(max(0, best_hdr_idx - 2), min(len(raw_rows), best_hdr_idx + 6)):
            has_sid = any(_is_student_id(c.strip()) for c in raw_rows[ri])
            tag = "[STUDENT]" if has_sid else ""
            self.stdout.write(f"  row[{ri}] {tag}: {raw_rows[ri]}")

        # Show per-column values for first 5 student rows
        self.stdout.write("\nPer-subject column values (first 5 students):")
        count = 0
        for ri, row in enumerate(raw_rows):
            if ri == best_hdr_idx:
                continue
            if not any(_is_student_id(c.strip()) for c in row):
                continue
            sid = next(c.strip() for c in row if _is_student_id(c.strip()))
            self.stdout.write(f"\n  Student {sid} (row {ri}):")
            for ci, code in best_col_map.items():
                # Show col_i and up to 4 columns to the right
                vals = []
                for off in range(5):
                    idx = ci + off
                    v = row[idx].strip() if idx < len(row) else ""
                    vals.append(f"col{idx}={v!r}")
                self.stdout.write(f"    {code}: {', '.join(vals)}")
            count += 1
            if count >= 5:
                break
