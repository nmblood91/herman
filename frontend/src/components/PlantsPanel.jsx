import { useEffect, useRef, useState } from 'react'
import { formatClock } from '../time'

// Pot fields only. A card no longer edits what a plant wants -- that is the
// plant editor's job, and a pot takes those settings by loading a saved plant.
// Keeping both here meant "Save Plant" wrote a profile as a side effect of
// saving a rail coordinate, so you could not touch one without the other.
//
// These are no longer a form waiting on a button: each field writes itself a
// moment after the last edit, so the draft is a debounce buffer rather than a
// pending change. What that costs is below -- resync has to leave a card that
// is mid-edit alone, and two states of a draft have to be held back rather
// than sent.
const draftFrom = (plant) => ({
  soil: plant.soil ?? '',
  position_mm: plant.position_mm ?? 0,
  watering_mode: plant.watering_mode ?? 'point',
  sweep_min_mm: plant.sweep_min_mm ?? 0,
  sweep_max_mm: plant.sweep_max_mm ?? 0,
})

// "Pot 2: Basil" rather than "Basil". Everything physical about a card is per
// pot -- the probe address, the LED range, the rail coordinate -- so the header
// has to say which pot before it says what is growing in it, or there is
// nothing tying the card to the planter in front of you.
//
// Pot rather than Plant for the half that does not move: the card is already
// split into "Plant Info" and "Pot Info", and a header that said "Plant 2"
// would be naming the pot with the word the card uses for its contents.
//
// The number comes from plant_id rather than the array index. Identical today,
// but the id is the identity the API and the state file key on, so a reordered
// list cannot relabel a pot.
const cardTitle = (plant) => {
  const matched = /(\d+)$/.exec(plant.plant_id ?? '')
  const number = matched?.[1]
  const pot = number ? `Pot ${number}` : plant.plant_id || 'Pot'
  const name = (plant.name ?? '').trim()
  // plants.default_plants names them "Plant 1".."Plant 4", so on a fresh
  // planter every name is a placeholder. Both spellings of the placeholder
  // count as unnamed: "Pot 1: Plant 1" says the same thing twice in two
  // vocabularies.
  const unnamed = !name || (number && (name === `Pot ${number}` || name === `Plant ${number}`))
  return unnamed ? pot : `${pot}: ${name}`
}

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
        `${MIN_SWEEP_SPAN_MM} mm. Use Fixed Position for a pot narrower ` +
        'than that.',
      warn: true,
    }
  }
  return { text: `Sweeping ${Math.round(span)} mm.` }
}

// How long to wait after the last edit before writing a pot field. Three of
// them are number inputs, so a save per keystroke would write 3, then 35, then
// 355 -- and 3 mm is a coordinate the gantry would happily accept. Short
// enough that nobody walks away from a card they think they have finished.
const SAVE_DEBOUNCE_MS = 700

