import { useState } from 'react'
import { API_BASE } from '../api'

// Puts the planter back as it was freshly installed. The plant profile and soil
// libraries are kept, and so is the history -- the list below says so, because
// "defaults" on its own reads as though those would go too.
export function SystemValuesPanel() {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const restore = async () => {
    // Behind a confirm: none of this comes back without setting it up again,
    // and the flow rate and dry points without measuring them again.
    const ok = window.confirm(
      'Restore the planter to its defaults, as if freshly installed?\n\n' +
        'Every pot goes back to its default: name, watering location, sweep, ' +
        'soil and field capacity. Every setting goes back too, including the ' +
        "pump flow rate and the probes' dry calibration.\n\n" +
        'Kept: the plant profile and soil libraries, and the history.',
    )
    if (!ok) return

    setBusy(true)
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/system/restore-defaults`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        // 409 while a watering cycle holds the hardware: it swaps out the
        // plant list that cycle is working through.
        setMessage(data.error || `Restore failed (HTTP ${response.status})`)
        return
      }
      // Reloaded rather than refreshed: most panels fetch their own data, so
      // there is no single refresh that reaches all of them.
      window.location.reload()
    } catch (error) {
      setMessage(`Restore failed: ${error.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-section">
      <h2>System Values</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <button
            type="button"
            className={busy ? 'working' : undefined}
            disabled={busy}
            onClick={restore}
          >
            Restore to Defaults
          </button>
          <p className="field-hint">
            Puts the planter back as it was freshly installed. Every pot returns
            to its default name, watering location, sweep, soil and field
            capacity, and every setting returns to the planter&apos;s .env file —
            including the pump flow rate and the probes&apos; dry calibration.
          </p>
          <p className="field-hint">
            Kept: the plant profile and soil libraries, and the history.
          </p>
          {message && <p className="field-hint warning">{message}</p>}
        </div>
      </div>
    </section>
  )
}
