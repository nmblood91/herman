// "Pot 2: Basil" rather than "Basil". Everything physical about a card is per
// pot -- the probe address, the LED range, the rail coordinate -- so the header
// has to say which pot before it says what is growing in it, or there is
// nothing tying the card to the planter in front of you.
//
// Pot rather than Plant for the half that does not move: the card is already
// split into "Plant Info" and "Pot Info", and a header that said "Plant 2"
// would be naming the pot with the word the card uses for its contents.
//
// The number comes from plant_id rather than the array index. Identical today,
// but the id is the identity the API and the state file key on, so a reordered
// list cannot relabel a pot.
//
// Its own file because both the plant cards and the soil panel's probe picker
// use it, and a component file that also exports a function cannot hot-reload.
export const cardTitle = (plant) => {
  const matched = /(\d+)$/.exec(plant.plant_id ?? '')
  const number = matched?.[1]
  const pot = number ? `Pot ${number}` : plant.plant_id || 'Pot'
  const name = (plant.name ?? '').trim()
  // plants.default_plants names them "Plant 1".."Plant 4", so on a fresh
  // planter every name is a placeholder. Both spellings of the placeholder
  // count as unnamed: "Pot 1: Plant 1" says the same thing twice in two
  // vocabularies.
  const unnamed = !name || (number && (name === `Pot ${number}` || name === `Plant ${number}`))
  return unnamed ? pot : `${pot}: ${name}`
}
