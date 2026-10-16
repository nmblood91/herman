import { useState } from 'react'
import { API_BASE } from '../api'

// "2026-10-14T14:00" -> "14:00". The planter only ever reports today-ish
// times here, and the date would just be noise.
const clock = (iso) => (iso ? iso.slice(11, 16) : '')

// What the startup home is doing right now, or null when there is nothing
// worth saying.
function startupLine(status) {
  switch (status?.phase) {
    case 'waiting':
      return status.held ? `Waiting to home: ${status.held}.` : 'Homing shortly.'
    case 'retrying':
      return (
        `Has not homed yet (${status.error}). Tried ${status.attempts} ` +
        `time${status.attempts === 1 ? '' : 's'}, trying again every minute.` +
        (status.held ? ` Paused for now: ${status.held}.` : '')
      )
    case 'done':
      return 'Homed since the planter started.'
    case 'next_start':
      return 'Takes effect the next time the planter starts.'
    default:
      return null
  }
}

function patrolLine(status) {
  const last = status?.last
  if (!status?.enabled || !last) return null
  return last.ok
    ? `Last patrol at ${clock(last.at)}.`
    : `The ${clock(last.at)} patrol did not run: ${last.error}.`
}

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

  const startupHome = overview?.startup_home
  const [homeOnStartup, setHomeOnStartup] = useState(false)
  const [startupMsg, setStartupMsg] = useState('')
  const [savingStartup, setSavingStartup] = useState(false)

  const patrol = overview?.auto_patrol
  const [patrolOn, setPatrolOn] = useState(false)
  const [patrolMsg, setPatrolMsg] = useState('')
  const [savingPatrol, setSavingPatrol] = useState(false)

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
    setHomeOnStartup(startupHome?.enabled ?? homeOnStartup)
    setPatrolOn(patrol?.enabled ?? patrolOn)
    setQuietOn(quiet?.quiet_hours_enabled ?? quietOn)
    setQuietStart(quiet?.quiet_hours_start ?? quietStart)
    setQuietStop(quiet?.quiet_hours_stop ?? quietStop)
  }

  // The switches save on toggle rather than behind a Save button: each is one
  // boolean with nothing to coordinate. Optimistic, so the box follows the
  // finger, and it goes back if the planter refuses.
  const saveToggle = async ({ path, enabled, previous, setOn, setMsg, setSaving, readBack }) => {
    setOn(enabled)
    setMsg('')
    setSaving(true)
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setOn(previous)
        setMsg(data.error || `Could not save (HTTP ${response.status})`)
        return
      }
      setOn(readBack(data))
      onRefresh?.()
    } catch (error) {
      setOn(previous)
      setMsg(`Could not save: ${error.message}`)
    } finally {
      setSaving(false)
    }
  }

  const saveAutoWatering = (enabled) =>
    saveToggle({
      path: '/watering/auto',
      enabled,
      previous: autoOn,
      setOn: setAutoOn,
      setMsg: setAutoMsg,
      setSaving: setSavingAuto,
      readBack: (data) => data.auto_watering_enabled,
    })

  const saveHomeOnStartup = (enabled) =>
    saveToggle({
      path: '/gantry/home-on-startup',
      enabled,
      previous: homeOnStartup,
      setOn: setHomeOnStartup,
      setMsg: setStartupMsg,
      setSaving: setSavingStartup,
      readBack: (data) => data.enabled,
    })

  const saveAutoPatrol = (enabled) =>
    saveToggle({
      path: '/patrol/auto',
      enabled,
      previous: patrolOn,
      setOn: setPatrolOn,
      setMsg: setPatrolMsg,
      setSaving: setSavingPatrol,
      readBack: (data) => data.enabled,
    })

  const [resumeMsg, setResumeMsg] = useState('')
  const resume = async () => {
    setResumeMsg('')
    try {
      const response = await fetch(`${API_BASE}/watering/resume`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setResumeMsg(data.error || `Could not resume (HTTP ${response.status})`)
        return
      }
      onRefresh?.()
    } catch (error) {
      setResumeMsg(`Could not resume: ${error.message}`)
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

          {watering?.soak_paused && (
            <div className="field-row">
              <p className="field-hint warning">
                Automatic watering is paused. {watering.soak_paused}
              </p>
              <div className="motion-grid">
                <button type="button" className="primary" onClick={resume}>
                  Resume watering
                </button>
              </div>
              {resumeMsg && <p className="field-hint warning">{resumeMsg}</p>}
            </div>
          )}

          {watering?.soak_check_enabled && (
            <p className="field-hint">
              After each watering, the pot&apos;s moisture probe has to show the
              water arriving within {watering.cooldown_minutes} minutes. Until it
              does, no pot is watered automatically, so an empty reservoir cannot
              run the pump dry one pot after another. Two waterings in a row that
              never show up pause automatic watering until you press Resume.
            </p>
          )}
        </div>

        {/* Both switches move the arm without anyone pressing a button, so
            both start off: a planter being assembled should not set off
            across the rail before someone has checked it is clear. */}
        <div className="settings-group">
          <h3>Homing</h3>

          <div className="field-row">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={homeOnStartup}
                disabled={savingStartup}
                onChange={(event) => saveHomeOnStartup(event.target.checked)}
              />
              Home after startup
            </label>
            <p className="field-hint">
              Homes the arm shortly after the planter comes up, and keeps trying
              once a minute until it succeeds. Until it homes, the board does not
              know where the arm is, so watering is refused outright. Waits for
              quiet hours or a snooze to end first.
            </p>
            {startupLine(startupHome) && (
              <p className={`field-hint${startupHome?.phase === 'retrying' ? ' warning' : ''}`}>
                {startupLine(startupHome)}
              </p>
            )}
            {startupMsg && <p className="field-hint warning">{startupMsg}</p>}

            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={patrolOn}
                disabled={savingPatrol}
                onChange={(event) => saveAutoPatrol(event.target.checked)}
              />
              Hourly auto-patrol
            </label>
            <p className="field-hint">
              Every hour, on the hour, the arm homes and then visits each plant
              in turn, moving the way that plant is watered: a pause over a point
              pot, a few passes across a sweep. Homing is the point: nothing
              tells the planter the arm has been nudged or a belt has slipped, so
              every plant position stays slightly wrong until the next home. The
              patrol shows you where it now thinks each plant is.
            </p>
            <p className="field-hint">
              Skipped during quiet hours and a snooze, since the arm is the other
              noisy part. If a watering is running, it waits a few minutes for it
              to finish.
            </p>
            {patrolLine(patrol) && (
              <p className={`field-hint${patrol?.last?.ok === false ? ' warning' : ''}`}>
                {patrolLine(patrol)}
              </p>
            )}
            {patrolMsg && <p className="field-hint warning">{patrolMsg}</p>}
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
