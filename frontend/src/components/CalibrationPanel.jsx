import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../api'

const SAMPLE_SECONDS = 20

// Dry only. The other end of the scale is field capacity, which is a property
// of the soil mix rather than of the probe -- two pots of different mix want
// different figures with identical sensors -- so it is measured per mix under
// Plants and Soil. This panel reports it but does not take it.
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

  const runCalibration = async () => {
    setBusy('dry')
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
          ? `Stored the dry point for all ${data.total} sensors.`
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
      setMessage(
        'Dry points cleared. Every sensor is back on MOISTURE_RAW_DRY. Field ' +
          'capacity is untouched — it belongs to the mixes and the pots.',
      )
      await load()
    } catch (error) {
      setMessage(`Reset failed: ${error.message}`)
    } finally {
      setBusy('')
    }
  }

  const sensors = calibration?.sensors ?? []
  const unmeasured = sensors.filter((sensor) => !sensor.usable)

  // The request outlives the sampling window by a little -- acquiring the
  // hardware lock, the final pass, serialising the reply -- so the countdown
  // hands over to "Finishing" instead of sitting on a stuck 0s.
  const buttonLabel = () => {
    if (busy !== 'dry') return 'Calibrate dry (air)'
    return remaining > 0 ? `Sampling… ${remaining}s` : 'Finishing…'
  }

  const capacityNote = (sensor) => {
    if (sensor.field_capacity_raw == null) return 'field capacity not measured'
    const where =
      sensor.field_capacity_source === 'pot'
        ? 'measured in this pot'
        : sensor.field_capacity_soil
          ? `from ${sensor.field_capacity_soil}`
          : 'source unknown'
    const span = sensor.field_capacity_raw - sensor.dry
    return `capacity ${sensor.field_capacity_raw} (${where}) · span ${span}`
  }

  return (
    <section className="panel-section">
      <h2>Moisture probes</h2>

      <div className="general-settings-form">
        <p className="field-hint">
          Measures each probe's dry reading, in open air. Probes read measurably
          differently from one another in identical conditions, so this is per
          sensor and is the floor of its scale.
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
          <p className="field-hint warning">
            These boards are not waterproof. Be sure to have heat shrinked the
            sensor from the white and above, covering all electrical components
            and connections.
          </p>
          <p className="field-hint">
            The top of the scale is <strong>field capacity</strong>, and it is
            not here. It is a property of the mix rather than the probe — the
            same mix in another pot gives roughly the same figure, and a
            different mix does not — so it is measured once per soil under
            Plants and Soil.
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
              <strong>{sensor.label || sensor.address}</strong> dry {sensor.dry}
              {sensor.calibrated_dry ? '' : ' (default)'} · {capacityNote(sensor)}
            </p>
          ))}
          {unmeasured.length > 0 && (
            <p className="field-hint warning">
              {unmeasured.length === 1 ? 'One pot has' : `${unmeasured.length} pots have`}{' '}
              no usable scale, so {unmeasured.length === 1 ? 'it reads' : 'they read'}{' '}
              nothing and {unmeasured.length === 1 ? 'is' : 'are'} never watered
              automatically. Either the field capacity has not been measured for
              that mix, or it sits too close to this probe's dry point to divide
              by — measure that pot's own under Plants and Soil.
            </p>
          )}
        </div>

        <div className="field-row">
          <button type="button" disabled={Boolean(busy)} onClick={reset}>
            Reset dry calibration
          </button>
          <p className="field-hint">
            Returns every sensor to MOISTURE_RAW_DRY. Field capacity is not
            affected: re-doing a dry pass should not throw away a measurement of
            somebody's potting mix.
          </p>
        </div>
      </div>
    </section>
  )
}
