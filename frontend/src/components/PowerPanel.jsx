import { useState } from 'react'
import { API_BASE } from '../api'
import { useHoldToConfirm } from '../useHoldToConfirm'
import { HoldRing } from './HoldRing'

// Shorter than the five-second deletes: nothing is lost by a shutdown, but a
// stray tap still should not take the planter offline.
const POWER_HOLD_MS = 3000

const DONE = {
  shutdown:
    'Shutting down. Wait until the green light on the Pi stops flashing, ' +
    'about 20 seconds, then it is safe to unplug. The SKR and the LED strip ' +
    'stay powered until you do.',
  reboot:
    'Rebooting. The page stops answering for a minute or so, then reconnects ' +
    'by itself.',
}

// Shutdown and reboot. Unplugging a running Pi can corrupt its SD card and
// leave it booting with no SSH and no web page, so the safe way has to be the
// easy way.
export function PowerPanel() {
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState('')

  const send = async (action) => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/system/power`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        // 409 while watering or moving, or when the installer has not added
        // the permission yet; either way the error says which.
        setMessage(data.error || data.detail || `Request failed (HTTP ${response.status})`)
        return
      }
      setSent(action)
      setMessage(DONE[action])
    } catch (error) {
      setMessage(`Could not reach Herman: ${error.message}`)
    }
  }

  const shutdownHold = useHoldToConfirm(POWER_HOLD_MS, () => send('shutdown'))
  const rebootHold = useHoldToConfirm(POWER_HOLD_MS, () => send('reboot'))

  const holdButton = (hold, label, holdingLabel) => (
    <button
      type="button"
      className={hold.progress > 0 ? 'hold-delete holding' : 'hold-delete'}
      disabled={Boolean(sent)}
      {...hold.handlers}
    >
      <HoldRing progress={hold.progress} />
      {hold.progress > 0 ? holdingLabel : label}
    </button>
  )

  return (
    <section className="panel-section">
      <h2>Power</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="motion-grid">
            {holdButton(shutdownHold, 'Hold to shut down', 'Shutting down…')}
            {holdButton(rebootHold, 'Hold to reboot', 'Rebooting…')}
          </div>
          <p className="field-hint">Shut down before unplugging.</p>
          {message && <p className="field-hint warning">{message}</p>}
        </div>
      </div>
    </section>
  )
}
