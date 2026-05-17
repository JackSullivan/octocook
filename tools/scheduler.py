"""Constraint-based scheduling of multiple recipes with shared kitchen tools.

Models each step as a fixed-duration interval, each tool (including the human
"cook") as a renewable resource with a capacity, and minimizes total makespan
using OR-Tools CP-SAT.

Tools that a recipe needs but the inventory doesn't have are resolved via a
substitution graph (see substitutions.yaml). The fallback tool is used and
the step's duration is scaled by the rule's time_multiplier.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml
from ortools.sat.python import cp_model


COOK_RESOURCE = "cook"

# Tools whose state persists between adjacent uses (oven temperature, skillet
# heat) — for these, any two same-recipe steps in a dependency chain must
# run back-to-back so no other recipe occupies the tool between a preheat
# and its bake (or between two consecutive bakes that share a preheated state).
_STATEFUL_TOOLS = frozenset({"oven"})


@dataclass
class Step:
    """One scheduled action in a recipe."""

    id: str                       # globally unique, e.g. "bombay_rolls.S1"
    recipe: str                   # the recipe this step belongs to
    description: str
    duration_min: int
    active: bool                  # True = consumes the cook for the duration
    tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # other globally-unique step ids
    ingredients: list[str] = field(default_factory=list)  # ingredient lines used in this step


@dataclass
class Inventory:
    counts: dict[str, int]

    def has(self, tool: str) -> bool:
        return self.counts.get(tool, 0) > 0

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Inventory":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(counts={str(k): int(v) for k, v in data.items()})


@dataclass
class SubstitutionRule:
    tool: str | None              # None = "by hand" (no tool reservation)
    time_multiplier: float
    note: str


@dataclass
class SubstitutionGraph:
    rules: dict[str, list[SubstitutionRule]]

    def chain(self, tool: str) -> list[SubstitutionRule]:
        return self.rules.get(tool, [])

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SubstitutionGraph":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        rules: dict[str, list[SubstitutionRule]] = {}
        for tool, chain in data.items():
            rules[tool] = [
                SubstitutionRule(
                    tool=entry.get("tool"),
                    time_multiplier=float(entry.get("time_multiplier", 1.0)),
                    note=str(entry.get("note", "")),
                )
                for entry in (chain or [])
            ]
        return cls(rules=rules)


@dataclass
class Substitution:
    """Record of a tool substitution applied to a step."""

    recipe: str
    step_id: str
    original_tool: str
    substitute_tool: str | None   # None = by hand
    time_multiplier: float
    note: str


@dataclass
class StepSchedule:
    step: Step                    # post-resolution (possibly substituted tools / scaled duration)
    start_min: int
    end_min: int
    cook_id: int | None = None    # which cook (0-indexed) runs this active step; None for passive


@dataclass
class Schedule:
    steps: list[StepSchedule]
    makespan_min: int
    substitutions: list[Substitution]


class UnsupportedToolError(RuntimeError):
    """Raised when a step needs a tool with no available substitute."""


def _find_substitute(
    tool: str,
    inventory: Inventory,
    subs: SubstitutionGraph,
) -> SubstitutionRule | None:
    for rule in subs.chain(tool):
        if rule.tool is None or inventory.has(rule.tool):
            return rule
    return None


def resolve_tools(
    steps: list[Step],
    inventory: Inventory,
    subs: SubstitutionGraph,
) -> tuple[list[Step], list[Substitution]]:
    """Apply substitutions; return adjusted steps + the substitution log."""
    out_steps: list[Step] = []
    out_subs: list[Substitution] = []

    for s in steps:
        new_tools: list[str] = []
        time_mult = 1.0
        for tool in s.tools:
            if tool == COOK_RESOURCE:
                continue  # cook is added later based on `active`, not as a per-step tool
            if inventory.has(tool):
                new_tools.append(tool)
                continue
            rule = _find_substitute(tool, inventory, subs)
            if rule is None:
                raise UnsupportedToolError(
                    f"Recipe {s.recipe!r} step {s.id!r} needs {tool!r}, "
                    f"which is not in inventory and has no available substitute. "
                    f"Edit inventory.yaml or substitutions.yaml."
                )
            if rule.tool is not None:
                new_tools.append(rule.tool)
            time_mult *= rule.time_multiplier
            out_subs.append(Substitution(
                recipe=s.recipe,
                step_id=s.id,
                original_tool=tool,
                substitute_tool=rule.tool,
                time_multiplier=rule.time_multiplier,
                note=rule.note,
            ))

        new_duration = max(1, round(s.duration_min * time_mult))
        out_steps.append(replace(s, tools=new_tools, duration_min=new_duration))

    return out_steps, out_subs


def solve(
    steps: list[Step],
    inventory: Inventory,
    subs: SubstitutionGraph,
    num_cooks: int | None = None,
) -> Schedule:
    """Build the CP-SAT model and return the optimal schedule.

    When `num_cooks` is provided, each active step is assigned to a specific
    cook (0..num_cooks-1) via optional intervals + per-cook NoOverlap, and the
    returned StepSchedule.cook_id is populated. When None, falls back to
    treating the cook pool as a cumulative resource with capacity from
    inventory (no individual assignment).
    """
    resolved, substitutions = resolve_tools(steps, inventory, subs)

    if not resolved:
        return Schedule(steps=[], makespan_min=0, substitutions=[])

    model = cp_model.CpModel()
    horizon = sum(s.duration_min for s in resolved)

    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    intervals: dict[str, cp_model.IntervalVar] = {}

    for s in resolved:
        start = model.NewIntVar(0, horizon, f"start_{s.id}")
        end = model.NewIntVar(0, horizon, f"end_{s.id}")
        intervals[s.id] = model.NewIntervalVar(start, s.duration_min, end, f"int_{s.id}")
        starts[s.id] = start
        ends[s.id] = end

    # Precedence (within a recipe; ignore dangling deps that point at unknown ids).
    for s in resolved:
        for dep in s.depends_on:
            if dep in ends:
                model.Add(starts[s.id] >= ends[dep])

    # Group intervals by tool. Stateful tools (oven) are handled separately
    # below as per-recipe session intervals so that one recipe holds the tool
    # from its first to its last use. The cook resource is also handled
    # separately so we can either treat it as cumulative (num_cooks is None)
    # or bind each active step to a specific cook (num_cooks is set).
    tool_intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)
    for s in resolved:
        for tool in s.tools:
            if tool in _STATEFUL_TOOLS:
                continue
            tool_intervals[tool].append(intervals[s.id])
        if s.active and num_cooks is None:
            tool_intervals[COOK_RESOURCE].append(intervals[s.id])

    # Per-cook assignment via optional intervals. Each active step has one
    # optional interval per cook; exactly one is "present", which both picks
    # the cook and (via NoOverlap on each cook's optional intervals) prevents
    # a single cook from working two steps in parallel.
    cook_assignment: dict[str, list[cp_model.IntVar]] = {}  # step.id -> [presence per cook]
    if num_cooks is not None:
        if num_cooks < 1:
            raise ValueError("num_cooks must be >= 1.")
        per_cook_intervals: list[list[cp_model.IntervalVar]] = [[] for _ in range(num_cooks)]
        for s in resolved:
            if not s.active:
                continue
            presences: list[cp_model.IntVar] = []
            for k in range(num_cooks):
                is_k = model.NewBoolVar(f"cook{k}_does_{s.id}")
                opt_iv = model.NewOptionalIntervalVar(
                    starts[s.id], s.duration_min, ends[s.id], is_k,
                    f"opt_{s.id}_c{k}",
                )
                per_cook_intervals[k].append(opt_iv)
                presences.append(is_k)
            model.AddExactlyOne(presences)
            cook_assignment[s.id] = presences
        for k in range(num_cooks):
            if per_cook_intervals[k]:
                model.AddNoOverlap(per_cook_intervals[k])

    # Stateful tools: build one session interval per (recipe, tool) spanning
    # from the recipe's first use of the tool to its last use. The session
    # interval is what consumes capacity, so two recipes can never overlap
    # their oven sessions even if their individual oven steps don't directly
    # collide. (Prep that happens in parallel with the preheat is fine — the
    # oven still belongs to that recipe for the duration.)
    steps_by_tool_recipe: dict[tuple[str, str], list[Step]] = defaultdict(list)
    for s in resolved:
        for tool in s.tools:
            if tool in _STATEFUL_TOOLS:
                steps_by_tool_recipe[(tool, s.recipe)].append(s)

    for (tool, recipe), recipe_steps in steps_by_tool_recipe.items():
        sess_start = model.NewIntVar(0, horizon, f"{tool}_sess_start_{recipe}")
        sess_end = model.NewIntVar(0, horizon, f"{tool}_sess_end_{recipe}")
        sess_dur = model.NewIntVar(1, horizon, f"{tool}_sess_dur_{recipe}")
        sess_interval = model.NewIntervalVar(
            sess_start, sess_dur, sess_end, f"{tool}_sess_{recipe}"
        )
        model.AddMinEquality(sess_start, [starts[s.id] for s in recipe_steps])
        model.AddMaxEquality(sess_end, [ends[s.id] for s in recipe_steps])
        tool_intervals[tool].append(sess_interval)

    for tool, ivs in tool_intervals.items():
        capacity = inventory.counts.get(tool, 0)
        if capacity == 0:
            # Should have been resolved away unless someone forgot to include the cook.
            raise UnsupportedToolError(
                f"Tool {tool!r} has 0 capacity but {len(ivs)} step(s) need it."
            )
        model.AddCumulative(ivs, [1] * len(ivs), capacity)

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))

    # Lexicographic objective: minimize makespan first, then minimize the
    # busiest cook's total active-minutes load. Without this tiebreaker the
    # solver can pile all work on one cook whenever the critical path doesn't
    # benefit from parallelism, leaving other cooks idle.
    if num_cooks is not None and cook_assignment:
        loads = [model.NewIntVar(0, horizon, f"load_c{k}") for k in range(num_cooks)]
        for k in range(num_cooks):
            terms = []
            for step_id, presences in cook_assignment.items():
                # Find the step's duration via resolved (cheap; resolved is small).
                dur = next(s.duration_min for s in resolved if s.id == step_id)
                terms.append(presences[k] * dur)
            model.Add(loads[k] == sum(terms))
        max_load = model.NewIntVar(0, horizon, "max_load")
        model.AddMaxEquality(max_load, loads)
        # max_load <= horizon, so (horizon + 1) is a safe lex multiplier.
        model.Minimize(makespan * (horizon + 1) + max_load)
    else:
        model.Minimize(makespan)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"CP-SAT could not find a schedule (status={solver.StatusName(status)})."
        )

    def _cook_for(step_id: str) -> int | None:
        presences = cook_assignment.get(step_id)
        if not presences:
            return None
        for k, p in enumerate(presences):
            if solver.Value(p) == 1:
                return k
        return None

    scheduled = [
        StepSchedule(
            step=s,
            start_min=int(solver.Value(starts[s.id])),
            end_min=int(solver.Value(ends[s.id])),
            cook_id=_cook_for(s.id),
        )
        for s in resolved
    ]
    scheduled.sort(key=lambda x: (x.start_min, x.step.recipe, x.step.id))

    if num_cooks is not None:
        _attribute_passive_steps(scheduled, num_cooks)

    return Schedule(
        steps=scheduled,
        makespan_min=int(solver.Value(makespan)),
        substitutions=substitutions,
    )


def _attribute_passive_steps(scheduled: list[StepSchedule], num_cooks: int) -> None:
    """Assign each passive step a `cook_id` so it appears in someone's timeline.

    Heuristic, applied iteratively until stable:
      1. If the step has any *attributed* predecessor, take the cook of the
         predecessor with the latest end (the most recent handoff).
      2. Else if it has any attributed successor, take the cook of the
         earliest successor (the one who will pick this work up next).
      3. Else (orphan passive): fall back to the cook with the least minutes
         already attributed on this recipe.

    "Attributed" includes both active steps (which the solver already bound)
    and passive steps placed by earlier iterations, so chains of consecutive
    passive steps inherit cleanly.
    """
    by_id = {ss.step.id: ss for ss in scheduled}

    # Build reverse dependency map: for each step id, who lists it in their depends_on.
    successors_of: dict[str, list[StepSchedule]] = defaultdict(list)
    for ss in scheduled:
        for dep in ss.step.depends_on:
            successors_of[dep].append(ss)

    pending = [ss for ss in scheduled if ss.cook_id is None]
    while pending:
        progress = False
        still: list[StepSchedule] = []
        for ss in pending:
            preds = [
                by_id[dep] for dep in ss.step.depends_on
                if dep in by_id and by_id[dep].cook_id is not None
            ]
            if preds:
                ss.cook_id = max(preds, key=lambda x: x.end_min).cook_id
                progress = True
                continue
            sucs = [s for s in successors_of.get(ss.step.id, []) if s.cook_id is not None]
            if sucs:
                ss.cook_id = min(sucs, key=lambda x: x.start_min).cook_id
                progress = True
                continue
            still.append(ss)
        if not progress:
            break
        pending = still

    # Orphans: passive step whose entire recipe has no attributed cook yet
    # (rare — would mean every step in the recipe is passive). Use the
    # least-loaded cook across the schedule as a fallback.
    if pending:
        per_cook_total: list[int] = [0] * num_cooks
        for ss in scheduled:
            if ss.cook_id is not None:
                per_cook_total[ss.cook_id] += ss.step.duration_min
        for ss in pending:
            k = min(range(num_cooks), key=lambda i: per_cook_total[i])
            ss.cook_id = k
            per_cook_total[k] += ss.step.duration_min


def _format_clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if m else f"{h}h"


def schedule_to_dict(schedule: Schedule) -> dict:
    """Serialize a Schedule into a JSON-friendly dict."""
    return {
        "makespan_min": schedule.makespan_min,
        "makespan_label": _format_duration(schedule.makespan_min),
        "substitutions": [
            {
                "recipe": sub.recipe,
                "step_id": sub.step_id,
                "original_tool": sub.original_tool,
                "substitute_tool": sub.substitute_tool,
                "time_multiplier": sub.time_multiplier,
                "note": sub.note,
            }
            for sub in schedule.substitutions
        ],
        "steps": [
            {
                "step_id": s.step.id,
                "recipe": s.step.recipe,
                "description": s.step.description,
                "duration_min": s.step.duration_min,
                "active": s.step.active,
                "tools": list(s.step.tools),
                "depends_on": list(s.step.depends_on),
                "ingredients": list(s.step.ingredients),
                "start_min": s.start_min,
                "end_min": s.end_min,
                "start_clock": _format_clock(s.start_min),
                "end_clock": _format_clock(s.end_min),
                "cook_id": s.cook_id,
            }
            for s in schedule.steps
        ],
    }


def format_schedule(schedule: Schedule) -> str:
    """Render the schedule as a plain-text plan."""
    lines: list[str] = []
    lines.append(f"SCHEDULE — total time: {_format_duration(schedule.makespan_min)}")
    lines.append("")

    if schedule.substitutions:
        lines.append("Substitutions in effect:")
        for sub in schedule.substitutions:
            sub_label = sub.substitute_tool if sub.substitute_tool else "(by hand)"
            lines.append(
                f"  - {sub.recipe}: {sub.original_tool} -> {sub_label} "
                f"({sub.time_multiplier}x time) — {sub.note}"
            )
        lines.append("")

    if not schedule.steps:
        lines.append("(no steps)")
        return "\n".join(lines)

    recipe_w = max(len(s.step.recipe) for s in schedule.steps)
    desc_w = max(40, max(len(s.step.description) for s in schedule.steps))

    header = (
        f"  {'Start':5}  {'End':5}  {'Recipe':<{recipe_w}}  "
        f"{'Step':<{desc_w}}  Tools / kind"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for s in schedule.steps:
        kind = "active" if s.step.active else "passive"
        tool_str = ", ".join(s.step.tools) if s.step.tools else "(no tool)"
        lines.append(
            f"  {_format_clock(s.start_min):5}  {_format_clock(s.end_min):5}  "
            f"{s.step.recipe:<{recipe_w}}  {s.step.description:<{desc_w}}  "
            f"[{kind}] {tool_str}"
        )

    return "\n".join(lines)
