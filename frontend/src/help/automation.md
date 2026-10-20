## Automation

### Water plants automatically
When this is on, the planter waters each pot whenever its soil water drops to
the level set in that pot's [plant profile](#plant-profile). The soil is read
every minute. After watering a pot, the planter waits an hour before that pot
can be watered again.

When it's off, the planter still reads the soil and records the history. You can
still trigger watering a plant manually on the **Controls** tab.

Measure the pump's flow rate on the Calibration tab before turning this on. The
planter uses that number to work out how long to run the pump. If it's wrong,
every watering is too much or too little.

### Checking each watering
After each watering, the planter watches that pot's
[moisture probe](#moisture-probe) for up to an hour to confirm the water reached
the soil. No other pot is watered until it does. So if the
[reservoir](#reservoir) runs dry, the pump can't run dry trying one pot after
another.

If a watering doesn't show up, you'll see a warning. Two in a row pause
automatic watering until you press **Resume watering**. Watering by hand still
works while it's paused.

### Home after startup
[Homing](#homing) means the arm moves to the end of the rail to establish
position. The planter can't water until it has homed. With this on,
it homes on its own a minute or two after being switched on, and keeps trying
until it succeeds.

### Hourly auto-patrol
Once an hour, the gantry homes and then visits each pot in turn. If the arm was
bumped or a belt slipped, this puts it back in the right place. It's also an
easy way to check that each pot's watering position is right.

### Quiet hours
The pump and the gantry are the noisy parts, so during quiet hours automatic
watering waits and the hourly patrol is skipped. A pot that needs water during
quiet hours is watered as soon as they end. Watering you start yourself is never
blocked.

Quiet hours can run past midnight, for example 10:00 PM to 7:00 AM.

### If something looks wrong
| What you see | What to do |
|---|---|
| Automatic watering is paused, and the same pot is named twice | Check the reservoir has water. Then check the nozzle is over that pot and its probe is pushed into the soil. Press **Resume watering**. |
| Paused, and two different pots are named | The reservoir is probably empty. Refill it and press **Resume watering**. |
| "Waiting to confirm the last watering reached…" | Nothing is wrong. The planter is checking the last watering, which can take up to an hour. |
| A pot never gets watered | Check that the pot has a plant profile and a soil profile, and that its probe shows a reading on the Plants and Soil tab. |
| Nothing happens at night | Quiet hours are on. That's expected. |
| Home after startup keeps retrying | The arm can't reach the end of the rail. Check nothing is blocking it, then try the home switch test on the Calibration tab. |
