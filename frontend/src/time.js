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
