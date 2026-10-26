import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { useHoldToConfirm } from '../useHoldToConfirm'
import { HoldRing } from './HoldRing'

const SAMPLE_SECONDS = 20

// Reset throws away all four air readings at once, which only a new
// calibration run brings back. Held like the profile deletes rather than one
// click, which it used to be.
const RESET_HOLD_MS = 3000

// The live check reads every probe this often, and switches itself off after
// LIVE_LIMIT_MS: each read briefly takes the hardware, and a check left
// running in a forgotten tab would keep nudging the watering loop aside.
const LIVE_POLL_MS = 2000
const LIVE_LIMIT_MS = 5 * 60 * 1000

// The probes' dry points, in open air: each probe's 0% water point, which an
// estimated wilting point is placed up from. The moisture scale itself runs
// from wilting point to a soil profile's field capacity reading, set in the
// Soil Profile Editor. This panel reports each pot's scale but does not take it.
export function CalibrationPanel() {
  const [calibration, setCalibration] = useState(null)
  const [busy, setBusy] = useState('')
  const [results, setResults] = useState(null)
  // {text, warn}: a run that stored every probe is not a warning.
  const [message, setMessage] = useState(null)
  const [deadline, setDeadline] = useState(null)
  const [remaining, setRemaining] = useState(0)
  const [live, setLive] = useState(false)
  // {sensors} from the last read, or {error} when the planter refused it.
  const [liveReading, setLiveReading] = useState(null)

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/sensors/calibration`)
      if (!response.ok) return
      setCalibration(await response.json())
    } catch {
      // A failed read leaves the table empty rather than breaking the panel;
      // the buttons below still work and will refresh it.
    }
  }, [])

  useEffect(() => {
    // Guarded rather than a bare load(): a response landing after the tab is
    // switched away would set state on a gone component, and setting state
    // straight from an effect body is what the hooks lint objects to.
    let canceled = false
    async function loadOnMount() {
      if (!canceled) await load()
    }
    loadOnMount()
    return () => {
      canceled = true
    }
  }, [load])

  // Counts down against a wall-clock deadline rather than decrementing a
  // counter: a background tab throttles timers to once a minute or so, and a
  // plain decrement would come back reading 19s after a 20s run.
  useEffect(() => {
    if (!deadline) return undefined
    const id = setInterval(() => {
      setRemaining(Math.max(0, Math.ceil((deadline - Date.now()) / 1000)))
    }, 250)
    return () => clearInterval(id)
  }, [deadline])

  // Paused while a calibration or reset runs: those hold the hardware, and
  // every read in the meantime would only come back busy.
  useEffect(() => {
    if (!live || busy) return undefined
    let canceled = false
    async function readNow() {
      try {
        const response = await fetch(`${API_BASE}/sensors/live`)
        const data = await response.json().catch(() => ({}))
        if (canceled) return
        setLiveReading(
          response.ok
            ? { sensors: data.sensors ?? [] }
            : { error: data.error || data.detail || `HTTP ${response.status}` },
        )
      } catch (error) {
        if (!canceled) setLiveReading({ error: error.message })
      }
    }
    readNow()
    const poll = setInterval(readNow, LIVE_POLL_MS)
    const limit = setTimeout(() => setLive(false), LIVE_LIMIT_MS)
    return () => {
      canceled = true
      clearInterval(poll)
      clearTimeout(limit)
    }
  }, [live, busy])

  const toggleLive = () => {
    setLiveReading(null)
    setLive((current) => !current)
  }

  const runCalibration = async () => {
    setBusy('dry')
    setResults(null)
    setMessage(null)
    // Seeded here rather than in the effect: the first value has to be on
    // screen before the first tick, and setting state in an effect body is
    // what the hooks lint objects to.
    setRemaining(SAMPLE_SECONDS)
    setDeadline(Date.now() + SAMPLE_SECONDS * 1000)
    try {
      // Blocks for the whole sampling window, the way a gantry move blocks for
      // its travel. The button stays disabled until it returns.
      const response = await fetch(`${API_BASE}/sensors/calibration/dry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds: SAMPLE_SECONDS }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        // 409 when a watering cycle holds the hardware. Always include the
        // status: a 404 is FastAPI's {"detail": "Not Found"} with no error
        // field, which otherwise shows as a bare "failed" and hides that the
        // API is running older code than the page.
        const detail = data.error || data.detail
        setMessage({
          text: detail
            ? `Calibration failed (${response.status}): ${detail}`
            : `Calibration failed (HTTP ${response.status}). If this is a 404, ` +
              'the planter software is older than this page. Restart the ' +
              'greenthumb-api service on the Pi.',
          warn: true,
        })
        return
      }
      setResults(data)
      setMessage(
        data.stored === data.total
          ? { text: `Stored the dry point for all ${data.total} sensors.`, warn: false }
          : { text: `Stored ${data.stored} of ${data.total}. See the reasons below.`, warn: true },
      )
      await load()
    } catch (error) {
      setMessage({ text: `Calibration failed: ${error.message}`, warn: true })
    } finally {
      setBusy('')
      setDeadline(null)
    }
  }

  const reset = async () => {
    setBusy('reset')
    setResults(null)
    setMessage(null)
    try {
      const response = await fetch(`${API_BASE}/sensors/calibration/reset`, { method: 'POST' })
      // Checked: it used to report success whatever the planter answered,
      // including when it refused because the hardware was busy.
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setMessage({
          text: data.error || data.detail || `Reset failed (HTTP ${response.status})`,
          warn: true,
        })
        return
      }
      setMessage({
        text:
          'Air readings cleared. Every probe is back on the default air reading ' +
          'until you calibrate again. The soil profiles are untouched.',
        warn: false,
      })
      await load()
    } catch (error) {
      setMessage({ text: `Reset failed: ${error.message}`, warn: true })
    } finally {
      setBusy('')
    }
  }

  const resetHold = useHoldToConfirm(RESET_HOLD_MS, reset)

  const sensors = calibration?.sensors ?? []
  const unmeasured = sensors.filter((sensor) => !sensor.usable)

  // The request outlives the sampling window by a little -- acquiring the
  // hardware lock, the final pass, serialising the reply -- so the countdown
  // hands over to "Finishing" instead of sitting on a stuck 0s.
  const buttonLabel = () => {
    if (busy !== 'dry') return 'Calibrate dry (air)'
    return remaining > 0 ? `Sampling… ${remaining}s` : 'Finishing…'
  }

  // The pot's scale: wilting point up to field capacity.
  const scaleNote = (sensor) => {
    if (sensor.scale_problem) return sensor.scale_problem
    const where = sensor.soil ? `from ${sensor.soil}` : 'no soil profile'
    const span = sensor.field_capacity_raw - sensor.wilting_point_raw
    const bottom =
      sensor.wilting_point_source === 'estimated'
        ? `~${sensor.wilting_point_raw} estimated`
        : sensor.wilting_point_raw
    return (
      `scale ${bottom}–${sensor.field_capacity_raw} ` +
      `(${where}) · span ${span}`
    )
  }

  return (
    <section className="panel-section">
      <h2>Moisture probes</h2>

      <div className="general-settings-form">
        <p className="field-hint">
          Each probe&apos;s reading in open air, its 0% point.
        </p>

        <div className="field-row">
          <button
            type="button"
            className={busy === 'dry' ? 'working' : undefined}
            disabled={Boolean(busy)}
            onClick={runCalibration}
          >
            {buttonLabel()}
          </button>
          <p className="field-hint">
            All sensors out of any soil, clean and dry, sitting in open air.
            Samples every sensor for {SAMPLE_SECONDS} seconds and takes the
            median. Watering is blocked while it runs.
          </p>
        </div>

        <div className="field-row">
          <button type="button" onClick={toggleLive}>
            {live ? 'Stop live readings' : 'Show live readings'}
          </button>
          <p className="field-hint">
            Reads every probe every {LIVE_POLL_MS / 1000} seconds, to check one
            responds: hold it or dip it in water and its number should rise.
            Stops by itself after {LIVE_LIMIT_MS / 60000} minutes.
          </p>
          {live && busy && <p className="field-hint">Paused while the calibration runs.</p>}
          {live && liveReading?.error && (
            <p className="field-hint warning">Could not read the probes: {liveReading.error}</p>
          )}
          {live &&
            liveReading?.sensors?.map((sensor) => (
              <p
                className={sensor.raw < 0 ? 'field-hint warning' : 'field-hint'}
                key={sensor.address}
              >
                <strong>{sensor.label || sensor.address}</strong>{' '}
                {sensor.raw < 0
                  ? 'not answering'
                  : `reads ${Math.round(sensor.raw)} (air ${sensor.dry})` +
                    (sensor.percent >= 0 ? ` · soil water ${sensor.percent}%` : '') +
                    ` · ${sensor.temperature_c}°C`}
              </p>
            ))}
        </div>

        {message && (
          <p className={message.warn ? 'field-hint warning' : 'field-hint'}>{message.text}</p>
        )}

        {results && (
          <div className="field-row">
            <h3>Last run</h3>
            {results.sensors.map((sensor) => (
              <p className="field-hint" key={sensor.address}>
                <strong>{sensor.label || sensor.address}</strong>{' '}
                {sensor.written
                  ? `stored a dry point of ${sensor.value}. Readings spread ` +
                    `${sensor.spread} points over ${sensor.samples} samples.`
                  : `not stored — ${sensor.reason}`}
              </p>
            ))}
          </div>
        )}

        <div className="field-row">
          <h3>Current scale</h3>
          {sensors.length === 0 && <p className="field-hint">No sensors reporting.</p>}
          {sensors.map((sensor) => (
            <p
              className={`field-hint${sensor.usable ? '' : ' warning'}`}
              key={sensor.address}
            >
              <strong>{sensor.label || sensor.address}</strong> air {sensor.dry}
              {sensor.calibrated_dry ? '' : ' (default)'} · {scaleNote(sensor)}
            </p>
          ))}
          {unmeasured.length > 0 && (
            <p className="field-hint warning">
              {unmeasured.length === 1 ? 'One pot has' : `${unmeasured.length} pots have`}{' '}
              no usable scale, so {unmeasured.length === 1 ? 'it reads' : 'they read'}{' '}
              nothing and {unmeasured.length === 1 ? 'is' : 'are'} never watered
              automatically. Each line above says what is missing.
            </p>
          )}
        </div>

        <div className="field-row">
          <button
            type="button"
            className={resetHold.progress > 0 ? 'hold-delete holding' : 'hold-delete'}
            disabled={Boolean(busy)}
            {...resetHold.handlers}
          >
            <HoldRing progress={resetHold.progress} />
            {resetHold.progress > 0 ? 'Resetting…' : 'Hold to reset dry calibration'}
          </button>
          <p className="field-hint">Soil profiles are not affected.</p>
        </div>
      </div>
    </section>
  )
}