// Which drafts are not worth sending yet, and what to say instead. There is no
// Save button any more, so an edit either reaches the planter or says why it
// did not: a draft that sits unsaved and unmentioned is the one failure this
// has to avoid.
const reasonToHold = (draft) => {
  // Number('') is 0, which is finite and is also the left end of the rail, so
  // without this, clearing the box to retype would park the watering spot
  // there the moment the debounce fired.
  if (String(draft.position_mm).trim() === '' || !Number.isFinite(Number(draft.position_mm))) {
    return 'Watering location is blank, so nothing has been saved.'
  }
  if (draft.watering_mode === 'sweep') {
    const summary = describeSweep(draft)
    // The API refuses a sweep whose span is too narrow to be one, so sending
    // this would be a red error for a card the user is still filling in.
    if (summary.warn) return `${summary.text} Not saved yet.`
  }
  return ''
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
  onMeasureFieldCapacity,
  onClearFieldCapacity,
}) {
  const [drafts, setDrafts] = useState({})
  // Which saved plant each card has picked, keyed by plant so one card's
  // choice cannot load onto another.
  const [picked, setPicked] = useState({})
  const [expandedPlantIds, setExpandedPlantIds] = useState([])
  // Keyed by plant so a warning about one card cannot appear under another.
  const [captureNote, setCaptureNote] = useState({})

  // Why this pot's save has not gone out, kept apart from captureNote above:
  // they are written by different things at different times, and sharing one
  // slot had the save clearing the capture button's clash warning 700ms after
  // it was raised.
  const [holdNote, setHoldNote] = useState({})

  // One pending save per pot, keyed the same way: editing two cards at once
  // must not have one card's timer cancel the other's write.
  const saveTimers = useRef({})
  useEffect(() => {
    const timers = saveTimers.current
    return () => Object.values(timers).forEach(clearTimeout)
  }, [])

  const scheduleSave = (plant, draft) => {
    clearTimeout(saveTimers.current[plant.plant_id])
    saveTimers.current[plant.plant_id] = setTimeout(() => {
      // Cleared before the write rather than after it, so a keystroke that
      // lands while the request is in flight registers as pending again and
      // the refresh below cannot overwrite it.
      delete saveTimers.current[plant.plant_id]
      const held = reasonToHold(draft)
      setHoldNote((current) => ({ ...current, [plant.plant_id]: held }))
      if (!held) onSave({ ...plant, ...draft })
    }, SAVE_DEBOUNCE_MS)
  }

  const capturePosition = (plant, field = 'position_mm') => {
    const say = (text) =>
      setCaptureNote((current) => ({ ...current, [plant.plant_id]: text }))

    // An unhomed axis reports a position relative to wherever it happened to
    // power up, which is a meaningless number that looks like a real one.
    if (!movement?.homed) {
      say('Home the gantry first — until then its position is not a real measurement.')
      return
    }
    // Checked before converting: Number(null) is 0, which is finite, so a
    // board reporting nothing would otherwise sail through this and quietly
    // set the plant's position to the left end of the rail.
    const raw = movement.position
    if (raw === null || raw === undefined || raw === '' || !Number.isFinite(Number(raw))) {
      say('No position reported. Is the motion board connected?')
      return
    }
    const here = Number(raw)
    const limit = Number(movement.max_x)
    if (Number.isFinite(limit) && (here < 0 || here > limit)) {
      say(`${here} mm is outside the usable rail (0 to ${limit} mm).`)
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
    updateDraft(plant, field, String(Math.round(here)))
    say(
      clash
        ? `Set the ${what} for ${plant.name} to ${Math.round(here)} mm and ` +
          `saving it — but that is within ${CONFUSION_MARGIN_MM} mm of ` +
          `${clash.name}, so check this is the right card. Jog over the right ` +
          'pot and press again to correct it.'
        : `Set the ${what} for ${plant.name} to ${Math.round(here)} mm. ` +
          'Saving it now.',
    )
  }

  // Drafts mirror the plants prop, and resyncing them during render rather than
  // in an effect means the inputs never paint one frame of stale values after
  // a save. React re-runs this component immediately, before touching the DOM.
  //
  // A card with a save still pending keeps its draft. Every save ends in a
  // dashboard refresh, which lands a moment later: taking the server's copy
  // then would delete whatever was typed in the meantime.
  const [syncedPlants, setSyncedPlants] = useState(null)
  if (plants !== syncedPlants) {
    setSyncedPlants(plants)
    setDrafts((current) =>
      Object.fromEntries(
        plants.map((plant) => [
          plant.plant_id,
          saveTimers.current[plant.plant_id]
            ? current[plant.plant_id] ?? draftFrom(plant)
            : draftFrom(plant),
        ]),
      ),
    )
  }

  const profileNames = (profiles ?? []).map((profile) => profile.name)
  const soilList = soils ?? []

  const togglePlantExpanded = (plantId) => {
    setExpandedPlantIds((current) =>
      current.includes(plantId)
        ? current.filter((id) => id !== plantId)
        : [...current, plantId],
    )
  }

  // Takes the whole plant rather than its id: saving needs the pot's other
  // fields, and reading them back off the plants prop at write time would use
  // whatever the last refresh brought instead of what is on screen.
  const updateDraft = (plant, field, value) => {
    const next = { ...(drafts[plant.plant_id] ?? draftFrom(plant)), [field]: value }
    setDrafts((current) => ({ ...current, [plant.plant_id]: next }))
    scheduleSave(plant, next)
  }

  return (
    <section className="panel-section">
      <h2>Active Plants</h2>
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
                <span>{cardTitle(plant)}</span>
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
                  {/* Read-only: what this pot is currently set up to want.
                      It is edited in the plant editor below, which keeps one
                      place for a plant and one for a pot. */}
                  <h3 className="card-group-title">Plant Info</h3>
                  <p className="field-hint">
                    <strong>{plant.name}</strong> — waters{' '}
                    {plant.watering_volume_ml} mL at {plant.moisture_target}{' '}
                    moisture reading. Lights on{' '}
                    {formatClock(plant.light_start_time)}–
                    {formatClock(plant.light_stop_time)}
                  </p>
                  {plant.notes && <p className="field-hint">Notes: {plant.notes}</p>}

                  {/* Directly under Plant Info because that is the block it
                      replaces: loading a saved plant rewrites those three
                      lines and touches nothing below. */}
                  <div className="plant-actions-row">
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

                  <h3 className="card-group-title">Watering</h3>
                  <div className="field-grid">
                    <label>
                      Watering mode
                      <select
                        value={draft.watering_mode}
                        onChange={(event) =>
                          updateDraft(plant, 'watering_mode', event.target.value)
                        }
                      >
                        <option value="point">Fixed Position</option>
                        <option value="sweep">Sweep Range</option>
                      </select>
                    </label>

                    {draft.watering_mode === 'point' && (
                      <label>
                        Watering location (mm)
                        <input
                          type="number"
                          value={draft.position_mm}
                          onChange={(event) =>
                            updateDraft(plant, 'position_mm', event.target.value)
                          }
                        />
                        {/* No field argument: this one captures the watering
                            location, and that is also the only field whose
                            capture checks for a neighbouring pot. */}
                        <button type="button" onClick={() => capturePosition(plant)}>
                          Use current position
                        </button>
                      </label>
                    )}

                    {draft.watering_mode === 'sweep' && (
                      <div className="sweep-fields">
                        <label>
                          Left edge (mm)
                          <input
                            type="number"
                            value={draft.sweep_min_mm}
                            onChange={(event) =>
                              updateDraft(plant, 'sweep_min_mm', event.target.value)
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
                              updateDraft(plant, 'sweep_max_mm', event.target.value)
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

                    {/* What the capture buttons and the saves actually did.
                        Kept here, beside the buttons, because unlike the
                        how-to these change with what just happened. */}
                    {captureNote[plant.plant_id] && (
                      <p className="field-hint warning">{captureNote[plant.plant_id]}</p>
                    )}
                    {holdNote[plant.plant_id] && (
                      <p className="field-hint warning">{holdNote[plant.plant_id]}</p>
                    )}
                  </div>

                  <h3 className="card-group-title">Pot Info</h3>
                  <div className="field-grid">
                    <label>
                      Soil
                      <select
                        value={draft.soil}
                        onChange={(event) => updateDraft(plant, 'soil', event.target.value)}
                      >
                        <option value="">
                          {soilList.length ? 'Not set' : 'No mixes installed'}
                        </option>
                        {soilList.map((soil) => (
                          <option key={soil.name} value={soil.name}>
                            {soil.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div>
                      <p className="field-hint">
                        {plant.field_capacity_raw != null ? (
                          <>
                            Field capacity reads{' '}
                            <strong>{plant.field_capacity_raw}</strong> here
                            {plant.field_capacity_source === 'pot'
                              ? ', measured in this pot'
                              : plant.field_capacity_soil
                                ? `, from ${plant.field_capacity_soil}`
                                : ''}
                            . That is the top of this pot's moisture scale.
                          </>
                        ) : (
                          <span className="warning">
                            No field capacity, so this pot reads nothing and is
                            never watered automatically. Measure it for the mix
                            in the Soil panel below, or for this pot alone
                            here.
                          </span>
                        )}
                      </p>
                      <div className="motion-grid two-up">
                        <button
                          type="button"
                          onClick={() => onMeasureFieldCapacity(plant.plant_id)}
                        >
                          Measure this pot (20s)
                        </button>
                        {plant.field_capacity_source === 'pot' && (
                          <button
                            type="button"
                            onClick={() => onClearFieldCapacity(plant.plant_id)}
                          >
                            Use the mix's figure instead
                          </button>
                        )}
                      </div>
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
