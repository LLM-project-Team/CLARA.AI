"""
Analytics Chat API
------------------
Handles the AI-powered chat bar inside the Academic Analytics feature.

Endpoints:
  POST /students/analytics/chat/   →  analytics_chat_api
"""

import json
import re
import traceback

from django.http import JsonResponse

from users.models import UserProfile


# Keywords that indicate a DB mutation (not a read/query)
_MUTATION_KEYWORDS = re.compile(
    r'\b(update|set|change|edit|modify|delete|remove|clear|reset)\b',
    re.IGNORECASE
)
_MARKS_CONTEXT = re.compile(
    r'\b(mark|marks|internal|grade|end\s*sem|cia|ia|ct|score|result)\b',
    re.IGNORECASE
)


def _is_mutation(message: str) -> bool:
    """Return True if this message looks like a DB-write command, not a query."""
    return bool(_MUTATION_KEYWORDS.search(message) and _MARKS_CONTEXT.search(message))


def analytics_chat_api(request):
    """
    Unified chat endpoint.

    Accepts multipart/form-data with:
      - department_id  (UUID)
      - batch_year     (str)
      - semester_number (int)
      - message        (str, optional – the NLP query)
      - file           (PDF, optional – mark sheet to import)

    Returns JSON:
      {
        "type": "pdf_import" | "nlpq",
        ... (format-specific fields, see below)
      }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)

    try:
        return _handle_chat(request)
    except Exception as exc:
        traceback.print_exc()   # log full traceback to server console
        return JsonResponse({"error": f"Server error: {exc}"}, status=500)


def _handle_chat(request):
    from utils.analytics_ai import AnalyticsAI  # late import to surface errors cleanly

    user_profile = UserProfile.get_by_email(request.user.email)
    if not user_profile or not user_profile.can_access_department_analytics():
        return JsonResponse({"error": "Permission denied."}, status=403)

    # ── Parse common params ────────────────────────────────────────────────────
    # Support both multipart (file upload) and JSON body (text query)
    department_id  = request.POST.get("department_id")  or _body_field(request, "department_id")
    batch_year     = request.POST.get("batch_year")     or _body_field(request, "batch_year")
    semester_raw   = request.POST.get("semester_number") or _body_field(request, "semester_number")
    message        = request.POST.get("message")        or _body_field(request, "message", "")
    uploaded_file  = request.FILES.get("file")
    internal_override_raw = request.POST.get("internal_override") or _body_field(request, "internal_override")
    try:
        internal_override = int(internal_override_raw) if internal_override_raw and internal_override_raw != 'auto' else None
    except (ValueError, TypeError):
        internal_override = None

    if not department_id or not batch_year or not semester_raw:
        return JsonResponse({"error": "department_id, batch_year, and semester_number are required."}, status=400)

    # HOD can only access their own department
    if user_profile.role == UserProfile.Role.HOD and str(user_profile.department_id) != str(department_id):
        return JsonResponse({"error": "Access restricted to your department."}, status=403)

    try:
        semester_number = int(semester_raw)
    except (ValueError, TypeError):
        return JsonResponse({"error": "semester_number must be an integer."}, status=400)

    ai = AnalyticsAI(
        department_id=department_id,
        batch_year=batch_year,
        semester_number=semester_number,
    )

    # ── Branch: file import (PDF or CSV) ─────────────────────────────────────
    if uploaded_file:
        fname = uploaded_file.name.lower()
        is_pdf = fname.endswith(".pdf")
        is_csv = fname.endswith(".csv")

        if not is_pdf and not is_csv:
            return JsonResponse({"error": "Only PDF and CSV files are supported."}, status=400)

        if uploaded_file.size > 20 * 1024 * 1024:  # 20 MB cap
            return JsonResponse({"error": "File too large (max 20 MB)."}, status=400)

        file_bytes = uploaded_file.read()

        if is_csv:
            result = ai.process_csv(file_bytes, uploaded_file.name, internal_override=internal_override)
        else:
            result = ai.process_pdf(file_bytes, uploaded_file.name, internal_override=internal_override)

        if "error" in result:
            return JsonResponse({"type": "pdf_import", "success": False, "error": result["error"]})

        return JsonResponse({
            "type":                "pdf_import",
            "success":             True,
            "summary":             result["summary"],
            "subjects_created":    [],                              # always empty now
            "subjects_not_found":  result.get("subjects_not_found", []),
            "subjects_existed":    result["subjects_existed"],
            "rows_inserted":       result["rows_inserted"],
            "rows_skipped":        result["rows_skipped"],
            "skip_reasons":        result.get("skip_reasons", {}),
            "mark_type":           result.get("mark_type", "internal"),
            "internal_number":     result.get("internal_number", 1),
            "pages_parsed":        result.get("pages_parsed", 1),
            "_debug":              result.get("_debug", {}),
        })

    # ── Branch: NLPQ or Mutation ──────────────────────────────────────────────
    if not message or not message.strip():
        return JsonResponse({"error": "Please enter a message or attach a PDF."}, status=400)

    msg = message.strip()

    # Parse conversation history (list of {role, content} dicts)
    history_raw = request.POST.get("history") or _body_field(request, "history", "[]")
    try:
        history = json.loads(history_raw) if isinstance(history_raw, str) else (history_raw or [])
        # Validate: must be a list of dicts with role+content
        if not isinstance(history, list):
            history = []
        history = [
            h for h in history
            if isinstance(h, dict) and 'role' in h and 'content' in h
        ][-20:]  # cap at last 20 entries
    except (json.JSONDecodeError, TypeError):
        history = []

    # Mutation path: update/delete/set/clear marks
    if _is_mutation(msg):
        result = ai.mutate_marks(msg)
        if "error" in result:
            return JsonResponse({"type": "mutation", "success": False, "error": result["error"]})
        return JsonResponse({
            "type":     "mutation",
            "success":  True,
            "action":   result.get("action", "update"),
            "affected": result.get("affected", 0),
            "detail":   result.get("detail", ""),
        })

    # Query path: answer a read-only question
    result = ai.answer_query(msg, history=history)
    return JsonResponse({"type": "nlpq", **result})


# ─── helper ───────────────────────────────────────────────────────────────────

def _body_field(request, key: str, default=None):
    """Try to read a field from a JSON request body (fallback when not multipart)."""
    try:
        data = json.loads(request.body)
        return data.get(key, default)
    except Exception:
        return default
