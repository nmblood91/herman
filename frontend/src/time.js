// Wall-clock strings from the planter, written the way the browser writes
// times: "8:00 AM" on a US locale, "08:00" on most others.
//
// Formatting only, and deliberately not a timezone conversion. "08:00" is the
// planter's own clock -- the lights come on when the Pi says eight -- so
// shifting it by the gap between the Pi's timezone and the browser's would
// print a time at which nothing happens. If the two disagree, the planter's
// clock is what wants fixing, on the Calibration tab.
export const formatClock = (value) => {
  const matched = /^(\d{1,2}):(\d{2})/.exec(String(value ?? '').trim())
  if (!matched) return value ?? ''

  const hour = Number(matched[1])
  const minute = Number(matched[2])
  // Anything out of range is shown as it arrived rather than wrapped into a
  // plausible time: Date would turn 25:00 into 1:00 AM, which reads as a
  // schedule somebody set rather than as a bad value.
  if (hour > 23 || minute > 59) return value

  const when = new Date()
  when.setHours(hour, minute, 0, 0)
  return when.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

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
export const describeLighting = (start, hours, brightness) => {
  const length = Number(hours)
  if (length <= 0) return 'off'
  const level = describeBrightness(brightness, 'brightness')
  const when =
    length >= 24
      ? 'on all day'
      : `on ${formatClock(start)} to ${formatClock(lightStop(start, length))} (${length} h)`
  return level ? `${when} at ${level}` : when
}
