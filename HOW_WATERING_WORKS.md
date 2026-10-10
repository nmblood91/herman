# How Herman Decides to Water

This explains, in plain language, how the planter figures out that a plant is
thirsty and what it does about it. No programming knowledge needed.

## The short version

Every minute, the planter checks how wet the soil is in each pot. It doesn't act
on any single check — it looks at the average of the last ten. If that average
says a plant is drier than you asked it to be, the watering arm slides over to
that pot and runs the pump for a measured number of seconds. Then it leaves that
plant alone for half an hour before it will consider watering it again.

That's the whole idea. The rest of this document explains why each of those
pieces is there.

## How it measures thirst

Each pot has a probe stuck in the soil. The probe doesn't measure water
directly — it measures how easily an electrical signal passes through the soil
around it, which changes depending on how wet that soil is. Wet soil and dry
soil give very different signals, and that difference is what we use.

The probe reports a plain number — a few hundred in open air, a few hundred
more sitting in water. Those two ends are the scale: the planter converts every
reading onto 0–100% between them, so when the app shows "43% moisture," that's
where the raw number falls between bone dry and underwater.

**Each probe gets its own two ends, and you measure them.** Probes differ from
each other by enough to matter — the four on this build read about 25 counts
apart in identical conditions — so one shared scale would bake that difference
into every percentage. Calibration is two passes, one with the sensors in open
air and one with them in water, and it stores a dry and wet point per sensor.
Run it from the Sensors tab, or see SENSOR_WIRING.md for the procedure and the
warning about not submerging the boards.

Until a sensor is calibrated it falls back to a rough built-in pair, which is
good enough to show a number but not good enough to water on.

One thing worth knowing: **soil never reaches 100%.** Plain water conducts better
than even soaking wet dirt, so a freshly watered pot might read 80%. That's
normal and it's the safe direction to be wrong in — the planter will never
mistake damp soil for wet enough.

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

Every minute, for each pot, the planter asks five questions in order. **All five
must be yes** or it moves on and tries again next minute.

1. **Am I allowed to make noise right now?** See quiet hours below.
2. **Do I have ten readings yet?** If it just started up, no — wait.
3. **Is the ten-minute average below the target for this plant?** Each pot has
   its own target, because a fern and a succulent don't want the same thing.
4. **Has it been at least 30 minutes since I last watered this pot?** See below.
5. **Did the arm actually reach the pot?** If the arm can't move — it isn't
   calibrated, something is in the way — the planter refuses to run the pump.
   Watering the wrong spot is worse than not watering.

Only then does the pump run.

## Two ways to lay the dose down

Each pot chooses one, on its card under **How to water**.

**One spot** is the original behaviour: the arm goes to the pot's watering
location and the whole dose goes in there.

**Sweep back and forth** walks the nozzle between a left edge and a right edge
for as long as the pump runs, so the same volume arrives spread across the pot
instead of into one place. This is for a wide pot, where a dose landing on one
spot runs straight down through one column of soil and out of the bottom while
the rest of the root ball stays dry. You can see that happen: the moisture
reading barely moves after watering, and the top of the pot is dry a centimetre
away from the wet patch.

Set the edges by jogging the arm to each side of the pot and pressing the
button next to each field, the same way you set a watering location. The span
needs to be at least 10 mm; anything narrower is a spot with extra steps and is
refused rather than quietly rounded.

**The dose does not change.** The pump runs for exactly as long either way —
the volume you set is the volume delivered, and the arm simply moves during it
rather than standing still. Nothing about a sweep makes a pot wetter or drier
than the same dose at one spot; it changes *where* the water lands.

### What a sweep will not do

Three cases make a pot water at its spot instead, and the log says which:

* **The dose is too small to cross the span.** A few millilitres over 400 mm
  would mean running the pump longer to fit the motion, which would over-water
  the pot. The dose wins and the sweep is dropped.
* **The span has fallen off the rail.** If the rail is re-measured shorter than
  a saved span, the arm would be sent somewhere it cannot go and the whole
  dose would fail. Watering at the spot is better than not watering.
* **The motion board has not said how fast it can move.** A sweep is timed
  against the board's own speed and acceleration figures, because a pass costs
  the time it spends speeding up and slowing down at each end. Guessing those
  too high would leave the pump running past the end of the motion.

In all three the plant still drinks. A sweep decides how the water is spread,
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

## Checking that the water actually arrived

There is a sensor clipped to the tube that feeds the nozzle. It does not decide
whether to water — it checks, a few seconds into each pour, that water is really
moving through the tube.

It works this way round for a simple reason: that tube empties itself into the
pot after every pour, so between waterings it is *supposed* to be dry. A planter
that refused to water whenever the tube was dry would never water at all.

