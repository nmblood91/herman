import { useState } from 'react'

const draftFrom = (plant) => ({
  name: plant.name,
  soil: plant.soil ?? '',
  light_start_time: plant.light_start_time ?? '08:00',
  light_stop_time: plant.light_stop_time ?? '20:00',
  moisture_target: plant.moisture_target ?? 'dry',
  watering_volume_ml: plant.watering_volume_ml ?? 100,
  position_mm: plant.position_mm ?? 0,
  watering_mode: plant.watering_mode ?? 'point',
  sweep_min_mm: plant.sweep_min_mm ?? 0,
  sweep_max_mm: plant.sweep_max_mm ?? 0,
})

// Mirrors greenthumb.sweep.MIN_SPAN_MM, and only for the hint below: the
// planter refuses a narrower span itself, so this number being stale would
// show a misleading warning rather than let a bad span through.
const MIN_SWEEP_SPAN_MM = 10

// Which stretch of rail each capture button fills in, for a note that names it.
// Pressing one of these on the wrong card or the wrong field is the whole risk.
const CAPTURE_LABELS = {
  position_mm: 'watering spot',
  sweep_min_mm: 'left edge',
  sweep_max_mm: 'right edge',
}

const describeSweep = (draft) => {
  const low = Number(draft.sweep_min_mm)
  const high = Number(draft.sweep_max_mm)
  if (draft.sweep_min_mm === '' || draft.sweep_max_mm === '' ||
      !Number.isFinite(low) || !Number.isFinite(high)) {
    return { text: 'Set both edges of the span.', warn: true }
  }

  const span = Math.abs(high - low)
  if (span < MIN_SWEEP_SPAN_MM) {
    return {
      text:
        `${Math.round(span)} mm is too narrow to sweep — it needs at least ` +
        `${MIN_SWEEP_SPAN_MM} mm. Use One spot for a pot narrower than that.`,
      warn: true,
    }
  }
  return {
    text:
      `Sweeping ${Math.round(span)} mm. The dose does not change: the same ` +
      'volume is laid along the span instead of into one place, so the nozzle ' +
      'moves for exactly as long as the pump runs. A dose too small to cross ' +
      'the span waters at the spot above instead, rather than over-watering.',
  }
}

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
  // The band leads and the percentage follows as detail. On a peat mix the
  // whole actionable range is a narrow strip near the top of the scale, so the
  // number alone invites reading precision the sensor cannot deliver.
  const band = status.moisture_band
  const target = status.target_moisture

  if (band === 'unknown') {
    return {
      text: 'no soil set',
      hint: `${text} — set a soil so the reading can be read`,
      warn: true,
    }
  }

  if (band && target) {
    // Drier than the target means due a drink. Band order is wettest first,
    // so a higher index is drier.
    const order = ['very wet', 'wet', 'medium', 'dry', 'very dry']
    const thirsty = order.indexOf(band) > order.indexOf(target)
    return {
      text: band,
      hint: thirsty ? `${text}, past its ${target} target` : `${text}, waters at ${target}`,
      dry: thirsty,
    }
  }
  return { text, hint: '' }
}

// How close two plants have to be before capturing one looks like a mix-up.
// Pots on a metre of rail sit hundreds of millimetres apart, so anything this
// near an already-configured plant almost certainly means the carriage was
// parked over that plant and the button pressed on the wrong card.
const CONFUSION_MARGIN_MM = 50

