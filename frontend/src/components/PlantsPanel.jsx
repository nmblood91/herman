import { useState } from 'react'

const draftFrom = (plant) => ({
  name: plant.name,
  light_start_time: plant.light_start_time ?? '08:00',
  light_stop_time: plant.light_stop_time ?? '20:00',
  moisture_target: plant.moisture_target ?? 45,
  watering_volume_ml: plant.watering_volume_ml ?? 100,
  position_mm: plant.position_mm ?? 0,
})

// -1 is "no reading", not dry. The backend uses it for a probe that is
// unplugged or unreadable, and showing that as 0% would read as "bone dry" and
// invite watering a plant whose sensor simply fell out.
const describeMoisture = (status) => {
  if (!status) return { text: '—', hint: 'no data yet' }
  if (status.moisture_percent == null || status.moisture_percent < 0) {
    return { text: 'no reading', hint: 'probe unplugged or unreadable', warn: true }
  }
  const text = `${status.moisture_percent.toFixed(0)}%`
  // Below a full window the loop will not water, so say so rather than show a
  // number that looks actionable.
  if (status.window_size && status.sample_count < status.window_size) {
    return {
      text,
      hint: `gathering history, ${status.sample_count}/${status.window_size}`,
    }
  }
  const target = status.target_moisture
  if (target != null) {
    return {
      text,
      hint:
        status.moisture_percent < target
          ? `below target of ${target}%`
          : `target ${target}%`,
      dry: status.moisture_percent < target,
    }
  }
  return { text, hint: '' }
}

// How close two plants have to be before capturing one looks like a mix-up.
// Pots on a metre of rail sit hundreds of millimetres apart, so anything this
// near an already-configured plant almost certainly means the carriage was
// parked over that plant and the button pressed on the wrong card.
const CONFUSION_MARGIN_MM = 50

