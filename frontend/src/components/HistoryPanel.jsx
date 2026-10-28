import { useEffect, useMemo, useState } from 'react'
import { Chart } from './Chart'
import { Segmented } from './Segmented'
import { API_BASE } from '../api'

const RANGES = [
  { label: '6h', value: 6 },
  { label: '24h', value: 24 },
  { label: '7d', value: 24 * 7 },
  { label: '30d', value: 24 * 30 },
  { label: '90d', value: 24 * 90 },
]

const METRICS = [
  { label: 'Moisture', value: 'moisture' },
  { label: 'Temperature', value: 'temperature' },
]

const UNITS = [
  { label: '°C', value: 'C' },
  { label: '°F', value: 'F' },
]

const PLANT_COLORS = ['#4ade80', '#60a5fa', '#f472b6', '#fbbf24']
// One empty list, so the temperature view's "no target lines" is the same
// value every render and does not rebuild the chart data each time.
const NO_TARGETS = []
// The moisture axis, as one value: the chart rebuilds whenever its range
// changes identity, and a fresh [0, 100] each render threw away any zoom.
const MOISTURE_RANGE = [0, 100]
// How often an open History tab fetches the latest readings. The control loop
// records one a minute, so more often would only fetch the same thing.
const HISTORY_POLL_MS = 60000

// Readings are stored and transmitted in Celsius. This converts for display
// only -- the history keeps one unit whatever anyone happens to be viewing in.
const toFahrenheit = (celsius) => (celsius == null ? null : (celsius * 9) / 5 + 32)

// One pot's line on the current view.
const valuesOf = (plant, moisture, fahrenheit) => {
  if (moisture) return plant.moisture_percent
  return fahrenheit ? plant.temperature_c.map(toFahrenheit) : plant.temperature_c
}

// Remembered per browser rather than on the Pi: it is a display preference,
// and someone reading the chart on a phone should not change what the laptop
// shows. localStorage can throw in a private window, so it never breaks the
// panel if it is unavailable.
// Deliberately not renamed with the product: this is a localStorage key
// nobody sees, and changing it would silently discard the °F preference
// of anyone who had already set one.
const UNIT_KEY = 'greenthumb.tempUnit'

const storedUnit = () => {
  try {
    return localStorage.getItem(UNIT_KEY) === 'F' ? 'F' : 'C'
  } catch {
    return 'C'
  }
}

