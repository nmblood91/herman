import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api'

// A slider fires a change per pixel of drag. Lighting applies on the spot here
// rather than behind a save button, so the writes are coalesced instead.
const APPLY_DEBOUNCE_MS = 250

// Three of the rows below are built from a list the API supplies, so when the
// API does not answer they render as a heading with nothing under it -- which
// reads as a UI that has lost those controls rather than a planter that has
// not answered yet. The jog buttons above have the better behaviour: they stay
// where they are and grey out. These do the same, with a disabled placeholder
// holding the row open and a hint saying what is missing.
const WAITING_HINT =
  'Waiting on the planter for this list. If the bar at the top says the ' +
  'connection failed, these fill themselves in once it answers.'

// Both plant rows come from the same list, so the reason is given once rather
// than identically under each of them.
const NO_PLANTS_HINT =
  'Waiting on the planter for the plant list, so this row and Water Plant ' +
  'below have nothing to name. If the bar at the top says the connection ' +
  'failed, both fill themselves in once it answers.'

const UI_MODE_BY_BACKEND = {
  schedule: 'schedule',
  manual: 'on',
  rainbow: 'rainbow',
  off: 'off',
}

const BACKEND_MODE_BY_UI = {
  schedule: 'schedule',
  on: 'manual',
  rainbow: 'rainbow',
  off: 'off',
}

