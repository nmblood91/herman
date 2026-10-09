import { useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { CalibrationPanel } from './CalibrationPanel'
import { LogsPanel } from './LogsPanel'

// Everything you reach for when something looks wrong, in one place rather
// than spread across Settings and the old Sensors tab.
//
// Ordered as checks you run, then references you read: the switch test and the
// version first, then calibration and the log.
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

      {/* Both fetch their own data, so running a calibration does not reload
          the rest of the dashboard. */}
      <CalibrationPanel />
      <LogsPanel />
    </>
  )
}
