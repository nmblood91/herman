# How Herman Decides to Water

This explains, in plain language, how the planter figures out that a plant is
thirsty and what it does about it. No programming knowledge needed.

## The short version

Every minute, the planter checks how wet the soil is in each pot. It doesn't act
on any single check — it looks at the average of the last ten. If that average
says a plant is drier than you asked it to be, the watering arm slides over to
that pot and runs the pump for a measured number of seconds. Then it leaves that
plant alone for an hour before it will consider watering it again, and watches
that pot's probe to make sure the water actually arrived.

That's the whole idea. The rest of this document explains why each of those
pieces is there.

## How it measures thirst

Each pot has a probe stuck in the soil. The probe doesn't measure water
directly — it measures how easily an electrical signal passes through the soil
around it, which changes depending on how wet that soil is. Wet soil and dry
soil give very different signals, and that difference is what we use.

The probe reports a plain number, a sensor reading: a few hundred in open air,
higher the wetter the soil around it. The planter reads every pot against two
readings of its soil:

- **The top: field capacity.** What the probe reads once the soil has been
  soaked and left to drain for 24 hours — as wet as it holds on its own.
  Measured once per **soil profile**.
- **The bottom: wilting point.** What the probe would read once the soil is so
  dry the plant can no longer pull water out of it. Worked out, not measured.

Field capacity belongs to the soil rather than the probe, because a different
mix holds a different amount of water. Herman ships with three soil profiles,
one for each kind of plant — see [SOIL_PROFILES.md](SOIL_PROFILES.md) for the
recipes. Each comes with a default field capacity reading, so a new planter
can water straight away. To use your own, type the reading into the **Soil
Profile Editor** or measure it there with one pot's probe. Every pot using that
soil profile reads against it.

Wilting point is worked out for each pot from its field capacity reading, its
probe's **air reading** (Calibration → Moisture probes), which counts as 0%
water, and the soil profile's **% VWC** figures. It sits the same fraction of
the way from air to field capacity as the soil's wilting point % is of its
field capacity %. Taking a real wilting point reading means drying a pot by
weight, which is slow and fiddly, and the estimate is close enough to water by.

A reading between those two ends becomes the soil's **water content**, % VWC:
the share of the pot's volume that is water. Each soil profile knows its own
figures for both ends, so the reading is placed between them. In Rich &
Retentive Mix, for example, field capacity is 50% and wilting point 17.5%, so a
pot halfway between its two readings is at about 34%.

**Each plant has a target**: water once the soil dries to this % VWC. The plant
profiles that ship with Herman give one per plant, and the planter names it in
words with this key:

| Water level | Water when soil drops to |
| --- | --- |
| Ultra Wet | over 45% |
| Very Wet | 41–45% |
| Wet | 35–40% — keep constantly damp, never dry out |
| Wet-Medium | 31–34% |
| Medium | 25–30% — top 1–2 inches dry |
| Medium-Dry | 21–24% |
| Dry | 16–20% — soil mostly dry 2–3 inches down |
| Very Dry | 11–15% |
| Ultra Dry | 10% and under — just above wilting point |

The figures are for a rich mix; coarse mixes hold less water, so a plant in a
coarse mix can show Ultra Dry at a target that is moist for that mix. The card
shows the pot's water content next to its target, along with a word for how
wet it is (very wet, wet, medium, dry, very dry).

**A target has to fit the soil.** If it is as wet as the soil can hold or
wetter, the pot can never dry to it and would be watered every half hour, so
watering is held and the card says why. If it is at or below the soil's wilting
point, the pot is watered one point above wilting point instead, and the card
says that too.

**Without a field capacity reading a pot reads nothing at all** — the card
shows "no reading" and says what is missing — and is never watered
automatically. That is deliberate. A made-up top of the scale would give a
believable percentage against a number nobody measured, and nothing downstream
could catch it.

**Which way the estimate is off.** Soil reads a little above air even bone
dry, and the probes do not respond in a perfectly straight line. Both put the
real wilting point a little *above* the estimate. So a pot reads slightly
wetter than it is, and is watered a little late rather than early. If a plant
looks thirsty before it is watered, raise its target a couple of points.

**Measuring wilting point instead.** A soil profile with a **Wilting point
(sensor reading)** uses that instead of the estimate. To take one without
wilting a plant, use a pot of the mix with no plant in it. Weigh it at field
capacity, work out how much water it holds at wilting point from the mix's
percentages and the pot's volume, and let it dry until it has lost the rest.
Then measure, with the same probe.

