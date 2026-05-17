import { useEffect, useMemo, useState } from 'react'
import {
  createKitchen,
  deleteKitchen,
  getKitchen,
  listKitchens,
  updateKitchen,
  type KitchenDetail,
} from './api'

interface Props {
  onClose: () => void
}

type InvRow = { tool: string; count: number }

const _BLANK_SUBS = `# tool_name:
#   - tool: substitute_tool   # or null for "by hand"
#     time_multiplier: 1.5
#     note: "Description of the workaround"
`

export function KitchenManager({ onClose }: Props) {
  const [kitchens, setKitchens] = useState<string[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [newName, setNewName] = useState<string | null>(null) // non-null = creating new
  const [detail, setDetail] = useState<KitchenDetail | null>(null)
  const [inventoryRows, setInventoryRows] = useState<InvRow[]>([])
  const [subsYaml, setSubsYaml] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)

  // initial load
  useEffect(() => {
    listKitchens()
      .then((ks) => {
        const names = ks.map((k) => k.name)
        setKitchens(names)
        if (names.length > 0) setSelected(names[0])
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
  }, [])

  // load selected kitchen
  useEffect(() => {
    if (!selected || newName !== null) return
    setError(null)
    setBusy(true)
    getKitchen(selected)
      .then((k) => {
        setDetail(k)
        setInventoryRows(
          Object.entries(k.inventory)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([tool, count]) => ({ tool, count })),
        )
        setSubsYaml(k.substitutions_yaml)
        setDirty(false)
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false))
  }, [selected, newName])

  const handleNew = () => {
    setNewName('')
    setDetail(null)
    setInventoryRows([{ tool: 'cook', count: 1 }])
    setSubsYaml(_BLANK_SUBS)
    setError(null)
    setDirty(true)
  }

  const handleDuplicate = () => {
    if (!detail) return
    // Keep the current inventoryRows / subsYaml — they already reflect the
    // selected kitchen — and switch the form into "creating new" mode with
    // a suggested name.
    setNewName(`${detail.name}_copy`)
    setDetail(null)
    setError(null)
    setDirty(true)
  }

  const updateRow = (idx: number, patch: Partial<InvRow>) => {
    setInventoryRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
    setDirty(true)
  }

  const removeRow = (idx: number) => {
    setInventoryRows((prev) => prev.filter((_, i) => i !== idx))
    setDirty(true)
  }

  const addRow = () => {
    setInventoryRows((prev) => [...prev, { tool: '', count: 1 }])
    setDirty(true)
  }

  const updateSubs = (text: string) => {
    setSubsYaml(text)
    setDirty(true)
  }

  const validateBeforeSave = (): string | null => {
    const seen = new Set<string>()
    for (const r of inventoryRows) {
      const t = r.tool.trim()
      if (!t) return 'Inventory has a row with no tool name.'
      if (!/^[a-z0-9_]+$/i.test(t)) {
        return `Invalid tool name "${t}". Use letters, digits, and underscores.`
      }
      if (seen.has(t)) return `Duplicate tool "${t}".`
      seen.add(t)
      if (!Number.isFinite(r.count) || r.count < 0) {
        return `Tool "${t}" has invalid count.`
      }
    }
    return null
  }

  const handleSave = async () => {
    const v = validateBeforeSave()
    if (v) { setError(v); return }
    const inventory: Record<string, number> = {}
    for (const r of inventoryRows) inventory[r.tool.trim()] = r.count

    setBusy(true)
    setError(null)
    try {
      if (newName !== null) {
        const name = newName.trim()
        if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
          throw new Error('Kitchen name must be letters, numbers, dash, or underscore.')
        }
        const created = await createKitchen({
          name,
          inventory,
          substitutions_yaml: subsYaml,
        })
        setKitchens((prev) => prev ? [...prev, created.name].sort() : [created.name])
        setNewName(null)
        setSelected(created.name)
        setDirty(false)
      } else if (selected) {
        const updated = await updateKitchen(selected, {
          inventory,
          substitutions_yaml: subsYaml,
        })
        setDetail(updated)
        setDirty(false)
      }
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!selected) return
    if (!confirm(`Delete kitchen "${selected}"? This cannot be undone.`)) return
    setBusy(true)
    setError(null)
    try {
      await deleteKitchen(selected)
      const remaining = (kitchens ?? []).filter((k) => k !== selected)
      setKitchens(remaining)
      setSelected(remaining[0] ?? null)
      setDetail(null)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const handleCancelNew = () => {
    setNewName(null)
    if (kitchens && kitchens.length > 0) {
      setSelected(kitchens[0])
    }
  }

  const editingName = newName !== null ? newName : selected ?? ''
  const canSave = !busy && dirty
  const canDelete = newName === null && !busy && kitchens !== null && kitchens.length > 1
  const canDuplicate = newName === null && detail !== null && !busy

  const sortedRows = useMemo(() => inventoryRows, [inventoryRows])

  return (
    <div className="kitchen-manager">
      <header className="km-header">
        <button className="link" onClick={onClose}>← Back to setup</button>
        <h1>Kitchens</h1>
      </header>

      <nav className="km-tabs">
        {(kitchens ?? []).map((name) => (
          <button
            key={name}
            className={selected === name && newName === null ? 'tab active' : 'tab'}
            onClick={() => { setSelected(name); setNewName(null) }}
            disabled={busy}
          >
            {name}
          </button>
        ))}
        <button
          className={newName !== null ? 'tab active' : 'tab'}
          onClick={handleNew}
          disabled={busy}
        >
          + New
        </button>
      </nav>

      {error && <p className="error">{error}</p>}

      {(detail || newName !== null) && (
        <section className="km-form">
          <label className="km-field">
            <span>Name</span>
            <input
              type="text"
              value={editingName}
              onChange={(e) => {
                if (newName !== null) {
                  setNewName(e.target.value)
                  setDirty(true)
                }
              }}
              disabled={newName === null}
              placeholder="my_kitchen"
            />
          </label>

          <h2>Inventory</h2>
          <p className="muted">
            Each tool and how many you have. <code>cook</code> is the number of human cooks
            (CLI uses this; the web app overrides it per session).
          </p>
          <table className="inv-table">
            <thead>
              <tr><th>Tool</th><th>Count</th><th></th></tr>
            </thead>
            <tbody>
              {sortedRows.map((row, idx) => (
                <tr key={idx}>
                  <td>
                    <input
                      type="text"
                      value={row.tool}
                      onChange={(e) => updateRow(idx, { tool: e.target.value })}
                      placeholder="chef_knife"
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      value={row.count}
                      onChange={(e) => updateRow(idx, { count: parseInt(e.target.value || '0', 10) })}
                    />
                  </td>
                  <td>
                    <button onClick={() => removeRow(idx)} className="link" aria-label="remove">✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={addRow}>+ Add tool</button>

          <h2>Substitutions</h2>
          <p className="muted">
            YAML mapping of missing tool → ordered list of fallbacks. Each fallback has
            <code> tool</code> (or <code>null</code> for "by hand"), <code>time_multiplier</code>,
            and <code>note</code>.
          </p>
          <textarea
            className="subs-yaml"
            value={subsYaml}
            onChange={(e) => updateSubs(e.target.value)}
            rows={16}
            spellCheck={false}
          />

          <div className="km-actions">
            {newName !== null && (
              <button onClick={handleCancelNew} disabled={busy}>Cancel</button>
            )}
            {canDuplicate && (
              <button onClick={handleDuplicate}>Duplicate as new</button>
            )}
            {canDelete && (
              <button onClick={handleDelete} className="danger" disabled={busy}>
                Delete kitchen
              </button>
            )}
            <button className="primary" onClick={handleSave} disabled={!canSave}>
              {busy ? 'Saving…' : newName !== null ? 'Create kitchen' : 'Save'}
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
