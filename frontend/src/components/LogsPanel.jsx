import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// Fetches its own log, like HistoryPanel and CalibrationPanel. It used to take
// the log as a prop from App's loadDashboard, which runs after every action --
// so pressing any button re-fetched the log whether or not this was on screen.
export function LogsPanel() {
  const [logs, setLogs] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function read() {
      try {
        const response = await fetch(`${API_BASE}/logs?lines=20`)
        if (cancelled) return
        if (!response.ok) {
          setError(`Could not read the log (HTTP ${response.status})`)
          return
        }
        setLogs(await response.json())
      } catch (err) {
        if (!cancelled) setError(`Could not read the log: ${err.message}`)
      }
    }
    read()
    return () => {
      cancelled = true
    }
  }, [])

  // Newest first. The API returns oldest-first, which is the wrong end to read
  // from when you are looking for what just happened.
  const reversedLogs = logs.length ? [...logs].reverse() : []

  return (
    <section className="panel-section">
      <h2>Recent Logs</h2>
      {error && <p className="field-hint warning">{error}</p>}
      <div className="log-box">
        {reversedLogs.length ? reversedLogs.join('') : 'No logs yet.'}
      </div>
    </section>
  )
}