So automatic watering needs, per pot: a soil profile with a field capacity
reading and its two % VWC figures (all three built-in soil profiles have
them). It is best with the probes' air readings taken; without them every probe
uses `MOISTURE_RAW_DRY` from `.env`.

## Why it averages ten readings instead of trusting one

A single reading can be wrong. The probe can be briefly disturbed, electrical
noise can nudge the number, or a pocket of water can sit against the probe while
the rest of the pot is dry. Acting on one bad reading means watering a plant that
didn't need it.

So the planter keeps the last ten readings for each pot and uses their average.
Since it checks once a minute, **the average covers the last ten minutes.** A
single odd number barely moves a ten-number average, but genuine drying — which
happens over hours — moves it steadily.

It also refuses to water at all until it has collected all ten readings. That
means for the first ten minutes after the planter is switched on or restarted,
it will watch but never water. This is deliberate: right after a restart it has
no history, and no history means no way to tell a real trend from a fluke.

## What has to be true before it waters

Every minute, for each pot, the planter asks six questions in order. **All six
must be yes** or it moves on and tries again next minute.

1. **Am I allowed to make noise right now?** See quiet hours below.
2. **Did the last watering, on any pot, show up on its moisture probe?** Until it
   does, nothing else is watered. See *Checking it reached the soil* below.
3. **Do I have ten readings yet?** If it just started up, no — wait.
4. **Is the ten-minute average below the target for this plant?** Each pot has
   its own target, because a fern and a succulent don't want the same thing.
5. **Has it been at least an hour since I last watered this pot?** See below.
6. **Did the arm actually reach the pot?** If the arm can't move — it isn't
   homed, something is in the way — the planter refuses to run the pump.
   Watering the wrong spot is worse than not watering.

On that last one: until the arm homes, the board reports a position relative
to wherever the arm happened to be when the power went on, which is a
meaningless number that looks like a real one. Home it from Controls after
each start, or switch on **Home after startup** under Automation, which does it
within a minute of the planter coming up and keeps retrying until it lands.
See *Homing* below.

Only then does the pump run.

## Two ways to lay the dose down

Each pot chooses one, on its card under **Watering mode**.

**Fixed Position** is the original behaviour: the arm goes to the pot's
watering position and the whole dose goes in there.

**Sweep Range** walks the nozzle between a left edge and a right edge
for as long as the pump runs, so the same volume arrives spread across the pot
instead of into one place. This is for a wide pot, where a dose landing on one
spot runs straight down through one column of soil and out of the bottom while
the rest of the root ball stays dry. You can see that happen: the moisture
reading barely moves after watering, and the top of the pot is dry a centimetre
away from the wet patch.

Set the edges by jogging the arm to each side of the pot and pressing the
button next to each field, the same way you set a watering position. The span
needs to be at least 10 mm; anything narrower is a spot with extra steps and is
refused rather than quietly rounded.

**The dose does not change.** The pump runs for exactly as long either way —
the volume you set is the volume delivered, and the arm simply moves during it
rather than standing still. Nothing about a sweep makes a pot wetter or drier
than the same dose at one spot; it changes *where* the water lands.

### Each plant has its own stretch of rail

A watering position and both sweep edges have to sit inside the plant's zone.
The edges are kept 50 mm from the far end of it: the left edge at least 50 mm
below the zone's top, the right edge at least 50 mm above its bottom, so
neither can be set hard against the wrong side of the pot. Each card shows the
range every field accepts in its title. A new planter starts each plant watering at the middle of its zone, with a
sweep span 50 mm either side of that middle already filled in, so switching a
pot to Sweep Range works straight away. Both are starting points: set them
anywhere in the zone once the pots are placed.

| Plant | Zone | Default spot | Default sweep |
| --- | --- | --- | --- |
| Plant 1 | 0–200 mm | 100 mm | 50–150 mm |
| Plant 2 | 200–445 mm | 322 mm | 272–372 mm |
| Plant 3 | 445–690 mm | 567 mm | 517–617 mm |
| Plant 4 | 690–890 mm | 790 mm | 740–840 mm |

