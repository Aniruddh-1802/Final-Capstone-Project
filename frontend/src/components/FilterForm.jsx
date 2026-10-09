import { useEffect, useState } from 'react'

// fields: [{name, label, type: 'text'|'number'|'date'|'select'|'checkbox-bool', options?: [{value,label}], placeholder?}]
// `values` come from the URL; submitting writes them back to the URL (and so triggers the server-side query).
export function FilterForm({ fields, values, onApply, label = 'Filters' }) {
  const [draft, setDraft] = useState(values)
  useEffect(() => setDraft(values), [JSON.stringify(values)])  // eslint-disable-line react-hooks/exhaustive-deps
  const set = (name) => (e) => setDraft((d) => ({ ...d, [name]: e.target.value }))
  return (
    <form className="filters" aria-label={label} onSubmit={(e) => { e.preventDefault(); onApply(draft) }}>
      {fields.map((f) => (
        <label key={f.name}>{f.label}
          {f.type === 'select' ? (
            <select value={draft[f.name] ?? ''} onChange={set(f.name)}>
              <option value="">{f.any || 'Any'}</option>
              {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          ) : (
            <input type={f.type || 'text'} value={draft[f.name] ?? ''} onChange={set(f.name)} placeholder={f.placeholder}
                   min={f.type === 'number' ? f.min : undefined} max={f.type === 'number' ? f.max : undefined} />
          )}
        </label>
      ))}
      <button type="submit" className="btn primary">Apply</button>
      <button type="button" className="btn" onClick={() => onApply({})}>Clear</button>
    </form>
  )
}
