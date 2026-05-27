import { useEffect, useMemo, useState } from 'react'
import { createSession, enrichRecipe, getRecipeDetail, ingestRecipe, listKitchens, listRecipes } from './api'
import type { RecipeDetail, RecipeOut } from './types'
import { Logo } from './Logo'

interface Unenriched {
  id: string
  title: string
}

interface Props {
  onCreated: (sessionId: string) => void
  onManageKitchens: () => void
  kitchensVersion: number
  backend: string
}

export function Setup({ onCreated, onManageKitchens, kitchensVersion, backend }: Props) {
  const [recipes, setRecipes] = useState<RecipeOut[] | null>(null)
  const [kitchens, setKitchens] = useState<string[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [kitchen, setKitchen] = useState<string>('')
  const [numCooks, setNumCooks] = useState(2)
  const [filter, setFilter] = useState('')
  const [ratingFilter, setRatingFilter] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [needsEnrichment, setNeedsEnrichment] = useState<Unenriched[]>([])
  const [enriching, setEnriching] = useState<Set<string>>(new Set())

  // Recipe detail modal
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detail, setDetail] = useState<RecipeDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Add-recipe panel (sqlite mode only)
  const [ingestOpen, setIngestOpen] = useState(false)
  const [ingestUrl, setIngestUrl] = useState('')
  const [ingestStatus, setIngestStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [ingestError, setIngestError] = useState<string | null>(null)

  // Recipes are heavy to fetch — only on mount.
  useEffect(() => {
    listRecipes()
      .then(setRecipes)
      .catch((e) => setError(String(e.message ?? e)))
  }, [])

  // Kitchens refresh whenever we return from the kitchen manager.
  useEffect(() => {
    listKitchens()
      .then((ks) => {
        const names = ks.map((k) => k.name)
        setKitchens(names)
        setKitchen((current) => {
          if (current && names.includes(current)) return current
          return names[0] ?? ''
        })
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [kitchensVersion])

  // Load detail when a recipe card's ⓘ is clicked.
  useEffect(() => {
    if (detailId === null) { setDetail(null); return }
    setDetailLoading(true)
    setDetail(null)
    getRecipeDetail(detailId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }, [detailId])

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleRating = (rating: string) => {
    setRatingFilter((prev) => {
      const next = new Set(prev)
      if (next.has(rating)) next.delete(rating)
      else next.add(rating)
      return next
    })
  }

  // Ratings present in the data, sorted: stars descending, then other emojis,
  // then "Unrated" last. Each entry carries a count so the chip can show it.
  const availableRatings = useMemo(() => {
    if (!recipes) return []
    const counts: Record<string, number> = {}
    for (const r of recipes) counts[r.rating] = (counts[r.rating] ?? 0) + 1
    return Object.keys(counts)
      .sort((a, b) => {
        if (a === '' && b !== '') return 1
        if (b === '' && a !== '') return -1
        const aStars = (a.match(/⭐/g) || []).length
        const bStars = (b.match(/⭐/g) || []).length
        if (aStars !== bStars) return bStars - aStars
        return a.localeCompare(b)
      })
      .map((value) => ({ value, count: counts[value] }))
  }, [recipes])

  const handleStart = async () => {
    setError(null)
    setNeedsEnrichment([])
    setSubmitting(true)
    try {
      const { session_id } = await createSession({
        recipe_ids: [...selected],
        kitchen,
        num_cooks: numCooks,
      })
      onCreated(session_id)
    } catch (e) {
      const msg = String((e as Error).message ?? e)
      // The backend returns 400 with detail={error, recipes:[...]} for the
      // unenriched-recipes case so we can surface a per-recipe Enrich UI.
      try {
        const body = JSON.parse(msg)
        if (body?.detail?.error === 'unenriched_recipes') {
          setNeedsEnrichment(body.detail.recipes as Unenriched[])
          return
        }
      } catch { /* not JSON — fall through */ }
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleEnrich = async (id: string) => {
    setEnriching((prev) => new Set(prev).add(id))
    try {
      await enrichRecipe(id)
      setNeedsEnrichment((prev) => prev.filter((r) => r.id !== id))
    } catch (e) {
      setError(`Enrichment failed: ${String((e as Error).message ?? e)}`)
    } finally {
      setEnriching((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const handleEnrichAll = async () => {
    const ids = needsEnrichment.map((r) => r.id)
    // Run serially so we don't hammer the Claude API with parallel calls.
    for (const id of ids) {
      if (!enriching.has(id)) await handleEnrich(id)
    }
  }

  const handleIngest = async () => {
    if (!ingestUrl.trim()) return
    setIngestStatus('loading')
    setIngestError(null)
    try {
      const newRecipe = await ingestRecipe(ingestUrl.trim())
      setRecipes((prev) => prev ? [newRecipe, ...prev] : [newRecipe])
      setIngestUrl('')
      setIngestStatus('success')
      setTimeout(() => setIngestStatus('idle'), 3000)
    } catch (e) {
      setIngestError(String((e as Error).message ?? e))
      setIngestStatus('error')
    }
  }

  if (recipes === null || kitchens === null) {
    return <div className="setup"><p>Loading…</p>{error && <p className="error">{error}</p>}</div>
  }

  const filtered = recipes.filter((r) => {
    if (ratingFilter.size > 0 && !ratingFilter.has(r.rating)) return false
    if (filter && !r.title.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  // Selected recipes, in the order the user picked them (Set preserves insertion order).
  const selectedRecipes = [...selected]
    .map((id) => recipes.find((r) => r.id === id))
    .filter((r): r is RecipeOut => Boolean(r))

  const canStart = selected.size > 0 && kitchen && numCooks >= 1 && !submitting

  return (
    <div className="setup">
      <header className="setup-hero">
        <Logo size={96} />
        <div>
          <h1>Octocook</h1>
          <p>Pick recipes, a kitchen, and how many cooks. We'll plan the rest.</p>
        </div>
      </header>

      <section>
        <label>
          Kitchen
          <select value={kitchen} onChange={(e) => setKitchen(e.target.value)}>
            {kitchens.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </label>
        <label>
          Cooks
          <input
            type="number"
            min={1}
            max={8}
            value={numCooks}
            onChange={(e) => setNumCooks(Math.max(1, parseInt(e.target.value || '1', 10)))}
          />
        </label>
        <button type="button" className="link kitchen-manage-link" onClick={onManageKitchens}>
          Manage kitchens →
        </button>
      </section>

      <section className="recipes">
        <div className="recipes-header">
          <h2>Recipes <span className="muted">({selected.size} selected)</span></h2>
          <input
            type="search"
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        {availableRatings.length > 0 && (
          <div className="rating-filters">
            {availableRatings.map(({ value, count }) => {
              const active = ratingFilter.has(value)
              return (
                <button
                  key={value || '__unrated__'}
                  type="button"
                  className={active ? 'chip active' : 'chip'}
                  onClick={() => toggleRating(value)}
                >
                  <span className="chip-label">{value || 'Unrated'}</span>
                  <span className="chip-count">{count}</span>
                </button>
              )
            })}
            {ratingFilter.size > 0 && (
              <button
                type="button"
                className="chip chip-clear"
                onClick={() => setRatingFilter(new Set())}
              >
                Clear
              </button>
            )}
          </div>
        )}
        {filtered.length === 0 ? (
          <p className="muted">No recipes match the current filter.</p>
        ) : (
          <ul className="recipe-grid">
            {filtered.map((r) => {
              const isSelected = selected.has(r.id)
              return (
                <li
                  key={r.id}
                  className={isSelected ? 'recipe-card selected' : 'recipe-card'}
                  onClick={() => toggle(r.id)}
                >
                  <div className="recipe-head">
                    <span className="icon">{r.icon}</span>
                    {isSelected && <span className="check">✓</span>}
                    <button
                      type="button"
                      className="detail-btn"
                      title="View recipe details"
                      onClick={(e) => { e.stopPropagation(); setDetailId(r.id) }}
                    >
                      ⓘ
                    </button>
                  </div>
                  <div className="title">{r.title}</div>
                  <div className="meta">
                    {r.found_in && <span className="found-in">{r.found_in}</span>}
                    {r.rating && <span className="rating">{r.rating}</span>}
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {backend === 'sqlite' && (
          <div className="ingest-panel">
            <button
              type="button"
              className="link"
              onClick={() => setIngestOpen((o) => !o)}
            >
              {ingestOpen ? '▲ Hide' : '▼ Add a recipe by URL'}
            </button>
            {ingestOpen && (
              <div className="ingest-form">
                <input
                  type="url"
                  placeholder="https://example.com/recipe"
                  value={ingestUrl}
                  onChange={(e) => setIngestUrl(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleIngest() }}
                  disabled={ingestStatus === 'loading'}
                />
                <button
                  type="button"
                  className="primary"
                  disabled={ingestStatus === 'loading' || !ingestUrl.trim()}
                  onClick={handleIngest}
                >
                  {ingestStatus === 'loading' ? 'Fetching…' : 'Fetch'}
                </button>
                {ingestStatus === 'success' && (
                  <p className="ingest-success">Recipe added!</p>
                )}
                {ingestStatus === 'error' && ingestError && (
                  <p className="error">{ingestError}</p>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      <div className="meal-panel">
        <div className="meal-header">
          <strong>🥘 Your meal</strong>
          <span className="muted">
            {selected.size === 0
              ? 'No recipes selected'
              : `${selected.size} recipe${selected.size === 1 ? '' : 's'}`}
          </span>
        </div>

        {selectedRecipes.length > 0 ? (
          <ul className="meal-pills">
            {selectedRecipes.map((r) => (
              <li
                key={r.id}
                className="pill"
                onClick={() => toggle(r.id)}
                title="Click to remove from meal"
              >
                <span className="pill-icon">{r.icon}</span>
                <span className="pill-title">{r.title}</span>
                <span className="pill-x" aria-hidden>✕</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="meal-empty muted">Pick recipes above to build your meal.</p>
        )}

        {error && <p className="error">{error}</p>}

        {needsEnrichment.length > 0 && (
          <div className="enrich-banner">
            <p>
              <strong>{needsEnrichment.length}</strong> recipe(s) need to be enriched before
              scheduling. Enrichment uses Claude to break instructions into atomic steps
              (~10–30s each).
            </p>
            <ul className="enrich-list">
              {needsEnrichment.map((r) => {
                const inFlight = enriching.has(r.id)
                return (
                  <li key={r.id}>
                    <span className="enrich-title">{r.title}</span>
                    <button
                      type="button"
                      disabled={inFlight}
                      onClick={() => handleEnrich(r.id)}
                    >
                      {inFlight ? 'Enriching…' : 'Enrich'}
                    </button>
                  </li>
                )
              })}
            </ul>
            <button
              type="button"
              className="primary"
              disabled={enriching.size > 0}
              onClick={handleEnrichAll}
            >
              {enriching.size > 0 ? `Enriching ${enriching.size}…` : 'Enrich all'}
            </button>
          </div>
        )}

        <button className="primary" disabled={!canStart} onClick={handleStart}>
          {submitting ? 'Planning…' : `Start cooking (${selected.size})`}
        </button>
      </div>

      {/* Recipe detail modal */}
      {detailId !== null && (
        <div className="modal-overlay" onClick={() => setDetailId(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setDetailId(null)}>✕</button>
            {detailLoading && <p className="muted">Loading…</p>}
            {detail && (
              <>
                <div className="modal-header">
                  <span className="modal-icon">{detail.icon}</span>
                  <div>
                    <h2>{detail.title}</h2>
                    {detail.found_in && <p className="muted">{detail.found_in}</p>}
                  </div>
                </div>
                <div className="modal-meta">
                  {detail.rating && <span>{detail.rating}</span>}
                  <span className={detail.enriched ? 'badge badge-ok' : 'badge badge-warn'}>
                    {detail.enriched ? `${detail.step_count} steps` : 'Not enriched'}
                  </span>
                </div>
                {detail.ingredients.length > 0 && (
                  <div className="modal-ingredients">
                    <h3>Ingredients</h3>
                    <ul>
                      {detail.ingredients.map((ing, i) => (
                        <li key={i}>{ing}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
