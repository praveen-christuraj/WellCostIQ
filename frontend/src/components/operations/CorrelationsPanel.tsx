import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Collapse,
  MenuItem,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { AddRounded } from '@mui/icons-material'
import { FormDialog, Tag, type Tone } from '../Common'
import { DataTable } from '../DataTable'
import { SectionCard } from '../ui/SectionCard'
import { CorrelationTree, type TreeNode } from './CorrelationTree'
import { useAuth } from '../../context/AuthContext'
import {
  auditExport,
  opsCodeLinks,
  opsCorrelations,
  opsCorrelationReference,
  opsCreateCodeLink,
  opsCreateCodeLinksBatch,
  opsCreateCorrelation,
  opsCreateCorrelationsBatch,
  opsDeleteCodeLinks,
  opsDeleteCorrelations,
  opsPurgeCodeLinks,
  opsPurgeCorrelations,
  opsRestoreCodeLinks,
  opsRestoreCorrelations,
  opsUpdateCodeLink,
  opsUpdateCorrelation,
  type OpsCodeLink,
  type OpsCodeLinkInput,
  type OpsCorrelation,
  type OpsCorrelationInput,
  type OpsCorrelationLibraryItem,
  type OpsCorrelationReference,
} from '../../lib/operations'
import {
  ALLOCATIONS,
  CLASSES,
  CORRELATION_KINDS,
  CRITERIA,
  SCOPES,
  asAllocation,
  asClassification,
  asScope,
  classificationProblem,
  printedKey,
  type CriterionKey,
} from './codeCriteria'

/** The server accepts at most 200 rows in one batch save (`OpsCodeLinkBatchIn`). */
const LINK_BATCH_LIMIT = 200

type Printed = OpsCorrelationReference['printed'][number]
type Selections = Partial<Record<CriterionKey, string[]>>

type CorrelationForm = {
  rowId: string
  kind: OpsCorrelationInput['kind']
  /** Composite `family::code`, so the printed option stays unambiguous across families. */
  printed_key: string
  /** Agency tokens are free text: the printed catalogue holds no operator names. */
  free_agency: string
  target_id: string
  scope: '' | 'drilling' | 'completion'
  target_classification: '' | 'Planned' | 'UPA' | 'NPT'
  target_allocation: '' | 'PT' | 'UPA' | 'NPT' | 'SP'
  note: string
}

type LinkForm = {
  rowId: string
  rule_name: string
  scope: '' | 'drilling' | 'completion'
  default_classification: '' | 'Planned' | 'UPA' | 'NPT'
  default_allocation: '' | 'PT' | 'UPA' | 'NPT' | 'SP'
  note: string
  selections: Selections
}

const emptyCorrelation = (): CorrelationForm => ({
  rowId: '',
  kind: 'operation',
  printed_key: '',
  free_agency: '',
  target_id: '',
  scope: '',
  target_classification: '',
  target_allocation: '',
  note: '',
})

const emptyLink = (): LinkForm => ({
  rowId: '',
  rule_name: '',
  scope: '',
  default_classification: '',
  default_allocation: '',
  note: '',
  selections: {},
})

const KIND_KEYS = CORRELATION_KINDS.map((k) => k.key) as OpsCorrelationInput['kind'][]

/** The kind a new row starts on: the filter when it names a kind, otherwise Operation. */
const defaultKind = (value: string): OpsCorrelationInput['kind'] =>
  KIND_KEYS.includes(value as OpsCorrelationInput['kind']) ? (value as OpsCorrelationInput['kind']) : 'operation'

const toneFor = (kind: string): Tone => (kind === 'npt' ? 'warning' : kind === 'cause' ? 'info' : kind === 'agency' ? 'success' : 'neutral')

/** Printed families the server accepts for each correlation kind (mirror of `KINDS`). */
const PRINTED_FAMILIES: Record<string, string[]> = {
  operation: ['Operation', 'OpenWells operation code'],
  activity: ['Activity', 'OpenWells code token'],
  npt: ['Trouble / NPT'],
  cause: ['Cause', 'Trouble / NPT'],
  phase: ['OpenWells phase', 'Programme phase'],
  agency: [],
}

/**
 * Code correlations & multi-criteria code links.
 *
 * The two rule sets answer different questions and are therefore kept apart:
 *
 * * a **correlation** maps one printed token (from a source document) onto one
 *   workspace code, optionally pinning companion criteria;
 * * a **code link** joins two or more workspace codes so extraction can fill a
 *   remaining empty dropdown only when every active link agrees.
 *
 * Both are edited as a table by default and as a schematic on request, because
 * the same rules are easier to audit in a list and easier to understand as a
 * hierarchy. Nothing here approves work: a rule only pre-selects a dropdown.
 */
