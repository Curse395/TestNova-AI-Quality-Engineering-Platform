# TestNova AI frontend

The frontend is a React 19 single-page application built with Vite, React Router,
Axios, Tailwind CSS, Motion for React, Lucide icons, and Recharts. Motion is used
for short route and agent-inspector transitions; product-specific components
remain custom rather than adopting a generic AI dashboard kit.

## Run locally

```sh
npm install
npm run dev
```

Set `VITE_API_BASE_URL` when the FastAPI service is not available at
`http://localhost:8000`. Build and validate the frontend with:

```sh
npm run build
npm test
npm run lint
```

## Application structure

- `src/App.jsx` defines the authenticated shell and routes.
- `src/components/layout/` contains the responsive navigation and page header.
- `src/context/` provides the persistent, system-aware light/dark theme.
- `src/api/` contains the authenticated API clients.
- `src/pages/` contains Mission Control, projects, document upload, test cases,
  workflows, analytics, release readiness, and the project knowledge assistant.

Mission Control uses the dashboard and persisted workflow APIs. Agent states
and dependency paths are rendered from workflow task records; no live activity
is fabricated when workflow data is absent. Browser notifications and profile
details are not exposed because the current backend has no corresponding
frontend API. The repository also has no dedicated requirements, investigation,
or evidence-vault frontend routes, so those workspaces are not represented by
mock pages or unsupported actions.
