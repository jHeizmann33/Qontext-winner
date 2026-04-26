# qontext frontend-v2

Conflict-review console (screen 1) plus 3D graph drilldown (screen 2) for the
qontext backend in `api/server.py`. Co-exists with the older Vite/JSX viewer
in `../frontend/`, which remains untouched.

## Routes

- `/` — conflict review queue + decision UI (replaces the older viewer as the
  primary screen; consumes `GET /conflicts?status=pending_review`).
- `/lens` — the original 3D Object Lens, reachable from any conflict via the
  "Open in graph" button. Accepts `?focus=<entity_id>` (e.g.
  `/lens?focus=Employee:emp_0431`) to deep-link into a specific node.
  (Path is `/lens` rather than `/graph` because `api/server.py`'s SPA
  fallback reserves `/graph` for the JSON graph API.)

## Dev

```bash
# Backend (in another terminal, from repo root)
python run_qontext_api.py

# Frontend
cd frontend-v2
cp .env.example .env.local
npm install
npm run dev    # http://localhost:8080
```

## Environment variables

See `.env.example`. The two switches that matter:

- `VITE_API_BASE_URL` — qontext FastAPI base. Default `http://127.0.0.1:8000`.
- `VITE_USE_MOCKS` — `"true"` forces the conflict screen to read the bundled
  mocks from `src/lib/qontext-data.ts` (also used as automatic fallback when
  the backend request fails).

## Layout

```
src/
├── App.tsx              # router: "/" -> Index, "/lens" -> GraphView
├── pages/
│   ├── Index.tsx        # conflict review console (screen 1)
│   └── GraphView.jsx    # 3D Object Lens, ported from ../frontend/src/App.jsx
├── lib/
│   ├── api.ts            # fetch wrapper for /conflicts + /resolve
│   ├── conflict-adapter.ts  # backend conflict shape -> UI Conflict shape
│   ├── useConflicts.ts   # React Query hooks (with mock fallback)
│   ├── qontext-data.ts   # UI types + mock CONFLICTS / PAST_DECISIONS
│   └── storyQueries.js   # FALLBACK_PAYLOAD + STORY_PRESETS for GraphView
└── graph-view.css        # styles for GraphView (carried over from old frontend)
```

The backend conflict shape (`{entity_id, field, existing_value, new_value, …}`)
does not match the UI's Source-A/Source-B contract document model 1:1. The
adapter in `conflict-adapter.ts` is the only place that bridges the two — keep
backend-specific logic there, not in the page.

## What this project does NOT touch

- `../frontend/` — older 3D-only viewer, still buildable and served by FastAPI.
- `../api/server.py` — backend endpoints unchanged. The `escalate` and `skip`
  decisions stay client-side until a dedicated endpoint exists.