Positions are whole millimetres; a middle that falls on a half is rounded
down. The card shows the plant's range, and a value outside it, or one with a
decimal, is not saved. A
"Use current position" press with the arm over a different plant is refused
too, since that is nearly always the wrong card. If an older saved setting
falls outside its zone, the planter will not water at that spot (and a sweep
drops back to the spot), so set it again on the card. The zones are defined in
`greenthumb/plants.py`.

### What a sweep will not do

Four cases make a pot water at its spot instead, and the log says which:

* **The dose is too small to cross the span.** A few millilitres over 400 mm
  would mean running the pump longer to fit the motion, which would over-water
  the pot. The dose wins and the sweep is dropped.
* **The span has fallen off the rail.** If the rail is re-measured shorter than
  a saved span, the arm would be sent somewhere it cannot go and the whole
  dose would fail. Watering at the spot is better than not watering.
* **The span reaches outside the plant's zone**, from a setting saved before
  the zones existed. It would water the neighbouring pot.
* **The motion board has not said how fast it can move.** A sweep is timed
  against the board's own speed and acceleration figures, because a pass costs
  the time it spends speeding up and slowing down at each end. Guessing those
  too high would leave the pump running past the end of the motion.

In all four the plant still drinks, as long as its spot is inside its zone. A sweep decides how the water is spread,
not whether it arrives.

### Why it is one instruction and not two

Worth knowing if you are reading the logs. The pump and the arm are both driven
by the motion board, and a dose is sent to it as a single block: switch the pump
on, run the passes, switch the pump off. The passes *are* the timer.

It cannot work any other way. The original dose is timed with a wait
instruction, and a wait blocks the board's queue — so a move sent separately
during a dose would not run alongside it, it would sit behind the wait and
happen after the pump had already stopped. Sending it all as one block also
means a dropped network connection mid-dose cannot strand the pump on with the
arm parked over one spot, which is the flood worth designing against.

## Checking it reached the soil

Each pot already has a moisture probe in it, and a watering that lands in the
pot makes that probe read wetter. So after every watering the planter watches
that pot's probe for the rise.

It has to be patient. The water spreads from where it lands to where the probe
sits, and how long that takes depends on the mix and the distance. It can be a
minute, or most of an hour. So:

- **It passes as soon as the rise shows up**, which is usually within a few
  minutes.
- **It is only called a miss after a full hour** with no rise. That is the same
  hour as the cooldown, so a pot is never watered again before its last
  watering has been judged.
- **The rise has to be real.** It is measured against the readings from the ten
  minutes before the watering, and it has to reach 5% of the pot's scale
  (`SOAK_RISE_PERCENT`; field capacity minus wilting point, in sensor counts). It
  has to hold over three readings in a row, so one noisy reading can't pass a
  watering that never arrived.
