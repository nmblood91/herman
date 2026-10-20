import { useEffect, useMemo, useState } from 'react'
import { Chart } from './Chart'
import { API_BASE } from '../api'

const RANGES = [
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 24 * 7 },
  { label: '30d', hours: 24 * 30 },
  { label: '90d', hours: 24 * 90 },
]

const PLANT_COLORS = ['#4ade80', '#60a5fa', '#f472b6', '#fbbf24']
// One empty list, so the temperature view's "no target lines" is the same
// value every render and does not rebuild the chart data each time.
const NO_TARGETS = []

// Readings are stored and transmitted in Celsius. This converts for display
// only -- the history keeps one unit whatever anyone happens to be viewing in.
const toFahrenheit = (celsius) => (celsius == null ? null : celsius * 9 / 5 + 32)

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
    let cancelled = false

    const load = async () => {
      setStatus('Loading history...')
      try {
        const response = await fetch(`${API_BASE}/history?hours=${hours}`)
        const data = await response.json()
        if (cancelled) return
        if (!response.ok) {
          setStatus(data.error || 'Failed to load history')
          return
        }
        setHistory(data)
        setStatus('')
      } catch (error) {
        if (!cancelled) setStatus(`Failed to load history: ${error.message}`)
      }
    }

    load()
    // Ignore a response that arrives after the range changed again.
    return () => {
      cancelled = true
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

  // On the moisture view each pot's target is drawn as a flat dashed line in
  // its colour: the reading and the target are on the same soil water scale,
  // so a line dropping to its dashes is a pot coming due.
  const targets = moisture && history ? history.plants : NO_TARGETS

  const data = useMemo(() => {
    if (!history) return [[]]
    return [
      history.timestamps,
      ...history.plants.map((plant) => {
        if (moisture) return plant.moisture_percent
        return fahrenheit
          ? plant.temperature_c.map(toFahrenheit)
          : plant.temperature_c
      }),
      ...targets.map((plant) => history.timestamps.map(() => plant.target_available ?? null)),
    ]
  }, [history, moisture, fahrenheit, targets])

  const series = useMemo(() => {
    if (!history) return [{}]
    return [
      {},
      ...history.plants.map((plant, index) => ({
        label: plant.name,
        stroke: PLANT_COLORS[index % PLANT_COLORS.length],
        width: 2,
        // Gaps are real: they mean the sensor could not be read.
        spanGaps: false,
        value: (self, raw) =>
          raw == null
            ? '--'
            : `${raw.toFixed(1)}${moisture ? '%' : fahrenheit ? '°F' : '°C'}`,
      })),
      ...targets.map((plant, index) => ({
        label: `${plant.name} waters at`,
        stroke: PLANT_COLORS[index % PLANT_COLORS.length],
        width: 1,
        dash: [6, 6],
        value: (self, raw) => (raw == null ? '--' : `${raw}%`),
      })),
    ]
  }, [history, moisture, fahrenheit, targets])

  // Fixed for moisture so plants and time ranges stay visually comparable
  // instead of the axis rescaling to whatever happens to be on screen.
  const yRange = moisture ? [0, 100] : undefined

  const hasData = history?.timestamps?.length > 0
  const missedCount = (history?.waterings || []).filter(
    (watering) => watering.soak === 'missed',
  ).length

  return (
    <section className="panel-section">
      <h2>History</h2>

      <div className="history-controls">
        <div className="range-row">
          {RANGES.map((range) => (
            <button
              key={range.label}
              type="button"
              className={hours === range.hours ? 'tab active' : 'tab'}
              onClick={() => setHours(range.hours)}
            >
              {range.label}
            </button>
          ))}
        </div>
        <div className="range-row">
          <button
            type="button"
            className={moisture ? 'tab active' : 'tab'}
            onClick={() => setMetric('moisture')}
          >
            Moisture
          </button>
          <button
            type="button"
            className={!moisture ? 'tab active' : 'tab'}
            onClick={() => setMetric('temperature')}
          >
            Temperature
          </button>
        </div>
        {!moisture && (
          <div className="range-row">
            <button
              type="button"
              className={unit === 'C' ? 'tab active' : 'tab'}
              onClick={() => chooseUnit('C')}
            >
              °C
            </button>
            <button
              type="button"
              className={unit === 'F' ? 'tab active' : 'tab'}
              onClick={() => chooseUnit('F')}
            >
              °F
            </button>
          </div>
        )}
      </div>

      {status && <p className="field-hint">{status}</p>}

      {!status && !hasData && (
        <p className="field-hint">
          No readings in this range yet. The control loop records one a minute,
          so a fresh install needs a few minutes before the chart fills in.
        </p>
      )}

      {hasData && (
        <>
          <Chart
            data={data}
            series={series}
            markers={history.waterings || []}
            yRange={yRange}
            yLabel={moisture ? 'Soil water %' : fahrenheit ? 'Temp °F' : 'Temp °C'}
          />
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
