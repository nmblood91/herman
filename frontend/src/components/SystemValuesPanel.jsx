import { useState } from 'react'
import { API_BASE } from '../api'

// Puts every setting that has a .env default back to it. The planter's own
// setup -- plants, positions, soils, saved plants, field capacity, history --
// has no default to go back to and is left alone, and the list below says so,
// because "defaults" on its own reads like a factory reset.
export function SystemValuesPanel() {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const restore = async () => {
    // Behind a confirm: this throws away a measured flow rate and the probes'
    // dry points, and neither comes back without redoing the measurement.
    const ok = window.confirm(
      'Restore system values to their defaults?\n\n' +
        'This resets auto-water, the pump flow rate, hourly auto-patrol, home ' +
        'after startup, quiet hours and any snooze, the LED strip settings, and ' +
        "the probes' dry calibration.\n\n" +
        'Plants, positions, soils, saved plants and field capacity are kept.',
    )
    if (!ok) return

    setBusy(true)
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/system/restore-defaults`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.error || `Restore failed (HTTP ${response.status})`)
        return
      }
      // Reloaded rather than refreshed: most panels on this tab fetch their own
      // data, so there is no single refresh that reaches all of them.
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
            Puts these back to the values in the planter&apos;s .env file:
            auto-water, the pump flow rate, hourly auto-patrol, home after
            startup, quiet hours (and any snooze), the LED strip settings, and
            the probes&apos; dry calibration.
          </p>
          <p className="field-hint">
            Kept: plants and their positions, soils, saved plants, field
            capacity, and history.
          </p>
          {message && <p className="field-hint warning">{message}</p>}
        </div>
      </div>
    </section>
  )
}