- **Some waterings aren't judged.** That covers a pot with no usable scale, soil
  already close to field capacity (where there's no room left to show a rise),
  and a probe that stops reporting partway through. These are recorded as not
  checked, never as misses.

**While a watering is waiting to show up, no pot is watered automatically.**
This is what stops an empty reservoir from running the pump dry over one pot
after another before anything has noticed. Watering a pot yourself from the app
still works, and gets checked the same way.

**One miss** is a warning in the status bar naming the pot. The plant card says
so too, and the History chart marks it as a **solid amber line**.

**Two misses in a row pause automatic watering** until you press **Resume** on
the Automation tab:

- **Both on the same pot:** check the reservoir has water, then that the nozzle
  lines up with the pot and the probe is in the soil.
- **On different pots:** the reservoir is probably empty. Refill it, then
  Resume.

The pause survives a restart. A watering that does show up between two misses
resets the count. Turn the whole check off with `SOAK_CHECK_ENABLED=false`.

## Quiet hours, and the snooze

The pump and the carriage are the only loud parts of this machine, and it lives
in a room people sit in. So anything the planter does on its own — watering,
and the re-homes described under *Homing* — can be held back two ways:

- **Quiet hours** — a nightly window, set under Automation. A window that ends before
  it starts runs through midnight, so 21:00 to 08:00 means overnight.
- **Snooze** — one tap in Controls for 1, 2 or 4 hours, for when you are
  watching something and do not want the pump starting up behind you.

Two things worth knowing about both:

**Anything you ask for yourself is never blocked.** Pressing Water on a plant,
or running a routine, happens immediately, quiet hours or not. You are standing
there; you already know the noise is coming.

**A thirsty plant is deferred, not skipped.** The check runs every minute
regardless, so a pot that crosses its threshold at midnight is watered on the
first pass after the window ends rather than waiting another full day. The
Controls tab says which of the two is in force and until when, so a planter
that is deliberately not watering never looks like one that is broken.

A snooze is stored as a moment in time rather than a countdown, so it survives
a restart with the right amount left — and one that expired while the planter
was powered off is simply gone, rather than resuming for its remaining hours
at some arbitrary later date.

## Homing

The motor is open-loop: nothing tells the planter where the carriage actually
is, only where it has been told to go. A belt that slips a tooth, or a carriage
nudged while you are watering a plant by hand, leaves every saved position
quietly wrong until the next home. Two switches in the Automation tab handle
that, and **both start off**, so a planter being put together never sets off
across the rail before you are ready for it.

**Home after startup.** Homes shortly after the planter comes up. Until it
does, the board does not know where the arm is and watering is refused
outright. If the home fails, usually because Klipper is still starting up,
it tries again every minute until it lands, and the Automation tab shows the
reason. Switching it on takes effect the next time the planter starts, not
right away.

**Hourly auto-patrol.** Every hour, on the hour, the arm homes and then visits
each plant in turn, moving the way that plant is watered. A point plant gets a
short pause over its position. A sweep plant gets three passes across its span
at the speed its own dose would use, finishing at the far end before moving
on. A real dose runs as many passes as fit the pump time, so three is a
preview, not the whole thing. If a plant is set to sweep but its dose would
fall back to a point (the span is off the rail, or the dose is too short to
cross it), the patrol pauses over its point position instead, so it never shows
a motion the watering would not make. Homing is the point; the patrol shows you
where the planter now thinks each plant is.

Rules both follow:

- **Held during quiet hours and a snooze**, same as watering. The arm is the
  other noisy part. The startup home waits for the window to close; the patrol
  skips that hour and runs at the next one.
- **Never interrupts anything real.** If a watering is running at the top of
  the hour, the patrol waits up to five minutes for it to finish, then gives
  up the hour.
- **Always parks at 0**, the same place homing leaves it.
- **Routines you start yourself always run**, quiet hours or not. They have
  no effect on the hourly schedule.

## The hour's wait, and why it matters

This is the rule that keeps a plant from drowning, and it's worth understanding.

When the pump runs, the soil doesn't change instantly — water takes time to
spread from where it lands to where the probe is sitting. On top of that, the
planter is using a ten-minute average, so even once the soil *is* wetter, it
takes a full ten minutes for that to show up in the average.

Without a waiting rule, here's what would happen: the planter waters, checks
again a minute later, still sees a dry average, and waters again. And again.
Roughly ten doses would go into a pot that needed one.

So after watering a pot, that pot is off-limits for an hour
(`WATERING_COOLDOWN_MINUTES`). That's long enough for the water to spread and the
average to catch up, and it's also the time the pot's probe gets to show that
the water arrived (see *Checking it reached the soil*). The wait carries over a
restart, so rebooting the planter doesn't let every pot be watered again at once.

## One job at a time

The planter has one watering arm and one pump, and it can only be in one place
at a time. So everything that touches the hardware — reading probes, moving the
arm, running the pump — takes turns. Nothing ever happens simultaneously.

If you press a button in the app while the planter is in the middle of an
automatic watering cycle, **your request is refused rather than queued.** You'll
see a message saying the hardware is busy. This is on purpose: a button you
pressed that quietly runs four minutes later, after you've walked away and
forgotten about it, is worse than one that tells you to try again.

The same applies in reverse. If you're moving the arm by hand, the automatic
check skips that minute entirely rather than fighting you for control. It picks
up again on the next pass.

## Reading the numbers in the app

Each plant in the Plants tab shows its current reading:

| What you see | What it means |
|---|---|
| `62%` · target 45% | How wet that pot is, and the target it is being held to |
| `32%` · below target of 45% | Drier than asked for. Shown in amber — it will be watered on the next check, cooldown permitting |
| `no reading` | The probe is unplugged, broken, or not installed |
| `38%` · gathering history, 3/10 | Still filling the ten-reading window — won't water until it is full |
| "Hardware is busy" | Something else is using the arm or pump; try again shortly |

**"No reading" never means dry.** Underneath it the probe reports -1, which
means "I don't know," and the planter treats it that way — a pot reporting it is
skipped entirely rather than watered. It is deliberately not shown as 0%, which
would look like the driest possible soil and invite watering a plant whose
sensor has simply fallen out. If a probe falls out the plant doesn't get
flooded; it just stops being monitored.

Probes can also be plugged in while the planter is running. It notices a new one
within a minute and starts including it — no restart needed.

## Turning automatic watering on

**It ships turned off.** The planter will measure, record, and display
everything, but it will not run the pump on its own until someone deliberately
enables it. Everything described above is what happens *once it's on*.

Turn it on with **Water plants automatically**, the first control in the
Automation tab. The choice is saved on the planter and survives a restart, so it
only has to be made once. While it is off the status bar says *"Watching only.
Automatic watering is switched off."* — which is how you tell that state apart
from quiet hours or a snooze, both of which read as *paused* instead.

This is intentional. Automatic watering should be switched on only after the
pump has been tested by hand and the flow rate has been measured, because the
planter converts "give this plant 100 mL" into "run the pump for this many
seconds." If it thinks the pump is twice as fast as it really is, every plant
gets half as much water as intended, forever, and nothing about that looks
broken from the outside.

## Measuring the flow rate

On the **Diagnostics** tab, under Pump. Until you do this the planter is using
the pump's rated figure, which assumes no lift and no tubing, so your real rate
is almost certainly lower. The panel says so in amber until it has been
measured.

1. **Press Run calibration once and ignore what comes out.** The first run
   fills the tube, and that volume is not flow.
2. **Catch the water in something on a kitchen scale**, tared, with the nozzle
   over it. Weigh rather than reading a jug: 1 g of water is 1 mL, and a scale
   beats graduations.
3. **Press Run calibration.** It runs for 60 seconds and stops on its own — you
   do not need a stopwatch, and the button only becomes a Stop in case
   something comes loose. The planter times its own run.
4. **Weigh what came out** and type the grams into *How much came out?*, then
   Save. The planter divides by the run it just timed.
5. **Do it three times.** They should agree within a few percent.

This is the only place in the app that runs the pump directly. Watering a plant
asks for a measured volume, so it stays on the Controls tab; there is no raw
"run the pump" button there any more.

The panel then tells you how long a 100 mL dose will run for, which is the
number to sanity-check: dose 100 mL into the cup and expect about 100 g.

Two things worth knowing. The rate is measured on **your** plumbing, so redo it
if you change the tubing, the nozzle or the height of the reservoir — though a
peristaltic pump is positive-displacement, so it cares much less about lift
than you would expect, which is why one number works at all. And peristaltic
tubing takes a set as it ages, so the rate drifts; re-measure once a season.

The figure lives in `data/state.json` with the rest of your calibration, not in
`.env`. It is a property of your pump and tubing, not configuration, so it is
set where it is measured and comes back after a reflash with everything else.

## If something goes wrong

The design assumes things will fail and tries to fail toward *not watering*
rather than toward flooding:

- **A probe stops responding.** That pot reports -1 and is skipped. The planter
  also quietly retries it every minute, so a loose connector that reseats itself
  recovers on its own.
- **The arm can't move.** The pump doesn't run. No water goes anywhere.
- **The reservoir runs dry.** The pour still runs, briefly and harmlessly, but
  the pot's moisture probe never shows the water arriving. Within the hour you
  get a warning and an amber mark on the chart, not a false record of a healthy
  watering. Nothing else is watered while that one is unconfirmed, and a second
  miss pauses automatic watering until you refill and press Resume. A probe
  that stops answering is recorded as *unknown* rather than as a miss, because
  "we couldn't tell" is not the same as "no water arrived".
- **The connection to the motion board drops mid-pour.** The pump is commanded
  off regardless, and the board is configured to shut the pump off by itself if
  it loses contact with the software. Two independent stops, because a pump stuck
  running is the one failure here that empties a reservoir onto your floor.
- **The automatic check itself hits an error.** It's logged, that minute is
  skipped, and checking continues. One bad minute never stops the planter for
  good.

The failure this design does *not* protect against is a wrong flow rate, because
nothing about it looks like an error — the planter reports success every time
while quietly delivering the wrong amount. The soak check confirms that water
arrived, not how much of it. That's why measuring it matters more than it
sounds like it should, and why the planter refuses a measurement that could not
be a real one rather than storing it: a run too short to weigh accurately, or a
volume that works out to a rate no pump of this kind could manage.