export function PlantsPanel({
  plants,
  onSave,
  status,
  movement,
  profiles,
  onLoadProfile,
  soils,
  bands,
}) {
  const [drafts, setDrafts] = useState({})
  // Which saved plant each card has picked, keyed by plant so one card's
  // choice cannot load onto another.
  const [picked, setPicked] = useState({})
  const [expandedPlantIds, setExpandedPlantIds] = useState([])
  // Keyed by plant so a warning about one card cannot appear under another.
  const [captureNote, setCaptureNote] = useState({})

  const capturePosition = (plant, field = 'position_mm') => {
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
    // Only for the watering spot. Two pots' spots landing on top of each
    // other is a mistake; a sweep edge sitting close to the neighbouring pot
    // is not, because a wide pot's span can reasonably reach most of the way
    // there -- warning about it would train the warning away.
    const clash =
      field === 'position_mm'
        ? plants.find(
            (other) =>
              other.plant_id !== plant.plant_id &&
              Math.abs(Number(other.position_mm) - here) < CONFUSION_MARGIN_MM,
          )
        : null
    const what = CAPTURE_LABELS[field]
    updateDraft(plant.plant_id, field, String(Math.round(here)))
    note(
      clash
        ? `Set the ${what} for ${plant.name} to ${Math.round(here)} mm — but ` +
          `that is within ${CONFUSION_MARGIN_MM} mm of ${clash.name}. Check ` +
          'you are over the right pot before saving.'
        : `Set the ${what} for ${plant.name} to ${Math.round(here)} mm. ` +
          'Save to keep it.',
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

  const profileNames = (profiles ?? []).map((profile) => profile.name)
  const soilList = soils ?? []
  // Very wet is deliberately not offered: a pot is only that just after
  // watering, so targeting it waters on a loop.
  const bandList = (bands ?? []).filter((band) => band.name !== 'very wet')

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
                  {/* At the top of the card rather than the foot: on a phone
                      the fields push Save below the fold, and Load belongs
                      beside it because loading then saving is the normal
                      sequence. */}
                  <div className="plant-actions-row">
                    <button
                      className="primary"
                      onClick={() => onSave({ ...plant, ...draft })}
                    >
                      Save Plant
                    </button>

                    <div className="load-profile-row">
                      <select
                        aria-label={`Saved plant to load onto ${plant.name}`}
                        value={picked[plant.plant_id] ?? ''}
                        onChange={(event) =>
                          setPicked((current) => ({
                            ...current,
                            [plant.plant_id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">
                          {profileNames.length ? 'Load a saved plant…' : 'Nothing saved yet'}
                        </option>
                        {profileNames.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={!picked[plant.plant_id]}
                        onClick={() => onLoadProfile(plant.plant_id, picked[plant.plant_id])}
                      >
                        Load
                      </button>
                    </div>
                  </div>

                  <p className="field-hint">
                    Saving stores these settings under the plant name, replacing
                    anything saved under that name already. Loading copies a
                    saved plant onto this one — <strong>not</strong> its
                    watering location, which belongs to the pot rather than to
                    the plant.
                  </p>

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
                      Water when it reaches
                      <select
                        value={draft.moisture_target}
                        onChange={(event) =>
                          updateDraft(plant.plant_id, 'moisture_target', event.target.value)
                        }
                      >
                        {bandList.map((band) => (
                          <option key={band.name} value={band.name}>
                            {band.name}
                            {band.description ? ` — ${band.description}` : ''}
                          </option>
                        ))}
                      </select>
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
                    <label>
                      How to water
                      <select
                        value={draft.watering_mode}
                        onChange={(event) =>
                          updateDraft(plant.plant_id, 'watering_mode', event.target.value)
                        }
                      >
                        <option value="point">
                          One spot — the whole dose at the location above
                        </option>
                        <option value="sweep">
                          Sweep back and forth across a span
                        </option>
                      </select>
                    </label>
                    <label>
                      Soil
                      <select
                        value={draft.soil}
                        onChange={(event) => updateDraft(plant.plant_id, 'soil', event.target.value)}
                      >
                        <option value="">
                          {soilList.length ? 'Not set' : 'No soils installed'}
                        </option>
                        {soilList.map((soil) => (
                          <option key={soil.name} value={soil.name}>
                            {soil.name}
                            {soil.available_points != null
                              ? ` — ${soil.available_points} pts usable`
                              : ''}
                          </option>
                        ))}
                      </select>
                    </label>

                    {draft.watering_mode === 'sweep' && (
                      <div className="sweep-fields">
                        <label>
                          Left edge (mm)
                          <input
                            type="number"
                            value={draft.sweep_min_mm}
                            onChange={(event) =>
                              updateDraft(plant.plant_id, 'sweep_min_mm', event.target.value)
                            }
                          />
                          <button
                            type="button"
                            onClick={() => capturePosition(plant, 'sweep_min_mm')}
                          >
                            Use current position
                          </button>
                        </label>
                        <label>
                          Right edge (mm)
                          <input
                            type="number"
                            value={draft.sweep_max_mm}
                            onChange={(event) =>
                              updateDraft(plant.plant_id, 'sweep_max_mm', event.target.value)
                            }
                          />
                          <button
                            type="button"
                            onClick={() => capturePosition(plant, 'sweep_max_mm')}
                          >
                            Use current position
                          </button>
                        </label>
                        {(() => {
                          const summary = describeSweep(draft)
                          return (
                            <p className={`field-hint${summary.warn ? ' warning' : ''}`}>
                              {summary.text}
                            </p>
                          )
                        })()}
                      </div>
                    )}

                    <div>
                      {/* Names the plant on the button itself: the whole risk
                          here is pressing this on the wrong card. */}
                      <button type="button" onClick={() => capturePosition(plant)}>
                        Use current position for {plant.name}
                      </button>
                      <p className="field-hint">
                        Jog the carriage until the nozzle is over this pot, then
                        press. Fills the field above — nothing is stored until
                        you Save. The sweep edges have their own buttons, so you
                        can jog to each side of a wide pot and capture it there.
                      </p>
                      {captureNote[plant.plant_id] && (
                        <p className="field-hint warning">{captureNote[plant.plant_id]}</p>
                      )}
                    </div>
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
