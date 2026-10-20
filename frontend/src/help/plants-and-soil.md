## Plants and Soil

### Active plants
Each card is one pot. **Soil water** is how much of the water the plant can use
is left in the soil, read from that pot's [moisture probe](#moisture-probe):
100% at [field capacity](#field-capacity), 0% at
[permanent wilting point](#wilting-point), when the plant can't draw any more.
Beside it is the level in words, such as Dry, and the point the plant is watered
at. Tap a card to open its settings.

**Plant Profile.** The plant's own settings: when to water, how much, its light
hours and its preferred soil. Load one from the list to set them all at once.
To change a profile, use the [Plant Profile Editor](#plant-profile-editor)
below the cards.

**Lights.** The color this pot's lights show during its scheduled light hours.
Brightness and hours come from the plant profile. You can override the lights
by hand on the **Controls** tab.

**Soil Profile.** Which soil mix is in this pot. The planter needs this to make
sense of the probe's reading. If the plant prefers a different mix, the card
warns you.

**Watering.**
- **Fixed Position:** the nozzle stays in one spot while it waters.
- **Sweep Range:** the nozzle moves back and forth between a left and a right
  edge while it waters.

To set a position, move the arm over the pot with the buttons on the card, then
press **Use current position**. Each field shows the part of the rail it
accepts.

### Plant Profile Editor
Where you make or change plant profiles. A profile holds:
- **Water at:** how low the soil water gets before the plant is watered,
  anywhere from 10% for plants that like to dry out to 90% for ones that like
  to stay wet. The name beside it, such as Medium-Dry, describes that level.
- **Watering volume:** how much water each watering gives.
- **Light start, hours and brightness:** when that pot's lights come on, for how
  long, and how bright.
- **Notes:** anything you want to remember about the plant.

Changing a profile doesn't change pots that already loaded it. Load it onto the
pot again to update it.

**Tip:** profiles are saved by name, so a new name makes a new profile. Use this
to try different settings side by side, such as "Basil - Dry" and
"Basil - Wet", or to keep separate profiles for a seedling and a grown plant.

### Soil Profile Editor
Herman comes with three soil mixes, which suit nearly every plant you're likely
to grow. To change one or make your own, it helps to know how a soil profile
works. Each has four numbers describing how much water the soil holds:
- **Field capacity (sensor reading):** the probe's reading when the soil is as
  wet as it can hold. Required, and measured with the probe (see below).
- **Wilting point (sensor reading):** the probe's reading when the soil is as
  dry as a plant can manage. Optional.
- **Field capacity (% VWC)** and **Wilting point (% VWC):** the published water
  content of that mix at each point. Both are required, and you type them in. You can use AI to help you estimate from the components used.

A pot's soil water reads 100% at [field capacity](#field-capacity) and 0% at
[wilting point](#wilting-point).

The built-in mixes come with a field capacity reading already filled in. To
measure your own, water a pot of that mix until water runs out the bottom.
Leave it for 24 hours, then choose that pot's probe and press
**Measure field capacity**. Measure again after repotting, because soil holds
less water as it ages.

The wilting point reading is optional, because taking it means drying a pot out
until its plant wilts for good. If you leave it blank, Herman estimates it from
the probe's dry (open air) reading, its field capacity reading, and the two
% VWC figures.

### Back up profiles
**Download backup** saves all your plant and soil profiles to a file on your
phone or computer. **Restore from file** brings them back. Do this whenever you
create or change a profile: if Herman loses power without properly shutting down, its
memory card can be damaged and your profiles lost.

### If something looks wrong
| What you see | What to do |
|---|---|
| "No plant profile loaded" | Load one from the list on the card. |
| "No soil profile set" | Choose the mix that's in the pot. |
| The moisture reading shows a dash | The probe isn't being read. Check its cable is plugged in at both ends. |
| The moisture reading never changes | Check the probe is pushed into the soil and not touching the pot's side. |
| A position won't save | It's outside the range shown in the field's name. Move the arm over the right pot and try again. |
