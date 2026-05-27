import { useEffect, useState } from 'react'
import { getConfig } from './api'
import { Setup } from './Setup'
import { CookView } from './CookView'
import { KitchenManager } from './KitchenManager'
import './App.css'

type View = 'setup' | 'kitchens'

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [view, setView] = useState<View>('setup')
  const [kitchensVersion, setKitchensVersion] = useState(0)
  const [backend, setBackend] = useState<string>('notion')

  useEffect(() => {
    getConfig()
      .then((c) => setBackend(c.backend))
      .catch(() => { /* fall back to 'notion' default */ })
  }, [])

  if (sessionId) {
    return <CookView sessionId={sessionId} onExit={() => setSessionId(null)} />
  }
  if (view === 'kitchens') {
    return (
      <KitchenManager
        onClose={() => {
          setKitchensVersion((v) => v + 1)
          setView('setup')
        }}
      />
    )
  }
  return (
    <Setup
      onCreated={setSessionId}
      onManageKitchens={() => setView('kitchens')}
      kitchensVersion={kitchensVersion}
      backend={backend}
    />
  )
}
