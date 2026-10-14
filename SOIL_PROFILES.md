# Soil Profiles

Herman ships with three soil profiles. Between them they cover every plant
the planter is meant for, and each is a soilless mix you can make from
hardware-store ingredients. Pick the one that matches your plant, mix it,
pot up, and choose that soil profile on the pot's card.

| Soil profile | For | Dries out indoors |
| --- | --- | --- |
| [Rich & Retentive Mix](#recipe-1-rich--retentive-mix) | Vegetables, leafy greens, herbs, thirsty houseplants | 5–10 days |
| [Fast-Draining Mix](#recipe-2-fast-draining-mix) | Cacti, succulents, drought-tolerant houseplants, woody herbs | 3–5 days |
| [Ultra-Coarse Epiphytic Mix](#recipe-3-ultra-coarse-epiphytic-mix) | Orchids, aroids, jungle cacti and other epiphytes | 1–3 days |

"Parts" are by volume — use the same scoop or container for every part. Mix
everything dry, then moisten it before potting.

---

## Recipe 1: Rich & Retentive Mix

**For vegetables and tropicals.** Fine organic matter (peat or coir) and
vermiculite create strong capillary suction, so the mix holds on to water and
nutrients and fast-growing plants never dry out.

| Ingredient | Parts |
| --- | --- |
| Potting mix | 2 |
| Peat or coir | 1 |
| Perlite | 1 |
| Vermiculite | 1 |

| Property | Value |
| --- | --- |
| Field capacity | 45–55% VWC — holds about half its volume in water after draining |
| Permanent wilting point | 15–20% VWC — the fine pores keep this much locked away from the roots |
| Plant-available water | about 30% VWC |
| Air space after draining | low to moderate, about 15–20% |
| Root type it suits | fine, fibrous, water-hungry roots |

**Best plants:**

- **Indoor vegetables:** tomatoes, peppers, bush beans, strawberries, cucumbers
- **Leafy greens and herbs:** lettuce, spinach, kale, basil, parsley, mint, cilantro
- **Thirsty houseplants:** ferns, calatheas, peace lilies, begonias, fittonia

---

## Recipe 2: Fast-Draining Mix

**For desert plants and succulents.** A high share of coarse, inert material
(perlite and sand) makes large pores that let water drain almost at once,
protecting dryland plants from root rot.

| Ingredient | Parts |
| --- | --- |
| Potting mix | 2 |
| Perlite | 2 |
| Coarse sand (or fine orchid bark) | 1 |

| Property | Value |
| --- | --- |
| Field capacity | 20–30% VWC — sheds 70–80% of what is poured in almost immediately |
| Permanent wilting point | 6–10% VWC — little organic matter, so nearly all the water is reachable |
| Plant-available water | about 15% VWC |
| Air space after draining | high, about 25–35% |
| Root type it suits | succulent, water-storing tap roots |

**Best plants:**

- **Desert cacti and succulents:** echeveria, aloe vera, jade, haworthia, cactus varieties
- **Drought-tolerant houseplants:** snake plants (sansevieria), ZZ plants, ponytail palms
- **Woody herbs:** rosemary, thyme, lavender, oregano

---

## Recipe 3: Ultra-Coarse Epiphytic Mix

**For orchids and jungle epiphytes.** Epiphytes grow attached to tree bark in
the rain forest. This mix works like a porous wooden scaffold with as much air
as possible, so thick, fleshy roots never sit in standing water or fine sludge.

| Ingredient | Parts |
| --- | --- |
| Coarse bark | 3 |
| Chunk coir or peat | 1 |
| Coarse perlite (or pumice) | 1 |

| Property | Value |
| --- | --- |
| Field capacity | 12–18% VWC — water is held only inside the bark and the coir fibres |
| Permanent wilting point | 3–5% VWC — almost no capillary hold; once the bark surface dries, it is near zero |
| Plant-available water | about 10% VWC |
| Air space after draining | extreme, about 45–55% |
| Root type it suits | thick, fleshy aerial roots |

**Best plants:**

- **Orchids:** phalaenopsis, cattleya, dendrobium, oncidium
- **Epiphytic tropicals:** anthuriums, monsteras, philodendrons, syngoniums, pothos
- **Jungle cacti and epiphytes:** Christmas and Thanksgiving cactus, hoyas, staghorn ferns, tillandsia (air plants)

---

## Side by side

| | Rich & Retentive | Fast-Draining | Ultra-Coarse Epiphytic |
| --- | --- | --- | --- |
| **Field capacity** | 45–55% VWC | 20–30% VWC | 12–18% VWC |
| **Permanent wilting point** | 15–20% VWC | 6–10% VWC | 3–5% VWC |
| **Plant-available water** | ~30% VWC | ~15% VWC | ~10% VWC |
| **Air space after draining** | low–moderate (~15–20%) | high (~25–35%) | extreme (~45–55%) |
| **Drying cycle indoors** | 5–10 days | 3–5 days | 1–3 days |
| **Root type** | fine, fibrous, water-hungry | succulent, water-storing tap roots | thick, fleshy aerial roots |

### Which plant profiles use which

Every one of the 70 plant profiles that ship names its preferred soil profile,
and loading it onto a pot switches the pot to that soil profile:

| Soil profile | Plant profiles |
| --- | --- |
| Rich & Retentive Mix | 45 — the vegetables, the leafy greens and soft herbs, and most foliage houseplants |
| Fast-Draining Mix | 15 — rosemary, thyme, oregano, sage, snake and ZZ plants, and the desert succulents and cacti |
| Ultra-Coarse Epiphytic Mix | 10 — Monstera adansonii, the orchids, anthuriums, hoyas, Christmas cactus and staghorn fern |

Each plant also has a target soil moisture in % VWC. A few targets fall
outside their soil's range; the plant card flags those (see README, *Watering
targets*).

---

## Setting a soil profile up for automatic watering

A moisture probe does not read water content directly. Its reading depends on
the exact mix, how firmly it was packed and the probe itself. So each soil
profile carries one **sensor reading**, its field capacity: what a probe reads
in that mix once it has been soaked and left to drain for 24 hours.

**Each of the three soil profiles ships with a default field capacity
reading**, measured on the reference build with the recipe mixed as written. So
the only setup step is the probes' **air readings**: with all four probes
clean, dry and in open air, press **Calibrate dry (air)** on the Calibration
tab. That is each probe's 0% water reading.

**Measuring your own field capacity** is worth doing if a mix seems to water
too early or too late, since every batch, and every brand of potting mix,
comes out a little different. Water a pot of the mix until it runs out of the
bottom, leave it to drain for 24 hours, then press **Measure field capacity**
in the Soil Profile Editor with that pot's probe selected. It replaces the
default for every pot using that soil profile. The reading can also be typed in
if you already know it, for example after reinstalling.

**Wilting point is worked out, not measured.** The planter takes each probe's
air reading as 0% water and its field capacity reading as the mix's field
capacity %, and places wilting point the same fraction of the way up as the
mix's wilting point % is of its field capacity %. For Rich & Retentive Mix that
is 17.5 ÷ 50, about a third of the way: a probe reading 320 in air and 800 at
field capacity puts wilting point at about 488. Each pot works this out from
its own probe's air reading.

Every pot using the soil profile then reads 100% at field capacity and 0% at
wilting point, and is watered when it dries past its plant's target.

The probe does not respond in a perfectly straight line, so the wilting point
is an estimate. It only has to be close enough to sort a pot into the right
dryness band. If you have measured wilting point properly, type it into
**Wilting point (sensor reading)** in the Soil Profile Editor, or press
**Measure wilting point**, and the soil profile uses that instead. To measure
it without wilting a plant, weigh a pot of the mix with no plant at field
capacity. Let it dry until it has lost about *soil volume in mL ×
(field capacity % − wilting point %) ÷ 100* grams (1 litre of Rich & Retentive
Mix loses about 325 g), then take the reading.

**If you measured your own, re-measure after repotting.** Mixes compact and
break down as they age and hold less water than when fresh, and every batch you
mix comes out a little different.
