# CLARA.AI: LLM-Powered Academic Administrator

> **An AI-Driven Intelligent Academic Administration Platform**
> Sri Shakthi Institute of Engineering and Technology, Coimbatore, India

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [System Architecture](#3-system-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Module Breakdown](#5-module-breakdown)
6. [Data Models & Schema](#6-data-models--schema)
7. [AI/LLM Pipeline](#7-aillm-pipeline)
8. [Workflow & User Journeys](#8-workflow--user-journeys)
9. [Role-Based Access Control (RBAC)](#9-role-based-access-control-rbac)
10. [API & Endpoint Reference](#10-api--endpoint-reference)
11. [RAG (Retrieval-Augmented Generation) Pipeline](#11-rag-retrieval-augmented-generation-pipeline)
12. [Key Algorithms & Engineering Decisions](#12-key-algorithms--engineering-decisions)
13. [Deployment Architecture](#13-deployment-architecture)
14. [Future Roadmap](#14-future-roadmap)

---

## 1. Executive Summary

**CLARA.AI** is a full-stack, AI-powered academic administration platform built on Django that automates and augments three critical institutional workflows:

| Capability | Description |
|---|---|
| **AI Circular Generator** | Auto-drafts official circulars (holiday notices, exam schedules, event announcements) using a local LLM (Ollama/Llama 3.1), overlaid on uploaded institutional letterhead templates |
| **Intelligent Academic Analytics** | Parses PDF/CSV mark sheets via coordinate-based table extraction + LLM metadata enrichment, stores structured results in PostgreSQL, and answers natural language queries about academic performance with chart/table/paragraph responses |
| **Unified Database Management** | Manages Students, Staff, Departments, Subjects, and Users with a four-tier RBAC system (Admin, Principal, Dean, HOD) |

The system runs **entirely on-premise** using a local Ollama LLM server — no student data leaves the institution's network.

---

## 2. Problem Statement

Indian engineering colleges face several administrative bottlenecks:

- **Circular drafting** is repetitive — the same holiday/exam/meeting notice is formatted year after year, yet each requires manual effort.
- **Mark sheet data entry** from university PDFs into internal databases is a manual, error-prone process involving thousands of rows per semester.
- **Academic performance analysis** relies on spreadsheets with no natural language interface — HODs and Deans must manually compute pass rates, toppers, and at-risk students.
- **Access control** across administrative roles is typically ad-hoc, with no unified system governing who can view/edit what.

CLARA.AI addresses all four problems through a single integrated platform.

---

## 3. System Architecture

### 3.1 High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                             │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  Login   │  │  Dashboard   │  │  Analytics   │  │ Circular   │  │
│  │  Page    │  │  (Role-based)│  │  Chat UI     │  │ Generator  │  │
│  └────┬─────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │
│       │               │                │                  │         │
└───────┼───────────────┼────────────────┼──────────────────┼─────────┘
        │               │                │                  │
        ▼               ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DJANGO APPLICATION SERVER                       │
│                                                                     │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │  users   │  │   pages   │  │ students  │  │    circulars     │  │
│  │  app     │  │   app     │  │   app     │  │      app         │  │
│  └────┬─────┘  └─────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │
│       │              │              │                  │             │
│  ┌────┴──────────────┴──────────────┴──────────────────┴──────────┐  │
│  │                    SHARED UTILITIES (utils/)                    │  │
│  │  ┌────────────┐  ┌─────────────┐  ┌───────────┐  ┌──────────┐ │  │
│  │  │analytics_ai│  │pdf_extraction│  │chroma_rag │  │festival_ │ │  │
│  │  │   .py      │  │    .py       │  │   .py     │  │dates.py  │ │  │
│  │  └─────┬──────┘  └──────┬──────┘  └─────┬─────┘  └──────────┘ │  │
│  └────────┼─────────────────┼───────────────┼─────────────────────┘  │
│           │                 │               │                        │
│  ┌────────┴─────────────────┴───────────────┴──────────────────────┐ │
│  │                    LLM CLIENT (aa/llm_client.py)                │ │
│  │              call_llm()  /  call_llm_chat()                     │ │
│  └──────────────────────────┬──────────────────────────────────────┘ │
│                             │                                        │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌───────────────────┐ ┌─────────────┐ ┌───────────────────┐
│  PostgreSQL DB    │ │ Ollama LLM  │ │  ChromaDB Vector  │
│  (DADDY_DB)       │ │ Server      │ │  Store             │
│                   │ │ localhost   │ │  (chroma_db_       │
│  • users          │ │  :11434     │ │   storage/)        │
│  • students       │ │             │ │                    │
│  • staff          │ │ Models:     │ └───────────────────┘
│  • departments    │ │ • llama3.1  │
│  • subjects       │ │   :8b      │
│  • subject_results│ │ • llama3.2  │
│  • end_semester   │ │   :3b      │
│  • semesters      │ │             │
│  • circulars      │ └─────────────┘
└───────────────────┘
```

### 3.2 Request-Response Flow

```
Browser Request
     │
     ▼
Django URL Router (aa/urls.py)
     │
     ├──→ users/    → Authentication, User/Department CRUD (Admin)
     ├──→ pages/    → Dashboard with AI-powered system insights
     ├──→ students/ → Student DB, Academic Analytics, Chat API, PDF Analysis
     ├──→ staff/    → Staff Directory (CRUD for Admin, read-only for others)
     └──→ circulars/→ Circular Generator + Template Management
```

---

## 4. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend Framework** | Django 4.2 + Django REST Framework | Web framework, ORM, authentication |
| **Database** | PostgreSQL (via psycopg2) | Primary relational data store |
| **LLM Inference** | Ollama (localhost:11434) | Local LLM serving |
| **LLM Models** | Llama 3.1 (8B) — heavy reasoning | PDF metadata extraction, NLP queries, circular drafting |
| | Llama 3.2 (3B) — lightweight | Dashboard insights (low-latency) |
| **PDF Processing** | PyMuPDF (fitz) | Coordinate-based text/image extraction from PDFs |
| **Vector Database** | ChromaDB | Persistent vector storage for RAG |
| **Embeddings** | sentence-transformers (all-mpnet-base-v2) | Text embeddings for semantic search |
| **Vision Model** | CLIP (ViT-Base-Patch32) | Image embeddings for multimodal RAG |
| **Image Processing** | Pillow (PIL) | Image manipulation for circulars and extracted images |
| **Password Security** | bcrypt | Cloud DB password hashing and verification |
| **Frontend** | Django Templates + Vanilla CSS/JS | Server-side rendered UI |
| **Environment** | python-dotenv | Secure environment variable management |

---

## 5. Module Breakdown

### 5.1 `users` — Authentication & User Management

```
users/
├── models.py          # CustomUser (Django auth) + UserProfile (cloud DB role table)
├── backends.py        # EmailBackend — dual auth: Django hash + bcrypt cloud DB hash
├── views.py           # User CRUD (add/edit/delete/change-password), Department CRUD
├── context_processors.py  # Injects user_role, user_profile into all templates
├── forms.py           # Login form customization
└── urls.py            # /login, /logout, /manage/*, /departments/*
```

**Key Design Decision**: The system maintains *two* user tables:
- `CustomUser` (Django's auth table) — handles session/authentication
- `UserProfile` (cloud `users` table, `managed=False`) — stores roles, institution links, bcrypt password hashes

The `EmailBackend` authenticates against *both*: Django's password hash first (for superusers), then the cloud DB's bcrypt hash (for regular users).

### 5.2 `pages` — Dashboard & System Insights

```
pages/
├── views.py    # home() — role-based dashboard with AI insight
└── utils.py    # get_system_insight() → upcoming holiday detection + LLM insight
```

**AI-Powered System Insight**: On every dashboard load, the system:
1. Scans a verified festival/holiday calendar (2024–2028) for events within 30 days
2. Calls the lightweight LLM (Llama 3.2:3b) with a 5-second timeout to generate a one-line advisory
3. Displays: *"Diwali (October 20) — in 5 days. Circular draft recommended."*

### 5.3 `students` — Academic Data & Analytics Engine

```
students/
├── models.py              # Department, Student, Semester, ProgramSemester, Subject,
│                          # SubjectResult, SemesterSummary, EndSemesterResult,
│                          # AnalyzedDocument, DocumentAnalysisResult, RAGIndexMetadata
├── views.py               # Student CRUD, Academic Analytics views, Subject CRUD,
│                          # Marks CRUD APIs, Section assignment
├── views_chat.py          # AI chat endpoint (POST /students/analytics/chat/)
├── views_pdf_analysis.py  # PDF upload/analysis/RAG query pipeline
└── urls.py                # 30+ URL patterns for all student/analytics operations
```

This is the largest and most complex module — the heart of the system.

### 5.4 `circulars` — AI Circular Generator

```
circulars/
├── models.py   # Circular (text content) + CircularTemplate (letterhead images)
├── views.py    # Generator UI, template upload, AI content generation, save/delete
└── urls.py     # /circulars/, /save/, /generate-ai/, /template/upload/
```

**6 Pre-built Template Types**:
| Type | Use Case |
|---|---|
| `holiday` | Festival/national holiday notice with auto-date lookup |
| `exam` | Examination schedule notification |
| `meeting` | Staff/department meeting circular |
| `disciplinary` | Formal warning/code of conduct notice |
| `event` | Event/function announcement |
| `general` | Free-form announcement |

#### 5.4.1 Circular Generation Backend Flow

The circular generator is a server-rendered Django workflow backed by two models and a small set of views. It supports two generation modes:

1. **Template-based quick generation** (holiday, exam, meeting, etc.)
2. **AI-assisted generation** (LLM-generated body with a strict SIET format)

The generated content is always saved in the database only when the user clicks **Save & Approve**.

#### 5.4.2 Models Used

**`CircularTemplate`** (letterhead image + margins)

- Stores the uploaded template image (logo/header/signature).
- One template is marked **active** per user at any time.
- Provides `content_top_margin` and `content_bottom_margin` to control the printable text area in mm.

**`Circular`** (saved circular text)

- Stores the full circular text that includes:
     - `Ref : ...` line
     - `CIRCULAR` heading
     - `Subject: ...` line
     - Body content
     - `Copy to:` block
- Saved only on explicit approval by the user.

#### 5.4.3 Views and Backend Logic

**`upload_template()`**

- Validates template image type and size.
- Stores as `CircularTemplate` with margins.
- Deactivates previous template for the same user.

**`generator_view()`**

- Loads recent history (last 10 circulars) from DB for the current user.
- Ensures an active template exists; otherwise, redirects to upload.
- If a template type is requested, generates a circular using the predefined format.
- If `auto_holiday` is used, resolves festival dates using `utils.festival_dates`.

**`generate_ai_content()`** (AJAX)

- Calls the local LLM (Ollama) through `aa/llm_client.py`.
- Uses a strict system prompt so the model returns a clean body only.
- Injects:
     - `Ref : ...` line
     - `CIRCULAR` heading
     - `Subject: <title>` line
     - `Copy to:` block
- Returns JSON with `content` and extracted `title`.

**`save_circular()`**

- Serializes the editor content into a single text blob.
- Saves a new `Circular` record in the DB.
- Redirects to the generator view, which reloads recent history from DB.

**`delete_circular()`**

- Deletes the selected `Circular` record in the DB.
- Redirects to the generator view so Recent reflects DB state.

#### 5.4.4 Rendering and Editor Behavior

- `templates/circulars/generator.html` parses the stored text and renders structured sections.
- Bold formatting is applied to:
     - `Ref : ...` line
     - Date
     - `Subject: ...` line
     - `Copy to:` label
- The **Recent** dropdown is always a live reflection of DB records.
- Deleting from Recent submits a POST to the delete endpoint and refreshes the list.

#### 5.4.5 Print Output Rules

- A strict print-only layout hides the UI and outputs only the A4 circular page.
- The template image is positioned behind the content with `object-fit: cover`.
- Content margins follow the template settings (top/bottom in mm, left/right fixed).

### 5.5 `staff` — Staff Directory Management

```
staff/
├── models.py   # Staff (maps to cloud 'staff' table, managed=False)
├── views.py    # Department list, staff list (search, filter, paginate),
│               # staff add/edit/delete (Admin-only for writes)
└── urls.py     # /staff/, /staff/<dept_id>/, /staff/add/, etc.
```

### 5.6 `utils` — Shared AI & Data Services

```
utils/
├── analytics_ai.py     # AnalyticsAI engine (3400+ lines) — PDF/CSV parsing,
│                       # NLP query answering, data mutation, chart generation
├── pdf_extraction.py   # PDFExtractor (PyMuPDF) + AcademicDataParser
├── chroma_rag.py       # ChromaRAGDB — multimodal vector search (text + CLIP images)
└── festival_dates.py   # Verified Indian holiday/festival calendar (2024-2028)
```

### 5.7 `aa` — Project Configuration

```
aa/
├── settings.py     # Django config, PostgreSQL, auth backends, static/media paths
├── llm_client.py   # Centralized Ollama client: call_llm() + call_llm_chat()
├── urls.py         # Root URL router
└── wsgi.py / asgi.py
```

---

## 6. Data Models & Schema

### 6.1 Entity-Relationship Diagram

```
┌──────────────┐     ┌──────────────┐     ┌───────────────────┐
│  Department  │     │   Semester   │     │  ProgramSemester  │
│──────────────│     │──────────────│     │───────────────────│
│ id (UUID)    │     │ number (PK)  │     │ id (UUID)         │
│ name         │◄────│ name         │◄────│ semester (FK)     │
│ full_name    │     │ year         │     │ batch_year        │
│ college_code │     └──────────────┘     │ status            │
│ is_active    │                          │  (upcoming/active/│
└──────┬───────┘                          │   completed)      │
       │                                  └───────────────────┘
       │
       │ department_id
       ▼
┌──────────────────┐       ┌──────────────────┐
│     Student      │       │     Subject      │
│──────────────────│       │──────────────────│
│ id (UUID)        │       │ code (PK)        │
│ roll_number      │       │ name             │
│ student_name     │       │ department (FK)  │
│ department_id    │       │ semester (FK)    │
│ registration_no  │       │ credits          │
│ section (A/B/C)  │       └────────┬─────────┘
│ batch_year       │                │
│ gender, DOB, ... │                │
└────────┬─────────┘                │
         │                          │
         │    ┌─────────────────────┘
         │    │
         ▼    ▼
┌────────────────────┐     ┌──────────────────────┐
│   SubjectResult    │     │  EndSemesterResult   │
│────────────────────│     │──────────────────────│
│ id (UUID)          │     │ id (UUID)            │
│ student (FK)       │     │ student (FK)         │
│ subject (FK)       │     │ subject (FK)         │
│ internal1          │     │ marks                │
│ internal2          │     │ max_marks            │
│ internal3          │     │ grade                │
│ internal1_absent   │     │ grade_points         │
│ internal2_absent   │     │ result_status        │
│ internal3_absent   │     │  (PASS/FAIL/AB/WH)   │
│ end_sem_marks      │     └──────────────────────┘
│ grade              │
│ grade_points       │
└────────────────────┘

┌──────────────────┐     ┌────────────────────────┐
│   UserProfile    │     │   CircularTemplate     │
│──────────────────│     │────────────────────────│
│ id (UUID)        │     │ user (FK → CustomUser) │
│ full_name        │     │ name                   │
│ email            │     │ template_image         │
│ password_hash    │     │ content_top_margin     │
│ role (ADMIN/     │     │ content_bottom_margin  │
│  PRINCIPAL/DEAN/ │     │ is_active              │
│  HOD)            │     └────────────────────────┘
│ department_id    │
│ institution_id   │     ┌────────────────────────┐
└──────────────────┘     │      Circular          │
                         │────────────────────────│
┌──────────────────┐     │ user (FK)              │
│      Staff       │     │ title                  │
│──────────────────│     │ content                │
│ id (UUID)        │     │ category (holiday/     │
│ department_id    │     │   manual)              │
│ name             │     └────────────────────────┘
│ designation      │
│ employee_code    │
│ qualification    │
│ specialization   │
└──────────────────┘
```

### 6.2 Key Design Patterns

- **`managed = False`**: Student, Staff, Department, and UserProfile models map to pre-existing cloud database tables — Django never alters them via migrations.
- **Dual Result Tables**: Internal marks (`SubjectResult`) and end-semester results (`EndSemesterResult`) are stored separately, reflecting the two-phase Indian university exam cycle.
- **UUID Primary Keys**: All entities use UUIDs to match the cloud database schema.
- **Batch-Year Partitioning**: Data is partitioned by `batch_year` (e.g., "2024") for performance and access control.

---

## 7. AI/LLM Pipeline

### 7.1 Centralized LLM Client (`aa/llm_client.py`)

```python
# Two model tiers for different use cases:
MAIN_MODEL  = "llama3.1:8b"   # Heavy reasoning (PDF parsing, NLP queries, circular drafting)
LIGHT_MODEL = "llama3.2:3b"   # Fast/lightweight (dashboard insights — 5s timeout)

# Two API modes:
call_llm(prompt, system_prompt, ...)          # /api/generate — simple completions
call_llm_chat(user_message, system_prompt, ...)  # /api/chat — instruction-following
```

### 7.2 PDF Mark Sheet Parsing Pipeline

This is the most sophisticated AI pipeline in the system. It processes university mark sheets (PDFs with complex tabular layouts) into structured database records.

```
PDF Upload (via Chat UI or PDF Analysis page)
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│  STEP 0: FULL DOCUMENT PRE-SCAN                            │
│  ─────────────────────────────                             │
│  • Read ENTIRE PDF before extracting any data              │
│  • Detect subject legend/mapping tables Code→Name→Credits) │
│  • Identify mark type (internal CIA vs end-semester)       │
│  • Collect all subject codes across every page             │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│  STEP 1: COORDINATE-BASED TABLE PARSING                    │
│  ──────────────────────────────────────                    │
│  Two parser strategies tried in order:                     │
│                                                            │
│  Strategy A: Vertical Layout Parser                        │
│  (One student per section, subjects as rows)               │
│  ┌─────────────────────────────────────────┐               │
│  │ STUDENT: 24AD001   Name: John Doe       │               │
│  │ S.No │ Code    │ Grade │ GP │ Credits   │               │
│  │ 1    │ 21AD101 │ A+    │ 9  │ 4         │               │
│  │ 2    │ 21CS101 │ O     │ 10 │ 3         │               │
│  └─────────────────────────────────────────┘               │
│                                                            │
│  Strategy B: Horizontal Layout Parser (most common)        │
│  (Subjects as column headers, students as rows)            │
│  ┌───────────────────────────────────────────────────┐     │
│  │ Roll No │ 21AD101 │ 21CS101 │ 21EN101 │           │     │
│  │         │ Max CIA │ Max CIA │ Max CIA │           │     │
│  │ 24AD001 │ 50  45  │ 50  48  │ 50  38  │           │     │
│  │ 24AD002 │ 50  42  │ 50  35  │ 50  41  │           │     │
│  └───────────────────────────────────────────────────┘     │
│                                                            │
│  Key Algorithm: _page_rows() + _find_header_row()          │
│  → Groups words by Y-coordinate into rows                  │
│  → Identifies subject-code header row via regex            │
│  → Maps each column X-position to a subject code           │
│  → Detects sub-columns (CIA/Max/Att%) to isolate marks     │
│  → Uses statistical bucketing to distinguish marks from    │
│    attendance percentages (Pass A/B/C algorithm)           │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│  STEP 2: LLM METADATA ENRICHMENT                           │
│  ────────────────────────────────                          │
│  Send header text + legend text to Ollama (llama3.1:8b)    │
│  LLM extracts:                                             │
│  • mark_type: "internal" or "end_semester"                 │
│  • internal_number: 1, 2, or 3                             │
│  • subjects: [{code, name, credits}]                       │
│  Temperature: 0.0 (deterministic)                          │
│  Context window: 8192 tokens                               │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│  STEP 3: SMART MERGE (Priority Chain)                      │
│  ────────────────────────────────────                      │
│  Subject names resolved with 3-tier priority:              │
│                                                            │
│  P1: Document legend table (highest trust)                 │
│      → e.g., "21AD101 — Fundamentals of AI" from the PDF   │
│                                                            │
│  P2: Coordinate parser names (from inline headers)         │
│      → Cleaned: teacher names, noise words stripped        │
│      → Validated: hallucination detection applied          │
│                                                            │
│  P3: LLM-generated names (only fills gaps)                 │
│      → Guardrailed: cleaned + hallucination-checked        │
│                                                            │
│  AI NEVER auto-creates subjects in the database.           │
│  Unknown codes are reported; user must add them first.     │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│  STEP 4: DATABASE COMMIT                                   │
│  ───────────────────────                                   │
│  • Match roll numbers to Student records (exact match only)│
│  • Match subject codes to Subject records (must pre-exist) │
│  • Internal marks → SubjectResult (internal1/2/3 fields)   │
│  • End-sem results → EndSemesterResult (grade, GP, status) │
│  • Auto-update ProgramSemester status:                     │
│    CIA upload: upcoming → active                           │
│    End-sem upload: active → completed; next sem → active   │
│  • Recompute SGPA in SemesterSummary                       │
└────────────────────────────────────────────────────────────┘
```

### 7.3 Natural Language Query (NLPQ) Pipeline

```
User types a question in the Analytics Chat Bar
     │
     ▼
┌─────────────────────────────────────────────────────┐
│  STEP 0: REFERENCE RESOLUTION                       │
│  Expand pronouns/references using conversation      │
│  history (last 6 messages):                         │
│  "What about them?" → "What about students who      │
│   failed in 21AD101?"                               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  STEP 1: DETERMINISTIC DIRECT QUERY ENGINE          │
│  15 regex-matched intent handlers (100% accurate):  │
│                                                     │
│  1.  Failed / arrears / grade U                     │
│  2.  Top N / bottom N / class topper                │
│  3.  Average / mean                                 │
│  4.  How many / count                               │
│  5.  Pass rate / fail rate                          │
│  6.  Chart / graph / visualization                  │
│  7.  All marks for a subject                        │
│  8.  Marks of a specific student                    │
│  9.  Stats / statistics / summary                   │
│  10. Threshold filter (below/above X)               │
│  11. Grade distribution                             │
│  12. Improvement / drop between CIA rounds           │
│  13. Percentile / quartile                          │
│  14. At-risk students (multi-subject failures)       │
│  15. Median / std deviation / variance              │
│                                                     │
│  → Returns: tables, charts, or paragraphs directly  │
│  → Zero LLM calls = instant + 100% accurate         │
└──────────────────────┬──────────────────────────────┘
                       │ (if no direct handler matches)
                       ▼
┌─────────────────────────────────────────────────────┐
│  STEP 2: LLM COMPUTE ENGINE                         │
│  For complex/custom queries that no handler covers:  │
│                                                     │
│  1. Fetch real DB data (marks, students, subjects)  │
│  2. Build a prompt with the actual dataset           │
│  3. Ask LLM to write Python analysis code            │
│  4. Execute code in a sandboxed environment          │
│  5. Return computed results                          │
│                                                     │
│  Key: LLM generates LOGIC, not DATA                 │
│  → Always operates on real DB data                  │
│  → Never hallucinates student/mark values            │
└─────────────────────────────────────────────────────┘
```

### 7.4 AI Circular Generation Pipeline

```
User selects circular type (e.g., "Holiday")
     │
     ├── Auto-fills: occasion, date (from festival_dates.py)
     ├── Generates: circular number (SIET/AD/2025-2026/01)
     │
     ▼
┌──────────────────────────────────────────────────┐
│  Template Rendering                               │
│  Pre-built template with placeholders:            │
│  {circular_no}, {date}, {holiday_date},           │
│  {occasion}, {copy_to}                            │
└──────────────────────┬───────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌────────────────────────┐
│  Quick Generate  │    │  AI-Enhanced Generate   │
│  (template only) │    │  call_llm_chat() with   │
│                  │    │  system prompt:          │
│                  │    │  "You are a formal       │
│                  │    │   institutional circular │
│                  │    │   writer..."             │
│                  │    │  → LLM refines language  │
│                  │    │  → Adds contextual detail│
└──────────────────┘    └────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│  Output: Circular text overlaid on uploaded       │
│  letterhead template (PNG/JPEG) with:             │
│  • Configurable content_top_margin (mm)           │
│  • Configurable content_bottom_margin (mm)        │
│  → Produces print-ready A4 circular               │
└──────────────────────────────────────────────────┘
```

### 7.5 Dashboard AI Insight Pipeline

```
Dashboard page loads (pages/views.py → home())
     │
     ▼
┌──────────────────────────────────────────────────┐
│  get_upcoming_events(days_ahead=30)               │
│  • Scans FIXED_HOLIDAYS + VARIABLE_FESTIVALS     │
│    for the current year (verified calendar)       │
│  • Returns sorted list of upcoming events         │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│  generate_ai_insight(upcoming_events)             │
│  • Picks the nearest event                        │
│  • Calls LIGHT_MODEL (llama3.2:3b)                │
│  • Timeout: 5 seconds                             │
│  • Max tokens: 40                                 │
│  • Fallback: static text if LLM is unavailable    │
│                                                   │
│  Result: "Diwali (Oct 20) — in 5 days.            │
│           Circular draft recommended."             │
└──────────────────────────────────────────────────┘
```

---

## 8. Workflow & User Journeys

### 8.1 Principal/Dean Journey: End-to-End Semester Management

```
1. LOGIN (email + password → dual auth backend)
   │
2. DASHBOARD
   │  AI insight: "Republic Day (Jan 26) — in 3 days"
   │  [Generate Circular] button → pre-filled holiday notice
   │
3. CIRCULAR GENERATOR
   │  Select "Holiday" → auto-fills Republic Day date
   │  Click "Generate with AI" → LLM drafts formal notice
   │  Review → Save → generates print-ready circular on letterhead
   │
4. ACADEMIC ANALYTICS
   │  Select Department → Select Batch → Select Semester
   │
   ├── SUBJECTS TAB: Define subjects (code, name, credits)
   │
   ├── UPLOAD MARKS: Drag-drop CIA PDF into chat bar
   │   → PDF parsed → marks written to SubjectResult table
   │   → "Imported 180 records for 6 subjects. 12 skipped (not in batch)."
   │
   ├── ASK QUESTIONS (NLP Chat):
   │   "Who are the top 5 students in 21AD101?"
   │   → Table: rank, roll_no, name, marks
   │
   │   "Show grade distribution as a pie chart"
   │   → Interactive pie chart rendered in browser
   │
   │   "Which students failed in more than 2 subjects?"
   │   → At-risk student list with arrear counts
   │
   ├── UPLOAD END-SEM RESULTS: Drop end-semester PDF
   │   → Parsed into EndSemesterResult table (grade, GP, status)
   │   → ProgramSemester auto-advances: Sem 3 → completed, Sem 4 → active
   │   → SGPA recomputed for all students
   │
5. STAFF DIRECTORY (view-only for Principal/Dean)
   │  Browse by department → search by name/designation
   │
6. STUDENT DB
   │  Add/edit students, assign sections (A/B/C)
   │  View individual student profiles
```

### 8.2 HOD Journey

```
LOGIN → DASHBOARD (limited features)
  │
  ├── ACADEMIC ANALYTICS (own department only)
  │   • Upload marks for department's students
  │   • Query analytics via NLP chat
  │   • Manage subjects
  │
  ├── STUDENT DB (own department only)
  │   • Add/edit students
  │   • View student details
  │
  └── ✗ NO access to: Circular Generator, Staff DB, other departments
```

### 8.3 Admin Journey

```
LOGIN → DASHBOARD
  │
  ├── USER MANAGEMENT
  │   • Add users (HOD, Dean, Principal)
  │   • Edit user details / change passwords
  │   • Assign departments to HODs
  │
  ├── DEPARTMENT MANAGEMENT
  │   • Create/edit/delete departments
  │
  ├── STAFF DATABASE (full CRUD)
  │   • Add/edit/delete staff records
  │   • Cross-department access
  │
  └── ✗ NO access to: Circular Generator, AI features, Analytics
```

---

## 9. Role-Based Access Control (RBAC)

### 9.1 Permission Matrix

| Feature | ADMIN | PRINCIPAL | DEAN | HOD |
|---|:---:|:---:|:---:|:---:|
| **User Management** (CRUD) | ✅ | ❌ | ❌ | ❌ |
| **Department Management** | ✅ | ❌ | ❌ | ❌ |
| **Staff DB — View** | ✅ | ✅ | ✅ | ✅ (own dept) |
| **Staff DB — Edit/Delete** | ✅ | ❌ | ❌ | ❌ |
| **Student DB — View** | ✅ | ✅ | ✅ | ✅ (own dept) |
| **Student DB — Add/Edit** | ✅ | ✅ | ✅ | ✅ (own dept) |
| **Student DB — Delete** | ✅ | ✅ | ✅ | ❌ |
| **Circular Generator** | ❌ | ✅ | ✅ | ❌ |
| **AI Features** | ❌ | ✅ | ✅ | ❌ |
| **Analytics — All Depts** | ❌ | ✅ (by dept) | ✅ (by batch) | ❌ |
| **Analytics — Own Dept** | ❌ | ✅ | ✅ | ✅ |

### 9.2 Implementation Pattern

Every view follows a consistent guard pattern:

```python
@login_required
def some_view(request):
    user_profile = UserProfile.get_by_email(request.user.email)
    
    if not user_profile or not user_profile.can_<action>():
        return render(request, 'access_denied.html', {...})
    
    # HOD scope restriction
    if user_profile.role == UserProfile.Role.HOD:
        if str(user_profile.department_id) != str(department_id):
            return render(request, 'access_denied.html', {...})
    
    # ... proceed with authorized logic
```

---

## 10. API & Endpoint Reference

### 10.1 Authentication

| Method | URL | Description |
|---|---|---|
| GET/POST | `/login/` | Email-based login (Django LoginView) |
| GET | `/logout/` | Session logout + redirect |

### 10.2 Dashboard

| Method | URL | Description |
|---|---|---|
| GET | `/pages/home/` | Role-based dashboard with AI insight |

### 10.3 User Management (Admin)

| Method | URL | Description |
|---|---|---|
| GET | `/manage/` | User list dashboard |
| POST | `/manage/add/` | Create new user |
| POST | `/manage/edit/<uuid>/` | Update user details |
| POST | `/manage/password/<uuid>/` | Change user password |
| POST | `/manage/delete/<uuid>/` | Delete user |

### 10.4 Student Database

| Method | URL | Description |
|---|---|---|
| GET | `/students/` | Department list |
| GET | `/students/<dept_id>/` | Batch list for department |
| GET | `/students/<dept_id>/<batch>/` | Student list |
| GET | `/students/detail/<student_id>/` | Student detail view |
| POST | `/students/add/` | Add new student |
| POST | `/students/edit/<student_id>/` | Edit student |

### 10.5 Academic Analytics

| Method | URL | Description |
|---|---|---|
| GET | `/students/analytics/` | Analytics entry point |
| GET | `/students/analytics/<dept_id>/` | Department batches |
| GET | `/students/analytics/<dept_id>/batch/<year>/` | Batch semesters |
| GET | `/students/analytics/<dept_id>/batch/<year>/sem/<n>/` | Semester details |
| **POST** | **`/students/analytics/chat/`** | **AI Chat API** (NLPQ + PDF import + mutations) |

### 10.6 Analytics Chat API (Core AI Endpoint)

**POST** `/students/analytics/chat/`

Accepts `multipart/form-data` or JSON:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `department_id` | UUID | ✅ | Target department |
| `batch_year` | string | ✅ | e.g., "2024" |
| `semester_number` | int | ✅ | e.g., 3 |
| `message` | string | ❌ | NLP query text |
| `file` | File | ❌ | PDF or CSV mark sheet |
| `history` | JSON | ❌ | Conversation history array |
| `internal_override` | int | ❌ | Force internal number (1/2/3) |

**Response Types**:

```json
// PDF Import
{"type": "pdf_import", "success": true, "summary": "...", "rows_inserted": 180, ...}

// NLP Query
{"type": "nlpq", "format": "table|paragraph|chart", "answer": "...", "data": [...]}

// Data Mutation
{"type": "mutation", "success": true, "action": "update", "affected": 5, ...}
```

### 10.7 Circular Generator

| Method | URL | Description |
|---|---|---|
| GET | `/circulars/` | Generator UI |
| POST | `/circulars/save/` | Save circular |
| POST | `/circulars/generate-ai/` | AI content generation |
| POST | `/circulars/template/upload/` | Upload letterhead |
| POST | `/circulars/template/delete/` | Delete letterhead |

### 10.8 Staff Database

| Method | URL | Description |
|---|---|---|
| GET | `/staff/` | Department list |
| GET | `/staff/<dept_id>/` | Staff list (search/filter/paginate) |
| POST | `/staff/add/` | Add staff (Admin only) |
| POST | `/staff/edit/<staff_id>/` | Edit staff (Admin only) |
| POST | `/staff/delete/<staff_id>/` | Delete staff (Admin only) |

---

## 11. RAG (Retrieval-Augmented Generation) Pipeline

### 11.1 Multimodal Document Ingestion

```
PDF Document
     │
     ├── TEXT PATH:
     │   PDFExtractor.extract()
     │   → Page-by-page text extraction (PyMuPDF)
     │   → Hierarchical smart chunking:
     │       1. Split into paragraphs (double-newline boundary)
     │       2. Split into sentences
     │       3. Sliding window chunks (420 tokens, 120 overlap)
     │   → Encode with all-mpnet-base-v2 (SentenceTransformer)
     │   → Store in ChromaDB collection: "batch_{id}_sem_{id}"
     │
     └── IMAGE PATH:
         PDFExtractor.extract()
         → Image extraction (PyMuPDF xref)
         → Convert to RGB (PIL)
         → Encode with CLIP (ViT-Base-Patch32)
         → Store in same ChromaDB collection (type="image")
```

### 11.2 Semantic Query

```
User text query
     │
     ▼
SentenceTransformer.encode(query)
     │
     ▼
ChromaDB.query(embedding, top_k=10)
     │
     ▼
Retrieved chunks (text + associated images)
     │
     ▼
Feed to LLM as context → Generate answer
```

---

## 12. Key Algorithms & Engineering Decisions

### 12.1 PDF Table Parsing — Sub-Column Detection

Indian university PDFs often have per-subject sub-columns (Max | Marks | Att%). Without sub-column awareness, the parser reads the wrong value. The system uses a multi-pass algorithm:

1. **Header Row Detection**: Regex matches subject codes (e.g., `21AD101`) to find the header row and map X-positions to subject codes.
2. **Sub-Column Label Scan**: Check 2-3 rows below the header for labels like "MARK", "CIA", "ATT%", "MAX".
3. **Statistical Bucketing** (when no labels exist): Group numeric values by X-position, then classify:
   - Constant buckets (≥75% same value) → Max-Marks column (skip)
   - Variable buckets with median > 75 → Attendance % (skip)
   - Remaining leftmost variable bucket → Actual marks ✓

### 12.2 Hallucination Prevention

The system implements multiple layers of hallucination prevention:

- **Subject names**: 3-tier priority chain (document legend > parser > LLM) with `_is_hallucinated_name()` validation
- **Subjects never auto-created**: The AI reports unknown subject codes but NEVER creates them — user must add manually
- **Student matching**: Exact roll/registration number matching only — NO fuzzy name matching
- **NLP queries**: 15 deterministic handlers tried first (100% accurate); LLM only used as fallback with real DB data
- **Mutation guard**: Regex detects write operations and routes them through a validated mutation pipeline

### 12.3 Dual Authentication Architecture

```
Login Request (email + password)
     │
     ▼
EmailBackend.authenticate()
     │
     ├── Try #1: Django's user.check_password()  ← for local superusers
     │   (Django PBKDF2 hash)
     │
     └── Try #2: UserProfile.password_hash        ← for cloud DB users
         (bcrypt hash → bcrypt.checkpw())
```

### 12.4 Semester Status Auto-Advancement

```
Mark Upload Event
     │
     ├── Internal marks uploaded → ProgramSemester: "upcoming" → "active"
     │
     └── End-semester uploaded → ProgramSemester: "active" → "completed"
                               → Next semester: "upcoming" → "active"
```

---

## 13. Deployment Architecture

### 13.1 On-Premise Deployment

```
┌──────────────────────────────────────────────────┐
│                INSTITUTION SERVER                 │
│                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Django     │  │   Ollama    │  │PostgreSQL│ │
│  │   App Server │  │   LLM      │  │  Database│ │
│  │   :8000      │  │   :11434   │  │  :5432   │ │
│  └─────────────┘  └─────────────┘  └──────────┘ │
│                                                  │
│  ┌─────────────┐  ┌──────────────────────────┐   │
│  │  ChromaDB   │  │  File Storage            │   │
│  │  (local dir)│  │  • media/ (templates)    │   │
│  └─────────────┘  │  • langbase_json/ (PDFs) │   │
│                   └──────────────────────────┘   │
└──────────────────────────────────────────────────┘
            │
            │ (No external API calls)
            │ (All LLM inference is local)
            ▼
     Student data NEVER leaves the institution network
```

### 13.2 Environment Configuration

```
# .env file
DB_NAME=DADDY_DB
DB_USER=postgres
DB_PASSWORD=<secure>
DB_HOST=localhost
DB_PORT=5432
OLLAMA_URL=http://localhost:11434
OLLAMA_MAIN_MODEL=llama3.1:8b
OLLAMA_LIGHT_MODEL=llama3.2:3b
```

---

## 14. Future Roadmap

| Phase | Feature | Description |
|---|---|---|
| **v2.0** | Celery Task Queue | Async PDF processing with Redis for large batch uploads |
| **v2.0** | Attendance Module | Track and analyze student attendance patterns |
| **v2.1** | Parent Portal | Read-only access for parents to view their ward's performance |
| **v2.1** | WhatsApp Integration | Send circulars directly via WhatsApp Business API |
| **v3.0** | Predictive Analytics | Use historical data to predict at-risk students before exams |
| **v3.0** | Multi-Institution** | SaaS deployment supporting multiple colleges |

---

## Project Statistics

| Metric | Value |
|---|---|
| Total Python modules | 30+ |
| Lines of code (analytics_ai.py alone) | 3,400+ |
| Database tables | 12+ |
| URL endpoints | 50+ |
| Direct NLP query handlers | 15 |
| Supported circular types | 6 |
| Festival/holiday entries | 100+ (2024–2028) |
| RBAC roles | 4 (Admin, Principal, Dean, HOD) |
| LLM models used | 2 (Llama 3.1:8b, Llama 3.2:3b) |

---

> **CLARA.AI** — *Comprehensive LLM-powered Academic Resource Administrator.*
>
> Repository: [LLM-project-Team/CLARA](https://github.com/LLM-project-Team/CLARA.AI  )
