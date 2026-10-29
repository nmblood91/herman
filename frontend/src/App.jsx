import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TopBar } from './components/TopBar'
import { TabBar } from './components/TabBar'
import { ControlsPanel } from './components/ControlsPanel'
import { AutomationPanel } from './components/AutomationPanel'
import { PlantsPanel } from './components/PlantsPanel'
import { PlantEditorPanel } from './components/PlantEditorPanel'
import { SoilPanel } from './components/SoilPanel'
import { LibraryBackupPanel } from './components/LibraryBackupPanel'
import { HelpPanel } from './components/HelpPanel'
import { HistoryPanel } from './components/HistoryPanel'
import { HomeSwitchPanel } from './components/HomeSwitchPanel'
import { MotorDirectionPanel } from './components/MotorDirectionPanel'
import { ClockPanel } from './components/ClockPanel'
import { HostnamePanel } from './components/HostnamePanel'
import { VersionPanel } from './components/VersionPanel'
import { PumpPanel } from './components/PumpPanel'
import { PowerPanel } from './components/PowerPanel'
import { CalibrationPanel } from './components/CalibrationPanel'
import { SystemValuesPanel } from './components/SystemValuesPanel'
import { LedStripPanel } from './components/LedStripPanel'
import { LogsPanel } from './components/LogsPanel'
import './App.css'
import { API_BASE } from './api'
import { describeLighting } from './time'

const fetchJson = async (path, options = {}) => {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (error) {
    // No answer at all: the Pi is off the network, rebooting, or wedged past
    // the timeout below. The browser's own wording ("Failed to fetch", "signal
    // timed out") says none of that.
    if (error.name === 'TypeError' || error.name === 'TimeoutError') {
      throw new Error('The planter is not answering. It may be restarting.', { cause: error })
    }
    throw error
  }

  // Read as text first: while the API restarts, nginx answers with an HTML
  // error page, and parsing that as JSON surfaced as "Unexpected token '<'".
  const text = await response.text()
  let data
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    throw new Error(
      response.ok
        ? 'The planter sent back something unreadable.'
        : `The planter is not answering (HTTP ${response.status}). It may be restarting.`,
    )
  }
  if (!response.ok) {
    throw new Error(data.detail || data.error || `Request failed (HTTP ${response.status})`)
  }

  return data
}

// How often the Controls tab re-reads the carriage position. Fast enough to
// watch a move, and only while that tab is open.
const GANTRY_POLL_MS = 1000
// How often the planter's state is re-read while the page is open. Without it
// the page only learned anything on load and after a button press here, so the
// status bar kept saying whatever was true then -- "test the motor direction"
// long after it had passed on another device.
const OVERVIEW_POLL_MS = 15000
// How soon a dashboard load that came back incomplete is tried again. Far
// sooner than the poll above, and it has to exist at all: the poll only reads
// the overview, so a pot list or library that failed on page load used to stay
// empty until someone reloaded the page.
const RETRY_MS = 3000
// A dashboard read that has not answered by now counts as failed, so a wedged
// Pi shows up as a retry rather than a page that waits forever. Only the
// reads: a watering request legitimately takes over a minute.
const LOAD_TIMEOUT_MS = 10000

