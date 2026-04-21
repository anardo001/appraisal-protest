# AGENTS.md

## Purpose
This repository houses the Dallas Appraisal Protest Helper, a public-facing demonstration application designed to help Dallas County homeowners discover comparable properties and generate evidence packages (PDF/HTML) for property tax protests.

## Project Structure Overview
- `backend/` - FastAPI Python backend. Handles SQLite DB queries, comp widening logic, and PDF/HTML generation.
  - `main.py` - Core API application and business logic.
- `frontend-vite/` - React frontend built with Vite. Implements a 4-step wizard interface.
  - `src/App.jsx` - Main application logic, state management, and UI screens.
- `dcad2026.db` - SQLite database (downloaded dynamically on startup, not stored in source control).
- `render.yaml` - Infrastructure-as-code for Render deployment.

## Task-Based Entry Points
- **UI/UX Changes:** `frontend-vite/src/App.jsx` (adjusting steps, layout, or frontend validation).
- **Comp Algorithm Adjustments:** `backend/main.py` -> `get_comps_data()`.
- **Evidence Formatting (PDF/HTML):** `backend/main.py` -> `evidence_html()` and `generate_pdf()`.
- **Database/Queries:** `backend/main.py` -> `get_subject()` and `property_lookup()`.
- **Deployment/Infra:** `render.yaml` or Render dashboard configurations.

## Source of Truth vs Generated Files
- **Source of truth:** `*.py`, `*.jsx`, `*.css`, `render.yaml`.
- **Generated/Ephemeral:** `frontend-vite/dist/` (build output), `dcad2026.db` (downloaded at runtime), `__pycache__/`, `node_modules/`.

## Validation Matrix
| Change Area | Validation Required |
| :--- | :--- |
| **Backend API / Logic** | Run FastAPI locally (`uvicorn main:app --reload`), test `/api/health`, verify DB downloads, test comp scoring. |
| **Frontend UI** | Run Vite dev server (`npm run dev`), walk through all 4 steps of the wizard. |
| **PDF Generation** | Generate a PDF via frontend Step 4, manually verify layout, margins, and data accuracy. |
| **Security/Inputs** | Verify HTML escaping for user inputs (`owner_name`) before rendering evidence HTML. |

## Coding Standards
- **Frontend:** React functional components, hooks (`useState`, `useEffect`, `useCallback`). Avoid complex global state (e.g., Redux) for this linear flow.
- **Backend:** FastAPI standard routing, raw SQLite queries using parameterized inputs (`?`). PEP8 style preferred.
- **Security:** Do not use `dangerouslySetInnerHTML` or raw `f-string` HTML generation without rigorous HTML escaping (e.g., `html.escape()`).

## Known Issues and Deferred Work
- **Security (Critical):** Unescaped user input (`owner_name`) in the backend HTML generator leads to Reflected XSS when rendered via `dangerouslySetInnerHTML` in React or directly via the API GET endpoint.
- **Infrastructure:** Cloudflare proxy loop issue (error 1000) preventing full WAF/DDoS protection. Currently running DNS-only. Migration to Cloudflare Pages for frontend is recommended.
- **Testing:** Lack of an automated re-runnable test suite (Playwright/pytest).
- **Telemetry:** Google Analytics and "About This Demo" copy need final UX polish.

## Glossary
- **DCAD:** Dallas Central Appraisal District.
- **ARB:** Appraisal Review Board.
- **uFILE:** The DCAD online portal for submitting electronic property tax protests.
- **Opinion of Value:** The homeowner's proposed fair market value for the property.
- **Progressive Widening:** The algorithm used to find comps by starting with tight similarity constraints (size, age) and gradually relaxing them if insufficient comps are found.