So instead it pours first and watches. Running the pump dry for a few seconds
does it no harm, and watching the tube fill answers a better question than
"is there water in the tank" — it answers "did water reach the plant", which
also catches a blocked tube, a kinked hose, or a pump that has failed while
still turning.

This is what stops a specific kind of lie. Without it, an empty reservoir looks
exactly like a successful watering: the pump runs, nothing comes out, and the
planter records that your plant was watered. Everything else here fails loudly;
that one failed silently.

When a pour delivers nothing, the planter says so in the status bar, writes a
warning to the log, and marks it on the history chart in the Sensors tab as a
**solid red line** instead of the usual dashed one.

The status bar escalates if it keeps happening. One failed pour reads as "the
last watering did not reach the plant" — that could be a kink or a clog on one
line. **Two or more in a row says the reservoir is probably empty**, because a
run of them across different plants points at the one thing they share. The
count survives a restart, so a planter rebooted with an empty tank comes back
still saying so rather than looking fine until the next dose fails.

Nothing gets blocked — the next pour tries again — so refilling the tank
quietly fixes it with nothing to reset, and the first dose that lands clears
the warning.

## Quiet hours, and the snooze

The pump and the carriage are the only loud parts of this machine, and it lives
in a room people sit in. So anything the planter does on its own — watering,
and the periodic re-home described under *Idle motion* — can be held back two
ways:

- **Quiet hours** — a nightly window, set in Settings. A window that ends before
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

## Idle motion

Every hour by default, the planter homes the arm and runs a short routine —
*Stretch*, *Wave*, *Shuffle* or *Patrol*, cycling through them. Both halves of
that are switchable in Settings.

**The re-home is the part that earns it.** The motor is open-loop: nothing
tells the planter where the carriage actually is, only where it has been told
to go. A belt that slips a tooth, or a carriage nudged while you are watering
a plant by hand, leaves every saved position quietly wrong — and it stays
wrong until the next home, which otherwise might be the next reboot. Hourly
caps that at an hour.

The routine on the end is there because a machine that only moves to water
looks broken the rest of the time, and because it makes the re-home visible
rather than something that happens behind you.

Rules it follows:

- **Held during quiet hours and a snooze**, same as watering. The arm is the
  other noisy part, and unlike watering, a routine has nowhere urgent to be.
- **Never delays anything real.** It takes the hardware only if nothing else
  wants it, and gives up rather than queueing if a watering cycle or a manual
  pump run is in progress.
- **Always parks at 0**, the same place homing leaves it.
- **Routines you start yourself always run**, quiet hours or not, and reset
  the clock so an automatic one does not follow a minute later.

Patrol is the odd one out: instead of a fixed pattern it visits each plant's
saved position in turn, pausing at every pot. It is worth watching after
changing a position, since it shows you where the planter thinks each plant
is.

## The half-hour wait, and why it matters

This is the rule that keeps a plant from drowning, and it's worth understanding.

When the pump runs, the soil doesn't change instantly — water takes time to
spread from where it lands to where the probe is sitting. On top of that, the
planter is using a ten-minute average, so even once the soil *is* wetter, it
takes a full ten minutes for that to show up in the average.

Without a waiting rule, here's what would happen: the planter waters, checks
again a minute later, still sees a dry average, and waters again. And again.
Roughly ten doses would go into a pot that needed one.

So after watering a pot, that pot is off-limits for 30 minutes. Long enough for
the water to spread and for the average to catch up to reality.

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
- **The reservoir runs dry.** The pour still runs — briefly and harmlessly — and
  the sensor on the nozzle tube notices that nothing came through. You get a
  warning and a red mark on the chart rather than a false record of a healthy
  watering. Refilling fixes it with nothing to reset; the next pour re-checks.
  A sensor that stops answering is recorded as *unknown* rather than as a
  failure, because "we couldn't tell" is not the same as "no water arrived".
- **The connection to the motion board drops mid-pour.** The pump is commanded
  off regardless, and the board is configured to shut the pump off by itself if
  it loses contact with the software. Two independent stops, because a pump stuck
  running is the one failure here that empties a reservoir onto your floor.
- **The automatic check itself hits an error.** It's logged, that minute is
  skipped, and checking continues. One bad minute never stops the planter for
  good.

The failure this design does *not* protect against is a wrong flow rate, because
nothing about it looks like an error — the planter reports success every time
while quietly delivering the wrong amount. The outlet sensor confirms that
water arrived, not how much of it. That's why measuring it matters more than it
sounds like it should, and why the planter refuses a measurement that could not
be a real one rather than storing it: a run too short to weigh accurately, or a
volume that works out to a rate no pump of this kind could manage.
