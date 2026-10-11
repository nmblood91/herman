import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// The pump's flow rate: run it for a fixed time, weigh what came out, type in
// the millilitres.
//
// Nothing in the app runs the pump by hand except the calibration run below --
// watering a plant is a measured volume and stays under Controls. A raw run is
// only ever a diagnostic: it fills the line, proves the MOSFET switches, and
// produces the figure measured here.
//
// That flow rate is the one number in the planter that is a guess until
// someone measures it. A dose is a run time worked out from it, so a wrong
// one scales every watering by the same factor and still reports success.
export function PumpPanel() {
  const [pump, setPump] = useState(null)
  const [pumpStatus, setPumpStatus] = useState('')
  const [measuredMl, setMeasuredMl] = useState('')
  // When the run in progress ends, so the button can count down. The person
  // doing this is stood there holding a cup.
  const [runEndsAt, setRunEndsAt] = useState(null)
  const [tick, setTick] = useState(() => Date.now())

  const readPump = async () => {
    try {
      const response = await fetch(`${API_BASE}/pump`)
      if (!response.ok) return
      setPump(await response.json())
    } catch {
      // Leaves the readout blank rather than breaking the panel.
    }
  }

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!cancelled) await readPump()
    }
    load()
    const id = setInterval(() => setTick(Date.now()), 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const pumpAction = async (action) => {
    setPumpStatus('')
    try {
      const response = await fetch(`${API_BASE}/pump/${action}`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setPumpStatus(data.error || `Request failed (HTTP ${response.status})`)
        return
      }
      // A pump that fails to start answers 200 with {status: "error"}, so
      // response.ok alone reported it as running -- and with no
      // max_run_seconds in that body the message read "after undefineds".
      if (data.status === 'error') {
        setPumpStatus(`Pump did not start: ${data.error || 'unknown error'}`)
        return
      }

      if (action === 'run') {
        const seconds = data.max_run_seconds
        setRunEndsAt(Date.now() + seconds * 1000)
        setPumpStatus(`Pump running — stops on its own after ${seconds}s.`)
        // Re-read once it has stopped, so the measured run length appears
        // without anyone having to reload. The extra second is for the
        // auto-stop to land and be recorded.
        window.setTimeout(
          () => {
            setRunEndsAt(null)
            readPump()
          },
          seconds * 1000 + 1200,
        )
      } else {
        setRunEndsAt(null)
        setPumpStatus('Pump stopped.')
        window.setTimeout(readPump, 400)
      }
    } catch (error) {
      // Louder than a console.error: this control moves water, so a silent
      // failure is not acceptable.
      setPumpStatus(`Failed to ${action} pump: ${error.message}`)
    }
  }

  const saveFlow = async () => {
    setPumpStatus('')
    try {
      const response = await fetch(`${API_BASE}/pump/calibrate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ measured_ml: Number(measuredMl) }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setPumpStatus(data.detail || data.error || `Request failed (HTTP ${response.status})`)
        return
      }
      setPumpStatus(
        `Flow rate is ${data.flow_ml_per_second} mL/s. A 100 mL dose now runs ` +
          `the pump for ${Math.round(data.seconds_for_100ml)}s.`,
      )
      setMeasuredMl('')
      await readPump()
    } catch (error) {
      setPumpStatus(`Could not save the flow rate: ${error.message}`)
    }
  }

  const secondsLeft = runEndsAt ? Math.max(0, Math.ceil((runEndsAt - tick) / 1000)) : 0
  const lastRun = pump?.last_run ?? null
  const runLongEnough = lastRun && lastRun.seconds >= (pump?.min_calibration_seconds ?? 0)
  // No saving mid-run: the figure being divided by is the *previous* run, so
  // typing a volume while another is in progress would calibrate against the
  // wrong one.
  const canSaveFlow = !!runLongEnough && measuredMl !== '' && Number(measuredMl) > 0 && !runEndsAt

  return (
    <section className="panel-section">
      <h2>Pump</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <label>Flow rate</label>
          <p className="field-hint">
            {pump
              ? `${pump.flow_ml_per_second} mL/s — a 100 mL dose runs the pump for ${Math.round(pump.seconds_for_100ml)}s.`
              : '—'}
          </p>
          {pump?.measured_at && (
            <p className="field-hint">Measured {new Date(pump.measured_at).toLocaleString()}.</p>
          )}
        </div>

        <div className="field-row">
          <p className="field-hint">
            Run pump for 60 seconds to measure the flow rate. Run once as a prime, and then run
            again to measure. I recommend using a kitchen scale to weigh the water. 1g = 1 mL.
          </p>
          {/* One control, which becomes its own abort while the run is going.
              There is deliberately no idle Stop button: nothing in the app
              runs the pump by hand any more, so a Stop with nothing running
              would be a control for a state that cannot exist. An abort while
              it *is* running is not the same thing -- that is sixty seconds of
              pumping, and a tube that comes off wants stopping. */}
          {runEndsAt ? (
            <button type="button" onClick={() => pumpAction('stop')}>
              Stop — {secondsLeft}s left
            </button>
          ) : (
            <button type="button" className="primary" onClick={() => pumpAction('run')}>
              Run calibration ({pump?.max_run_seconds ?? 60}s)
            </button>
          )}
          {pumpStatus && <p className="field-hint warning">{pumpStatus}</p>}
        </div>

        <div className="field-row">
          <label>
            How much came out? (mL or g)
            <input
              type="number"
              min="0"
              value={measuredMl}
              onChange={(event) => setMeasuredMl(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary group-save-button"
            disabled={!canSaveFlow}
            onClick={saveFlow}
          >
            Save flow rate
          </button>
          {/* Nothing to say once the last run is long enough to divide by. */}
          {!lastRun && (
            <p className="field-hint warning">
              Run the pump to calibrate flow rate. A flow rate is the volume of water divided by the
              time it took to deliver it.
            </p>
          )}
          {lastRun && !runLongEnough && (
            <p className="field-hint warning">
              The last run was only {lastRun.seconds}s — too short to weigh accurately. Run the full{' '}
              {pump?.max_run_seconds ?? 60}s.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
