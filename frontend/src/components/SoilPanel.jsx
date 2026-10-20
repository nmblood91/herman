import { useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { useHoldToConfirm } from '../useHoldToConfirm'
import { HoldRing } from './HoldRing'
import { cardTitle } from '../potLabel'

// The soil library, on the same tab as the pots that use it.
//
// Takes `soils` as a prop rather than fetching its own copy. It used to live in
// Settings, a tab away from the plant cards, and self-fetched a second list
// that the dashboard was already holding for the soil dropdown -- so the two
// could disagree until something reloaded.
const SAMPLE_SECONDS = 20

// How long Delete has to be held. Matches the plant profile editor's.
const DELETE_HOLD_MS = 5000

const BLANK = {
  name: '',
  capacity: '',
  wilting: '',
  capacityRaw: '',
  wiltingRaw: '',
  notes: '',
}

// The sensor readings as the form shows them: blank for none.
const rawText = (value) => (value == null ? '' : String(value))

export function SoilPanel({ soils, plants, onRefresh }) {
  // 'new' types a free name below; 'existing' turns that field into a picker
  // over the list. Picked is only ever non-empty in 'existing' mode -- every
  // path back to 'new' clears it, so the two stay in lockstep. Same split as
  // the plant profile editor, and for the same reason: there was no way to edit an
  // existing mix's figures short of retyping its name exactly and hoping the
  // overwrite landed on the right one.
  //
  // There is also no standing list of every mix any more, same as the plant
  // editor has none of every plant: this is a single-entity editor, and
  // "what exists" is the dropdown's job.
  const [mode, setMode] = useState('new')
  const [picked, setPicked] = useState('')
  const [form, setForm] = useState(BLANK)
  const [message, setMessage] = useState('')

  // Which pot's probe to measure the picked mix with. Not keyed by name --
  // only one mix is ever in view at a time now -- and defaulting to the
  // first pot rather than forcing a pick, the way the field capacity button
  // on a pot's own card does.
  const [probe, setProbe] = useState('')
  const [measuring, setMeasuring] = useState('')

  const list = soils ?? []
  const pots = plants ?? []
  const pickedSoil = list.find((soil) => soil.name === picked)

  // The list already carries every field, so the form fills from the prop
  // rather than fetching the entry again. Synced during render, not in an
  // effect, so the inputs never paint one frame of the previous mix.
  const [syncedPick, setSyncedPick] = useState('')
  // The sensor readings the form was last filled with. A reading is sent on
  // save only when its field differs from this -- not from what is stored,
  // because a measurement taken after the form filled would then be
  // overwritten by the stale number still sitting in the box.
  const [rawBase, setRawBase] = useState({ capacityRaw: '', wiltingRaw: '' })
  if (picked !== syncedPick) {
    setSyncedPick(picked)
    const base = {
      capacityRaw: rawText(pickedSoil?.field_capacity_raw),
      wiltingRaw: rawText(pickedSoil?.wilting_point_raw),
    }
    setRawBase(base)
    setForm(
      pickedSoil
        ? {
            name: pickedSoil.name,
            capacity: String(pickedSoil.field_capacity_vwc ?? ''),
            wilting: String(pickedSoil.wilting_point_vwc ?? ''),
            ...base,
            notes: pickedSoil.notes ?? '',
          }
        : BLANK,
    )
  } else if (pickedSoil) {
    // A measurement landed while this mix was open. Show it in any reading
    // field nobody has typed into, and make it the new baseline.
    for (const [field, value] of [
      ['capacityRaw', rawText(pickedSoil.field_capacity_raw)],
      ['wiltingRaw', rawText(pickedSoil.wilting_point_raw)],
    ]) {
      if (value !== rawBase[field]) {
        setRawBase((current) => ({ ...current, [field]: value }))
        if (form[field] === rawBase[field]) {
          setForm((current) => ({ ...current, [field]: value }))
        }
      }
    }
  }

  const update = (field, value) => setForm((current) => ({ ...current, [field]: value }))

  // A no-op on the already-active mode, like a tab: clicking New Profile again
  // does not discard a half-typed draft.
  const startNewProfile = () => {
    if (mode === 'new') return
    setMode('new')
    setPicked('')
    setSyncedPick('')
    setForm(BLANK)
    setMessage('')
  }

  const browseProfiles = () => {
    if (mode === 'existing') return
    setMode('existing')
    // Picked is always '' on the way in here, so the picker opens on its
    // placeholder. Blank the rest too, rather than showing a new-mix draft's
    // leftover fields under a dropdown that says nothing is chosen yet.
    setForm(BLANK)
    setMessage('')
  }

  // `kind` is 'field-capacity' or 'wilting-point': the two endpoints take the
  // same body and differ only in which end of the scale they store.
  const measure = async (kind) => {
    const plantId = probe || pots[0]?.plant_id
    if (!plantId) return
    const label = kind === 'wilting-point' ? 'wilting point' : 'field capacity'
    setMessage('')
    setMeasuring(kind)
    try {
      const response = await fetch(
        `${API_BASE}/soils/${encodeURIComponent(picked)}/${kind}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plant_id: plantId, seconds: SAMPLE_SECONDS }),
        },
      )
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(
          data.detail || data.error || `Could not measure (HTTP ${response.status})`,
        )
        return
      }
      if (!data.written) {
        setMessage(`Not stored — ${data.reason}`)
        return
      }
      if (kind === 'wilting-point') {
        setMessage(`${picked} reads ${data.value} at wilting point, measured with ${data.measured_with}.`)
        onRefresh?.()
        return
      }
      const applied = data.inherited_by ?? []
      setMessage(
        `${picked} reads ${data.value} at ${label}, measured with ` +
          `${data.measured_with}. ` +
          (applied.length
            ? `Used by ${applied.join(', ')}.`
            : 'No pot is filled with it yet.'),
      )
      onRefresh?.()
    } catch (error) {
      setMessage(`Could not measure: ${error.message}`)
    } finally {
      setMeasuring('')
    }
  }

  const save = async () => {
    setMessage('')
    // Only the readings that were edited. Left out, the planter keeps what it
    // has -- including a measurement and when it was taken. Blank clears.
    const readings = {}
    for (const [field, key, label] of [
      ['capacityRaw', 'field_capacity_raw', 'Field capacity (sensor reading)'],
      ['wiltingRaw', 'wilting_point_raw', 'Wilting point (sensor reading)'],
    ]) {
      const text = String(form[field]).trim()
      if (text === rawBase[field]) continue
      if (text === '') {
        readings[key] = null
        continue
      }
      const value = Number(text)
      if (!Number.isInteger(value) || value <= 0) {
        setMessage(`${label} has to be a whole number above 0.`)
        return
      }
      readings[key] = value
    }

    try {
      const response = await fetch(`${API_BASE}/soils`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          // Optional reference figures: blank is sent as none rather than as
          // Number('') -- which is 0, and refused.
          field_capacity_vwc: String(form.capacity).trim() === '' ? null : Number(form.capacity),
          wilting_point_vwc: String(form.wilting).trim() === '' ? null : Number(form.wilting),
          notes: form.notes,
          ...readings,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      const applied = data.inherited_by ?? []
      setMessage(
        `Saved soil profile ${data.name}.` +
          (applied.length ? ` New field capacity used by ${applied.join(', ')}.` : ''),
      )
      setRawBase({
        capacityRaw: String(form.capacityRaw).trim(),
        wiltingRaw: String(form.wiltingRaw).trim(),
      })
      setMode('existing')
      setPicked(data.name)
      setSyncedPick(data.name)
      onRefresh?.()
    } catch (error) {
      setMessage(`Save failed: ${error.message}`)
    }
  }

  const remove = async () => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/soils/${encodeURIComponent(picked)}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Could not delete ${picked}`)
        return
      }
      // Pots still naming it keep the name, which stops resolving. Saying so
      // is the point -- a silently cleared soil hides that a pot is no longer
      // described, and a pot with no soil is never watered automatically.
      setMessage(`Deleted soil profile ${picked}. Any pot still set to it needs a new soil profile.`)
      setPicked('')
      setSyncedPick('')
      setForm(BLANK)
      onRefresh?.()
    } catch (error) {
      setMessage(`Could not delete ${picked}: ${error.message}`)
    }
  }

  const { progress: holdProgress, handlers: holdHandlers, cancel: cancelHold } =
    useHoldToConfirm(DELETE_HOLD_MS, remove)

  // A hold in progress belongs to the mix that was picked when it started.
  // If picked changes under it -- there is no ordinary way to do that with
  // one pointer, but a keyboard can tab away mid-hold -- it must not go on to
  // remove whatever is picked by the time the five seconds are up.
  //
  // cancelHold deliberately left out of the deps: it is a fresh closure every
  // render (the hook does not memoise it), so including it would re-fire this
  // effect on every render -- which, while a hold is in progress, is every
  // animation frame, canceling the hold the instant it ticks.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => cancelHold, [picked])

  // Only a name: every figure is optional, and a soil profile can be saved
  // first and measured afterwards.
  const formReady = Boolean(form.name.trim())

  return (
    <section className="panel-section">
      <h2>Soil Profile Editor</h2>

      <div className="general-settings-form">
        <div className="field-row">
          <div className="plant-editor-mode">
            <button
              type="button"
              className={mode === 'new' ? 'tab active' : 'tab'}
              onClick={startNewProfile}
            >
              New Profile
            </button>
            <button
              type="button"
              className={mode === 'existing' ? 'tab active' : 'tab'}
              disabled={!list.length}
              onClick={browseProfiles}
            >
              Edit Profile
            </button>
          </div>
          {!list.length && (
            <p className="field-hint warning">
              No soil profiles. The installer adds a starting set, so this
              means they were all deleted — add your own below, or put the set
              back with <code>python -m greenthumb.soil_library --install</code>{' '}
              on the Pi. Until a pot has a soil profile it is never watered
              automatically.
            </p>
          )}
        </div>

        <div className="field-row">
          {mode === 'existing' ? (
            <label>
              Name
              <select
                aria-label="Soil profile to edit"
                value={picked}
                onChange={(event) => setPicked(event.target.value)}
              >
                <option value="">Choose a soil profile…</option>
                {list.map((soil) => (
                  <option key={soil.name} value={soil.name}>
                    {soil.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              Name
              <input
                value={form.name}
                placeholder="My potting mix"
                onChange={(event) => update('name', event.target.value)}
              />
            </label>
          )}
        </div>

        {/* The two sensor readings first: they are the scale every pot using
            this soil profile is read on. Watering needs field capacity; wilting
            point is estimated from it and the % pair unless one is given. */}
        <div className="field-row">
          <div className="soil-form">
            <label>
              Field capacity (sensor reading)
              <input
                type="number"
                min="1"
                step="1"
                placeholder="Not set"
                value={form.capacityRaw}
                onChange={(event) => update('capacityRaw', event.target.value)}
              />
            </label>
            <label>
              Wilting point (sensor reading, optional)
              <input
                type="number"
                min="1"
                step="1"
                placeholder={
                  pickedSoil?.estimated_wilting_raw != null
                    ? `Estimated ${pickedSoil.estimated_wilting_raw}`
                    : 'Estimated'
                }
                value={form.wiltingRaw}
                onChange={(event) => update('wiltingRaw', event.target.value)}
              />
            </label>
          </div>
        </div>

        <div className="field-row">
          <div className="soil-form">
            <label>
              Field capacity (% VWC)
              <input
                type="number"
                min="1"
                max="100"
                value={form.capacity}
                onChange={(event) => update('capacity', event.target.value)}
              />
            </label>
            <label>
              Wilting point (% VWC)
              <input
                type="number"
                min="1"
                max="100"
                value={form.wilting}
                onChange={(event) => update('wilting', event.target.value)}
              />
            </label>
          </div>
        </div>

        {/* Measured, not typed -- so it lives beside the picker rather than
            inside the field grid above. Only shown once a mix is picked: a
            brand new one has nothing in the database yet to attach a
            measurement to. */}
        {mode === 'existing' && picked && (
          <div className="field-row">
            <p className={pickedSoil?.field_capacity_raw != null ? 'field-hint' : 'field-hint warning'}>
              {pickedSoil?.field_capacity_raw != null ? (
                <>
                  Field capacity reads <strong>{pickedSoil.field_capacity_raw}</strong>
                  {pickedSoil.field_capacity_measured_at
                    ? `, measured ${pickedSoil.field_capacity_measured_at.slice(0, 10)}`
                    : ' (default or typed in, not measured on this planter)'}
                  .
                </>
              ) : (
                'Field capacity not set. Pots using this soil profile read nothing and are never watered automatically.'
              )}
            </p>
            {/* A warning only when there is neither a reading nor what an
                estimate needs: then it is missing the bottom of the scale. */}
            <p
              className={
                pickedSoil?.wilting_point_raw != null ||
                pickedSoil?.wilting_fraction != null
                  ? 'field-hint'
                  : 'field-hint warning'
              }
            >
              {pickedSoil?.wilting_point_raw != null ? (
                <>
                  Wilting point reads <strong>{pickedSoil.wilting_point_raw}</strong>
                  {pickedSoil.wilting_point_measured_at
                    ? `, measured ${pickedSoil.wilting_point_measured_at.slice(0, 10)}`
                    : ''}
                  {pickedSoil.estimated_wilting_raw != null &&
                    `; the percentages would estimate ${pickedSoil.estimated_wilting_raw}`}
                  .
                </>
              ) : pickedSoil?.wilting_fraction != null ? (
                pickedSoil.estimated_wilting_raw != null ? (
                  <>
                    Wilting point estimated at about{' '}
                    <strong>{pickedSoil.estimated_wilting_raw}</strong> from the
                    field capacity reading. Each pot works out its own from its
                    probe.
                  </>
                ) : (
                  'Wilting point will be estimated once field capacity is set.'
                )
              ) : (
                'Wilting point not set, and no percentages to estimate it from. Pots using this soil profile read nothing and are never watered automatically.'
              )}
            </p>
            <div className="soil-capacity">
              <button
                type="button"
                disabled={Boolean(measuring) || !pots.length}
                onClick={() => measure('field-capacity')}
              >
                {measuring === 'field-capacity' ? 'Measuring…' : 'Measure field capacity'}
              </button>
              <button
                type="button"
                disabled={Boolean(measuring) || !pots.length}
                onClick={() => measure('wilting-point')}
              >
                {measuring === 'wilting-point' ? 'Measuring…' : 'Measure wilting point'}
              </button>
              <select
                aria-label={`Probe to measure ${picked} with`}
                value={probe || pots[0]?.plant_id || ''}
                onChange={(event) => setProbe(event.target.value)}
              >
                {pots.map((pot) => (
                  <option key={pot.plant_id} value={pot.plant_id}>
                    {cardTitle(pot)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        <div className="field-row">
          <label>
            Notes
            <textarea
              rows="3"
              value={form.notes}
              placeholder="Where these figures came from."
              onChange={(event) => update('notes', event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <div className="save-delete-row">
            <button
              type="button"
              className="primary group-save-button"
              disabled={!formReady}
              onClick={save}
            >
              Save soil profile
            </button>
            {/* Hold rather than an inline Remove on every row: one place to
                delete a mix, same as a plant profile, and a slip of the thumb
                cannot finish five seconds by accident. */}
            {mode === 'existing' && picked && (
              <button
                type="button"
                className={holdProgress > 0 ? 'hold-delete holding' : 'hold-delete'}
                {...holdHandlers}
              >
                <HoldRing progress={holdProgress} />
                {holdProgress > 0 ? `Deleting ${picked}…` : `Hold to delete ${picked}`}
              </button>
            )}
          </div>
          {message && <p className="field-hint">{message}</p>}
        </div>
      </div>
    </section>
  )
}
