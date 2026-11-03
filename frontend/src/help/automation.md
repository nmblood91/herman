## Automation

### Water plants automatically
When this is on, the planter runs the [hourly patrol](#hourly-patrol) and
waters each pot whose soil water has dropped to the level set in that pot's
[plant profile](#plant-profile). The soil is read every minute. A pot watered
on one patrol can be watered again on the next hour's patrol, once its
watering has had time to soak in.

When it's off, nothing moves on the hour. The planter still reads the soil and
records the history, and you can still water a plant yourself on the
**Controls** tab.

Measure the pump's flow rate on the Calibration tab before turning this on. The
planter uses that number to work out how long to run the pump. If it's wrong,
every watering is too much or too little.

### Checking each watering
After each watering, the planter watches that pot's
[moisture probe](#moisture-probe) for up to an hour to confirm the water reached
the soil. Until it does, the next patrol still visits every pot but waters
none. So if the [reservoir](#reservoir) runs dry, the pump can't keep running
dry hour after hour.

If a watering doesn't show up, you'll see a warning. Two in a row pause
automatic watering until you press **Resume watering**. Watering by hand still
works while it's paused.

### Hourly patrol
Every hour, on the hour, the arm [homes](#homing), then makes one trip along
the rail. It waters each pot that needs it, and pauses briefly over the
others. Homing every hour also puts the arm back in the right place if it was
bumped or a belt slipped.

Afterwards the arm parks and its motor switches off. **Motor idle** is normal:
it saves power and keeps the motor cool, and the arm homes again before it
next moves.

### Home after startup
[Homing](#homing) means the arm moves to the end of the rail to establish
position. With this on, it homes on its own a minute or two after being
switched on, and keeps trying until it succeeds. Automatic watering needs it,
so the switch stays on while automatic watering is on.

### Quiet hours
The pump and the gantry are the noisy parts, so the hourly patrol is skipped
during quiet hours. A pot that needs water during quiet hours is watered on
the first patrol after they end. Watering you start yourself is never blocked.

Quiet hours can run past midnight, for example 10:00 PM to 7:00 AM.

### If something looks wrong
| What you see | What to do |
|---|---|
| Automatic watering is paused, and the same pot is named twice | Check the reservoir has water. Then check the nozzle is over that pot and its probe is pushed into the soil. Press **Resume watering**. |
| Paused, and two different pots are named | The reservoir is probably empty. Refill it and press **Resume watering**. |
| "Waiting to confirm the last watering reached…" | Nothing is wrong. The planter is checking the last watering, which can take up to an hour. |
| Motor idle | Nothing is wrong. The arm homes again before its next move. |
| A pot never gets watered | Check that the pot has a plant profile and a soil profile, and that its probe shows a reading on the Plants and Soil tab. |
| Nothing happens at night | Quiet hours are on. That's expected. |
| Home after startup keeps retrying | The arm can't reach the end of the rail. Check nothing is blocking it, then try the home switch test on the Calibration tab. |
