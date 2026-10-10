import { useState } from 'react'
import { API_BASE } from '../api'

// The soil library, on the same tab as the pots that use it.
//
// Takes `soils` as a prop rather than fetching its own copy. It used to live in
// Settings, a tab away from the plant cards, and self-fetched a second list
// that the dashboard was already holding for the soil dropdown -- so the two
// could disagree until something reloaded.
const SAMPLE_SECONDS = 20

export function SoilsPanel({ soils, plants, onRefresh }) {
  const [name, setName] = useState('')
  const [capacity, setCapacity] = useState('')
  const [wilting, setWilting] = useState('')
  const [notes, setNotes] = useState('')
  const [message, setMessage] = useState('')

  // Which probe each mix will be measured with. One figure per mix is enough:
  // probes of the same kind read closely enough that a good reading from any
  // of them beats four nobody got round to taking. A pot that wants better
  // measures its own, on its card.
  const [probe, setProbe] = useState({})
  const [measuring, setMeasuring] = useState('')

  const list = soils ?? []
  const pots = plants ?? []

  const measure = async (soilName) => {
    const plantId = probe[soilName] || pots[0]?.plant_id
    if (!plantId) return
    setMessage('')
    setMeasuring(soilName)
    try {
      const response = await fetch(
        `${API_BASE}/soils/${encodeURIComponent(soilName)}/field-capacity`,
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
      const applied = data.inherited_by ?? []
      setMessage(
        `${soilName} reads ${data.value} at field capacity, measured with ` +
          `${data.measured_with}. ` +
          (applied.length
            ? `Applied to ${applied.join(', ')}.`
            : 'No pot is filled with it yet, so nothing changed.'),
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
    try {
      const response = await fetch(`${API_BASE}/soils`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          field_capacity_vwc: Number(capacity),
          wilting_point_vwc: Number(wilting),
          notes,
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Save failed (HTTP ${response.status})`)
        return
      }
      setMessage(
        `Saved ${data.name}: ${data.available_points} points of usable water, ` +
          `wilting at ${Math.round((data.wilting_fraction ?? 0) * 100)}% of field capacity.`,
      )
      setName('')
      setCapacity('')
      setWilting('')
      setNotes('')
      onRefresh?.()
    } catch (error) {
      setMessage(`Save failed: ${error.message}`)
    }
  }

  const remove = async (soilName) => {
    setMessage('')
    try {
      const response = await fetch(`${API_BASE}/soils/${encodeURIComponent(soilName)}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setMessage(data.detail || data.error || `Could not remove ${soilName}`)
        return
      }
      // Pots still naming it keep the name, which stops resolving. Saying so
      // is the point -- a silently cleared soil hides that a pot is no longer
      // described, and a pot with no soil is never watered automatically.
      setMessage(`Removed ${soilName}. Any pot still set to it needs a new soil.`)
      onRefresh?.()
    } catch (error) {
      setMessage(`Could not remove ${soilName}: ${error.message}`)
    }
  }

  const formReady = name.trim() && capacity !== '' && wilting !== ''

  return (
    <section className="panel-section">
      <h2>Soils</h2>

      <div className="general-settings-form">
        <div className="field-row">
          {list.length ? (
            <ul className="soil-list">
              {list.map((soil) => (
                <li key={soil.name}>
                  <span>
                    <strong>{soil.name}</strong>
                    <small>
                      field capacity {soil.field_capacity_vwc}% &middot; wilting{' '}
                      {soil.wilting_point_vwc}% &middot; {soil.available_points} pts usable
                    </small>
                    {soil.field_capacity_raw != null ? (
                      <small>
                        reads {soil.field_capacity_raw} at field capacity
                        {soil.field_capacity_measured_at
                          ? `, measured ${soil.field_capacity_measured_at.slice(0, 10)}`
                          : ''}
                      </small>
                    ) : (
                      <small className="warning">
                        not measured — pots of this mix read nothing and are never
                        watered automatically
                      </small>
                    )}
                    {soil.notes && <small>{soil.notes}</small>}
                    <span className="soil-capacity">
                      <select
                        aria-label={`Probe to measure ${soil.name} with`}
                        value={probe[soil.name] ?? pots[0]?.plant_id ?? ''}
                        onChange={(event) =>
                          setProbe((current) => ({
                            ...current,
                            [soil.name]: event.target.value,
                          }))
                        }
                      >
                        {pots.map((pot) => (
                          <option key={pot.plant_id} value={pot.plant_id}>
                            {pot.name}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={Boolean(measuring) || !pots.length}
                        onClick={() => measure(soil.name)}
                      >
                        {measuring === soil.name
                          ? 'Measuring…'
                          : 'Measure field capacity'}
                      </button>
                    </span>
                  </span>
                  <button type="button" onClick={() => remove(soil.name)}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="field-hint warning">
              No soils. The installer adds a starting set, so this means they
              were all removed — add your own below, or put the set back with{' '}
              <code>python -m greenthumb.soil_library --install</code> on the
              Pi. Until a pot has a soil it is never watered automatically.
            </p>
          )}
        </div>

        <div className="field-row">
          <div className="soil-form">
            <label>
              Name
              <input
                value={name}
                placeholder="My potting mix"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              Field capacity (% VWC)
              <input
                type="number"
                min="1"
                max="100"
                value={capacity}
                onChange={(event) => setCapacity(event.target.value)}
              />
            </label>
            <label>
              Wilting point (% VWC)
              <input
                type="number"
                min="1"
                max="100"
                value={wilting}
                onChange={(event) => setWilting(event.target.value)}
              />
            </label>
          </div>
          <button
            type="button"
            className="primary group-save-button"
            disabled={!formReady}
            onClick={save}
          >
            Save soil
          </button>
          {message && <p className="field-hint">{message}</p>}
        </div>

        <div className="field-row">
          <label>
            Notes
            <textarea
              rows="3"
              value={notes}
              placeholder="Where these figures came from."
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
        </div>

        <div className="field-row">
          <p className="field-hint">
            Saving replaces any soil of the same name. Only the <em>ratio</em>
            {' '}of these two percentages leaves this table usefully — it is
            dimensionless, so a published figure applies to any pot of that mix,
            and it is what fixes the bottom of the moisture scale.
          </p>
          <p className="field-hint">
            The percentages do not convert into sensor readings, which is why
            each mix also needs <strong>field capacity measured once</strong>,
            above. Soak a pot of it through, let it drain 24 hours, pick the
            probe sitting in that pot, and measure. That figure is copied onto
            every pot filled with the mix, and gives the top of their scale.
            Re-measure after a repot: mixes lose capacity as they age and
            compact.
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
    </section>
  )
}
