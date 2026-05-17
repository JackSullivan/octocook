export interface RecipeOut {
  id: string
  title: string
  icon: string
  found_in: string
  rating: string
}

export interface ScheduleStep {
  step_id: string
  recipe: string
  description: string
  duration_min: number
  active: boolean
  tools: string[]
  depends_on: string[]
  ingredients: string[]
  start_min: number
  end_min: number
  start_clock: string
  end_clock: string
  cook_id: number | null
}

export interface Schedule {
  makespan_min: number
  makespan_label: string
  substitutions: Substitution[]
  steps: ScheduleStep[]
  icons: Record<string, string>
  num_cooks: number
}

export interface Substitution {
  recipe: string
  step_id: string
  original_tool: string
  substitute_tool: string | null
  time_multiplier: number
  note: string
}

export interface StepState {
  started_at: string | null
  completed_at: string | null
  actual_seconds: number | null
}

export interface Session {
  id: string
  created_at: string
  num_cooks: number
  kitchen: string
  recipe_titles: string[]
  schedule: Schedule
  step_state: Record<string, StepState>
}
