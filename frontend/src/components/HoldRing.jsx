const RADIUS = 8
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// The sweep for a press-and-hold button, from useHoldToConfirm's progress.
// A dashed stroke the circle's own circumference long, revealed by
// stroke-dashoffset like a clock hand sweeping back -- cheaper than canvas or
// an animation library for a ring that only ever needs to close.
function HoldRing({ progress }) {
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

// A hold button's contents: `idle` until a hold starts, then the ring and
// `busy`. Both are always laid out in the same grid cell, one of them hidden,
// so the button is as wide as the wider of the two the whole time. Swapping
// them shrank the button under a finger mid-hold, and the pointer leaving it
// canceled the hold.
export function HoldLabel({ progress, idle, busy }) {
  const holding = progress > 0
  return (
    <span className="hold-label">
      <span className={holding ? 'hold-label-off' : undefined}>{idle}</span>
      <span className={holding ? undefined : 'hold-label-off'}>
        <HoldRing progress={progress} />
        {busy}
      </span>
    </span>
  )
}
