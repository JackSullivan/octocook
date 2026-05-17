import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { doneStep, getSession, startStep } from './api'
import type { ScheduleStep, Session } from './types'

interface Props {
  sessionId: string
  onExit: () => void
}

type StepStatus = 'done' | 'in_progress' | 'ready' | 'blocked'

export function CookView({ sessionId, onExit }: Props) {
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeCook, setActiveCook] = useState(0)
  const [now, setNow] = useState(() => Date.now())

  const refresh = useCallback(async () => {
    try {
      const s = await getSession(sessionId)
      setSession(s)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    }
  }, [sessionId])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000)
    return () => clearInterval(t)
  }, [refresh])

  // Ticking clock for live timers.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  if (error) return <div className="cook-view"><p className="error">{error}</p><button onClick={onExit}>Back</button></div>
  if (!session) return <div className="cook-view"><p>Loading…</p></div>

  const numCooks = session.num_cooks

  const handleStart = async (stepId: string) => {
    setSession((s) => s && {
      ...s,
      step_state: {
        ...s.step_state,
        [stepId]: { started_at: new Date().toISOString(), completed_at: null, actual_seconds: null },
      },
    })
    try { await startStep(sessionId, stepId) } catch (e) { setError(String((e as Error).message ?? e)) }
    refresh()
  }

  const handleDone = async (stepId: string) => {
    setSession((s) => {
      if (!s) return s
      const prev = s.step_state[stepId]
      return {
        ...s,
        step_state: {
          ...s.step_state,
          [stepId]: {
            started_at: prev?.started_at ?? null,
            completed_at: new Date().toISOString(),
            actual_seconds: prev?.started_at
              ? Math.max(1, Math.round((Date.now() - Date.parse(prev.started_at)) / 1000))
              : null,
          },
        },
      }
    })
    try { await doneStep(sessionId, stepId) } catch (e) { setError(String((e as Error).message ?? e)) }
    refresh()
  }

  return (
    <div className="cook-view">
      <header className="cook-header">
        <button className="link" onClick={onExit}>← Setup</button>
        <h1>Cooking · {session.recipe_titles.length} recipes</h1>
        <span className="muted">total ~ {session.schedule.makespan_label}</span>
      </header>

      <nav className="cook-tabs">
        {Array.from({ length: numCooks }, (_, k) => (
          <button
            key={k}
            className={k === activeCook ? 'tab active' : 'tab'}
            onClick={() => setActiveCook(k)}
          >
            Cook {k + 1}
          </button>
        ))}
      </nav>

      <CookPane
        session={session}
        cookId={activeCook}
        nowMs={now}
        onStart={handleStart}
        onDone={handleDone}
      />
    </div>
  )
}

interface PaneProps {
  session: Session
  cookId: number
  nowMs: number
  onStart: (stepId: string) => void
  onDone: (stepId: string) => void
}

