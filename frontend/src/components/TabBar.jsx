export function TabBar({ activeTab, onChange }) {
  const tabs = [
    { key: 'controls', label: 'Controls' },
    { key: 'plants', label: 'Plants' },
    { key: 'sensors', label: 'Sensors' },
    { key: 'camera', label: 'Camera' },
    { key: 'settings', label: 'Settings' },
  ]

  return (
    <nav className="tab-bar">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          className={activeTab === tab.key ? 'tab active' : 'tab'}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
