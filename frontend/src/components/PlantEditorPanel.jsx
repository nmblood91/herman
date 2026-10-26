import { useEffect, useState } from 'react'
import { API_BASE } from '../api'
import { useHoldToConfirm } from '../useHoldToConfirm'
import { HoldRing } from './HoldRing'
import { describeBrightness, formatClock, lightStop } from '../time'
import { groupByCategory } from '../profileGroups'

const BLANK = {
  name: '',
  category: '',
  preferred_soil: '',
  target_available: 40,
  watering_volume_ml: 100,
  light_start_time: '07:00',
  light_hours: 12,
  light_brightness: 75,
  notes: '',
}

// The water level a target falls in, as a share of the soil's available water.
// A label only, worked out from the target and never stored: the percentage
// waters. Mirrors greenthumb.care.WATER_LEVEL_FLOORS and its 10-90% range.
const WATER_LEVEL_FLOORS = [
  [88, 'Ultra Wet'],
  [76, 'Very Wet'],
  [63, 'Wet'],
  [51, 'Medium-Wet'],
  [38, 'Medium-Dry'],
  [26, 'Dry'],
  [13, 'Very Dry'],
  [0, 'Ultra Dry'],
]
const MIN_TARGET = 10
const MAX_TARGET = 90
const waterLevelFor = (percent) =>
  WATER_LEVEL_FLOORS.find(([floor]) => Number(percent) >= floor)?.[1] ?? ''

const formFrom = (entry) => ({
  name: entry.name,
  category: entry.category ?? '',
  preferred_soil: entry.preferred_soil ?? '',
  target_available: entry.target_available ?? BLANK.target_available,
  watering_volume_ml: entry.watering_volume_ml ?? BLANK.watering_volume_ml,
  light_start_time: entry.light_start_time ?? BLANK.light_start_time,
  light_hours: entry.light_hours ?? BLANK.light_hours,
  light_brightness: entry.light_brightness ?? BLANK.light_brightness,
  notes: entry.notes ?? '',
})

// How long Delete has to be held. Long enough that it cannot fire by brushing
// the button, short enough that meaning it does not feel like a chore.
const DELETE_HOLD_MS = 5000

