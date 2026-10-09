import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

const DEFAULT_COLOR_ORDERS = ['RGB', 'RBG', 'GRB', 'GBR', 'BRG', 'BGR']

export function SettingsPanel({ overview, onRefresh }) {
  const lighting = overview?.lighting
  const colorOrderOptions = lighting?.color_order_options ?? DEFAULT_COLOR_ORDERS
  const chipOptions = lighting?.chip_options ?? []

  const [chip, setChip] = useState('WS2811')
  const [colorOrder, setColorOrder] = useState('GRB')
  const [status, setStatus] = useState('')

  const watering = overview?.watering
  const [autoOn, setAutoOn] = useState(false)
  const [autoMsg, setAutoMsg] = useState('')
  const [savingAuto, setSavingAuto] = useState(false)

  const idle = overview?.idle_motion
  const [idleOn, setIdleOn] = useState(true)
  const [idleMinutes, setIdleMinutes] = useState(60)
  const [idleMsg, setIdleMsg] = useState('')

  const quiet = overview?.quiet
  const [quietOn, setQuietOn] = useState(false)
  const [quietStart, setQuietStart] = useState('21:00')
  const [quietStop, setQuietStop] = useState('08:00')
  const [quietMsg, setQuietMsg] = useState('')

  // The soil library. Self-fetched rather than passed down: it changes only
  // when edited here, so putting it in the dashboard poll would reload it
  // after every unrelated button press.
  const [soils, setSoils] = useState([])
  const [soilName, setSoilName] = useState('')
  const [soilCapacity, setSoilCapacity] = useState('')
  const [soilWilting, setSoilWilting] = useState('')
  const [soilMsg, setSoilMsg] = useState('')

  // Resynced during render rather than in an effect, so the form never paints
  // one frame of stale values after a refresh.
  const [syncedOverview, setSyncedOverview] = useState(null)
  if (overview !== syncedOverview) {
    setSyncedOverview(overview)
    setChip(lighting?.chip ?? chip)
    setAutoOn(watering?.auto_watering_enabled ?? autoOn)
    setIdleOn(idle?.enabled ?? idleOn)
    setIdleMinutes(idle?.minutes ?? idleMinutes)
    setQuietOn(quiet?.quiet_hours_enabled ?? quietOn)
    setQuietStart(quiet?.quiet_hours_start ?? quietStart)
    setQuietStop(quiet?.quiet_hours_stop ?? quietStop)
    setColorOrder(lighting?.color_order ?? colorOrder)
  }

  // Explicit save, unlike the lighting controls: these are build-time facts
  // about the hardware, and selecting a chip resets the colour order to that
  // chip's default, so the two have to be sent in a known order.
  const save = async () => {
    setStatus('')
    try {
      for (const [path, body] of [
        ['/lights/chip', { chip }],
        ['/lights/color-order', { color_order: colorOrder }],
      ]) {
        const response = await fetch(`${API_BASE}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          setStatus(data.error || `Save failed (HTTP ${response.status})`)
          return
        }
      }
      setStatus('Saved.')
    } catch (error) {
      setStatus(`Save failed: ${error.message}`)
    }
  }

  // Saves on toggle rather than behind the Save button: it is one boolean
  // with nothing to coordinate, and the status bar answers immediately once
  // the dashboard reloads. Optimistic, so the box follows the finger, and it
  // goes back if the planter refuses.
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
        body: JSON.stringify({ enabled: idleOn, minutes: Number(idleMinutes) }),
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

  const readSoils = async () => {
    try {
      const response = await fetch(`${API_BASE}/soils`)
      if (!response.ok) return
      const data = await response.json()
      setSoils(data.soils ?? [])
    } catch {
      // Leaves the list empty rather than breaking the panel.
    }
  }

  useEffect(() => {
    readSoils()
  }, [])

  const saveSoil = async () => {
    setSoilMsg('')
    try {
      const response = await fetch(`${API_BASE}/soils`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: soilName,
          field_capacity_vwc: Number(soilCapacity),
          wilting_point_vwc: Number(soilWilting),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setSoilMsg(data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setSoilMsg(
        `Saved ${data.name}: ${data.available_points} points of usable water, ` +
          `wilting at ${Math.round((data.wilting_fraction ?? 0) * 100)}% of field capacity.`,
      )
      setSoilName('')
      setSoilCapacity('')
      setSoilWilting('')
      await readSoils()
    } catch (error) {
      setSoilMsg(`Save failed: ${error.message}`)
    }
  }

  const removeSoil = async (name) => {
    setSoilMsg('')
    try {
      const response = await fetch(`${API_BASE}/soils/${encodeURIComponent(name)}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setSoilMsg(data.error || `Could not remove ${name}`)
        return
      }
      // Pots still naming it keep the name, which stops resolving. Saying so
      // is the point -- a silently cleared soil hides that a pot is no longer
      // described, and a pot with no soil is never watered automatically.
      setSoilMsg(`Removed ${name}. Any pot still set to it needs a new soil.`)
      await readSoils()
    } catch (error) {
      setSoilMsg(`Could not remove ${name}: ${error.message}`)
    }
  }

  const soilFormReady =
    soilName.trim() && soilCapacity !== '' && soilWilting !== ''

  return (
    <section className="panel-section">
      <h2>Settings</h2>

      {/* Grouped rather than left as one column of unrelated fields. The order
          is what the planter does on its own, then when it is allowed to, then
          the hardware it was built with. The clock those schedules run on is a
          readout with warning states rather than a setting, so it sits in
          Diagnostics. */}
      <div className="general-settings-form">
        <div className="settings-group">
          <h3>Watering</h3>

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
              Before turning this on, measure the pump's flow rate and set it in{' '}
              <code>PUMP_FLOW_ML_PER_SECOND</code>. A dose is a run time worked
              out from that number, so if it is wrong every automatic watering is
              wrong by the same factor and still reports success.
            </p>
            {autoMsg && <p className="field-hint warning">{autoMsg}</p>}
          </div>
        </div>

        <div className="settings-group">
          <h3>Movement</h3>

          <div className="field-row">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={idleOn}
                onChange={(event) => setIdleOn(event.target.checked)}
              />
              Move about now and then
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
              Re-homes the arm and runs a short routine on this interval, cycling
              through them. The re-home is the useful half: nothing tells the
              planter the arm has been nudged or that a belt slipped, so every
              plant position stays slightly wrong until it homes again.
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
            {quietMsg && <p className="field-hint warning">{quietMsg}</p>}
          </div>
        </div>

        <div className="settings-group">
          <h3>Lighting</h3>

          <div className="field-row">
            <label>
              LED strip type
              <select value={chip} onChange={(event) => setChip(event.target.value)}>
                {chipOptions.map((option) => (
                  <option key={option.name} value={option.name}>
                    {option.name} ({option.description})
                  </option>
                ))}
              </select>
            </label>
            <p className="field-hint">
              Sets the signal timing for your strip. WS2811 drives three LEDs per
              pixel, so set LED count to a third of the LEDs you can see.
            </p>
          </div>

          <div className="field-row">
            <label>
              LED colour order
              <select value={colorOrder} onChange={(event) => setColorOrder(event.target.value)}>
                {colorOrderOptions.map((order) => (
                  <option key={order} value={order}>
                    {order}
                  </option>
                ))}
              </select>
            </label>
            <p className="field-hint">
              If red and green look swapped on the strip, try a different order.
              Choosing a strip type resets this to that chip's usual order, so set
              the type first.
            </p>
          </div>

          {/* In the group it belongs to, and named after it. This button only
              ever saved these two fields, and sitting at the foot of the panel
              labelled "Save Settings" it read as saving everything above it --
              including three groups that each save themselves. */}
          <button type="button" className="primary group-save-button" onClick={save}>
            Save lighting
          </button>
          {status && <p className="field-hint warning">{status}</p>}
        </div>

        <div className="settings-group">
          <h3>Soils</h3>

          <div className="field-row">
            {soils.length ? (
              <ul className="soil-list">
                {soils.map((soil) => (
                  <li key={soil.name}>
                    <span>
                      <strong>{soil.name}</strong>
                      <small>
                        field capacity {soil.field_capacity_vwc}% &middot; wilting{' '}
                        {soil.wilting_point_vwc}% &middot; {soil.available_points} pts usable
                      </small>
                    </span>
                    <button type="button" onClick={() => removeSoil(soil.name)}>
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="field-hint warning">
                No soils yet. Install the starting set on the Pi with{' '}
                <code>python -m greenthumb.soil_library --install</code>, or add
                your own below. Until a pot has a soil it is never watered
                automatically.
              </p>
            )}
          </div>

          <div className="field-row">
            <div className="soil-form">
              <label>
                Name
                <input
                  value={soilName}
                  placeholder="My potting mix"
                  onChange={(event) => setSoilName(event.target.value)}
                />
              </label>
              <label>
                Field capacity (% VWC)
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={soilCapacity}
                  onChange={(event) => setSoilCapacity(event.target.value)}
                />
              </label>
              <label>
                Wilting point (% VWC)
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={soilWilting}
                  onChange={(event) => setSoilWilting(event.target.value)}
                />
              </label>
            </div>
            <button
              type="button"
              className="primary group-save-button"
              disabled={!soilFormReady}
              onClick={saveSoil}
            >
              Save soil
            </button>
            {soilMsg && <p className="field-hint">{soilMsg}</p>}
          </div>

          <div className="field-row">
            <p className="field-hint">
              Saving replaces any soil of the same name. Only the <em>ratio</em>
              {' '}of these two leaves this table usefully — it is dimensionless, so
              a published figure applies to any pot of that mix, and it is what
              fixes the bottom of the moisture scale. The absolute figures do
              not convert into sensor readings, which is why field capacity is
              still measured per pot by the wet calibration.
            </p>
            <p className="field-hint">
              To measure your own: weigh the pot soaked and drained 24 hours,
              then again bone dry, and the difference is the water it holds.
              Bagged mixes vary by manufacturer and by how firmly they were
              packed, and they lose capacity as they age and compact — so a
              measured mix beats a looked-up one.
            </p>
          </div>
        </div>

      </div>
    </section>
  )
}
