import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

const DEFAULT_COLOR_ORDERS = ['RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR']

export function SettingsPanel({ overview, onQuietChange }) {
  const lighting = overview?.lighting
  const colorOrderOptions = lighting?.color_order_options ?? DEFAULT_COLOR_ORDERS
  const chipOptions = lighting?.chip_options ?? []

  const [chip, setChip] = useState('WS2811')
  const [colorOrder, setColorOrder] = useState('GRB')
  const [status, setStatus] = useState('')

  const quiet = overview?.quiet
  const [quietOn, setQuietOn] = useState(false)
  const [quietStart, setQuietStart] = useState('21:00')
  const [quietStop, setQuietStop] = useState('08:00')
  const [quietMsg, setQuietMsg] = useState('')
  const [build, setBuild] = useState(null)

  const [clock, setClock] = useState(null)
  const [clockStatus, setClockStatus] = useState('')
  const [syncing, setSyncing] = useState(false)
  // Ticks locally off the offset between the planter's clock and this device's,
  // so the readout counts seconds like a device display instead of freezing on
  // whatever the last fetch returned.
  const [skewMs, setSkewMs] = useState(null)
  const [tick, setTick] = useState(() => Date.now())

  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone

  const readClock = async () => {
    try {
      const response = await fetch(`${API_BASE}/system/time`)
      if (!response.ok) return
      const data = await response.json()
      setClock(data)
      setSkewMs(new Date(data.now).getTime() - Date.now())
    } catch {
      // Leaves the readout blank rather than breaking the panel.
    }
  }

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!cancelled) await readClock()
    }
    load()
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

  // Resynced during render rather than in an effect, so the form never paints
  // one frame of stale values after a refresh.
  const [syncedOverview, setSyncedOverview] = useState(null)
  if (overview !== syncedOverview) {
    setSyncedOverview(overview)
    setChip(lighting?.chip ?? chip)
    setQuietOn(quiet?.quiet_hours_enabled ?? quietOn)
    setQuietStart(quiet?.quiet_hours_start ?? quietStart)
    setQuietStop(quiet?.quiet_hours_stop ?? quietStop)
    setColorOrder(lighting?.color_order ?? colorOrder)
  }

  // Explicit save, unlike the lighting controls: these are build-time facts
  // about the hardware, and selecting a chip resets the colour order to that
  // chip's default, so the two have to be sent in a known order.
  const save = async () => {
    setStatus('')
    try {
      for (const [path, body] of [
        ['/lights/chip', { chip }],
        ['/lights/color-order', { color_order: colorOrder }],
      ]) {
        const response = await fetch(`${API_BASE}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          setStatus(data.error || `Save failed (HTTP ${response.status})`)
          return
        }
      }
      setStatus('Saved.')
    } catch (error) {
      setStatus(`Save failed: ${error.message}`)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function readVersion() {
      try {
        const response = await fetch(`${API_BASE}/version`)
        if (!response.ok || cancelled) return
        setBuild(await response.json())
      } catch {
        // Leaves the panel without a version rather than breaking it.
      }
    }
    readVersion()
    return () => {
      cancelled = true
    }
  }, [])

  const saveQuiet = async () => {
    setQuietMsg('')
    try {
      const response = await fetch(`${API_BASE}/quiet/hours`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: quietOn, start: quietStart, stop: quietStop }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setQuietMsg(data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setQuietMsg('Saved.')
      onQuietChange?.()
    } catch (error) {
      setQuietMsg(`Save failed: ${error.message}`)
    }
  }

  return (
    <section className="panel-section">
      <h2>Settings</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <label>
            LED strip type
            <select value={chip} onChange={(event) => setChip(event.target.value)}>
              {chipOptions.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name} ({option.description})
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">
            Sets the signal timing for your strip. WS2811 drives three LEDs per
            pixel, so set LED count to a third of the LEDs you can see.
          </p>
        </div>

        <div className="field-row">
          <label>
            LED colour order
            <select value={colorOrder} onChange={(event) => setColorOrder(event.target.value)}>
              {colorOrderOptions.map((order) => (
                <option key={order} value={order}>
                  {order}
                </option>
              ))}
            </select>
          </label>
          <p className="field-hint">
            If red and green look swapped on the strip, try a different order.
            Choosing a strip type resets this to that chip's usual order, so set
            the type first.
          </p>
        </div>

        <div className="field-row">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={quietOn}
              onChange={(event) => setQuietOn(event.target.checked)}
            />
            Quiet hours
          </label>
          <div className="slider-row">
            <label>
              From
              <input
                type="time"
                value={quietStart}
                onChange={(event) => setQuietStart(event.target.value)}
              />
            </label>
            <label>
              To
              <input
                type="time"
                value={quietStop}
                onChange={(event) => setQuietStop(event.target.value)}
              />
            </label>
            <button type="button" onClick={saveQuiet}>Save quiet hours</button>
          </div>
          <p className="field-hint">
            Holds off <em>automatic</em> watering overnight — the pump and the
            gantry are the only loud parts. A window that ends before it starts
            runs through midnight. Watering you start yourself is never blocked,
            and a plant that comes due during the window is watered as soon as
            it ends rather than skipped.
          </p>
          {quietMsg && <p className="field-hint warning">{quietMsg}</p>}
        </div>

        <div className="field-row">
          <label>Planter time</label>
          <div className="slider-row">
            <span className="position-readout">{planterClock}</span>
            <button type="button" disabled={syncing || !clock?.can_set} onClick={syncTimezone}>
              {syncing ? 'Syncing…' : 'Sync to Local Time'}
            </button>
          </div>
          <p className="field-hint">
            The planter runs its lighting schedule on its own clock, so if this
            is not your local time the lights come on at the wrong hours.
            Syncing sets it to {browserZone} — the time zone this device is in.
          </p>
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

        <div className="field-row">
          <label>Software</label>
          <p className="field-hint">
            Version {build?.version ?? '—'} · API {build?.running_commit ?? '—'} ·
            page {__BUILD_COMMIT__}
          </p>
          {build?.stale && (
            <p className="field-hint warning">
              The planter has newer code on disk ({build.checkout_commit}) than
              the service is running ({build.running_commit}). Something was
              pulled without restarting. Run{' '}
              <code>sudo systemctl restart greenthumb-api</code> on the Pi.
            </p>
          )}
          {build?.running_commit &&
            __BUILD_COMMIT__ !== 'unknown' &&
            build.running_commit !== __BUILD_COMMIT__ && (
              <p className="field-hint warning">
                This page was built from {__BUILD_COMMIT__} but the API is
                running {build.running_commit}. Rebuild the frontend, or you
                will hit features the API does not have.
              </p>
            )}
        </div>

        <button type="button" className="primary save-settings-button" onClick={save}>
          Save Settings
        </button>
        {status && <p className="field-hint warning">{status}</p>}
      </div>
    </section>
  )
}