// The library of plant profiles, edited in its own right.
//
// 
// Nothing here touches a pot. A plant becomes real on a pot when you load it
// from that pot's card, which is the same direction the whole pot/plant split
// runs in: this names what a plant wants, the card says where it lives.
export function PlantEditorPanel({ profiles, soils, onRefresh }) {
  // 'new' types a free name below; 'existing' turns that field into a picker
  // over the list. Picked is only ever non-empty in 'existing' mode -- every
  // path back to 'new' clears it, so the two stay in lockstep.
  const [mode, setMode] = useState('new')
  const [picked, setPicked] = useState('')
  const [form, setForm] = useState(BLANK)
  const [message, setMessage] = useState('')

  const list = profiles ?? []
  const soilList = soils ?? []
  const categories = [...new Set(list.map((profile) => profile.category).filter(Boolean))]

  // The list already carries every field, so the form fills from the prop
  // rather than fetching the entry again. Synced during render, not in an
  // effect, so the inputs never paint one frame of the previous plant.
  const [syncedPick, setSyncedPick] = useState('')
  if (picked !== syncedPick) {
    setSyncedPick(picked)
    const entry = list.find((profile) => profile.name === picked)
    setForm(entry ? formFrom(entry) : BLANK)
  }

  const stopsAt = lightStop(form.light_start_time, form.light_hours)

  // Profiles are keyed by name, ignoring case, so saving a new one under a
  // name already in the list replaces that one. It used to do so silently.
  const clash =
    mode === 'new'
      ? list.find(
          (profile) =>
            profile.name.trim().toLocaleLowerCase() === form.name.trim().toLocaleLowerCase(),
        )
      : null

  // A variant of an existing plant -- "Basil - Dry" beside "Basil" -- starts
  // from that plant's settings rather than a blank form. Moves to New Profile
  // with every field kept and the name marked as a copy, to be renamed.
  const makeCopy = () => {
    setMode('new')
    setPicked('')
    setSyncedPick('')
    setForm((current) => ({ ...current, name: `${current.name} copy` }))
    setMessage('Copied. Give it its own name, change what you like, then save.')
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
    // Picked is always '' on the way in here (startNewProfile clears it, and
    // it starts '' on mount), so the picker opens on its placeholder. Blank
    // the rest too, rather than showing a new-plant draft's leftover fields
    // under a dropdown that says nothing is chosen yet.
    setForm(BLANK)
    setMessage('')
  }

  const save = async () => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/plant-profiles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          target_available: Number(form.target_available),
          watering_volume_ml: Number(form.watering_volume_ml),
          light_hours: Number(form.light_hours),
          light_brightness: Number(form.light_brightness),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setMessage(`Saved plant profile ${data.name}. Load it onto a pot from that pot's card.`)
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
      const response = await fetch(`${API_BASE}/plant-profiles/${encodeURIComponent(picked)}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Could not delete ${picked}`)
        return
      }
      // Pots already carrying these settings keep them: loading copied the
      // values across rather than linking to the entry.
      setMessage(`Deleted plant profile ${picked}. Pots already using it keep their settings.`)
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

  // A hold in progress belongs to the plant that was picked when it started.
  // If picked changes under it -- there is no ordinary way to do that with
  // one pointer, but a keyboard can tab away mid-hold -- it must not go on to
  // delete whatever is picked by the time the five seconds are up.
  //
  // cancelHold deliberately left out of the deps: it is a fresh closure every
  // render (the hook does not memoise it), so including it would re-fire this
  // effect on every render -- which, while a hold is in progress, is every
  // animation frame, canceling the hold the instant it ticks.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => cancelHold, [picked])

  return (
    <section className="panel-section">
      <h2>Plant Profile Editor</h2>

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
              No plant profiles. The installer adds a starter set, so this means
              they were all deleted — fill the form below, or put the set back
              with <code>python -m greenthumb.plant_library --install</code> on
              the Pi. A pot takes its care settings by loading one of these, so
              until there is at least one there is nothing to load.
            </p>
          )}
        </div>

        <div className="field-grid">
          {mode === 'existing' ? (
            <label>
              Plant name
              <select
                aria-label="Plant profile to edit"
                value={picked}
                onChange={(event) => setPicked(event.target.value)}
              >
                <option value="">Choose a plant profile…</option>
                {groupByCategory(list).map(([category, members]) => (
                  <optgroup key={category} label={category}>
                    {members.map((profile) => (
                      <option key={profile.name} value={profile.name}>
                        {profile.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
          ) : (
            <label>
              Plant name
              <input
                value={form.name}
                placeholder="New Plant Name"
                onChange={(event) => update('name', event.target.value)}
              />
            </label>
          )}
          <div className="field-pair">
            <label>
              Category
              <input
                list="plant-categories"
                value={form.category}
                placeholder="Optional"
                onChange={(event) => update('category', event.target.value)}
              />
              <datalist id="plant-categories">
                {categories.map((category) => (
                  <option key={category} value={category} />
                ))}
              </datalist>
            </label>
            <label>
              Preferred soil
              <select
                value={form.preferred_soil}
                onChange={(event) => update('preferred_soil', event.target.value)}
              >
                <option value="">None</option>
                {soilList.map((soil) => (
                  <option key={soil.name} value={soil.name}>
                    {soil.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label>
            Water at: {form.target_available}% soil water ({waterLevelFor(form.target_available)})
            <input
              type="range"
              min={MIN_TARGET}
              max={MAX_TARGET}
              step="1"
              value={form.target_available}
              onChange={(event) => update('target_available', event.target.value)}
            />
          </label>
          <p className="field-hint">Watered once the soil dries to this.</p>
          <label>
            Watering Volume (mL)
            <input
              type="number"
              min="0"
              step="10"
              value={form.watering_volume_ml}
              onChange={(event) => update('watering_volume_ml', event.target.value)}
            />
          </label>

          <div className="field-pair">
            <label>
              Lights on at
              <input
                type="time"
                value={form.light_start_time}
                onChange={(event) => update('light_start_time', event.target.value)}
              />
            </label>
            <label>
              Hours of light
              <input
                type="number"
                min="0"
                max="24"
                step="1"
                value={form.light_hours}
                onChange={(event) => update('light_hours', event.target.value)}
              />
            </label>
          </div>
          <p className="field-hint">
            {Number(form.light_hours) >= 24
              ? 'Lights stay on all day.'
              : Number(form.light_hours) <= 0
                ? 'Lights stay off.'
                : stopsAt
                  ? `Lights off at ${formatClock(stopsAt)}.`
                  : 'Set a start time and a whole number of hours.'}
          </p>
          <label>
            Brightness: {describeBrightness(form.light_brightness)}
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={form.light_brightness}
              onChange={(event) => update('light_brightness', event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <label>
            Notes
            <textarea
              rows="3"
              value={form.notes}
              placeholder="Write notes about the plant here"
              onChange={(event) => update('notes', event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <div className="save-delete-row">
            <button
              type="button"
              className="primary group-save-button"
              disabled={!form.name.trim()}
              onClick={save}
            >
              {clash ? `Replace ${clash.name}` : 'Save plant profile'}
            </button>
            {mode === 'existing' && picked && (
              <button type="button" onClick={makeCopy}>
                Make a copy
              </button>
            )}
            {/* Hold rather than click-twice: a slip of the thumb cannot finish
                five seconds by accident, so there is nothing left for a
                second confirmation to catch. Releasing early -- pointer up,
                leaving the button, losing focus -- cancels for free, since
                nothing happens until the hold completes. */}
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
          {clash && (
            <p className="field-hint warning">
              A plant profile named {clash.name} already exists. Saving replaces
              it. Give this one a different name to keep both.
            </p>
          )}
          {message && <p className="field-hint">{message}</p>}
        </div>
      </div>
    </section>
  )
}
