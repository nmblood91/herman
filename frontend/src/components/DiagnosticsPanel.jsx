import { useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { CalibrationPanel } from './CalibrationPanel'
import { LogsPanel } from './LogsPanel'

// Everything you reach for when something looks wrong, in one place rather
// than spread across Settings and the old Sensors tab.
//
// Ordered as checks you run, then references you read: the switch test and the
// version first, then the two calibrations -- pump flow and the moisture
// probes -- and the log last.
export function DiagnosticsPanel() {
  // Home switch. Not polled on mount: reading it takes the gantry lock, so a
  // background poll would collide with the control loop and with every
  // watering cycle. It runs when asked, and the watch below is a short burst so
  // you can press the switch and see the reading move -- which is the only
  // check that separates a switch on the wrong terminal from a broken wire.
  const [endstop, setEndstop] = useState(null)
  const [endstopBusy, setEndstopBusy] = useState(false)
  const [watching, setWatching] = useState(false)

  // The planter's clock. A readout with three warning states rather than a
  // setting, which is why it lives here: there is no battery-backed clock, so
  // after a power cut it reverts to roughly its last shutdown, and "the lights
  // came on at the wrong time" is answered from this panel.
  const [clock, setClock] = useState(null)
  const [clockStatus, setClockStatus] = useState('')
  const [syncing, setSyncing] = useState(false)
  // Ticks locally off the offset between the planter's clock and this device's,
  // so the readout counts seconds like a device display instead of freezing on
  // whatever the last fetch returned.
  const [skewMs, setSkewMs] = useState(null)
  const [tick, setTick] = useState(() => Date.now())

  const [build, setBuild] = useState(null)

  // The pump. Here rather than in Controls because the only reasons to run it
  // by hand are diagnostic: priming the line, proving the MOSFET switches, and
  // measuring the flow rate below.
  //
  // That flow rate is the one number in the planter that is a guess until
  // someone measures it. A dose is a run time worked out from it, so a wrong
  // one scales every watering by the same factor and still reports success.
  const [pump, setPump] = useState(null)
  const [pumpStatus, setPumpStatus] = useState('')
  const [measuredMl, setMeasuredMl] = useState('')
  // When the run in progress ends, so the button can count down. The person
  // doing this is stood there holding a cup.
  const [runEndsAt, setRunEndsAt] = useState(null)

  const readPump = async () => {
    try {
      const response = await fetch(`${API_BASE}/pump`)
      if (!response.ok) return
      setPump(await response.json())
    } catch {
      // Leaves the readout blank rather than breaking the panel.
    }
  }

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
        window.setTimeout(() => {
          setRunEndsAt(null)
          readPump()
        }, seconds * 1000 + 1200)
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
          `the pump for ${data.seconds_for_100ml}s.`,
      )
      setMeasuredMl('')
      await readPump()
    } catch (error) {
      setPumpStatus(`Could not save the flow rate: ${error.message}`)
    }
  }

  const secondsLeft = runEndsAt ? Math.max(0, Math.ceil((runEndsAt - tick) / 1000)) : 0
  const lastRun = pump?.last_run ?? null
  const runLongEnough =
    lastRun && lastRun.seconds >= (pump?.min_calibration_seconds ?? 0)
  const canSaveFlow =
    !!runLongEnough && measuredMl !== '' && Number(measuredMl) > 0 && !runEndsAt

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
    readPump()
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

  const readEndstop = async () => {
    setEndstopBusy(true)
    try {
      const response = await fetch(`${API_BASE}/diagnostics/endstop`)
      const data = await response.json()
      // 409 carries {ok:false,error} from the hardware-busy handler, which is
      // a real answer rather than a failure: the gantry is mid-move.
      setEndstop(
        response.status === 409
          ? { ok: false, verdict: 'busy', detail: data.error || 'The gantry is busy.' }
          : data,
      )
    } catch (error) {
      setEndstop({
        ok: false,
        verdict: 'unavailable',
        detail: `Could not reach Herman: ${error.message}`,
      })
    } finally {
      setEndstopBusy(false)
    }
  }

  // Polls for twenty seconds then stops itself. Long enough to walk over and
  // press the switch, short enough that it cannot sit there taking the gantry
  // lock once a second forever.
  useEffect(() => {
    if (!watching) return undefined
    readEndstop()
    const poll = setInterval(readEndstop, 1000)
    const stop = setTimeout(() => setWatching(false), 20000)
    return () => {
      clearInterval(poll)
      clearTimeout(stop)
    }
    // readEndstop is recreated every render and depending on it would restart
    // the interval each tick; watching is the only real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching])

  const endstopTone =
    endstop?.verdict === 'healthy' || endstop?.verdict === 'at_switch'
      ? 'field-hint'
      : 'field-hint warning'

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

  return (
    <>
      <section className="panel-section">
        <h2>Diagnostics</h2>

        <div className="general-settings-form">
          <div className="field-row">
            <label>Home switch</label>
            <div className="slider-row">
              <button type="button" disabled={endstopBusy || watching} onClick={readEndstop}>
                {endstopBusy && !watching ? 'Reading…' : 'Test home switch'}
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => setWatching((on) => !on)}
              >
                {watching ? 'Stop watching' : 'Watch for 20s'}
              </button>
              {endstop?.ok && (
                <span className="position-readout">
                  {endstop.triggered ? 'Triggered' : 'Open'}
                </span>
              )}
            </div>

            {!endstop ? (
              <p className="field-hint">
                Reads the switch at the far end of the rail and says what the
                reading means. <strong>Watch for 20s</strong> then press the
                switch by hand — seeing it change is the only check that tells a
                switch on the wrong terminal apart from a broken wire.
              </p>
            ) : (
              <p className={endstopTone}>{endstop.detail}</p>
            )}

            {watching && (
              <p className="field-hint">
                Watching. Press and release the switch; the reading above should
                follow. This stops by itself.
              </p>
            )}

            {endstop?.ok && (
              <p className="field-hint">
                Wired normally closed, so a closed contact reads <em>open</em> and
                an open circuit reads <em>triggered</em>. That is why an unplugged
                switch makes homing refuse rather than drive into the end of the
                rail.
                {endstop.homed === false &&
                  ' The axis is not homed, so the position is a counter rather than a measurement.'}
              </p>
            )}
          </div>

          <div className="field-row">
            <label>Clock</label>
            <div className="slider-row">
              <button type="button" disabled={syncing || !clock?.can_set} onClick={syncTimezone}>
                {syncing ? 'Syncing…' : 'Sync to Local Time'}
              </button>
              <span className="position-readout">Herman&apos;s clock: {planterClock}</span>
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
        </div>
      </section>

      <section className="panel-section">
        <h2>Pump</h2>

        <div className="general-settings-form">
          <div className="field-row">
            <label>Flow rate</label>
            <p className="field-hint">
              {pump
                ? `${pump.flow_ml_per_second} mL/s — a 100 mL dose runs the pump for ${pump.seconds_for_100ml}s.`
                : '—'}
            </p>
            {pump && !pump.measured_at && (
              <p className="field-hint warning">
                Never measured. This is the pump's rated figure, which assumes
                no lift and no tubing, so your real rate is almost certainly
                lower and every dose is wrong by the same factor. Measure it
                before turning automatic watering on.
              </p>
            )}
            {pump?.measured_at && (
              <p className="field-hint">
                Measured {new Date(pump.measured_at).toLocaleString()}. Worth
                redoing once a season — peristaltic tubing takes a set as it
                ages, and the rate drifts with it.
              </p>
            )}
          </div>

          <div className="field-row">
            <div className="motion-grid two-up">
              <button type="button" disabled={!!runEndsAt} onClick={() => pumpAction('run')}>
                {runEndsAt
                  ? `Running — ${secondsLeft}s left`
                  : `Run pump for ${pump?.max_run_seconds ?? 60}s`}
              </button>
              {/* Never disabled: it is the panic control, and disabling it on
                  the frontend's idea of state would fail exactly when that idea
                  is wrong. Stopping an already-stopped pump is harmless. */}
              <button type="button" onClick={() => pumpAction('stop')}>
                Stop Pump
              </button>
            </div>
            <p className="field-hint">
              Runs the pump where it stands, without moving the gantry. It stops
              on its own at the end even if you close this page.
            </p>
            {pumpStatus && <p className="field-hint warning">{pumpStatus}</p>}
          </div>

          <div className="field-row">
            <label>
              How much came out? (mL)
              <input
                type="number"
                min="0"
                step="1"
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
            {lastRun ? (
              <p className={`field-hint${runLongEnough ? '' : ' warning'}`}>
                {runLongEnough
                  ? `Divided by the last run, which was ${lastRun.seconds}s.`
                  : `The last run was only ${lastRun.seconds}s — too short to ` +
                    `weigh accurately. Run the full ${pump?.max_run_seconds ?? 60}s.`}
              </p>
            ) : (
              <p className="field-hint warning">
                Run the pump first. A flow rate is a volume divided by the time
                it took to deliver it.
              </p>
            )}
            <p className="field-hint">
              Weigh it rather than reading a jug — 1 g of water is 1 mL, and a
              kitchen scale beats graduations. Prime the line first: the very
              first run fills the tube, and that volume is not flow. Three runs
              that agree within a few percent is a number you can trust.
            </p>
          </div>
        </div>
      </section>

      {/* Both fetch their own data, so running a calibration does not reload
          the rest of the dashboard. */}
      <CalibrationPanel />
      <LogsPanel />
    </>
  )
}