const toHexColor = (value) => {
  if (Array.isArray(value)) {
    const [r, g, b] = value
    return `#${[r, g, b].map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
  }
  return value || '#00ff80'
}

const parseHexColor = (hex) => {
  const clean = hex.replace('#', '')
  const full = clean.length === 3 ? clean.split('').map((char) => char + char).join('') : clean
  const numeric = Number.parseInt(full, 16)
  return { r: (numeric >> 16) & 255, g: (numeric >> 8) & 255, b: numeric & 255 }
}

export function ControlsPanel({
  plants,
  quiet,
  onRefresh,
  gantryPosition,
  overview,
  onHome,
  onMove,
  onMoveToEnd,
  onMoveToPlant,
  onWaterPlant,
}) {
  const lighting = overview?.lighting

  // Klipper refuses every move until the axis has a reference, so an unhomed
  // gantry turns each of these buttons into a guaranteed failure. Disabled
  // rather than left to fail, since the error arrives a second later in a
  // status bar the user may not be looking at.
  //
  // Undefined overview counts as not ready, so the buttons stay disabled until
  // the first poll answers rather than flickering enabled for a moment.
  const movement = overview?.movement
  const boardDown = movement?.ok === false
  const motionReady = !boardDown && movement?.homed === true

  // Defaulted here rather than at each use: a failed dashboard load leaves the
  // prop an empty array today, but a crash on undefined would take the whole
  // panel down, jog buttons included.
  const plantList = plants ?? []

  const [ledMode, setLedMode] = useState('schedule')
  const [brightness, setBrightness] = useState(75)
  const [color, setColor] = useState('#00ff80')
  const [lightingError, setLightingError] = useState('')
  const [quietStatus, setQuietStatus] = useState('')
  const [dances, setDances] = useState([])
  const [dancing, setDancing] = useState('')
  const [danceStatus, setDanceStatus] = useState('')

  // Follows the server during render rather than in an effect, so the controls
  // never paint one frame of stale values after a refresh.
  const [syncedOverview, setSyncedOverview] = useState(null)
  if (overview !== syncedOverview) {
    setSyncedOverview(overview)
    setLedMode(UI_MODE_BY_BACKEND[lighting?.mode] ?? ledMode)
    setBrightness(lighting?.brightness ?? brightness)
    setColor(toHexColor(lighting?.color || color))
  }

  const timers = useRef({})
  useEffect(() => {
    const pending = timers.current
    return () => Object.values(pending).forEach(clearTimeout)
  }, [])

  const post = async (path, body) => {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setLightingError(data.error || `Request failed (HTTP ${response.status})`)
        return
      }
      setLightingError('')
    } catch (error) {
      setLightingError(`Could not reach the controller: ${error.message}`)
    }
  }

  // Keyed so a brightness drag and a colour drag do not cancel each other.
  const postDebounced = (key, path, body) => {
    clearTimeout(timers.current[key])
    timers.current[key] = setTimeout(() => post(path, body), APPLY_DEBOUNCE_MS)
  }

  const changeMode = (value) => {
    setLedMode(value)
    post('/lights/mode', { mode: BACKEND_MODE_BY_UI[value] || 'schedule' })
    if (value === 'on') {
      const { r, g, b } = parseHexColor(color)
      post('/lights/color', { r, g, b })
    }
  }

  const changeBrightness = (value) => {
    setBrightness(value)
    postDebounced('brightness', '/lights/brightness', { brightness: Number(value) })
  }

  const changeColor = (value) => {
    setColor(value)
    postDebounced('color', '/lights/color', parseHexColor(value))
  }

  const snooze = async (hours) => {
    setQuietStatus('')
    try {
      const path = hours === 0 ? '/quiet/resume' : '/quiet/snooze'
      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hours }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setQuietStatus(data.error || `Request failed (HTTP ${response.status})`)
        return
      }
      onRefresh?.()
    } catch (error) {
      setQuietStatus(`Could not reach the controller: ${error.message}`)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function loadDances() {
      try {
        const response = await fetch(`${API_BASE}/dances`)
        if (!response.ok || cancelled) return
        const data = await response.json()
        setDances(data.dances || [])
      } catch {
        // No buttons rather than a broken panel.
      }
    }
    loadDances()
    return () => {
      cancelled = true
    }
  }, [])

  const runDance = async (dance) => {
    setDancing(dance.name)
    setDanceStatus(`${dance.title}...`)
    try {
      const response = await fetch(`${API_BASE}/dances/run/${dance.name}`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      setDanceStatus(
        data.ok ? `${dance.title} done.` : data.error || `Failed (HTTP ${response.status})`,
      )
      onRefresh?.()
    } catch (error) {
      setDanceStatus(`Failed: ${error.message}`)
    } finally {
      setDancing('')
    }
  }

  return (
    <>
      <section className="panel-section">
        <h2>Gantry</h2>

        <div className="position-readout">Position: {gantryPosition}</div>

        <div className="motion-grid">
          <button className="primary" onClick={onHome}>Home Gantry</button>
        </div>

        {!motionReady && (
          <p className="field-hint warning">
            {boardDown
              ? 'The motion board is not responding, so the gantry cannot be moved. Check the USB lead to the SKR.'
              : 'Home the gantry first. Until it has a reference, Klipper refuses every move.'}
          </p>
        )}

        <div className="motion-grid two-up">
          <button disabled={!motionReady} onClick={() => onMove(-10)}>Move Left 10 mm</button>
          <button disabled={!motionReady} onClick={() => onMove(10)}>Move Right 10 mm</button>
        </div>

        <div className="motion-grid two-up">
          <button disabled={!motionReady} onClick={() => onMove(-50)}>Move Left 50 mm</button>
          <button disabled={!motionReady} onClick={() => onMove(50)}>Move Right 50 mm</button>
        </div>

        {/* The far end is resolved by the API from Klipper's axis_maximum, so
            this does not need to know how long the rail is. */}
        <div className="motion-grid two-up">
          <button disabled={!motionReady} onClick={() => onMoveToEnd('left')}>
            All the way left
          </button>
          <button disabled={!motionReady} onClick={() => onMoveToEnd('right')}>
            All the way right
          </button>
        </div>

        <div className="subsection">
          <h3>Dances</h3>
          <div className="plant-actions-grid">
            {dances.length ? (
              dances.map((dance) => (
                <button
                  key={dance.name}
                  title={dance.description}
                  className={dancing === dance.name ? 'working' : undefined}
                  disabled={Boolean(dancing)}
                  onClick={() => runDance(dance)}
                >
                  {dance.title}
                </button>
              ))
            ) : (
              <button disabled>No routines loaded</button>
            )}
          </div>
          <p className="field-hint">
            Homes first if the arm has lost its place, then runs the routine and
            parks back at 0. {danceStatus}
          </p>
          {!dances.length && <p className="field-hint warning">{WAITING_HINT}</p>}
        </div>

        <div className="subsection">
          <h3>Move to Plant</h3>
          <div className="plant-actions-grid">
            {plantList.length ? (
              plantList.map((plant) => (
                <button
                  key={plant.plant_id}
                  disabled={!motionReady}
                  onClick={() => onMoveToPlant(plant.plant_id)}
                >
                  {plant.name}
                </button>
              ))
            ) : (
              <button disabled>No plants loaded</button>
            )}
          </div>
          {!plantList.length && <p className="field-hint warning">{NO_PLANTS_HINT}</p>}
        </div>

        <div className="subsection">
          <h3>Water Plant</h3>
          <div className="plant-actions-grid">
            {plantList.length ? (
              plantList.map((plant) => (
                <button
                  key={plant.plant_id}
                  disabled={!motionReady}
                  onClick={() => onWaterPlant(plant.plant_id)}
                >
                  {plant.name}
                </button>
              ))
            ) : (
              <button disabled>No plants loaded</button>
            )}
          </div>
          <p className="field-hint">
            Moves to the plant and doses its saved volume. Takes about a minute;
            watch the status bar at the top.
            {!motionReady && ' Held until the gantry is homed, since a dose starts with a move.'}
          </p>
        </div>
      </section>

      <section className="panel-section">
        <h2>Lighting</h2>

        <div className="general-settings-form">
          <div className="field-row">
            <label>
              LED mode
              <select value={ledMode} onChange={(event) => changeMode(event.target.value)}>
                <option value="schedule">Schedule</option>
                <option value="on">On</option>
                <option value="rainbow">Rainbow Mode</option>
                <option value="off">Off</option>
              </select>
            </label>
          </div>

          {ledMode !== 'off' && (
            <div className="field-row">
              <label>
                Brightness
                <div className="slider-row">
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={brightness}
                    onChange={(event) => changeBrightness(Number(event.target.value))}
                  />
                  <span>{brightness}%</span>
                </div>
              </label>
            </div>
          )}

          {ledMode === 'on' && (
            <div className="field-row">
              <label>
                LED color
                <input
                  type="color"
                  value={color}
                  onChange={(event) => changeColor(event.target.value)}
                />
              </label>
            </div>
          )}

          <p className="field-hint">
            Lighting applies as you change it. Strip type and colour order are
            under Calibration — they are facts about the strip you soldered on,
            not things you change day to day.
          </p>

          {lighting && lighting.spi_ready === false && (
            <p className="field-hint warning">
              LED output unavailable, SPI did not open
              {lighting.error ? `: ${lighting.error}` : ''}
            </p>
          )}
          {lightingError && <p className="field-hint warning">{lightingError}</p>}
        </div>
      </section>

      <section className="panel-section">
        <h2>Quiet</h2>

        <div className="general-settings-form">
          <div className="field-row">
            <div className="motion-grid">
              {[1, 2, 4].map((hours) => (
                <button key={hours} type="button" onClick={() => snooze(hours)}>
                  Snooze {hours}h
                </button>
              ))}
            </div>
            {quiet?.snooze_until && (
              <div className="motion-grid">
                <button type="button" className="primary" onClick={() => snooze(0)}>
                  Resume watering now
                </button>
              </div>
            )}
            <p className="field-hint">
              {quiet?.suppressed_because
                ? `Automatic watering is held: ${quiet.suppressed_because}. A plant that comes due waits rather than being skipped.`
                : 'Holds off automatic watering for a while. The pump and the gantry are the noisy parts, and a dose you start yourself still runs.'}
            </p>
            {quietStatus && <p className="field-hint warning">{quietStatus}</p>}
          </div>
        </div>
      </section>

    </>
  )
}
