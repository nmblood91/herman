import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

const VALID = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/

// The planter's network name, the part before .local. Every planter flashes
// as "herman"; with two on one network, whichever boots first keeps
// herman.local and the other quietly becomes herman-2.local.
export function HostnamePanel() {
  const [current, setCurrent] = useState(null)
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [moved, setMoved] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function readName() {
      try {
        const response = await fetch(`${API_BASE}/system/hostname`)
        if (!response.ok || cancelled) return
        const data = await response.json()
        setCurrent(data.hostname)
        setName(data.hostname)
      } catch {
        // Leaves the field empty rather than breaking the panel.
      }
    }
    readName()
    return () => {
      cancelled = true
    }
  }, [])

  const wanted = name.trim().toLowerCase()
  const valid = VALID.test(wanted)
  const changed = valid && wanted !== current

  const save = async () => {
    setSaving(true)
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/system/hostname`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hostname: wanted }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.error || data.detail || `Rename failed (HTTP ${response.status})`)
        return
      }
      setCurrent(data.hostname)
      setName(data.hostname)
      setMoved(data.address)
    } catch (error) {
      setMessage(`Rename failed: ${error.message}`)
    } finally {
      setSaving(false)
    }
  }

  // The new address, keeping whatever port this page was opened on.
  const newUrl = moved
    ? `${window.location.protocol}//${moved}${window.location.port ? `:${window.location.port}` : ''}`
    : null

  return (
    <section className="panel-section">
      <h2>Network name</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <p className="field-hint">
            Open the planter at <strong>http://{current ?? '…'}.local</strong>.
          </p>
          <div className="slider-row">
            <input
              type="text"
              value={name}
              maxLength={63}
              spellCheck={false}
              autoCapitalize="none"
              onChange={(event) => setName(event.target.value)}
            />
            <span className="position-readout">.local</span>
            <button type="button" className="primary" disabled={!changed || saving} onClick={save}>
              {saving ? 'Renaming…' : 'Rename'}
            </button>
          </div>
          {name && !valid && (
            <p className="field-hint warning">
              Letters, digits and hyphens only, without a hyphen at the start or end.
            </p>
          )}
          {moved && (
            <p className="field-hint warning">
              Renamed. The old address stops working, so open{' '}
              <a href={newUrl}>{newUrl}</a> from now on, and update any bookmark.
              For SSH, use <code>ssh pi@{moved}</code>.
            </p>
          )}
          {message && <p className="field-hint warning">{message}</p>}
        </div>
      </div>
    </section>
  )
}
