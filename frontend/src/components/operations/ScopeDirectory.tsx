import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, MenuItem, TextField, Typography } from '@mui/material'
import { ChevronRightRounded, FolderOpenOutlined } from '@mui/icons-material'
import { DataTable } from '../DataTable'
import {
  operationsFolders,
  operationsRecords,
  opsScopeReference,
  type OpsFolderCount,
  type OpsRegisters,
  type OpsScopeReference,
} from '../../lib/operations'

export type Folder = { well_id: string; scope: string }
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
      <TextField
        select
        label="Scope"
        value={folder.scope}
        onChange={(e) => change({ ...folder, scope: e.target.value })}
      >
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

type Register = keyof OpsRegisters
export type DirectoryLocation = { rig: string; well?: string; scope?: string }
const keyFor = (id: string | null, snapshot = '') => (id ? `id:${id}` : `snapshot:${snapshot}`)
const scopeNames: Record<string, string> = { drilling: 'Drilling', completion: 'Completion' }
export const directorySearch = ({ rig, well, scope }: DirectoryLocation, deleted = false) => {
  const params = new URLSearchParams()
  if (rig) params.set('rig', rig)
  if (rig && well) params.set('well', well)
  if (rig && well && scope) params.set('scope', scope)
  if (deleted) params.set('view', 'deleted')
  return params
}
export const recordLocation = (r: {
  rig_id: string | null
  well_id: string | null
  rig_code_snapshot: string
  well_code_snapshot: string
  scope: string
}): DirectoryLocation => ({
  rig: keyFor(r.rig_id, r.rig_code_snapshot),
  well: keyFor(r.well_id, r.well_code_snapshot),
  scope: r.scope,
})

