import type { RecipeOut, Schedule, Session } from './types'

// Default to /api so the browser dev proxy (and same-origin production) keep
// working unchanged. For the Capacitor/Android build, set
// VITE_API_BASE_URL=http://<laptop-lan-ip>:8000 in web/.env.local so the
// phone hits the FastAPI backend on your laptop directly.
const base = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || `HTTP ${r.status}`)
  }
  return r.json() as Promise<T>
}

export async function listRecipes(): Promise<RecipeOut[]> {
  return json(await fetch(`${base}/recipes`))
}

export async function listKitchens(): Promise<{ name: string }[]> {
  return json(await fetch(`${base}/kitchens`))
}

export interface KitchenDetail {
  name: string
  inventory: Record<string, number>
  substitutions_yaml: string
}

export async function getKitchen(name: string): Promise<KitchenDetail> {
  return json(await fetch(`${base}/kitchens/${encodeURIComponent(name)}`))
}

export async function createKitchen(body: KitchenDetail): Promise<KitchenDetail> {
  return json(
    await fetch(`${base}/kitchens`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function updateKitchen(
  name: string,
  body: Omit<KitchenDetail, 'name'>,
): Promise<KitchenDetail> {
  return json(
    await fetch(`${base}/kitchens/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function deleteKitchen(name: string): Promise<{ deleted: string }> {
  return json(
    await fetch(`${base}/kitchens/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  )
}

export async function createSession(body: {
  recipe_ids: string[]
  kitchen: string
  num_cooks: number
}): Promise<{ session_id: string; schedule: Schedule }> {
  return json(
    await fetch(`${base}/sessions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function getSession(id: string): Promise<Session> {
  return json(await fetch(`${base}/sessions/${id}`))
}

export async function startStep(sessionId: string, stepId: string): Promise<{ started_at: string }> {
  return json(
    await fetch(`${base}/sessions/${sessionId}/steps/${encodeURIComponent(stepId)}/start`, {
      method: 'POST',
    }),
  )
}

export async function enrichRecipe(id: string): Promise<{ title: string; step_count: number }> {
  return json(
    await fetch(`${base}/recipes/${id}/enrich`, { method: 'POST' }),
  )
}

export async function doneStep(
  sessionId: string,
  stepId: string,
  actualSeconds?: number,
): Promise<{ completed_at: string; actual_seconds: number | null }> {
  return json(
    await fetch(`${base}/sessions/${sessionId}/steps/${encodeURIComponent(stepId)}/done`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ actual_seconds: actualSeconds ?? null }),
    }),
  )
}
