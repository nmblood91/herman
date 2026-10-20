import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// The planter's clock. A readout with three warning states rather than a
// setting, which is why it lives with the checks: there is no battery-backed
// clock, so after a power cut it reverts to roughly its last shutdown, and "the
// lights came on at the wrong time" is answered from here.
export function ClockPanel() {
  const [clock, setClock] = useState(null)
  const [clockStatus, setClockStatus] = useState('')
  const [syncing, setSyncing] = useState(false)
  // Ticks locally off the offset between the planter's clock and this device's,
  // so the readout counts seconds like a device display instead of freezing on
  // whatever the last fetch returned.
  const [skewMs, setSkewMs] = useState(null)
  const [tick, setTick] = useState(() => Date.now())

  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone

  useEffect(() => {
    let cancelled = false
    async function readClock() {
      try {
        const response = await fetch(`${API_BASE}/system/time`)
        if (!response.ok || cancelled) return
        const data = await response.json()
        setClock(data)
        setSkewMs(new Date(data.now).getTime() - Date.now())
      } catch {
        // Leaves the readout blank rather than breaking the panel.
      }
    }
    readClock()
    const id = setInterval(() => setTick(Date.now()), 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const planterClock =
    skewMs === null
      ? '—'
      : new Date(tick + skewMs).toLocaleString(undefined, {
          timeZone: clock?.timezone || undefined,
          dateStyle: 'medium',
          timeStyle: 'medium',
        })

  const syncTimezone = async () => {
    setSyncing(true)
    setClockStatus('')
    try {
      const response = await fetch(`${API_BASE}/system/timezone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: browserZone }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setClockStatus(data.error || `Could not sync (HTTP ${response.status})`)
        return
      }
      setClock(data)
      setSkewMs(new Date(data.now).getTime() - Date.now())
      setClockStatus(`Planter time zone set to ${data.timezone}.`)
    } catch (error) {
      setClockStatus(`Could not sync: ${error.message}`)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <section className="panel-section">
      <h2>Clock</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="slider-row">
            <button type="button" disabled={syncing || !clock?.can_set} onClick={syncTimezone}>
              {syncing ? 'Syncing…' : 'Sync to Local Time'}
            </button>
            <span className="position-readout">Herman&apos;s clock: {planterClock}</span>
          </div>
          <p className="field-hint">The lights follow this clock.</p>
          {clock && !clock.ntp_synchronised && (
            <p className="field-hint warning">
              The clock has not reached a time server yet, so it may be wrong
              until the planter is online. There is no battery-backed clock, so
              it reverts to roughly its last shutdown after a power cut.
            </p>
          )}
          {clock && !clock.can_set && (
            <p className="field-hint warning">
              This host cannot set its time zone from here. Set it on the Pi
              with <code>sudo timedatectl set-timezone {browserZone}</code>.
            </p>
          )}
          {clockStatus && <p className="field-hint warning">{clockStatus}</p>}
        </div>
      </div>
    </section>
  )
}