export function CorrelationsPanel({ focusKind = '', focusCode = '', onClearFocus }: {
  focusKind?: string
  focusCode?: string
  onClearFocus?: () => void
}) {
  const { can } = useAuth()
  const [ref, setRef] = useState<OpsCorrelationReference | null>(null)
  const [rows, setRows] = useState<OpsCorrelation[]>([])
  const [links, setLinks] = useState<OpsCodeLink[]>([])
  const [deleted, setDeleted] = useState(false)
  const [kind, setKind] = useState(focusKind)
  const [view, setView] = useState<'table' | 'tree'>('table')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => setKind(focusKind), [focusKind])

  const [form, setForm] = useState<CorrelationForm | null>(null)
  const [formError, setFormError] = useState('')
  const [companionOpen, setCompanionOpen] = useState(false)
  const [batch, setBatch] = useState<{ kind: OpsCorrelationInput['kind']; printed_key: string; target_id: string }[] | null>(null)
  const [batchError, setBatchError] = useState('')
  const [linkForm, setLinkForm] = useState<LinkForm | null>(null)
  const [linkError, setLinkError] = useState('')
  const [pending, setPending] = useState<
    | { type: 'correlation' | 'link'; ids: string[]; action: 'delete' | 'restore' | 'purge' }
    | null
  >(null)

  // One fetch path: the tab, a filter change and every save all read the same
  // three endpoints, and a save must never fire them twice. Each filter change
  // takes a ticket; a response that belongs to a filter the user has already left
  // is dropped instead of painting another tab's rows over this one.
  const requestTicket = useRef(0)
  const load = useCallback(async () => {
    const ticket = ++requestTicket.current
    setError('')
    try {
      const [reference, correlations, codeLinks] = await Promise.all([
        opsCorrelationReference(),
        opsCorrelations({ kind: kind || undefined, deleted }),
        opsCodeLinks({ deleted }),
      ])
      if (ticket !== requestTicket.current) return
      setRef(reference)
      setRows(correlations)
      setLinks(codeLinks)
    } catch (e) {
      if (ticket === requestTicket.current) setError((e as Error).message)
      throw e
    }
  }, [kind, deleted])

  useEffect(() => {
    // Failures are already shown by load(); this keeps them out of the console.
    load().catch(() => undefined)
  }, [load])

  const run = async (fn: () => Promise<unknown>, message = '') => {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
      if (message) setNotice(message)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const libraryFor = (k: string) => ref?.library[k] ?? []
  const libraryItem = (k: string, id: string): OpsCorrelationLibraryItem | undefined =>
    libraryFor(k).find((c) => c.id === id)

  /** Printed options the server will accept for the chosen kind, with the composite key. */
  const printedOptions = useMemo(() => {
    if (!form || form.kind === 'agency') return []
    const families = PRINTED_FAMILIES[form.kind] ?? []
    return (ref?.printed ?? []).filter((p) => families.includes(p.family))
  }, [form, ref])

  const printedSelection = useMemo(() => {
    if (!form?.printed_key) return null
    return (ref?.printed ?? []).find((p) => printedKey(p.family, p.code) === form.printed_key) ?? null
  }, [form?.printed_key, ref])

  const saveCorrelation = async () => {
    if (!form) return
    const agency = form.kind === 'agency'
    const source_code = agency ? form.free_agency.trim() : (printedSelection?.code ?? '')
    const source_family = agency ? 'Source agency' : (printedSelection?.family ?? '')
    if (!source_code) {
      setFormError(agency ? 'Type the printed agency exactly as the source writes it.' : 'Choose a printed code.')
      return
    }
    if (!form.target_id) {
      setFormError('Choose the workspace code this printed token should pre-select.')
      return
    }
    setFormError('')
    await run(async () => {
      if (form.rowId) {
        await opsUpdateCorrelation(form.rowId, {
          target_id: form.target_id,
          scope: asScope(form.scope),
          target_classification: asClassification(form.target_classification),
          target_allocation: asAllocation(form.target_allocation),
          note: form.note,
          is_active: true,
        })
      } else {
        const payload: OpsCorrelationInput = {
          kind: form.kind,
          source_family,
          source_code,
          source_label: printedSelection?.name ?? printedSelection?.description ?? '',
          target_id: form.target_id,
          scope: asScope(form.scope),
          target_classification: asClassification(form.target_classification),
          target_allocation: asAllocation(form.target_allocation),
          note: form.note,
        }
        await opsCreateCorrelation(payload)
      }
      setForm(null)
      setCompanionOpen(false)
    })
  }

  const saveBatch = async () => {
    if (!batch?.length) return
    const items: OpsCorrelationInput[] = []
    for (const [index, row] of batch.entries()) {
      const printed = (ref?.printed ?? []).find((p) => printedKey(p.family, p.code) === row.printed_key)
      if (!printed || !row.target_id) {
        setBatchError(`Row ${index + 1}: choose both a printed code and a workspace code.`)
        return
      }
      items.push({
        kind: row.kind,
        source_family: printed.family,
        source_code: printed.code,
        source_label: printed.name ?? printed.description,
        target_id: row.target_id,
      })
    }
    setBatchError('')
    await run(async () => {
      const result = await opsCreateCorrelationsBatch(items)
      setBatch(null)
      setNotice(`Created ${result.created_count} correlation${result.created_count === 1 ? '' : 's'} in one transaction.`)
    })
  }

  const openLink = (link?: OpsCodeLink) => {
    setLinkError('')
    if (!link) {
      setLinkForm(emptyLink())
      return
    }
    const selections: Selections = {}
    for (const criterion of CRITERIA) {
      const raw = (link as unknown as Record<string, string | null>)[criterion.linkId]
      if (raw) selections[criterion.key] = [raw]
    }
    setLinkForm({
      rowId: link.id,
      rule_name: link.rule_name,
      scope: asScope(link.scope),
      default_classification: asClassification(link.default_classification),
      default_allocation: asAllocation(link.default_allocation),
      note: link.note,
      selections,
    })
  }

  /** Cartesian product of the selected values; every chosen criterion must be represented. */
  const fanOut = useMemo(() => {
    if (!linkForm) return []
    const chosen = CRITERIA.filter((c) => (linkForm.selections[c.key] ?? []).length > 0)
    if (chosen.length < 2) return []
    let combos: Selections[] = [{}]
    for (const criterion of chosen) {
      const values = linkForm.selections[criterion.key] ?? []
      // Grow the product a criterion at a time and stop once it cannot fit, so a
      // selection that lands exactly on the cap is still saved rather than
      // silently becoming "no combinations".
      if (combos.length * values.length > LINK_BATCH_LIMIT) return []
      const next: Selections[] = []
      for (const combo of combos) {
        for (const value of values) next.push({ ...combo, [criterion.key]: [value] })
      }
      combos = next
    }
    return combos
  }, [linkForm])

  const selectedCombinationCount = useMemo(() => {
    if (!linkForm) return 0
    const sizes = CRITERIA.map((c) => (linkForm.selections[c.key] ?? []).length).filter((n) => n > 0)
    if (sizes.length < 2) return 0
    return sizes.reduce((total, n) => total * n, 1)
  }, [linkForm])

  const describeSelections = (selections: Selections) =>
    CRITERIA.flatMap((c) => {
      const id = selections[c.key]?.[0]
      if (!id) return []
      return [`${c.label}: ${libraryItem(c.library, id)?.code ?? id}`]
    }).join(' + ')

  const saveLink = async () => {
    if (!linkForm) return
    const chosenCount = CRITERIA.filter((c) => (linkForm.selections[c.key] ?? []).length > 0).length
    if (chosenCount < 2) {
      setLinkError('Select at least two workspace code criteria (for example Operation + Activity, or NPT + Cause + Agency).')
      return
    }
    const nptSelected = (linkForm.selections.npt ?? []).length > 0
    const problem = classificationProblem(linkForm.default_classification, linkForm.default_allocation, nptSelected)
    if (problem) {
      setLinkError(problem)
      return
    }
    if (!linkForm.rowId && fanOut.length === 0) {
      setLinkError(
        `This selection would create ${selectedCombinationCount.toLocaleString()} links at once, and one save ` +
          `accepts at most ${LINK_BATCH_LIMIT}. Narrow the selection or save it in smaller batches.`,
      )
      return
    }
    if (!linkForm.rowId && fanOut.length > 1) {
      const items: OpsCodeLinkInput[] = fanOut.map((selection) => ({
        rule_name: linkForm.rule_name,
        scope: asScope(linkForm.scope),
        default_classification: asClassification(linkForm.default_classification),
        default_allocation: asAllocation(linkForm.default_allocation),
        note: linkForm.note,
        ...Object.fromEntries(
          CRITERIA.map((c) => [c.linkId, selection[c.key]?.[0] ?? null]),
        ),
      }))
      setLinkError('')
      await run(async () => {
        const result = await opsCreateCodeLinksBatch(items)
        setLinkForm(null)
        setNotice(`Linked ${result.created_count} criterion combination${result.created_count === 1 ? '' : 's'}.`)
      })
      return
    }
    const item: OpsCodeLinkInput = {
      rule_name: linkForm.rule_name,
      scope: asScope(linkForm.scope),
      default_classification: asClassification(linkForm.default_classification),
      default_allocation: asAllocation(linkForm.default_allocation),
      note: linkForm.note,
      ...Object.fromEntries(CRITERIA.map((c) => [c.linkId, linkForm.selections[c.key]?.[0] ?? null])),
    }
    setLinkError('')
    await run(async () => {
      if (linkForm.rowId) await opsUpdateCodeLink(linkForm.rowId, item)
      else await opsCreateCodeLink(item)
      setLinkForm(null)
    })
  }

  const runPending = async () => {
    if (!pending) return
    const fn =
      pending.type === 'correlation'
        ? pending.action === 'delete'
          ? opsDeleteCorrelations
          : pending.action === 'restore'
            ? opsRestoreCorrelations
            : opsPurgeCorrelations
        : pending.action === 'delete'
          ? opsDeleteCodeLinks
          : pending.action === 'restore'
            ? opsRestoreCodeLinks
            : opsPurgeCodeLinks
    await run(async () => {
      await fn(pending.ids)
      setPending(null)
    })
  }

  const targetLabelFor = (row: OpsCorrelation) => {
    if (row.extra_criteria_summary) return `${row.target_label} · ${row.extra_criteria_summary}`
    return row.target_label
  }

  const focusRows = (code: string) =>
    rows.filter((r) => code && Object.values(r as unknown as Record<string, unknown>).includes(code))
  const focusLinks = (code: string) =>
    links.filter((l) => code && Object.values(l as unknown as Record<string, unknown>).includes(code))
  const visibleRows = focusCode ? focusRows(focusCode) : rows
  const visibleLinks = focusCode ? focusLinks(focusCode) : links

  // ---- Schematic data -----------------------------------------------------
  const hierarchyRoot = useMemo<TreeNode>(() => {
    const phases = new Map<string, TreeNode>()
    for (const link of visibleLinks) {
      const phaseKey = link.phase_code_id || '__none'
      const phaseLabel = link.phase_label || 'No phase set'
      let phaseNode = phases.get(phaseKey)
      if (!phaseNode) {
        phaseNode = { id: `phase:${phaseKey}`, label: phaseLabel, meta: undefined, tone: 'info', children: [] }
        phases.set(phaseKey, phaseNode)
      }
      const opKey = `${phaseKey}/${link.operation_code_id || '__none'}`
      let opNode = phaseNode.children!.find((n) => n.id === `op:${opKey}`)
      if (!opNode) {
        opNode = {
          id: `op:${opKey}`,
          label: link.operation_label || 'No operation code',
          children: [],
        }
        phaseNode.children!.push(opNode)
      }
      const actKey = `${opKey}/${link.activity_code_id || '__none'}`
      let actNode = opNode.children!.find((n) => n.id === `act:${actKey}`)
      if (!actNode) {
        actNode = {
          id: `act:${actKey}`,
          label: link.activity_label || 'No activity code',
          rule: { type: 'link', id: link.id },
          children: [],
        }
        opNode.children!.push(actNode)
      }
      for (const criterion of CRITERIA) {
        if (criterion.key === 'phase' || criterion.key === 'operation' || criterion.key === 'activity') continue
        const raw = (link as unknown as Record<string, string | null>)[criterion.linkId]
        if (!raw) continue
        actNode.children!.push({
          id: `leaf:${link.id}:${criterion.key}`,
          label: `${criterion.label}: ${(link as unknown as Record<string, string>)[criterion.linkLabel] || raw}`,
          tone: toneFor(criterion.key),
          meta: 'workspace code link',
        })
      }
    }
    for (const phaseNode of phases.values()) {
      if (!phaseNode.children!.length) {
        delete phaseNode.children
      }
    }
    return {
      id: 'operational-root',
      label: 'Operational hierarchy',
      meta: 'Phase → Operation → Activity → NPT / Cause / Agency',
      children: [...phases.values()],
    }
  }, [visibleLinks])

  const sourceRoot = useMemo<TreeNode>(() => {
    const families = new Map<string, TreeNode>()
    for (const row of visibleRows) {
      const familyKey = row.source_family || 'Unfiled printed family'
      let familyNode = families.get(familyKey)
      if (!familyNode) {
        familyNode = { id: `family:${familyKey}`, label: familyKey, tone: 'info', children: [] }
        families.set(familyKey, familyNode)
      }
      const printedNode: TreeNode = {
        id: `printed:${row.id}`,
        label: row.source_code,
        meta: row.source_label,
        rule: { type: 'correlation', id: row.id },
        children: [
          {
            id: `target:${row.id}`,
            label: row.target_label || 'Workspace code',
            tone: 'success',
            meta: `${row.kind} code · ${row.scope ? row.scope : 'every scope'}`,
            children: row.extra_criteria_summary
              ? [
                  {
                    id: `criteria:${row.id}`,
                    label: 'Companion criteria',
                    meta: row.extra_criteria_summary,
                  },
                ]
              : undefined,
          },
        ],
      }
      familyNode.children!.push(printedNode)
    }
    return {
      id: 'source-root',
      label: 'Source mapping',
      meta: 'Family → Printed → Workspace → Criteria',
      children: [...families.values()],
    }
  }, [visibleRows])

  const coverage = useMemo(() => {
    const cr = ref?.library ?? {}
    return CRITERIA.map((criterion) => {
      const items = cr[criterion.library] ?? []
      const linked = items.filter((i) => (i.correlation_count ?? 0) > 0)
      return {
        criterion,
        total: items.length,
        linked: linked.length,
        unlinked: items.filter((i) => (i.correlation_count ?? 0) === 0),
      }
    })
  }, [ref])

  const unlinkedCount = coverage.reduce((n, c) => n + c.unlinked.length, 0)
  const canCorrelate = can('ops-master:correlate')
  const canPurge = can('ops-master:permanent-delete')
  const treeBusy = busy

  return (
    <Box mt={1.5} data-testid="operations-correlations">
      <Alert severity="info" sx={{ mb: 1.5 }}>
        Extraction pre-selects a dropdown only when a correlation exists. No correlation leaves the field empty so the
        engineer chooses from this workspace&rsquo;s own library. Correlating a code never approves a block and never
        changes an already saved report.
      </Alert>
      {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setNotice('')}>{notice}</Alert>}
      {focusCode && (
        <Alert severity="info" sx={{ mb: 1.5 }} onClose={() => onClearFocus?.()}>
          Showing only rules that reference this workspace code. Clear the filter to see every rule.
        </Alert>
      )}

      <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center" mb={1.5}>
        <TextField
          select
          label="Code kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          sx={{ minWidth: 210 }}
        >
          <MenuItem value="">All kinds</MenuItem>
          {CORRELATION_KINDS.map((k) => (
            <MenuItem key={k.key} value={k.key}>
              {k.label}
            </MenuItem>
          ))}
        </TextField>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={view}
          onChange={(_e, next: 'table' | 'tree' | null) => next && setView(next)}
          aria-label="Correlation view"
        >
          <ToggleButton value="table" sx={{ px: 2, textTransform: 'none', fontWeight: 700 }}>
            Table view
          </ToggleButton>
          <ToggleButton value="tree" sx={{ px: 2, textTransform: 'none', fontWeight: 700 }}>
            Tree schematic
          </ToggleButton>
        </ToggleButtonGroup>
        <Button variant="outlined" onClick={() => { setDeleted(!deleted); setNotice('') }}>
          {deleted ? 'Active rules' : 'Deleted entries'}
        </Button>
        {!deleted && canCorrelate && (
          <>
            <Button
              variant="contained"
              startIcon={<AddRounded />}
              onClick={() => {
                setFormError('')
                setCompanionOpen(false)
                setForm(emptyCorrelation())
              }}
            >
              Add correlation
            </Button>
            <Button variant="outlined" onClick={() => { setBatchError(''); setBatch([{ kind: defaultKind(kind), printed_key: '', target_id: '' }]) }}>
              Batch correlate
            </Button>
            <Button variant="outlined" onClick={() => openLink()}>
              Link criteria
            </Button>
          </>
        )}
      </Box>

      {view === 'tree' ? (
        <Stack gap={2}>
          <SectionCard
            title="Operational hierarchy"
            subtitle="Phase → Operation → Activity → NPT / Cause / Agency, built from the active multi-criteria code links."
          >
            {visibleLinks.length ? (
              <CorrelationTree
                label="Operational hierarchy"
                root={hierarchyRoot}
                handlers={{
                  busy: treeBusy,
                  onEditRule: (type, id) => {
                    const link = links.find((l) => l.id === id)
                    if (type === 'link' && link && !deleted) openLink(link)
                  },
                  onUnlink: (type, id) => {
                    if (deleted) return
                    setPending({ type, ids: [id], action: 'delete' })
                  },
                }}
              />
            ) : (
              <Typography color="text.secondary" fontSize={12.5}>
                No multi-criteria code links yet. Choose <strong>Link criteria</strong> to join two or more workspace codes.
              </Typography>
            )}
          </SectionCard>
          <SectionCard
            title="Source mapping"
            subtitle="Printed family → printed code → the workspace code it pre-selects → any companion criteria."
          >
            {visibleRows.length ? (
              <CorrelationTree
                label="Source mapping"
                root={sourceRoot}
                handlers={{
                  busy: treeBusy,
                  onEditRule: (type, id) => {
                    const row = rows.find((r) => r.id === id)
                    if (type === 'correlation' && row && !deleted) {
                      setCompanionOpen(Boolean(row.extra_criteria_summary))
                      setFormError('')
                      setForm({
                        ...emptyCorrelation(),
                        rowId: row.id,
                        kind: row.kind,
                        printed_key: printedKey(row.source_family, row.source_code),
                        target_id: row.target_id ?? '',
                        scope: asScope(row.scope ?? ''),
                        target_classification: asClassification(row.target_classification ?? ''),
                        target_allocation: asAllocation(row.target_allocation ?? ''),
                        note: row.note,
                      })
                    }
                  },
                  onUnlink: (type, id) => {
                    if (deleted) return
                    setPending({ type, ids: [id], action: 'delete' })
                  },
                }}
              />
            ) : (
              <Typography color="text.secondary" fontSize={12.5}>
                No correlations yet. Add one so a printed token can pre-select a workspace code.
              </Typography>
            )}
          </SectionCard>
          <SectionCard
            title="Library coverage & unlinked codes"
            subtitle="How many codes in each of the seven libraries are referenced by a rule, and which ones still are unlinked."
          >
            <Box display="grid" gap={1.5} gridTemplateColumns="repeat(auto-fit,minmax(230px,1fr))" mb={2}>
              {coverage.map(({ criterion, total, linked }) => (
                <Box key={criterion.key} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, p: 1.25 }}>
                  <Typography fontSize={11} textTransform="uppercase" letterSpacing=".08em" color="text.secondary" fontWeight={800}>
                    {criterion.label}
                  </Typography>
                  <Typography fontSize={20} fontWeight={800}>
                    {linked}/{total}
                  </Typography>
                  <Typography fontSize={11.5} color="text.secondary">
                    codes referenced by a rule
                  </Typography>
                </Box>
              ))}
            </Box>
            {unlinkedCount ? (
              <Box display="flex" gap={0.75} flexWrap="wrap">
                {coverage.flatMap(({ criterion, unlinked }) =>
                  unlinked.slice(0, 12).map((item) => (
                    <Tag key={`${criterion.key}:${item.id}`} tone="neutral">
                      {criterion.label}: {item.code}
                    </Tag>
                  )),
                )}
                {unlinkedCount > 12 && <Tag tone="neutral">+{unlinkedCount - 12} more unlinked</Tag>}
              </Box>
            ) : (
              <Typography fontSize={12.5} color="text.secondary">
                Every workspace code in the seven libraries is referenced by at least one rule.
              </Typography>
            )}
          </SectionCard>
        </Stack>
      ) : (
        <>
          <SectionCard
            title={deleted ? 'Deleted correlations' : 'Printed-code correlations'}
            subtitle="A printed token maps onto one workspace code. Companion criteria pin the scope, classification or a second code."
            sx={{ mb: 2 }}
            bodyPadding={0}
          >
            <DataTable
              key={`${kind}/${deleted}`}
              rows={visibleRows as unknown as Record<string, unknown>[]}
              searchPlaceholder="Search printed code, meaning or library code…"
              canExport={can('ops-master:export')}
              onExport={auditExport('library')}
              exportName="operations-correlations"
              columns={[
                { field: 'kind', headerName: 'Kind', minWidth: 110 },
                { field: 'source_family', headerName: 'Printed family', minWidth: 190 },
                { field: 'source_code', headerName: 'Printed code', minWidth: 120 },
                { field: 'source_label', headerName: 'Printed meaning', minWidth: 240, tooltipField: 'source_label' },
                {
                  field: 'target_label',
                  headerName: 'Workspace code',
                  minWidth: 240,
                  tooltipField: 'target_label',
                  valueFormatter: (p) => targetLabelFor(p.data as OpsCorrelation),
                },
                { field: 'note', headerName: 'Note', minWidth: 180, tooltipField: 'note' },
                {
                  headerName: 'Actions',
                  width: 240,
                  minWidth: 230,
                  sortable: false,
                  cellRenderer: ({ data: row }: { data: OpsCorrelation }) => (
                    <>
                      {!deleted && canCorrelate && (
                        <Button
                          size="small"
                          onClick={() => {
                            setCompanionOpen(Boolean(row.extra_criteria_summary))
                            setFormError('')
                            setForm({
                              ...emptyCorrelation(),
                              rowId: row.id,
                              kind: row.kind,
                              printed_key: printedKey(row.source_family, row.source_code),
                              target_id: row.target_id ?? '',
                              scope: asScope(row.scope ?? ''),
                              target_classification: asClassification(row.target_classification ?? ''),
                              target_allocation: asAllocation(row.target_allocation ?? ''),
                              note: row.note,
                            })
                          }}
                        >
                          Edit
                        </Button>
                      )}
                      {canCorrelate && (
                        <Button
                          size="small"
                          color={deleted ? 'inherit' : 'error'}
                          disabled={busy}
                          onClick={() => setPending({ type: 'correlation', ids: [row.id], action: deleted ? 'restore' : 'delete' })}
                        >
                          {deleted ? 'Restore' : 'Delete'}
                        </Button>
                      )}
                      {deleted && canPurge && (
                        <Button
                          size="small"
                          color="error"
                          disabled={busy}
                          onClick={() => setPending({ type: 'correlation', ids: [row.id], action: 'purge' })}
                        >
                          Delete permanently
                        </Button>
                      )}
                    </>
                  ),
                },
              ]}
            />
          </SectionCard>

          <SectionCard
            title={deleted ? 'Deleted multi-criteria code links' : 'Multi-criteria workspace code links'}
            subtitle="Two or more workspace codes joined as one rule. Extraction fills an empty dropdown only when every active link agrees."
            bodyPadding={0}
          >
            <DataTable
              key={`links/${deleted}`}
              rows={visibleLinks as unknown as Record<string, unknown>[]}
              searchPlaceholder="Search linked codes or a rule name…"
              canExport={can('ops-master:export')}
              onExport={auditExport('library')}
              exportName="operations-code-links"
              columns={[
                { field: 'rule_name', headerName: 'Rule name', minWidth: 170 },
                { field: 'summary_label', headerName: 'Linked criteria', minWidth: 380, flex: 2, tooltipField: 'summary_label' },
                { field: 'scope', headerName: 'Scope', minWidth: 100 },
                { field: 'default_classification', headerName: 'Class', minWidth: 95 },
                { field: 'default_allocation', headerName: 'Allocation', minWidth: 105 },
                { field: 'criteria_count', headerName: 'Criteria', minWidth: 95 },
                {
                  headerName: 'Actions',
                  width: 260,
                  minWidth: 250,
                  sortable: false,
                  cellRenderer: ({ data: row }: { data: OpsCodeLink }) => (
                    <>
                      {!deleted && canCorrelate && (
                        <Button size="small" onClick={() => openLink(row)}>
                          Edit
                        </Button>
                      )}
                      {canCorrelate && (
                        <Button
                          size="small"
                          color={deleted ? 'inherit' : 'error'}
                          disabled={busy}
                          onClick={() => setPending({ type: 'link', ids: [row.id], action: deleted ? 'restore' : 'delete' })}
                        >
                          {deleted ? 'Restore' : 'Delete'}
                        </Button>
                      )}
                      {deleted && canPurge && (
                        <Button
                          size="small"
                          color="error"
                          disabled={busy}
                          onClick={() => setPending({ type: 'link', ids: [row.id], action: 'purge' })}
                        >
                          Delete permanently
                        </Button>
                      )}
                    </>
                  ),
                },
              ]}
            />
          </SectionCard>
        </>
      )}

      {/* ---- Correlation dialog ------------------------------------------- */}
      {form && (
        <FormDialog
          open
          title={form.rowId ? 'Edit a correlation' : 'Correlate a printed code'}
          subtitle="The printed left-hand code is read from the source document. The right-hand value is what this workspace wants the dropdown to show. Extraction still asks the engineer to accept it."
          onClose={() => {
            setForm(null)
            setCompanionOpen(false)
          }}
          onSubmit={() => void saveCorrelation()}
          busy={busy}
          submitDisabled={!form.target_id || (!form.rowId && form.kind !== 'agency' && !form.printed_key)}
        >
          <Box display="grid" gap={2} pt={0.5}>
            {formError && <Alert severity="error">{formError}</Alert>}
            <TextField
              select
              label="Code kind"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as CorrelationForm['kind'], target_id: '', printed_key: '' })}
              disabled={Boolean(form.rowId)}
              helperText={form.rowId ? 'A saved correlation keeps its code kind; add a new rule to use another kind.' : 'Kind decides which library the printed token can come from.'}
            >
              {CORRELATION_KINDS.map((k) => (
                <MenuItem key={k.key} value={k.key}>
                  {k.label}
                </MenuItem>
              ))}
            </TextField>
            {form.kind === 'agency' ? (
              <TextField
                label="Printed agency token"
                value={form.free_agency}
                disabled={Boolean(form.rowId)}
                onChange={(e) => setForm({ ...form, free_agency: e.target.value })}
                helperText="Agency names are operator data, not a built-in catalogue. Type the token exactly as the source document writes it; it is matched case-insensitively."
              />
            ) : (
              <>
                <Autocomplete<Printed, false, false, false>
                  options={printedOptions}
                  disabled={Boolean(form.rowId)}
                  value={printedSelection}
                  onChange={(_e, next) => {
                    setForm({
                      ...form,
                      printed_key: next ? printedKey(next.family, next.code) : '',
                      target_id: '',
                    })
                  }}
                  getOptionLabel={(p) => `${p.code} — ${p.name || p.description || p.family}`}
                  isOptionEqualToValue={(a, b) => a.family === b.family && a.code === b.code}
                  renderOption={(props, p) => {
                    const { key, ...rest } = props as typeof props & { key: string }
                    return (
                      <Box component="li" key={key} {...rest} sx={{ display: 'block !important' }}>
                        <Typography fontSize={13} fontWeight={700}>
                          {p.code} — {p.name || p.family}
                        </Typography>
                        <Typography fontSize={11.5} color="text.secondary">
                          {p.family}
                          {p.detail ? ` · ${p.detail}` : ''}
                        </Typography>
                      </Box>
                    )
                  }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Printed default code"
                      helperText={
                        form.rowId
                          ? 'A saved correlation keeps its printed token.'
                          : 'Only codes in the built-in reference can be correlated; each printed token appears once per kind.'
                      }
                    />
                  )}
                />
                {printedSelection?.detail && (
                  <Alert severity="info" icon={false}>
                    <strong>{printedSelection.code}</strong> — {printedSelection.detail}
                  </Alert>
                )}
              </>
            )}
            <Autocomplete<OpsCorrelationLibraryItem, false, false, false>
              options={libraryFor(form.kind)}
              value={form.target_id ? (libraryItem(form.kind, form.target_id) ?? null) : null}
              onChange={(_e, next) => setForm({ ...form, target_id: next?.id ?? '' })}
              getOptionLabel={(item) => `${item.code} — ${item.name}`}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              noOptionsText="This library has no codes yet. Add one on its tab first."
              renderInput={(params) => (
                <TextField {...params} label="Workspace code" helperText="The value extraction should pre-select for this printed token." />
              )}
            />
            <TextField
              label="Note"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              multiline
              minRows={2}
              helperText="Optional. Record why this printed code maps to that workspace code."
            />
            <Box>
              <Button size="small" onClick={() => setCompanionOpen(!companionOpen)} aria-expanded={companionOpen}>
                {companionOpen ? 'Hide companion criteria' : 'Add companion criteria'}
              </Button>
              <Collapse in={companionOpen}>
                <Box display="grid" gap={2} pt={1.5}>
                  <Typography fontSize={12.5} color="text.secondary">
                    Companion criteria are optional. They pin the same printed token to a scope, a classification, or a
                    second workspace code (for example NPT + Cause + Agency).
                  </Typography>
                  <Box display="flex" gap={2} flexWrap="wrap">
                    <TextField
                      select
                      label="Scope"
                      value={form.scope}
                      onChange={(e) => setForm({ ...form, scope: asScope(e.target.value) })}
                      sx={{ minWidth: 170 }}
                    >
                      {SCOPES.map((s) => (
                        <MenuItem key={s.key} value={s.key}>
                          {s.label}
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      select
                      label="Classification"
                      value={form.target_classification}
                      onChange={(e) => setForm({ ...form, target_classification: asClassification(e.target.value) })}
                      sx={{ minWidth: 170 }}
                    >
                      {CLASSES.map((c) => (
                        <MenuItem key={c || 'none'} value={c}>
                          {c || 'Unset'}
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      select
                      label="Allocation"
                      value={form.target_allocation}
                      onChange={(e) => setForm({ ...form, target_allocation: asAllocation(e.target.value) })}
                      sx={{ minWidth: 170 }}
                    >
                      {ALLOCATIONS.map((a) => (
                        <MenuItem key={a || 'none'} value={a}>
                          {a || 'Unset'}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Box>
                  {CRITERIA.filter((c) => c.key !== form.kind && c.key !== 'mark').map((criterion) => (
                    <Autocomplete<OpsCorrelationLibraryItem, false, false, false>
                      key={criterion.key}
                      options={libraryFor(criterion.library)}
                      value={
                        (form as unknown as Record<string, string | null>)[criterion.corrId]
                          ? (libraryItem(criterion.library, (form as unknown as Record<string, string>)[criterion.corrId]) ?? null)
                          : null
                      }
                      onChange={(_e, next) =>
                        setForm({ ...form, [criterion.corrId]: next?.id ?? null } as typeof form)
                      }
                      getOptionLabel={(item) => `${item.code} — ${item.name}`}
                      isOptionEqualToValue={(a, b) => a.id === b.id}
                      renderInput={(params) => <TextField {...params} label={`Companion ${criterion.label.toLowerCase()} code`} />}
                    />
                  ))}
                </Box>
              </Collapse>
            </Box>
          </Box>
        </FormDialog>
      )}

      {/* ---- Batch correlate ---------------------------------------------- */}
      {batch && (
        <FormDialog
          open
          maxWidth="lg"
          title="Batch correlate printed codes"
          subtitle="Every row is validated before anything is written: one invalid row cancels the whole batch, so the library never ends up half-mapped."
          onClose={() => setBatch(null)}
          onSubmit={() => void saveBatch()}
          busy={busy}
          submitDisabled={batch.every((r) => !r.printed_key || !r.target_id)}
        >
          <Stack gap={1.5} pt={0.5}>
            {batchError && <Alert severity="error">{batchError}</Alert>}
            <Alert severity="info">
              Rows are saved in one transaction. A duplicate printed token — inside the batch or already in the library —
              rejects the whole batch with the row number.
            </Alert>
            {batch.map((row, index) => (
              <Box key={index} display="grid" gap={1.25} gridTemplateColumns={{ xs: '1fr', md: '160px 1fr 1fr 40px' }} alignItems="center">
                <TextField
                  select
                  size="small"
                  label={`Row ${index + 1} kind`}
                  value={row.kind}
                  onChange={(e) => {
                    const next = [...batch]
                    next[index] = { ...row, kind: e.target.value as OpsCorrelationInput['kind'], printed_key: '' }
                    setBatch(next)
                  }}
                >
                  {CORRELATION_KINDS.map((k) => (
                    <MenuItem key={k.key} value={k.key}>
                      {k.label}
                    </MenuItem>
                  ))}
                </TextField>
                <Autocomplete<Printed, false, false, false>
                  size="small"
                  options={(ref?.printed ?? []).filter((p) => (PRINTED_FAMILIES[row.kind] ?? []).includes(p.family))}
                  value={(ref?.printed ?? []).find((p) => printedKey(p.family, p.code) === row.printed_key) ?? null}
                  onChange={(_e, next) => {
                    const copy = [...batch]
                    copy[index] = { ...row, printed_key: next ? printedKey(next.family, next.code) : '' }
                    setBatch(copy)
                  }}
                  getOptionLabel={(p) => `${p.code} — ${p.name || p.description || p.family}`}
                  isOptionEqualToValue={(a, b) => a.family === b.family && a.code === b.code}
                  renderInput={(params) => <TextField {...params} label="Printed code" />}
                />
                <Autocomplete<OpsCorrelationLibraryItem, false, false, false>
                  size="small"
                  options={libraryFor(row.kind)}
                  value={row.target_id ? (libraryItem(row.kind, row.target_id) ?? null) : null}
                  onChange={(_e, next) => {
                    const copy = [...batch]
                    copy[index] = { ...row, target_id: next?.id ?? '' }
                    setBatch(copy)
                  }}
                  getOptionLabel={(item) => `${item.code} — ${item.name}`}
                  isOptionEqualToValue={(a, b) => a.id === b.id}
                  renderInput={(params) => <TextField {...params} label="Workspace code" />}
                />
                <Button
                  size="small"
                  color="error"
                  aria-label={`Remove row ${index + 1}`}
                  disabled={batch.length === 1}
                  onClick={() => setBatch(batch.filter((_, i) => i !== index))}
                >
                  Remove
                </Button>
              </Box>
            ))}
            <Box>
              <Button
                size="small"
                startIcon={<AddRounded />}
                onClick={() => setBatch([...batch, { kind: defaultKind(kind), printed_key: '', target_id: '' }])}
              >
                Add another row
              </Button>
            </Box>
          </Stack>
        </FormDialog>
      )}

      {/* ---- Link criteria dialog ----------------------------------------- */}
      {linkForm && (
        <FormDialog
          open
          maxWidth="md"
          title={linkForm.rowId ? 'Edit a multi-criteria code link' : 'Link workspace code criteria'}
          subtitle="Choose two or more workspace codes that belong together. Extraction fills a remaining empty dropdown only when every active link agrees on the same value."
          onClose={() => setLinkForm(null)}
          onSubmit={() => void saveLink()}
          busy={busy}
        >
          <Stack gap={1.75} pt={0.5}>
            {linkError && <Alert severity="error">{linkError}</Alert>}
            <Alert severity="info">
              A link never edits a saved report. It only fills a field the extraction left empty, and the block still
              waits for the engineer&rsquo;s confirmation.
            </Alert>
            <TextField
              label="Rule name (optional)"
              value={linkForm.rule_name}
              onChange={(e) => setLinkForm({ ...linkForm, rule_name: e.target.value })}
              helperText="A short name makes the rule easy to find in the table and the schematic."
            />
            <Box display="flex" gap={2} flexWrap="wrap">
              <TextField
                select
                label="Scope"
                value={linkForm.scope}
                onChange={(e) => setLinkForm({ ...linkForm, scope: asScope(e.target.value) })}
                sx={{ minWidth: 170 }}
              >
                {SCOPES.map((s) => (
                  <MenuItem key={s.key} value={s.key}>
                    {s.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Default classification"
                value={linkForm.default_classification}
                onChange={(e) => setLinkForm({ ...linkForm, default_classification: asClassification(e.target.value) })}
                sx={{ minWidth: 185 }}
              >
                {CLASSES.map((c) => (
                  <MenuItem key={c || 'none'} value={c}>
                    {c || 'Unset'}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Default allocation"
                value={linkForm.default_allocation}
                onChange={(e) => setLinkForm({ ...linkForm, default_allocation: asAllocation(e.target.value) })}
                sx={{ minWidth: 185 }}
              >
                {ALLOCATIONS.map((a) => (
                  <MenuItem key={a || 'none'} value={a}>
                    {a || 'Unset'}
                  </MenuItem>
                ))}
              </TextField>
            </Box>
            {CRITERIA.map((criterion) => (
              <Autocomplete<OpsCorrelationLibraryItem, true, false, false>
                key={criterion.key}
                multiple
                disableCloseOnSelect
                size="small"
                options={libraryFor(criterion.library)}
                value={(linkForm.selections[criterion.key] ?? []).map((id) => libraryItem(criterion.library, id) ?? { id, code: id, name: '' })}
                onChange={(_e, next) =>
                  setLinkForm({
                    ...linkForm,
                    selections: { ...linkForm.selections, [criterion.key]: next.map((item) => item.id) },
                  })
                }
                getOptionLabel={(item) => `${item.code} — ${item.name}`}
                isOptionEqualToValue={(a, b) => a.id === b.id}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label={criterion.label}
                    helperText={
                      (linkForm.selections[criterion.key] ?? []).length > 1
                        ? 'Several values create one link per combination (fan-out).'
                        : undefined
                    }
                  />
                )}
              />
            ))}
            <TextField
              label="Note (optional)"
              value={linkForm.note}
              onChange={(e) => setLinkForm({ ...linkForm, note: e.target.value })}
              multiline
              minRows={2}
            />
            {!linkForm.rowId && (
              <Alert severity={fanOut.length ? 'success' : 'info'} icon={false}>
                {fanOut.length
                  ? `This saves ${fanOut.length} code link${fanOut.length === 1 ? '' : 's'}: ${fanOut
                      .slice(0, 2)
                      .map(describeSelections)
                      .join('; ')}${fanOut.length > 2 ? `; +${fanOut.length - 2} more` : ''}.`
                  : 'Select at least two criteria. Multiple values in a criterion fan out into one link per combination.'}
              </Alert>
            )}
          </Stack>
        </FormDialog>
      )}

      {/* ---- Delete / restore / purge confirmation ------------------------ */}
      {pending && (
        <FormDialog
          open
          danger={pending.action !== 'restore'}
          title={
            pending.action === 'delete'
              ? `Move ${pending.type === 'correlation' ? 'correlation' : 'code link'} to Deleted entries?`
              : pending.action === 'restore'
                ? `Restore ${pending.type === 'correlation' ? 'correlation' : 'code link'}?`
                : `Delete ${pending.type === 'correlation' ? 'correlation' : 'code link'} permanently?`
          }
          submitLabel={
            pending.action === 'delete'
              ? 'Move to Deleted entries'
              : pending.action === 'restore'
                ? 'Restore'
                : 'Delete permanently'
          }
          onClose={() => setPending(null)}
          onSubmit={() => void runPending()}
          busy={busy}
        >
          <Box display="grid" gap={2} pt={0.5}>
            {error && <Alert severity="error">{error}</Alert>}
            <Typography fontSize={13} color="text.secondary">
              {pending.action === 'delete' &&
                'Extraction stops applying this rule immediately. A code still referenced by an active rule cannot be deleted from its library tab until the rule is removed.'}
              {pending.action === 'restore' && 'The rule becomes active again and extraction starts applying it to new documents.'}
              {pending.action === 'purge' &&
                'A permanent delete cannot be undone. The audit trail keeps the rule’s identity, its target and who removed it.'}
            </Typography>
            {pending.action === 'purge' && (
              <Alert severity="warning" icon={false}>
                Delete the rule first; permanent deletion is offered only from Deleted entries.
              </Alert>
            )}
          </Box>
        </FormDialog>
      )}
    </Box>
  )
}
