import { useMemo, useState } from 'react'
import { Box, Button, MenuItem, Paper, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { AccountTreeOutlined, ViewListOutlined } from '@mui/icons-material'
import type { OpsScopeReference } from '../../lib/operations'

export type Folder = { well_id: string; scope: string }
type Scoped = {
  well_id: string | null
  rig_id: string | null
  scope: string
  rig_code_snapshot: string
  well_code_snapshot: string
}

export function FolderFields({
  reference,
  folder,
  change,
}: {
  reference: OpsScopeReference | null
  folder: Folder
  change: (f: Folder) => void
}) {
  const well = reference?.wells.find((w) => w.id === folder.well_id)
  return (
    <>
      <TextField
        select
        required
        label="Well · rig"
        value={folder.well_id}
        onChange={(e) => {
          const next = reference?.wells.find((w) => w.id === e.target.value)
          if (next) change({ well_id: next.id, scope: next.drilling_available ? 'drilling' : 'completion' })
        }}
        helperText="Only configured well scopes are available."
      >
        {(reference?.wells ?? []).map((w) => (
          <MenuItem key={w.id} value={w.id}>
            {w.display_name} · {reference?.rigs.find((r) => r.id === w.rig_id)?.rig_code}
          </MenuItem>
        ))}
      </TextField>
      <TextField select label="Scope" value={folder.scope} onChange={(e) => change({ ...folder, scope: e.target.value })}>
        <MenuItem disabled={!well?.drilling_available} value="drilling">
          Drilling
        </MenuItem>
        <MenuItem disabled={!well?.completion_available} value="completion">
          Completion
        </MenuItem>
      </TextField>
    </>
  )
}

/** Same drill-down as the daily cost register. Keep the grid (including Actions) in view. */
export function ScopeDirectory<T extends Scoped>({
  rows,
  reference,
  folder,
  change,
}: {
  rows: T[]
  reference: OpsScopeReference | null
  folder: Folder | null
  change: (folder: Folder | null) => void
}) {
  const [grouped, setGrouped] = useState(true)
  const tree = useMemo(() => {
    const rigs = new Map<string, Map<string, { name: string; scopes: Map<string, number> }>>()
    function put(rig: string, id: string, name: string, scope: string, count: number) {
      const wells = rigs.get(rig) ?? new Map()
      rigs.set(rig, wells)
      const well = wells.get(id) ?? { name, scopes: new Map() }
      wells.set(id, well)
      well.scopes.set(scope, (well.scopes.get(scope) ?? 0) + count)
    }
    const rigLabel = (id: string | null) => reference?.rigs.find((r) => r.id === id)?.rig_code
    for (const w of reference?.wells ?? [])
      for (const scope of ['drilling', 'completion'] as const)
        if (w[`${scope}_available`]) put(rigLabel(w.rig_id) ?? 'Unassigned rig', w.id, w.display_name, scope, 0)
    for (const r of rows) {
      const w = reference?.wells.find((w) => w.id === r.well_id)
      put(
        rigLabel(r.rig_id ?? w?.rig_id ?? null) ?? (r.rig_code_snapshot || 'Unassigned rig'),
        r.well_id ?? '',
        w?.display_name ?? (r.well_code_snapshot || 'Unassigned well'),
        r.scope,
        1,
      )
    }
    return rigs
  }, [rows, reference])
  return (
    <Paper variant="outlined" sx={{ p: 1.5, mb: 1.5 }}>
      <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
        <ToggleButtonGroup
          size="small"
          exclusive
          value={grouped ? 'grouped' : 'flat'}
          onChange={(_, v) => {
            if (v) {
              setGrouped(v === 'grouped')
              change(null)
            }
          }}
        >
          <ToggleButton value="grouped">
            <AccountTreeOutlined fontSize="small" /> Grouped (Rig → Well → Scope)
          </ToggleButton>
          <ToggleButton value="flat">
            <ViewListOutlined fontSize="small" /> Flat list
          </ToggleButton>
        </ToggleButtonGroup>
        {folder && <Button onClick={() => change(null)}>All folders</Button>}
        <Typography variant="body2">
          {folder
            ? `${reference?.wells.find((w) => w.id === folder.well_id)?.well_code ?? 'Well'} / ${folder.scope}`
            : 'Showing all folders'}
        </Typography>
      </Box>
      {grouped && (
        <Box mt={1} sx={{ maxHeight: 240, overflow: 'auto' }}>
          {[...tree].map(([rig, wells]) => (
            <Box component="details" key={rig} sx={{ borderTop: 1, borderColor: 'divider', py: 0.5 }}>
              <Typography component="summary" sx={{ cursor: 'pointer', fontWeight: 700 }}>
                {rig} · {wells.size} {wells.size === 1 ? 'well' : 'wells'}
              </Typography>
              {[...wells].map(([id, w]) => (
                <Box key={id} display="flex" alignItems="center" gap={1} flexWrap="wrap" pl={2}>
                  <Typography variant="body2">{w.name}</Typography>
                  {[...w.scopes].map(([scope, n]) => (
                    <Button
                      key={scope}
                      size="small"
                      variant={folder?.well_id === id && folder.scope === scope ? 'contained' : 'text'}
                      onClick={() => change({ well_id: id, scope })}
                    >
                      {scope} ({n})
                    </Button>
                  ))}
                </Box>
              ))}
            </Box>
          ))}
        </Box>
      )}
    </Paper>
  )
}
