// Plant profiles grouped by category for a dropdown, in the order each
// category first appears; profiles with none go last under "Other". Each group
// is sorted by name.
export const groupByCategory = (profiles) => {
  const groups = new Map()
  for (const profile of profiles ?? []) {
    const category = profile.category || 'Other'
    if (!groups.has(category)) groups.set(category, [])
    groups.get(category).push(profile)
  }
  if (groups.has('Other')) {
    const other = groups.get('Other')
    groups.delete('Other')
    groups.set('Other', other)
  }
  return [...groups].map(([category, members]) => [
    category,
    [...members].sort((a, b) => a.name.localeCompare(b.name)),
  ])
}