export function HistoryPanel() {
  const [hours, setHours] = useState(24)
  const [metric, setMetric] = useState('moisture')
  const [unit, setUnit] = useState(storedUnit)
  const [history, setHistory] = useState(null)
  const [status, setStatus] = useState('Loading history...')

  useEffect(() => {
    let canceled = false

    // `quiet` for the periodic refresh: the chart stays up while it fetches,
    // rather than flashing "Loading" once a minute.
    const load = async (quiet = false) => {
      if (!quiet) setStatus('Loading history...')
      if (quiet && document.visibilityState !== 'visible') return
      try {
        const response = await fetch(`${API_BASE}/history?hours=${hours}`)
        const data = await response.json()
        if (canceled) return
        if (!response.ok) {
          setStatus(data.error || 'Failed to load history')
          return
        }
        setHistory(data)
        setStatus('')
      } catch (error) {
        if (!canceled) setStatus(`Failed to load history: ${error.message}`)
      }
    }

    load()
    const id = setInterval(() => load(true), HISTORY_POLL_MS)
    // Ignore a response that arrives after the range changed again.
    return () => {
      canceled = true
      clearInterval(id)
    }
  }, [hours])

  const moisture = metric === 'moisture'
  const fahrenheit = !moisture && unit === 'F'

  const chooseUnit = (next) => {
    setUnit(next)
    try {
      localStorage.setItem(UNIT_KEY, next)
    } catch {
      // A browser that refuses storage still gets the toggle, just not the
      // memory of it.
    }
  }

  // Only pots with a plant profile loaded. An empty pot's probe still reports,
  // but it is not a plant anyone is watching, and its line and legend entry
  // crowded the chart. Each pot keeps the color of its position, so loading a
  // plant into one pot does not recolor the others.
  const shown = useMemo(
    () =>
      (history?.plants || [])
        .map((plant, index) => ({ ...plant, color: PLANT_COLORS[index % PLANT_COLORS.length] }))
        .filter((plant) => plant.profile),
    [history],
  )

  // On the moisture view each pot's target is drawn as a flat dashed line in
  // its color: the reading and the target are on the same soil water scale,
  // so a line dropping to its dashes is a pot coming due.
  const targets = moisture ? shown : NO_TARGETS

  const data = useMemo(() => {
    if (!history) return [[]]
    return [
      history.timestamps,
      ...shown.map((plant) => valuesOf(plant, moisture, fahrenheit)),
      ...targets.map((plant) => history.timestamps.map(() => plant.target_available ?? null)),
    ]
  }, [history, shown, moisture, fahrenheit, targets])

  // The series only depend on each pot's name, color and target, so they are
  // keyed on those rather than on the fetched history: a new series list
  // rebuilds the chart, and the minute-by-minute refresh would otherwise reset
  // the zoom.
  const plantKey = JSON.stringify(
    shown.map((plant) => [plant.name, plant.color, plant.target_available ?? null]),
  )
  const plantMeta = useMemo(
    () => JSON.parse(plantKey).map(([name, color, target]) => ({ name, color, target })),
    [plantKey],
  )
  const targetMeta = moisture ? plantMeta : NO_TARGETS

  const series = useMemo(() => {
    if (!plantMeta.length) return [{}]
    return [
      {},
      ...plantMeta.map((plant) => ({
        label: plant.name,
        stroke: plant.color,
        width: 2,
        // Gaps are real: they mean the sensor could not be read.
        spanGaps: false,
      })),
      ...targetMeta.map((plant) => ({
        label: `${plant.name} waters at`,
        stroke: plant.color,
        width: 1,
        dash: [6, 6],
      })),
    ]
  }, [plantMeta, targetMeta])

  // Fixed for moisture so plants and time ranges stay visually comparable
  // instead of the axis rescaling to whatever happens to be on screen.
  const yRange = moisture ? MOISTURE_RANGE : undefined

  // The point under the cursor, or null for each pot's latest reading.
  const [cursorIdx, setCursorIdx] = useState(null)
  const suffix = moisture ? '%' : fahrenheit ? '°F' : '°C'
  const readingAt = (values) => {
    if (cursorIdx != null) return values[cursorIdx]
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (values[i] != null) return values[i]
    }
    return null
  }

  const hasData = history?.timestamps?.length > 0 && shown.length > 0
  const missedCount = (history?.waterings || []).filter(
    (watering) => watering.soak === 'missed',
  ).length

  return (
    <section className="panel-section">
      <h2>History</h2>

      {/* What to plot goes above the chart; how far back goes below it. The
          unit sits at the end of the same row, so it appearing on Temperature
          moves nothing under it. */}
      <div className="history-toolbar">
        <Segmented label="Show" options={METRICS} value={metric} onChange={setMetric} />
        {!moisture && <Segmented label="Unit" options={UNITS} value={unit} onChange={chooseUnit} />}
      </div>

      {status && <p className="field-hint">{status}</p>}

      {!status && history && !shown.length && (
        <p className="field-hint">
          No plants loaded. Load a plant profile onto a pot in Plants and Soil to chart it here.
        </p>
      )}

      {!status && shown.length > 0 && !hasData && (
        <p className="field-hint">
          No readings in this range yet. The control loop records one a minute,
          so a fresh install needs a few minutes before the chart fills in.
        </p>
      )}

      {hasData && (
        <Chart
          data={data}
          series={series}
          markers={history.waterings || []}
          yRange={yRange}
          yLabel={moisture ? 'Soil water %' : fahrenheit ? 'Temp °F' : 'Temp °C'}
          onCursor={setCursorIdx}
        />
      )}

      {/* One chip per pot instead of uPlot's table, which gave every pot a
          second row for its target and listed the time as a series of its
          own. The target lines get one shared key. */}
      {hasData && (
        <ul className="chart-legend">
          {shown.map((plant) => {
            const value = readingAt(valuesOf(plant, moisture, fahrenheit))
            return (
              <li key={plant.plant_id}>
                <span className="chart-swatch" style={{ background: plant.color }} />
                {plant.name}
                <strong>{value == null ? '--' : `${value.toFixed(1)}${suffix}`}</strong>
              </li>
            )
          })}
          {moisture && (
            <li className="chart-legend-key">Dashed line is &lsquo;water-at&rsquo; level</li>
          )}
        </ul>
      )}

      {/* Outside the chart's block, so a range with no readings still offers
          the way to pick another one. */}
      <Segmented
        label="Time range"
        className="history-range"
        options={RANGES}
        value={hours}
        onChange={setHours}
      />

      {hasData && (
        <>
          <p className="field-hint">
            {history.waterings?.length === 1
              ? '1 watering in this range.'
              : `${history.waterings?.length || 'No'} waterings in this range.`}
          </p>
          {missedCount > 0 && (
            <p className="field-hint warning">
              {missedCount === 1 ? '1 dose' : `${missedCount} doses`} never
              showed up on the pot&apos;s moisture probe within the hour, drawn
              as solid amber lines. Check the reservoir, that the nozzle lines up
              with the pot, and that the probe is in the soil.
            </p>
          )}
        </>
      )}
    </section>
  )
}
