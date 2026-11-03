import { createContext, useContext } from 'react'

// Whether times of day are written "14:00" rather than "2:00 PM". A planter
// setting, on the Calibration tab's System Time panel, rather than the
// browser's locale: the planter writes times into the status bar and the log
// too, and those should read the same as the rest of the page. App provides it
// from the overview.
export const Clock24hContext = createContext(false)
export const useClock24h = () => useContext(Clock24hContext)

// Wall-clock strings from the planter: "08:00" -> "8:00 AM", or "08:00" with
// the 24-hour clock.
//
// Formatting only, and deliberately not a timezone conversion. "08:00" is the
// planter's own clock -- the lights come on when the Pi says eight -- so
// shifting it by the gap between the Pi's timezone and the browser's would
// print a time at which nothing happens. If the two disagree, the planter's
// clock is what wants fixing, on the Calibration tab.
export const formatClock = (value, hour24 = false) => {
  const matched = /^(\d{1,2}):(\d{2})/.exec(String(value ?? '').trim())
  if (!matched) return value ?? ''

  const hour = Number(matched[1])
  const minute = Number(matched[2])
  // Anything out of range is shown as it arrived rather than wrapped into a
  // plausible time: 25:00 turned into 1:00 AM reads as a schedule somebody
  // set rather than as a bad value.
  if (hour > 23 || minute > 59) return value

  const mm = String(minute).padStart(2, '0')
  if (hour24) return `${String(hour).padStart(2, '0')}:${mm}`
  return `${hour % 12 || 12}:${mm} ${hour < 12 ? 'AM' : 'PM'}`
}

// The time of day in one of the planter's timestamps ("2026-10-14T14:00" ->
// "2:00 PM"). The date is left out: these are always today-ish.
export const formatTimeOf = (iso, hour24 = false) => (iso ? formatClock(iso.slice(11, 16), hour24) : '')

// A full date and time in the browser's way of writing dates, but with the
// planter's clock setting.
export const formatDateTime = (value, hour24 = false, options = {}) =>
  new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    hourCycle: hour24 ? 'h23' : 'h12',
    ...options,
  })

// When the lights go off: "HH:MM" start plus whole hours, wrapping past
// midnight. Mirrors greenthumb.care.light_stop, and only for showing -- the
// planter works it out for itself. '' when either input is unusable.
export const lightStop = (start, hours) => {
  const matched = /^(\d{1,2}):(\d{2})/.exec(String(start ?? '').trim())
  const length = Number(hours)
  if (!matched || String(hours ?? '').trim() === '' || !Number.isInteger(length)) return ''
  const total = (Number(matched[1]) * 60 + Number(matched[2]) + length * 60) % (24 * 60)
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}

// Mirrors greenthumb.care.LIGHT_LEVELS.
export const LIGHT_LEVELS = [
  ['Low', 25],
  ['Medium', 50],
  ['High', 75],
  ['Intense', 100],
]

// "75% (High)": the nearest named level, for describing a brightness.
// "75% (High)", or "75% brightness (High)" with the noun, for a sentence
// where a bare percentage would not say what it is a percentage of.
export const describeBrightness = (brightness, noun = '') => {
  const value = Number(brightness)
  if (!Number.isFinite(value)) return ''
  const [name] = LIGHT_LEVELS.reduce((best, level) =>
    Math.abs(level[1] - value) < Math.abs(best[1] - value) ? level : best,
  )
  return `${value}%${noun ? ` ${noun}` : ''} (${name})`
}

// The words after "Lights": "on 7:00 AM to 6:00 PM (11 h) at 75% brightness
// (High)", "on all day at ...", or just "off", which has no brightness to give.
export const describeLighting = (start, hours, brightness, hour24 = false) => {
  const length = Number(hours)
  if (length <= 0) return 'off'
  const level = describeBrightness(brightness, 'brightness')
  const when =
    length >= 24
      ? 'on all day'
      : `on ${formatClock(start, hour24)} to ${formatClock(lightStop(start, length), hour24)} (${length} h)`
  return level ? `${when} at ${level}` : when
}