export function useOperationsRegister<K extends Register>(resource: K) {
  const [params, setParams] = useSearchParams()
  const rig = params.get('rig') ?? '',
    well = rig ? (params.get('well') ?? '') : ''
  const requestedScope = params.get('scope') ?? ''
  const scope = well && Object.hasOwn(scopeNames, requestedScope) ? requestedScope : ''
  const deleted = params.get('view') === 'deleted'
  const location = { rig, well, scope }
  const [version, setVersion] = useState(0)
  const refresh = useCallback(async () => {
    setVersion((v) => v + 1)
  }, [])
  const [reference, setReference] = useState<OpsScopeReference | null>(null)
  const [refError, setRefError] = useState('')
  const [counts, setCounts] = useState<{ version: string; rows: OpsFolderCount[]; error?: string } | null>(null)
  const [records, setRecords] = useState<{ version: string; rows: OpsRegisters[K][]; error?: string } | null>(null)
  const countsVersion = `${resource}/${deleted}/${version}`
  const recordVersion = JSON.stringify([countsVersion, rig, well, scope])
  useEffect(() => {
    let current = true
    opsScopeReference()
      .then((r) => {
        if (current) setReference(r)
      })
      .catch((e) => {
        if (current) setRefError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [])
  useEffect(() => {
    let current = true
    operationsFolders(resource, deleted)
      .then((rows) => {
        if (current) setCounts({ version: countsVersion, rows })
      })
      .catch((e) => {
        if (current) setCounts({ version: countsVersion, rows: [], error: (e as Error).message })
      })
    return () => {
      current = false
    }
  }, [resource, deleted, countsVersion])
  useEffect(() => {
    let current = true
    if (rig && well) {
      operationsRecords(resource, rig, well, scope, deleted)
        .then((rows) => {
          if (current) setRecords({ version: recordVersion, rows })
        })
        .catch((e) => {
          if (current) setRecords({ version: recordVersion, rows: [], error: (e as Error).message })
        })
    }
    return () => {
      current = false
    }
  }, [resource, rig, well, scope, deleted, recordVersion])
  const currentCounts = counts?.version === countsVersion ? counts : null
  const currentRecords = records?.version === recordVersion ? records : null
  const folders = useMemo(() => {
    const entries = [...(currentCounts?.rows ?? [])]
    if (!deleted) {
      const known = new Set(entries.map((f) => JSON.stringify([f.rig_key, f.well_key, f.scope])))
      const rigs = new Map(reference?.rigs.map((r) => [r.id, r.rig_code]))
      for (const w of reference?.wells ?? []) {
        for (const s of ['drilling', 'completion'] as const) {
          const rigKey = keyFor(w.rig_id),
            wellKey = keyFor(w.id)
          if (!w[`${s}_available`] || known.has(JSON.stringify([rigKey, wellKey, s]))) continue
          entries.push({
            rig_key: rigKey,
            well_key: wellKey,
            scope: s,
            rig_id: w.rig_id,
            well_id: w.id,
            rig_code: rigs.get(w.rig_id) ?? '',
            well_code: w.well_code,
            well_name: w.well_name,
            record_count: 0,
          })
        }
      }
    }
    return entries
  }, [currentCounts, deleted, reference])
  const destination = (selected = location): Folder | null => {
    const w = reference?.wells.find((w) => keyFor(w.id) === selected.well)
    if (!w) return null
    const s =
      selected.scope === 'completion' && w.completion_available
        ? 'completion'
        : w.drilling_available
          ? 'drilling'
          : 'completion'
    return { well_id: w.id, scope: s }
  }
  const formLocation = (folder: Folder): DirectoryLocation => ({
    rig: keyFor(reference?.wells.find((w) => w.id === folder.well_id)?.rig_id ?? null),
    well: keyFor(folder.well_id),
    scope: folder.scope,
  })
  return {
    location,
    deleted,
    reference,
    refresh,
    folders,
    destination,
    formLocation,
    rows: currentRecords?.rows ?? [],
    loading: !currentCounts || (Boolean(well) && !currentRecords),
    error: refError || currentCounts?.error || currentRecords?.error || '',
    change: (loc: DirectoryLocation, showDeleted = deleted) => setParams(directorySearch(loc, showDeleted)),
  }
}

/** Only rig folders are visible at entry; the well register is mounted after drill-down. */
export function ScopeDirectory({
  folders,
  location,
  change,
  loading,
  resource,
}: {
  folders: OpsFolderCount[]
  location: DirectoryLocation
  change: (location: DirectoryLocation) => void
  loading: boolean
  resource: Register
}) {
  const rigs = useMemo(() => {
    const rows = new Map<string, { id: string; name: string; wells: Set<string>; count: number }>()
    for (const f of folders) {
      const r = rows.get(f.rig_key) ?? {
        id: f.rig_key,
        name: f.rig_code || 'Unassigned rig',
        wells: new Set(),
        count: 0,
      }
      r.count += f.record_count
      r.wells.add(f.well_key)
      rows.set(f.rig_key, r)
    }
    return [...rows.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  }, [folders])
  const wells = useMemo(() => {
    const rows = new Map<string, { id: string; code: string; name: string; count: number; scopes: string[] }>()
    for (const f of folders.filter((f) => f.rig_key === location.rig)) {
      const w = rows.get(f.well_key) ?? {
        id: f.well_key,
        code: f.well_code || 'Unassigned well',
        name: f.well_name,
        count: 0,
        scopes: [],
      }
      w.count += f.record_count
      w.scopes.push(f.scope)
      rows.set(f.well_key, w)
    }
    return [...rows.values()].sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
  }, [folders, location.rig])
  const well = wells.find((w) => w.id === location.well)
  const rig = rigs.find((r) => r.id === location.rig)
  const open = (label: string, handler: () => void, type: string) => (
    <Button size="small" startIcon={<FolderOpenOutlined />} aria-label={`Open ${type} ${label}`} onClick={handler}>
      Open {type}
    </Button>
  )
  return (
    <Box mb={1.5}>
      <Box
        component="nav"
        aria-label="Rig and well folders"
        display="flex"
        alignItems="center"
        gap={1}
        flexWrap="wrap"
        sx={{ borderBlock: 1, borderColor: 'divider', py: 1, mb: 1.5 }}
      >
        {location.rig ? (
          <Button size="small" onClick={() => change({ rig: '' })}>
            All rigs
          </Button>
        ) : (
          <Typography fontWeight={700}>Rig folders</Typography>
        )}
        {location.rig && (
          <>
            <ChevronRightRounded fontSize="small" aria-hidden />
            {location.well ? (
              <Button size="small" onClick={() => change({ rig: location.rig })}>
                {rig?.name || 'Rig'} wells
              </Button>
            ) : (
              <Typography fontWeight={700}>{rig?.name || 'Rig'} wells</Typography>
            )}
          </>
        )}
        {location.well && (
          <>
            <ChevronRightRounded fontSize="small" aria-hidden />
            <Typography fontWeight={700} aria-current="location">
              {well?.code || 'Well folder'}
            </Typography>
            <TextField
              size="small"
              select
              label="Scope"
              sx={{ minWidth: 145, ml: { sm: 'auto' } }}
              value={location.scope ?? ''}
              onChange={(e) => change({ ...location, scope: e.target.value })}
            >
              <MenuItem value="">All scopes</MenuItem>
              <MenuItem value="drilling">Drilling</MenuItem>
              <MenuItem value="completion">Completion</MenuItem>
            </TextField>
          </>
        )}
      </Box>
      {!location.well &&
        (loading ? (
          <Typography role="status">Loading folders…</Typography>
        ) : location.rig ? (
          wells.length ? (
            <DataTable
              key={location.rig}
              rows={wells}
              canExport={false}
              fillHeight
              searchPlaceholder="Find a well…"
              columns={[
                { field: 'code', headerName: 'Well code' },
                { field: 'name', headerName: 'Well name' },
                {
                  field: 'scopes',
                  headerName: 'Scopes',
                  valueFormatter: (p) => (p.value as string[]).map((s) => scopeNames[s] ?? s).join(', '),
                },
                {
                  field: 'count',
                  headerName: resource === 'plans' ? 'Plan versions' : resource === 'reports' ? 'Reports' : 'Documents',
                },
                {
                  headerName: 'Actions',
                  cellRenderer: ({ data }: { data: (typeof wells)[number] }) =>
                    open(data.code, () => change({ rig: location.rig, well: data.id }), 'well'),
                },
              ]}
            />
          ) : (
            <Alert severity="info">No wells in this rig folder.</Alert>
          )
        ) : rigs.length ? (
          <DataTable
            key="rigs"
            rows={rigs.map((r) => ({ ...r, wellCount: r.wells.size }))}
            canExport={false}
            fillHeight
            searchPlaceholder="Find a rig…"
            columns={[
              { field: 'name', headerName: 'Rig' },
              { field: 'wellCount', headerName: 'Wells' },
              {
                field: 'count',
                headerName: resource === 'plans' ? 'Plan versions' : resource === 'reports' ? 'Reports' : 'Documents',
              },
              {
                headerName: 'Actions',
                cellRenderer: ({ data }: { data: (typeof rigs)[number] }) =>
                  open(data.name, () => change({ rig: data.id }), 'rig'),
              },
            ]}
          />
        ) : (
          <Alert severity="info">No rig folders to show here.</Alert>
        ))}
    </Box>
  )
}
