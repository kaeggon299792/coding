# CASINO IN black-hole profile island

This directory is an isolated React/TypeScript/Vite island used only for the
authenticated top-bar account menu's centred avatar effect. Flask/Jinja keeps
rendering the existing account menu, greeting, rank and links, while the island
replaces only the bounded avatar-effect container. A static Jinja avatar remains
as the no-JavaScript fallback. Vite's hashed production files and `manifest.json`
are written to `dashboard/static/blackhole-hero` and are committed because the
PythonAnywhere host does not provide Node/npm.

Build from this directory with a current Node.js installation:

```text
npm ci
npm run typecheck
npm run build
```

The reusable component lives in `src/components/ui` so component imports keep
the conventional shadcn-compatible layout without installing shadcn or
Tailwind into the existing Flask site.
