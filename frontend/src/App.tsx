import { useEffect, useState } from 'react'
import './App.css'

// Backend base URL. Override with VITE_API_BASE in a .env file if the backend runs elsewhere.
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

type Health = { status: string; version: string }
type BackendState =
  | { kind: 'loading' }
  | { kind: 'ok'; health: Health }
  | { kind: 'error'; message: string }

function App() {
  const [backend, setBackend] = useState<BackendState>({ kind: 'loading' })

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<Health>
      })
      .then((health) => setBackend({ kind: 'ok', health }))
      .catch((e: unknown) =>
        setBackend({ kind: 'error', message: e instanceof Error ? e.message : String(e) }),
      )
  }, [])

  return (
    <main className="app">
      <h1>MTG Analyzer</h1>
      <p className="tagline">Local Commander (EDH) deck analyzer, simulator &amp; recommender</p>

      <section className="status-card">
        <h2>Backend</h2>
        {backend.kind === 'loading' && <p>Checking…</p>}
        {backend.kind === 'ok' && (
          <p className="ok">
            ● Connected — status <code>{backend.health.status}</code>, v
            {backend.health.version}
          </p>
        )}
        {backend.kind === 'error' && (
          <p className="error">
            ● Not reachable at <code>{API_BASE}</code> ({backend.message}).
            <br />
            Start it: <code>uvicorn mtg_analyzer.api.app:app --reload</code>
          </p>
        )}
      </section>
    </main>
  )
}

export default App
