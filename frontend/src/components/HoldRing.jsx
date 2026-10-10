const RADIUS = 8
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// The sweep for a press-and-hold button, from useHoldToConfirm's progress.
// A dashed stroke the circle's own circumference long, revealed by
// stroke-dashoffset like a clock hand sweeping back -- cheaper than canvas or
// an animation library for a ring that only ever needs to close.
//
// Renders nothing at progress 0, so a caller can mount it unconditionally
// and the button looks like any other button until a hold actually starts.
export function HoldRing({ progress }) {
  if (!progress) return null
  return (
    <svg className="hold-ring" viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r={RADIUS} className="hold-ring-track" />
      <circle
        cx="10"
        cy="10"
        r={RADIUS}
        className="hold-ring-fill"
        style={{
          strokeDasharray: CIRCUMFERENCE,
          strokeDashoffset: CIRCUMFERENCE * (1 - progress),
        }}
      />
    </svg>
  )
}
