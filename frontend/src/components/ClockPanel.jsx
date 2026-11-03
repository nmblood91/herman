import { useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { Segmented } from './Segmented'

const CLOCK_FORMATS = [
  { label: '12-hour (2:00 PM)', value: '12h' },
  { label: '24-hour (14:00)', value: '24h' },
]

// The planter's clock. A readout with three warning states rather than a
// setting, which is why it lives with the checks: there is no battery-backed
// clock, so after a power cut it reverts to roughly its last shutdown, and "the
// lights came on at the wrong time" is answered from here.
export function ClockPanel({ onRefresh }) {
  const [clock, setClock] = useState(null)
  const [clockStatus, setClockStatus] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [savingFormat, setSavingFormat] = useState(false)
  const hour24 = clock?.clock_24h ?? false
  // Ticks locally off the offset between the planter's clock and this device's,
  // so the readout counts seconds like a device display instead of freezing on
  // whatever the last fetch returned.
  const [skewMs, setSkewMs] = useState(null)
  const [tick, setTick] = useState(() => Date.now())

  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone

  useEffect(() => {
    let canceled = false
    async function readClock() {
      try {
        const response = await fetch(`${API_BASE}/system/time`)
        if (!response.ok || canceled) return
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
      canceled = true
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
          hourCycle: hour24 ? 'h23' : 'h12',
        })

  // Every time of day the app writes follows this, the status bar and the log
  // included, so it is stored on the planter rather than in this browser.
  const saveFormat = async (enabled) => {
    setSavingFormat(true)
    setClockStatus('')
    try {
      const response = await fetch(`${API_BASE}/system/clock-format`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setClockStatus(data.error || `Could not save (HTTP ${response.status})`)
        return
      }
      setClock((current) => ({ ...current, clock_24h: data.clock_24h }))
      onRefresh?.()
    } catch (error) {
      setClockStatus(`Could not save: ${error.message}`)
    } finally {
      setSavingFormat(false)
    }
  }

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
      // The time zone answer does not carry the clock format.
      setClock((current) => ({ ...data, clock_24h: current?.clock_24h }))
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
      <h2>System Time</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="slider-row">
            <button type="button" disabled={syncing || !clock?.can_set} onClick={syncTimezone}>
              {syncing ? 'Syncing…' : 'Sync to Local Time'}
            </button>
            <span className="position-readout">Herman&apos;s clock: {planterClock}</span>
          </div>
          <p className="field-hint">The lights follow this clock.</p>
          <Segmented
            label="Clock format"
            options={CLOCK_FORMATS.map((option) => ({
              ...option,
              disabled: savingFormat || !clock,
            }))}
            value={hour24 ? '24h' : '12h'}
            onChange={(value) => {
              if ((value === '24h') !== hour24) saveFormat(value === '24h')
            }}
          />
          <p className="field-hint">How times are shown everywhere in the app.</p>
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