export function PlantsPanel({ plants, onSave, status, movement }) {
  const [drafts, setDrafts] = useState({})
  const [expandedPlantIds, setExpandedPlantIds] = useState([])
  // Keyed by plant so a warning about one card cannot appear under another.
  const [captureNote, setCaptureNote] = useState({})

  const capturePosition = (plant) => {
    const note = (text) => setCaptureNote((current) => ({ ...current, [plant.plant_id]: text }))

    // An unhomed axis reports a position relative to wherever it happened to
    // power up, which is a meaningless number that looks like a real one.
    if (!movement?.homed) {
      note('Home the gantry first — until then its position is not a real measurement.')
      return
    }
    // Checked before converting: Number(null) is 0, which is finite, so a
    // board reporting nothing would otherwise sail through this and quietly
    // set the plant's position to the left end of the rail.
    const raw = movement.position
    if (raw === null || raw === undefined || raw === '' || !Number.isFinite(Number(raw))) {
      note('No position reported. Is the motion board connected?')
      return
    }
    const here = Number(raw)
    const limit = Number(movement.max_x)
    if (Number.isFinite(limit) && (here < 0 || here > limit)) {
      note(`${here} mm is outside the usable rail (0 to ${limit} mm).`)
      return
    }

    // The mistake this is guarding: jog to one pot, press the button on a
    // different plant's card. The captured value then lands on top of a plant
    // that is already configured there.
    const clash = plants.find(
      (other) =>
        other.plant_id !== plant.plant_id &&
        Math.abs(Number(other.position_mm) - here) < CONFUSION_MARGIN_MM,
    )
    updateDraft(plant.plant_id, 'position_mm', String(Math.round(here)))
    note(
      clash
        ? `Set ${plant.name} to ${Math.round(here)} mm — but that is within ` +
          `${CONFUSION_MARGIN_MM} mm of ${clash.name}. Check you are over the ` +
          `right pot before saving.`
        : `Set ${plant.name} to ${Math.round(here)} mm. Save to keep it.`,
    )
  }

  // Drafts mirror the plants prop, and resyncing them during render rather than
  // in an effect means the inputs never paint one frame of stale values after
  // a save. React re-runs this component immediately, before touching the DOM.
  const [syncedPlants, setSyncedPlants] = useState(null)
  if (plants !== syncedPlants) {
    setSyncedPlants(plants)
    setDrafts(Object.fromEntries(plants.map((plant) => [plant.plant_id, draftFrom(plant)])))
  }

  const togglePlantExpanded = (plantId) => {
    setExpandedPlantIds((current) =>
      current.includes(plantId)
        ? current.filter((id) => id !== plantId)
        : [...current, plantId],
    )
  }

  const updateDraft = (plantId, field, value) => {
    setDrafts((current) => ({
      ...current,
      [plantId]: {
        ...current[plantId],
        [field]: value,
      },
    }))
  }

  return (
    <section className="panel-section">
      <h2>Plant Settings</h2>
      <div className="cards">
        {plants.map((plant) => {
          const draft = drafts[plant.plant_id] || draftFrom(plant)
          const isExpanded = expandedPlantIds.includes(plant.plant_id)
          const reading = describeMoisture(
            status?.find((item) => item.plant_id === plant.plant_id),
          )

          return (
            <div key={plant.plant_id} className="plant-card">
              <button
                type="button"
                className="plant-header"
                onClick={() => togglePlantExpanded(plant.plant_id)}
                aria-expanded={isExpanded}
              >
                <span>{plant.name}</span>
                <span className="plant-reading">
                  <strong className={reading.warn ? 'warn' : reading.dry ? 'dry' : undefined}>
                    {reading.text}
                  </strong>
                  {reading.hint && <small>{reading.hint}</small>}
                </span>
                <span className="plant-chevron">{isExpanded ? '−' : '+'}</span>
              </button>

              {isExpanded && (
                <>
                  <div className="field-grid">
                    <label>
                      Plant name
                      <input
                        value={draft.name}
                        onChange={(event) => updateDraft(plant.plant_id, 'name', event.target.value)}
                      />
                    </label>
                    <label>
                      Light start
                      <input
                        type="time"
                        value={draft.light_start_time}
                        onChange={(event) => updateDraft(plant.plant_id, 'light_start_time', event.target.value)}
                      />
                    </label>
                    <label>
                      Light stop
                      <input
                        type="time"
                        value={draft.light_stop_time}
                        onChange={(event) => updateDraft(plant.plant_id, 'light_stop_time', event.target.value)}
                      />
                    </label>
                    <label>
                      Moisture target (%)
                      <input
                        type="number"
                        value={draft.moisture_target}
                        onChange={(event) => updateDraft(plant.plant_id, 'moisture_target', event.target.value)}
                      />
                    </label>
                    <label>
                      Watering volume (mL)
                      <input
                        type="number"
                        min="0"
                        step="10"
                        value={draft.watering_volume_ml}
                        onChange={(event) =>
                          updateDraft(plant.plant_id, 'watering_volume_ml', event.target.value)
                        }
                      />
                    </label>
                    <label>
                      Watering location (mm)
                      <input
                        type="number"
                        value={draft.position_mm}
                        onChange={(event) => updateDraft(plant.plant_id, 'position_mm', event.target.value)}
                      />
                    </label>
                    <div>
                      {/* Names the plant on the button itself: the whole risk
                          here is pressing this on the wrong card. */}
                      <button type="button" onClick={() => capturePosition(plant)}>
                        Use current position for {plant.name}
                      </button>
                      <p className="field-hint">
                        Jog the carriage until the nozzle is over this pot, then
                        press. Fills the field above — nothing is stored until
                        you Save.
                      </p>
                      {captureNote[plant.plant_id] && (
                        <p className="field-hint warning">{captureNote[plant.plant_id]}</p>
                      )}
                    </div>
                  </div>

                  <div className="plant-actions-row">
                    <button
                      className="primary"
                      onClick={() => onSave({ ...plant, ...draft })}
                    >
                      Save Plant
                    </button>
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