// "a", "a and b", "a, b and c".
const joinNames = (names) =>
  names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`

function App() {
  const [activeTab, setActiveTab] = useState('plants')
  const [overview, setOverview] = useState(null)
  const [plants, setPlants] = useState([])
  // The plant profile library. Fetched alongside the dashboard because saving a
  // plant changes it, so it has to refresh on the same beat.
  const [profiles, setProfiles] = useState([])
  const [soils, setSoils] = useState([])
  // Which lists have arrived at least once. An empty list means two different
  // things -- "not heard yet" and "there are none" -- and the panels warn that
  // the library was deleted on the second, which is alarming and wrong on the
  // first.
  const [loaded, setLoaded] = useState({ plants: false, profiles: false, soils: false })
  // What the last dashboard load could not get, or ''. Kept apart from
  // `action` because it must not expire while it is still true.
  const [loadProblem, setLoadProblem] = useState('')
  const loadsInFlight = useRef(0)
  // Transient feedback from something the user just did. Clears itself so the
  // bar falls back to the planter's actual state rather than freezing on the
  // last thing that happened to be clicked.
  const [action, setAction] = useState('')
  const actionTimer = useRef(null)

  const setStatus = useCallback((message, { sticky = false } = {}) => {
    clearTimeout(actionTimer.current)
    setAction(message)
    if (!sticky) {
      actionTimer.current = setTimeout(() => setAction(''), 6000)
    }
  }, [])

  useEffect(() => () => clearTimeout(actionTimer.current), [])

  // Motion endpoints answer 200 with {ok: false, error} when Klipper refuses
  // the move, so a successful request is not a successful move.
  const describeResult = (result) => (result?.ok === false ? `failed - ${result.error}` : 'ok')

  // Each read stands alone. This was one Promise.all, so a single slow or
  // failed read -- the overview mid-restart, say -- threw away the three that
  // had answered and left the pots and both libraries empty. Now whatever
  // arrived is shown, whatever did not keeps its last good copy, and the gap
  // is named in the status bar until a retry fills it.
  const loadDashboard = useCallback(async () => {
    loadsInFlight.current += 1
    try {
      const read = (path) => fetchJson(path, { signal: AbortSignal.timeout(LOAD_TIMEOUT_MS) })
      const [overviewResult, plantsResult, profileResult, soilResult] = await Promise.allSettled([
        read('/overview'),
        read('/plants'),
        read('/plant-profiles'),
        read('/soils'),
      ])
      const ok = (result) => result.status === 'fulfilled'

      if (ok(overviewResult)) setOverview(overviewResult.value)
      if (ok(plantsResult)) setPlants(plantsResult.value)
      if (ok(profileResult)) setProfiles(profileResult.value.profiles ?? [])
      if (ok(soilResult)) setSoils(soilResult.value.soils ?? [])
      setLoaded((prev) => ({
        plants: prev.plants || ok(plantsResult),
        profiles: prev.profiles || ok(profileResult),
        soils: prev.soils || ok(soilResult),
      }))

      const failed = [
        ['the planter status', overviewResult],
        ['the pots', plantsResult],
        ['the plant profiles', profileResult],
        ['the soil profiles', soilResult],
      ].filter(([, result]) => !ok(result))
      // Deliberately does not touch `action`. This runs after every action, so
      // writing to it here would wipe the feedback from whatever the user just
      // pressed; loadProblem shows once that feedback expires.
      setLoadProblem(
        failed.length
          ? `Could not load ${joinNames(failed.map(([name]) => name))}: ` +
              `${failed[0][1].reason.message} Retrying...`
          : '',
      )
    } finally {
      loadsInFlight.current -= 1
    }
  }, [])

  useEffect(() => {
    // Guarded rather than a bare loadDashboard(): a response that lands after
    // the component is gone would set state on nothing, and setting state
    // straight from an effect body is what the hooks lint objects to.
    let canceled = false
    async function loadOnMount() {
      if (!canceled) await loadDashboard()
    }
    loadOnMount()
    return () => {
      canceled = true
    }
  }, [loadDashboard])

  // Until a load comes back whole. Skipped while one is still out, so a Pi
  // that answers slowly is not buried under overlapping retries, and while the
  // page is hidden -- the next tick after it comes back catches up.
  useEffect(() => {
    if (!loadProblem) return undefined
    const id = setInterval(() => {
      if (loadsInFlight.current === 0 && document.visibilityState === 'visible') loadDashboard()
    }, RETRY_MS)
    return () => clearInterval(id)
  }, [loadProblem, loadDashboard])

  // Only the overview: the plant list, profiles and soils feed editors, and
  // those are re-read after each save rather than under someone's typing.
  // Skipped while the page is hidden, and done at once when it comes back.
  useEffect(() => {
    let canceled = false
    async function refresh() {
      if (document.visibilityState !== 'visible') return
      try {
        const data = await fetchJson('/overview')
        if (!canceled) setOverview(data)
      } catch {
        // The next refresh tries again; a load or a button press reports it.
      }
    }
    const id = setInterval(refresh, OVERVIEW_POLL_MS)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      canceled = true
      clearInterval(id)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [])

  const systemStatus = overview?.system_status ?? {
    level: 'info',
    message: 'Waking Herman up...',
  }

  // The carriage's live position, polled only while the Controls tab is open.
  // The dashboard is fetched on load and after each button press, so on its
  // own it misses every move the planter makes by itself -- automatic
  // watering, the hourly patrol, the startup home -- and anything done from another
  // browser. This is a cheap read that Klipper answers even mid-move, so it
  // does not wait on, or hold up, a watering cycle.
  const [livePosition, setLivePosition] = useState(null)

  useEffect(() => {
    if (activeTab !== 'controls') return undefined
    let canceled = false
    async function poll() {
      try {
        const data = await fetchJson('/gantry/position')
        if (!canceled) setLivePosition(data)
      } catch {
        // A missed poll keeps the last reading; the next one replaces it.
      }
    }
    poll()
    const id = setInterval(poll, GANTRY_POLL_MS)
    return () => {
      canceled = true
      clearInterval(id)
      // Dropped on leaving the tab, so coming back shows the dashboard's
      // reading until the first poll lands rather than one from minutes ago.
      setLivePosition(null)
    }
  }, [activeTab])

  const gantryPosition = useMemo(() => {
    const movement = livePosition ?? overview?.movement ?? {}
    if (movement.ok === false) return 'unavailable'
    // Klipper invents a position for the homing move (negative, counting up),
    // so there is no real number to show until the switch trips.
    if (movement.homing) return 'homing…'
    if (!movement.homed) return 'not homed'

    // Whole millimeters: Klipper reports tenths, and the decimal flickers on a
    // readout polled every second without telling anyone anything.
    const numericValue = Math.round(Number(movement.position))
    if (!Number.isFinite(numericValue)) return 'unknown'
    return movement.moving
      ? `${numericValue} mm → ${Math.round(movement.target)} mm`
      : `${numericValue} mm`
  }, [livePosition, overview])

  const homeGantry = async () => {
    try {
      setStatus('Homing gantry...', { sticky: true })
      const result = await fetchJson('/gantry/home', { method: 'POST' })
      setStatus(`Home gantry: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Home failed: ${error.message}`)
    }
  }

  const moveGantry = async (distance) => {
    try {
      setStatus(`Moving gantry ${distance} mm...`, { sticky: true })
      const result = await fetchJson('/gantry/move', {
        method: 'POST',
        body: JSON.stringify({ distance_mm: distance }),
      })
      setStatus(`Move gantry ${distance} mm: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Move failed: ${error.message}`)
    }
  }

  const moveGantryToEnd = async (end) => {
    try {
      setStatus(`Moving all the way ${end}...`, { sticky: true })
      const result = await fetchJson('/gantry/end', {
        method: 'POST',
        body: JSON.stringify({ end }),
      })
      setStatus(`Move all the way ${end}: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Move failed: ${error.message}`)
    }
  }

  const moveToPlant = async (plantId) => {
    try {
      const plant = plants.find((item) => item.plant_id === plantId)
      setStatus(`Moving gantry to ${plant?.name || plantId}...`, { sticky: true })
      const result = await fetchJson(`/plants/${plantId}/move`, { method: 'POST' })
      setStatus(`Move to ${plant?.name || plantId}: ${describeResult(result)}`)
      await loadDashboard()
    } catch (error) {
      setStatus(`Move to plant failed: ${error.message}`)
    }
  }

  const waterPlant = async (plantId) => {
    try {
      const plant = plants.find((item) => item.plant_id === plantId)
      const label = plant?.name || plantId
      // The request does not return until the gantry has moved and the dose has
      // finished, which is over a minute, so say so rather than looking hung.
      setStatus(`Watering ${label}, this takes a minute...`, { sticky: true })
      const result = await fetchJson(`/water/${plantId}`, { method: 'POST' })
      setStatus(
        result?.status === 'error'
          ? `Water ${label}: failed - ${result.error}`
          : `Watered ${label} with ${result.volume_ml} mL. Its moisture probe should show it within the hour.`,
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Water failed: ${error.message}`)
    }
  }

  const loadProfile = async (plantId, name) => {
    try {
      setStatus(`Loading plant profile ${name}...`, { sticky: true })
      const result = await fetchJson(`/plants/${plantId}/profile/load`, {
        method: 'POST',
        body: JSON.stringify({ name }),
      })
      // Says what the soil profile became, because loading a plant profile
      // changes it, and what was left alone: the pot's position.
      setStatus(
        `Loaded plant profile ${result.name}: waters ${result.watering_volume_ml} mL ` +
          `at ${result.target_available}% soil water, lights ` +
          `${describeLighting(result.light_start_time, result.light_hours, result.light_brightness)}. Soil profile: ` +
          `${result.soil || 'not set'}. ` +
          (result.soil_note ? `${result.soil_note} ` : '') +
          `The pot keeps its position (${result.position_mm} mm).`,
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Load failed: ${error.message}`)
    }
  }

  const clearProfile = async (plantId) => {
    try {
      const result = await fetchJson(`/plants/${plantId}/profile/clear`, { method: 'POST' })
      setStatus(
        `Cleared the plant profile. ${result.name} keeps its position and soil.`,
      )
      await loadDashboard()
    } catch (error) {
      setStatus(`Clear failed: ${error.message}`)
    }
  }


  // Pot fields only. This used to be nine calls ending in a profile save, so
  // storing a rail coordinate also wrote a plant profile -- the two are edited
  // in separate places now, and this is the pot half.
  //
  // Answers '' when saved, or why not, so the card can keep the edit on screen
  // and say so under the field rather than only in the status bar for a moment.
  const savePot = async (plant) => {
    try {
      setStatus(`Saving ${plant.name}'s pot...`, { sticky: true })

      await fetchJson(`/plants/${plant.plant_id}/position`, {
        method: 'POST',
        body: JSON.stringify({ position_mm: Number(plant.position_mm) }),
      })

      await fetchJson(`/plants/${plant.plant_id}/soil`, {
        method: 'POST',
        body: JSON.stringify({ soil: plant.soil ?? '' }),
      })

      // The span goes before the mode, and the order is not arbitrary:
      // switching a pot to sweep is refused while its span is too narrow to be
      // one, so the span has to be in place first.
      //
      // Sent only when there is a span to send. The default is 0 to 0, which
      // is not a span, and posting it would come back refused and take the
      // rest of the save down with it.
      const low = Number(plant.sweep_min_mm)
      const high = Number(plant.sweep_max_mm)
      if (Number.isFinite(low) && Number.isFinite(high) && low !== high) {
        await fetchJson(`/plants/${plant.plant_id}/sweep`, {
          method: 'POST',
          body: JSON.stringify({ sweep_min_mm: low, sweep_max_mm: high }),
        })
      }

      await fetchJson(`/plants/${plant.plant_id}/watering-mode`, {
        method: 'POST',
        body: JSON.stringify({ watering_mode: plant.watering_mode || 'point' }),
      })

      setStatus(`Saved ${plant.name}'s pot.`)
      await loadDashboard()
      return ''
    } catch (error) {
      setStatus(`Save failed: ${error.message}`)
      return `Not saved: ${error.message}`
    }
  }

  return (
    <div className="app-shell">
      <TopBar />
      <TabBar activeTab={activeTab} onChange={setActiveTab} />
      {/* One line, and it answers "what is my planter doing". Shows feedback
          from something you just did while that is fresh, otherwise the
          planter's own computed state -- never the log, which is a record of
          what was written rather than a description of what is true. */}
      <div
        className={`status-bar ${
          action ? '' : loadProblem ? 'level-problem' : `level-${systemStatus.level}`
        }`}
      >
        {action || loadProblem || systemStatus.message}
      </div>

      {activeTab === 'plants' && (
        <>
          <PlantsPanel
            plants={plants}
            onSave={savePot}
            status={overview?.plants}
            movement={overview?.movement}
            profiles={profiles}
            onLoadProfile={loadProfile}
            onClearProfile={clearProfile}
            soils={soils}
            loaded={loaded.plants}
            onMove={moveGantry}
            onRefresh={loadDashboard}
          />
          {/* Below the cards, because both are libraries the cards pick from:
              a plant and a mix are chosen from dropdowns up there, so editing
              them belongs on the same tab rather than one away. */}
          <PlantEditorPanel
            profiles={profiles}
            soils={soils}
            loaded={loaded.profiles}
            onRefresh={loadDashboard}
          />
          <SoilPanel
            soils={soils}
            plants={plants}
            loaded={loaded.soils}
            onRefresh={loadDashboard}
          />
          <LibraryBackupPanel onRefresh={loadDashboard} />
        </>
      )}

      {activeTab === 'controls' && (
        <ControlsPanel
          plants={plants}
          gantryPosition={gantryPosition}
          overview={overview}
          onHome={homeGantry}
          onMove={moveGantry}
          onMoveToEnd={moveGantryToEnd}
          onMoveToPlant={moveToPlant}
          onWaterPlant={waterPlant}
          quiet={overview?.quiet}
          onRefresh={loadDashboard}
        />
      )}
      {activeTab === 'controls' && <PowerPanel />}

      {activeTab === 'automation' && (
        <AutomationPanel overview={overview} onRefresh={loadDashboard} />
      )}

      {/* The calibrations, then the log. All of these fetch their own data, so
          running one does not reload the rest of the dashboard -- which is why
          they can be mounted side by side here rather than nested inside one
          another as Calibration and Logs were. */}
      {activeTab === 'calibration' && (
        <>
          <ClockPanel />
          <HostnamePanel />
          <HomeSwitchPanel />
          <MotorDirectionPanel overview={overview} onRefresh={loadDashboard} />
          <PumpPanel />
          <CalibrationPanel />
          <LedStripPanel overview={overview} />
          <SystemValuesPanel />
          <VersionPanel />
          <LogsPanel />
        </>
      )}

      {/* Its own tab now. It was below the plant cards, but that tab also
          carries the soil library and the cards themselves, and the chart is
          the thing you consult afterwards rather than act on. */}
      {activeTab === 'history' && <HistoryPanel />}
      {activeTab === 'help' && <HelpPanel />}
    </div>
  )
}

export default App
