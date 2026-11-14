# LocalHusk Web UI

React + TypeScript + Vite frontend for LocalHusk.

## Features (connected to the local backend)

- Chat with the configured LLM
- Tasks, notes, calendar, mail
- Agents and approval queue
- Automations
- Model / provider settings
- MCP server connections
- History and logs

## Requirements

- Node.js 18+ (20+ recommended)
- Running LocalHusk backend on `http://127.0.0.1:8000` (default)

## Develop

```bash
npm install
npm run dev
```

Vite prints a localhost URL (bound to `127.0.0.1`).

## Production build

```bash
npm run build
```

Output is written to `dist/`. The installer runs this step when Node is available.

## Configuration

API base URL is resolved in `src/api-base.ts` (defaults to the local backend).  
Do **not** put provider API keys in frontend environment variables; keys are stored by the backend / OS keyring.

## Project layout

```
src/
  App.tsx              # shell + routing
  api-base.ts          # backend origin
  features/            # page-level feature modules
  ...
```

## Notes

This UI is intended to talk only to the local LocalHusk API. It is not a standalone cloud client.