function CookPane({ session, cookId, nowMs, onStart, onDone }: PaneProps) {
  const allSteps = session.schedule.steps
  const icons = session.schedule.icons || {}
  const stepState = session.step_state

  // Lookup: every step in the schedule (any cook), keyed by id.
  const stepById = useMemo(() => {
    const m: Record<string, ScheduleStep> = {}
    for (const s of allSteps) m[s.step_id] = s
    return m
  }, [allSteps])

  // Status per step across the whole schedule (deps may cross cooks).
  const statusById = useMemo(() => {
    const result: Record<string, StepStatus> = {}
    for (const s of allSteps) {
      const st = stepState[s.step_id]
      if (st?.completed_at) result[s.step_id] = 'done'
      else if (st?.started_at) result[s.step_id] = 'in_progress'
      else {
        const allDepsDone = s.depends_on.every((d) => !!stepState[d]?.completed_at)
        result[s.step_id] = allDepsDone ? 'ready' : 'blocked'
      }
    }
    return result
  }, [allSteps, stepState])

  // This cook's assigned steps in chronological order.
  const cookSteps = useMemo(
    () =>
      allSteps
        .filter((s) => s.cook_id === cookId)
        .sort((a, b) => a.start_min - b.start_min || a.step_id.localeCompare(b.step_id)),
    [allSteps, cookId],
  )

  // Position of each step within its recipe (1-indexed) for "step X/Y of dish".
  const recipeIndex = useMemo(() => {
    const totals: Record<string, number> = {}
    const positions: Record<string, number> = {}
    const byRecipe: Record<string, ScheduleStep[]> = {}
    for (const s of allSteps) {
      ;(byRecipe[s.recipe] ||= []).push(s)
    }
    for (const [recipe, steps] of Object.entries(byRecipe)) {
      const sorted = [...steps].sort((a, b) => a.start_min - b.start_min || a.step_id.localeCompare(b.step_id))
      totals[recipe] = sorted.length
      sorted.forEach((s, i) => { positions[s.step_id] = i + 1 })
    }
    return { totals, positions }
  }, [allSteps])

  const completedCount = cookSteps.filter((s) => statusById[s.step_id] === 'done').length

  // 1-indexed chronological position of each step within the cook's sequence,
  // independent of how segments group them visually.
  const cookPosById = useMemo(() => {
    const m: Record<string, number> = {}
    cookSteps.forEach((s, i) => { m[s.step_id] = i + 1 })
    return m
  }, [cookSteps])

  // Group the cook's steps into segments: either a single step, or a passive
  // step that contains one or more active steps entirely within its window
  // (the lane visualization).
  type Segment =
    | { kind: 'step'; step: ScheduleStep }
    | { kind: 'lane'; passive: ScheduleStep; nested: ScheduleStep[] }

  const segments = useMemo<Segment[]>(() => {
    const result: Segment[] = []
    const consumed = new Set<string>()
    for (const s of cookSteps) {
      if (consumed.has(s.step_id)) continue
      if (!s.active) {
        const nested = cookSteps.filter((other) =>
          other.active &&
          !consumed.has(other.step_id) &&
          other.start_min >= s.start_min &&
          other.end_min <= s.end_min
        )
        consumed.add(s.step_id)
        nested.forEach((n) => consumed.add(n.step_id))
        result.push(
          nested.length === 0
            ? { kind: 'step', step: s }
            : { kind: 'lane', passive: s, nested },
        )
      } else {
        consumed.add(s.step_id)
        result.push({ kind: 'step', step: s })
      }
    }
    return result
  }, [cookSteps])

  // Focus: first in-progress on this cook, else first ready, else first not-done.
  const focusStepId = useMemo(() => {
    const find = (st: StepStatus) => cookSteps.find((s) => statusById[s.step_id] === st)?.step_id
    return (
      find('in_progress') ?? find('ready') ?? cookSteps.find((s) => statusById[s.step_id] !== 'done')?.step_id ?? null
    )
  }, [cookSteps, statusById])

  const focusRef = useRef<HTMLLIElement | null>(null)
  useEffect(() => {
    if (focusRef.current) {
      focusRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [focusStepId])

  if (cookSteps.length === 0) {
    return (
      <div className="cook-pane">
        <p className="muted">Nothing assigned to Cook {cookId + 1} this round. Try another tab.</p>
      </div>
    )
  }

  const pct = Math.round((completedCount / cookSteps.length) * 100)

  return (
    <div className="cook-pane">
      <div className="progress-block">
        <div className="progress-label">
          <span>{completedCount} / {cookSteps.length} steps done</span>
          <span className="muted">{pct}%</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <ol className="step-list">
        {segments.map((seg) => {
          const buildCardProps = (s: ScheduleStep) => {
            const status = statusById[s.step_id]
            const blockers = status === 'blocked'
              ? s.depends_on
                  .map((d) => stepById[d])
                  .filter((d) => d && !stepState[d.step_id]?.completed_at)
              : []
            return {
              step: s,
              icon: icons[s.recipe] || '🍽️',
              dishPos: recipeIndex.positions[s.step_id],
              dishTotal: recipeIndex.totals[s.recipe],
              cookPos: cookPosById[s.step_id],
              cookTotal: cookSteps.length,
              status,
              blockers,
              ownCookId: cookId,
              startedAt: stepState[s.step_id]?.started_at ?? null,
              nowMs,
              onStart: () => onStart(s.step_id),
              onDone: () => onDone(s.step_id),
            }
          }

          if (seg.kind === 'step') {
            const s = seg.step
            return (
              <StepCard
                key={s.step_id}
                {...buildCardProps(s)}
                focusRef={s.step_id === focusStepId ? focusRef : undefined}
              />
            )
          }

          // lane segment: passive step alongside its nested active steps.
          const p = seg.passive
          const containsFocus =
            p.step_id === focusStepId || seg.nested.some((n) => n.step_id === focusStepId)
          return (
            <li
              key={p.step_id}
              className="passive-segment"
              ref={containsFocus ? focusRef : undefined}
            >
              <PassiveLane {...buildCardProps(p)} />
              <ul className="active-column">
                {seg.nested.map((n) => (
                  <StepCard key={n.step_id} {...buildCardProps(n)} />
                ))}
              </ul>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

interface CardProps {
  step: ScheduleStep
  icon: string
  dishPos: number
  dishTotal: number
  cookPos: number
  cookTotal: number
  status: StepStatus
  blockers: ScheduleStep[]
  ownCookId: number
  startedAt: string | null
  nowMs: number
  onStart: () => void
  onDone: () => void
  focusRef?: React.RefObject<HTMLLIElement | null>
}

function StepCard({
  step, icon, dishPos, dishTotal, cookPos, cookTotal, status, blockers, ownCookId,
  startedAt, nowMs, onStart, onDone, focusRef,
}: CardProps) {
  const elapsedSec = startedAt
    ? Math.max(0, Math.floor((nowMs - Date.parse(startedAt)) / 1000))
    : 0
  const elapsedLabel = `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, '0')}`
  const kind = step.active ? 'active' : 'passive'

  const showStartTimer = step.active && status === 'ready'
  const showTimer = step.active && status === 'in_progress'
  const showDone = status === 'ready' || status === 'in_progress'

  return (
    <li className={`step-card ${status} ${kind}`} ref={focusRef}>
      <div className="step-head">
        <span className="step-icon">{icon}</span>
        <div className="step-meta">
          <div className="step-recipe">
            {step.recipe}
            {!step.active && <span className="passive-tag">hands-off</span>}
          </div>
          <div className="step-positions">
            <span>Step {dishPos}/{dishTotal} of dish</span>
            <span className="dot">·</span>
            <span>Step {cookPos}/{cookTotal} for you</span>
            <span className="dot">·</span>
            <span>~ {step.duration_min} min</span>
          </div>
        </div>
        {status === 'done' && <span className="step-check">✓</span>}
      </div>

      <div className="step-desc">{step.description}</div>

      {step.ingredients.length > 0 && (
        <ul className="step-ingredients">
          {step.ingredients.map((ing, i) => (
            <li key={i}>{ing}</li>
          ))}
        </ul>
      )}

      {step.tools.length > 0 && (
        <div className="step-tools">{step.tools.join(' · ')}</div>
      )}

      {status === 'blocked' && blockers.length > 0 && (
        <div className="step-blockers">
          Waiting on:
          <ul>
            {blockers.map((b) => (
              <li key={b.step_id}>
                {b.description}
                <span className="muted">
                  {' '}· {b.cook_id === ownCookId
                    ? 'yours'
                    : b.cook_id == null
                      ? 'unassigned'
                      : `Cook ${b.cook_id + 1}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(showStartTimer || showTimer || showDone) && (
        <div className="step-actions">
          {showTimer && <span className="timer">⏱ {elapsedLabel}</span>}
          {showStartTimer && <button onClick={onStart}>Start timer</button>}
          {!step.active && (
            <span className="muted">Tap Done when the equipment finishes.</span>
          )}
          {showDone && <button className="primary" onClick={onDone}>Done</button>}
        </div>
      )}
    </li>
  )
}

type LaneProps = Omit<CardProps, 'focusRef'>

function PassiveLane({
  step, icon, dishPos, dishTotal, cookPos, cookTotal, status, blockers, ownCookId,
  startedAt, nowMs, onStart, onDone,
}: LaneProps) {
  const elapsedSec = startedAt
    ? Math.max(0, Math.floor((nowMs - Date.parse(startedAt)) / 1000))
    : 0
  const elapsedLabel = `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, '0')}`

  return (
    <div className={`passive-lane ${status}`}>
      <div className="lane-edge lane-start">
        <div className="edge-label">Start · ~{step.duration_min} min</div>
        <div className="step-head">
          <span className="step-icon">{icon}</span>
          <div className="step-meta">
            <div className="step-recipe">
              {step.recipe}
              <span className="passive-tag">hands-off</span>
            </div>
            <div className="step-positions">
              <span>Step {dishPos}/{dishTotal} of dish</span>
              <span className="dot">·</span>
              <span>Step {cookPos}/{cookTotal} for you</span>
            </div>
          </div>
        </div>
        <div className="step-desc">{step.description}</div>
        {step.ingredients.length > 0 && (
          <ul className="step-ingredients">
            {step.ingredients.map((ing, i) => (
              <li key={i}>{ing}</li>
            ))}
          </ul>
        )}
        {step.tools.length > 0 && (
          <div className="step-tools">{step.tools.join(' · ')}</div>
        )}
        {status === 'blocked' && blockers.length > 0 && (
          <div className="step-blockers">
            Waiting on:
            <ul>
              {blockers.map((b) => (
                <li key={b.step_id}>
                  {b.description}
                  <span className="muted">
                    {' '}· {b.cook_id === ownCookId
                      ? 'yours'
                      : b.cook_id == null
                        ? 'unassigned'
                        : `Cook ${b.cook_id + 1}`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {status === 'ready' && !startedAt && (
          <button onClick={onStart}>I've started it</button>
        )}
      </div>

      <div className="lane-bar">
        {status === 'in_progress' && startedAt && (
          <span className="lane-timer">⏱ {elapsedLabel}</span>
        )}
      </div>

      <div className="lane-edge lane-end">
        <div className="edge-label">End</div>
        {status === 'done' ? (
          <span className="step-check">✓ Done</span>
        ) : status === 'blocked' ? (
          <span className="muted">Waiting…</span>
        ) : (
          <button className="primary" onClick={onDone}>Done</button>
        )}
      </div>
    </div>
  )
}
