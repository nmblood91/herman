import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

// The X home switch.
//
// Not polled on mount: reading it takes the gantry lock, so a background poll
// would collide with the control loop and with every watering cycle. It runs
// when asked, and the watch below is a short burst so you can press the switch
// and see the reading move -- which is the only check that separates a switch
// on the wrong terminal from a broken wire.
export function HomeSwitchPanel() {
  const [endstop, setEndstop] = useState(null)
  const [endstopBusy, setEndstopBusy] = useState(false)
  const [watching, setWatching] = useState(false)

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
    const poll = setInterval(readEndstop, 1000)
    const stop = setTimeout(() => setWatching(false), 20000)
    return () => {
      clearInterval(poll)
      clearTimeout(stop)
    }
    // readEndstop is recreated every render and depending on it would restart
    // the interval each tick; watching is the only real trigger.
  }, [watching])

  // The first reading is taken here rather than in the effect above, so the
  // answer is on screen straight away instead of a second into the watch.
  const toggleWatching = () => {
    if (!watching) readEndstop()
    setWatching((on) => !on)
  }

  const endstopTone =
    endstop?.verdict === 'healthy' || endstop?.verdict === 'at_switch'
      ? 'field-hint'
      : 'field-hint warning'

  return (
    <section className="panel-section">
      <h2>Limit / home switch</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="slider-row">
            <button type="button" disabled={endstopBusy || watching} onClick={readEndstop}>
              {endstopBusy && !watching ? 'Reading…' : 'Test home switch'}
            </button>
            <button type="button" className="primary" onClick={toggleWatching}>
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
      </div>
    </section>
  )
}
