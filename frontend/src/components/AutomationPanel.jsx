import { useState } from 'react'
import { API_BASE } from '../api'

// Everything the planter does on its own, and the windows in which it is
// allowed to. Three groups in that order: what it does unattended, how it keeps
// itself accurate, and when it has to stay quiet.
//
// These were spread across the old Settings tab alongside hardware facts like
// the LED chip, which meant "does this planter water by itself" sat next to
// "which strip did you solder on". They are not the same kind of question.
export function AutomationPanel({ overview, onRefresh }) {
  const watering = overview?.watering
  const [autoOn, setAutoOn] = useState(false)
  const [autoMsg, setAutoMsg] = useState('')
  const [savingAuto, setSavingAuto] = useState(false)

  const idle = overview?.idle_motion
  const [idleOn, setIdleOn] = useState(true)
  const [idleMinutes, setIdleMinutes] = useState(60)
  const [homeOnStartup, setHomeOnStartup] = useState(true)
  const [idleMsg, setIdleMsg] = useState('')

  const quiet = overview?.quiet
  const [quietOn, setQuietOn] = useState(false)
  const [quietStart, setQuietStart] = useState('21:00')
  const [quietStop, setQuietStop] = useState('08:00')
  const [quietMsg, setQuietMsg] = useState('')

  // Resynced during render rather than in an effect, so the form never paints
  // one frame of stale values after a refresh.
  const [syncedOverview, setSyncedOverview] = useState(null)
  if (overview !== syncedOverview) {
    setSyncedOverview(overview)
    setAutoOn(watering?.auto_watering_enabled ?? autoOn)
    setIdleOn(idle?.enabled ?? idleOn)
    setIdleMinutes(idle?.minutes ?? idleMinutes)
    setHomeOnStartup(idle?.home_on_startup ?? homeOnStartup)
    setQuietOn(quiet?.quiet_hours_enabled ?? quietOn)
    setQuietStart(quiet?.quiet_hours_start ?? quietStart)
    setQuietStop(quiet?.quiet_hours_stop ?? quietStop)
  }

  // Saves on toggle rather than behind a Save button: it is one boolean with
  // nothing to coordinate, and the status bar answers immediately once the
  // dashboard reloads. Optimistic, so the box follows the finger, and it goes
  // back if the planter refuses.
  const saveAutoWatering = async (enabled) => {
    const previous = autoOn
    setAutoOn(enabled)
    setAutoMsg('')
    setSavingAuto(true)
    try {
      const response = await fetch(`${API_BASE}/watering/auto`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setAutoOn(previous)
        setAutoMsg(data.error || `Could not save (HTTP ${response.status})`)
        return
      }
      setAutoOn(data.auto_watering_enabled)
      onRefresh?.()
    } catch (error) {
      setAutoOn(previous)
      setAutoMsg(`Could not save: ${error.message}`)
    } finally {
      setSavingAuto(false)
    }
  }

  // Behind a button rather than saving on each keystroke, like quiet hours:
  // the interval is a typed number, and halfway through editing 90 it is 9.
  const saveIdle = async () => {
    setIdleMsg('')
    try {
      const response = await fetch(`${API_BASE}/dances/auto`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: idleOn,
          minutes: Number(idleMinutes),
          home_on_startup: homeOnStartup,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setIdleMsg(data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setIdleMsg('Saved.')
      onRefresh?.()
    } catch (error) {
      setIdleMsg(`Save failed: ${error.message}`)
    }
  }

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
      onRefresh?.()
    } catch (error) {
      setQuietMsg(`Save failed: ${error.message}`)
    }
  }

  return (
    <section className="panel-section">
      <h2>Automation</h2>

      <div className="general-settings-form">
        <div className="settings-group">
          <h3>Auto-water</h3>

          <div className="field-row">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={autoOn}
                disabled={savingAuto}
                onChange={(event) => saveAutoWatering(event.target.checked)}
              />
              Water plants automatically
            </label>
            <p className="field-hint">
              Lets the planter water on its own whenever a plant sits below its
              moisture target. Switched off it still reads the sensors and keeps
              the history — watering only happens when you press a button.
            </p>
            <p className="field-hint">
              Before turning this on, measure the pump's flow rate under
              Calibration. A dose is a run time worked out from that number, so
              if it is wrong every automatic watering is wrong by the same
              factor and still reports success.
            </p>
            {autoMsg && <p className="field-hint warning">{autoMsg}</p>}
          </div>
        </div>

        {/* Named after the half that matters. This was "Move about now and
            then", which described the visible effect and hid the point: the
            routine is a side effect of the re-home, not the other way round. */}
        <div className="settings-group">
          <h3>Auto-home</h3>

          <div className="field-row">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={homeOnStartup}
                onChange={(event) => setHomeOnStartup(event.target.checked)}
              />
              Re-home on startup
            </label>
            <p className="field-hint">
              Homes once, shortly after the planter comes up. Until it homes,
              the board reports a position relative to wherever the arm happened
              to be when the power went on — so every saved plant coordinate is
              wrong by an unknown amount and watering is refused outright.
              Deferred, not skipped, if the planter boots inside quiet hours.
            </p>

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={idleOn}
                onChange={(event) => setIdleOn(event.target.checked)}
              />
              Re-home during operation
            </label>
            <div className="slider-row">
              <label>
                Every
                <input
                  type="number"
                  min="5"
                  max="1440"
                  value={idleMinutes}
                  onChange={(event) => setIdleMinutes(event.target.value)}
                />
              </label>
              <span>minutes</span>
              <button type="button" onClick={saveIdle}>Save</button>
            </div>
            <p className="field-hint">
              Re-homes the arm on this interval and runs a short routine while it
              is up, cycling through them. The re-home is the useful half:
              nothing tells the planter the arm has been nudged or that a belt
              slipped, so every plant position stays slightly wrong until it
              homes again.
            </p>
            <p className="field-hint">
              Held during quiet hours and a snooze, same as watering — the arm is
              the other noisy part. Routines you start yourself always run.
              {idle?.last_at ? ` Last moved ${idle.last_at}.` : ''}
            </p>
            {idleMsg && <p className="field-hint warning">{idleMsg}</p>}
          </div>
        </div>

        <div className="settings-group">
          <h3>Quiet hours</h3>

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
            <p className="field-hint">
              To hold watering off right now rather than on a schedule, use the
              snooze under Controls.
            </p>
            {quietMsg && <p className="field-hint warning">{quietMsg}</p>}
          </div>
        </div>

      </div>
    </section>
  )
}
