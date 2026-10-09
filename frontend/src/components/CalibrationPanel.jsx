import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../api'

const SAMPLE_SECONDS = 20

// The endpoints are the two ends of the sensor's range, so saying which end was
// just written is clearer than repeating "dry" or "wet" on its own.
const ENDPOINT_NOUN = {
  dry: 'dry min',
  wet: 'wet max',
}

const INSTRUCTIONS = {
  dry: 'All sensors should be out of any soil, clean and dry, sitting in open air.',
  wet:
    'Each probe in its own pot, soaked through and drained for 24 hours — '
    + 'field capacity, the wettest the soil actually gets. Not a glass of water: '
    + 'that holds far more than soil can, which puts the top of the scale '
    + 'somewhere the pot can never reach. Re-run it after repotting.',
}

export function CalibrationPanel() {
  const [calibration, setCalibration] = useState(null)
  const [busy, setBusy] = useState('')
  const [results, setResults] = useState(null)
  const [message, setMessage] = useState('')
  const [deadline, setDeadline] = useState(null)
  const [remaining, setRemaining] = useState(0)

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
    let cancelled = false
    async function loadOnMount() {
      if (!cancelled) await load()
    }
    loadOnMount()
    return () => {
      cancelled = true
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

  const runCalibration = async (endpoint) => {
    setBusy(endpoint)
    setResults(null)
    setMessage('')
    // Seeded here rather than in the effect: the first value has to be on
    // screen before the first tick, and setting state in an effect body is
    // what the hooks lint objects to.
    setRemaining(SAMPLE_SECONDS)
    setDeadline(Date.now() + SAMPLE_SECONDS * 1000)
    try {
      // Blocks for the whole sampling window, the way a gantry move blocks for
      // its travel. The button stays disabled until it returns.
      const response = await fetch(`${API_BASE}/sensors/calibration/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds: SAMPLE_SECONDS }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        // 409 when a watering cycle holds the hardware, 400 for a bad
        // endpoint. Always include the status: a 404 is FastAPI's
        // {"detail": "Not Found"} with no error field, which otherwise shows
        // as a bare "failed" and hides that the API is running older code
        // than the page.
        const detail = data.error || data.detail
        setMessage(
          detail
            ? `Calibration failed (${response.status}): ${detail}`
            : `Calibration failed (HTTP ${response.status}). If this is a 404, ` +
              'the planter software is older than this page. Restart the ' +
              'greenthumb-api service on the Pi.',
        )
        return
      }
      setResults(data)
      setMessage(
        data.stored === data.total
          ? `Stored the ${endpoint} point for all ${data.total} sensors.`
          : `Stored ${data.stored} of ${data.total}. See the reasons below.`,
      )
      await load()
    } catch (error) {
      setMessage(`Calibration failed: ${error.message}`)
    } finally {
      setBusy('')
      setDeadline(null)
    }
  }

  const reset = async () => {
    setBusy('reset')
    setResults(null)
    try {
      await fetch(`${API_BASE}/sensors/calibration/reset`, { method: 'POST' })
      setMessage('Calibration cleared. All sensors are back on the .env defaults.')
      await load()
    } catch (error) {
      setMessage(`Reset failed: ${error.message}`)
    } finally {
      setBusy('')
    }
  }

  const sensors = calibration?.sensors ?? []

  // The request outlives the sampling window by a little -- acquiring the
  // hardware lock, the final pass, serialising the reply -- so the countdown
  // hands over to "Finishing" instead of sitting on a stuck 0s.
  const buttonLabel = (endpoint, idleLabel) => {
    if (busy !== endpoint) return idleLabel
    return remaining > 0 ? `Sampling… ${remaining}s` : 'Finishing…'
  }

  return (
    <section className="panel-section">
      <h2>Moisture calibration</h2>

      <div className="general-settings-form">
        <p className="field-hint">
          Measures each sensor's own dry and wet data reads. Every sensor reads slightly
          differently from each other in identical conditions.
        </p>

        <div className="field-row">
          <div className="motion-grid two-up">
            <button
              type="button"
              className={busy === 'dry' ? 'working' : undefined}
              disabled={Boolean(busy)}
              onClick={() => runCalibration('dry')}
            >
              {buttonLabel('dry', 'Calibrate dry (air)')}
            </button>
            <button
              type="button"
              className={busy === 'wet' ? 'working' : undefined}
              disabled={Boolean(busy)}
              onClick={() => runCalibration('wet')}
            >
              {buttonLabel('wet', 'Calibrate wet (soil at field capacity)')}
            </button>
          </div>
          <p className="field-hint">
            <strong>Dry:</strong> {INSTRUCTIONS.dry}
            <br />
            <strong>Wet:</strong> {INSTRUCTIONS.wet}
          </p>
          <p className="field-hint warning">
            These boards are not waterproof. Be sure to have heat shrinked the sensor from the white and above, covering all electrical components and connections.
          </p>
          <p className="field-hint">
            Each run samples every sensor for {SAMPLE_SECONDS} seconds and takes
            the median. Watering is blocked while it runs. Dry and Wet tests must be done on their own.
          </p>
        </div>

        {message && <p className="field-hint warning">{message}</p>}

        {results && (
          <div className="field-row">
            <h3>Last run</h3>
            {results.sensors.map((sensor) => (
              <p className="field-hint" key={sensor.address}>
                <strong>{sensor.label || sensor.address}</strong>{' '}
                {sensor.written
                  ? `stored ${ENDPOINT_NOUN[results.endpoint] ?? results.endpoint} as ` +
                    `${sensor.value}. Readings spread ${sensor.spread} points over ` +
                    `${sensor.samples} samples.`
                  : `not stored — ${sensor.reason}`}
              </p>
            ))}
          </div>
        )}

        <div className="field-row">
          <h3>Current calibration</h3>
          {sensors.length === 0 && <p className="field-hint">No sensors reporting.</p>}
          {sensors.map((sensor) => {
            const both = sensor.calibrated_dry && sensor.calibrated_wet
            const neither = !sensor.calibrated_dry && !sensor.calibrated_wet
            const source = neither
              ? 'using .env defaults'
              : both
                ? 'calibrated'
                : `half calibrated, ${sensor.calibrated_dry ? 'wet' : 'dry'} still default`
            return (
              <p className="field-hint" key={sensor.address}>
                <strong>{sensor.label || sensor.address}</strong> dry {sensor.dry} · wet {sensor.wet} ·
                span {sensor.wet - sensor.dry} — {source}
              </p>
            )
          })}
          <p className="field-hint">
            Air and water measure the sensor's full range, not the soil's. Dry
            soil reads around 30-40% on that scale, but you should fine tune each plant's target by
            watching the History tab to see how a sensor is reading.
          </p>
        </div>

        <div className="field-row">
          <button type="button" disabled={Boolean(busy)} onClick={reset}>
            Reset calibration
          </button>
          <p className="field-hint">
            Clears calibrated values and returns every sensor to default values for
            MOISTURE_RAW_DRY and MOISTURE_RAW_WET.
          </p>
        </div>
      </div>
    </section>
  )
}
