import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useLocation } from 'react-router-dom'
import {
  AddRounded, ArrowForwardRounded, DeleteOutlineRounded, EditOutlined, HelpOutlineRounded,
  LockOutlined, MenuBookOutlined, RefreshRounded, SearchRounded, SendRounded, TuneRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, IconButton, InputAdornment, Link,
  MenuItem, Paper, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { AnswerCard, GuideIntro } from '../components/assistant/AnswerCard'
import { useAuth } from '../context/AuthContext'
import {
  ASSISTANT_CATEGORIES, askGuide, assistantHistory, assistantMemory, assistantOverview,
  createAssistantMemory, deleteAssistantMemory, updateAssistantMemory,
  type AssistantAnswer, type AssistantConversation, type AssistantMemoryCategory,
  type AssistantMemoryEntry, type AssistantOverview,
} from '../lib/assistant'

type MemoryDraft = {
  title: string
  category: AssistantMemoryCategory
  keywords: string
  body: string
  steps: string
  route: string
  permission: string
}

const EMPTY_DRAFT: MemoryDraft = {
  title: '', category: 'faq', keywords: '', body: '', steps: '', route: '', permission: '',
}

function draftFrom(entry: AssistantMemoryEntry): MemoryDraft {
  return {
    title: entry.title,
    category: entry.category,
    keywords: entry.keywords,
    body: entry.body,
    steps: entry.steps.join('\n'),
    route: entry.route,
    permission: entry.permission,
  }
}

function MemoryRow({ entry, canManage, onEdit, onDelete }: {
  entry: AssistantMemoryEntry
  canManage: boolean
  onEdit: (entry: AssistantMemoryEntry) => void
  onDelete: (entry: AssistantMemoryEntry) => void
}) {
  const [open, setOpen] = useState(false)
  return <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
    <Box
      role="button" tabIndex={0} aria-expanded={open}
      onClick={() => setOpen(value => !value)}
      onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(value => !value) } }}
      sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1.5, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}
    >
      <Box minWidth={0} flex={1}>
        <Typography fontSize={13} fontWeight={700} noWrap>{entry.title}</Typography>
        <Box display="flex" alignItems="center" gap={.6} mt={.4} flexWrap="wrap">
          <Tag tone="neutral">{ASSISTANT_CATEGORIES.find(item => item.value === entry.category)?.label ?? entry.category}</Tag>
          {entry.is_system ? <Tag tone="info">Shipped</Tag> : <Tag tone="success">Workspace</Tag>}
          {entry.route && <Typography fontSize={11.5} color="text.secondary" fontFamily="monospace">{entry.route}</Typography>}
          {entry.permission && <Box display="flex" alignItems="center" gap={.3}>
            <LockOutlined sx={{ fontSize: 12, color: 'text.disabled' }}/>
            <Typography fontSize={11.5} color="text.secondary" fontFamily="monospace">{entry.permission}</Typography>
          </Box>}
        </Box>
      </Box>
      {!entry.is_system && canManage && <>
        <IconButton size="small" aria-label={`Edit ${entry.title}`} onClick={event => { event.stopPropagation(); onEdit(entry) }}><EditOutlined fontSize="small"/></IconButton>
        <IconButton size="small" aria-label={`Remove ${entry.title}`} onClick={event => { event.stopPropagation(); onDelete(entry) }}><DeleteOutlineRounded fontSize="small"/></IconButton>
      </>}
    </Box>
    {open && <Box sx={{ px: 1.7, pb: 1.6 }}>
      <Divider sx={{ mb: 1.2 }}/>
      <Typography fontSize={12.6} lineHeight={1.65} sx={{ whiteSpace: 'pre-line' }}>{entry.body}</Typography>
      {entry.steps.length > 0 && <Box component="ol" sx={{ mt: 1.2, mb: 0, pl: 2.2 }}>
        {entry.steps.map((step, index) => <Typography component="li" key={index} fontSize={12.2} lineHeight={1.6}>{step}</Typography>)}
      </Box>}
      {entry.keywords && <Typography fontSize={11.5} color="text.secondary" sx={{ mt: 1.1 }}>
        Matched on: <Box component="span" fontFamily="monospace">{entry.keywords}</Box>
      </Typography>}
      <Typography fontSize={11.5} color="text.secondary" sx={{ mt: .8 }}>
        {entry.is_system ? 'Shipped with the application; it cannot be edited or removed.'
          : `Workspace entry${entry.created_by_name ? ` by ${entry.created_by_name}` : ''}. You can edit or remove it.`}
      </Typography>
    </Box>}
  </Paper>
}

export default function Assistant() {
  const { can } = useAuth()
  const location = useLocation()
  const canManage = can('assistant:manage')
  const [tab, setTab] = useState<'ask' | 'memory'>('ask')

  const [overview, setOverview] = useState<AssistantOverview | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null)
  const [asked, setAsked] = useState<string>('')
  const [history, setHistory] = useState<AssistantConversation[]>([])
  const [error, setError] = useState('')

  const [memory, setMemory] = useState<AssistantMemoryEntry[]>([])
  const [memoryError, setMemoryError] = useState('')
  const [memoryLoading, setMemoryLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [onlyWorkspace, setOnlyWorkspace] = useState(false)
  const [dialog, setDialog] = useState<{ mode: 'create' | 'edit'; entry?: AssistantMemoryEntry } | null>(null)
  const [draft, setDraft] = useState<MemoryDraft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [pendingDelete, setPendingDelete] = useState<AssistantMemoryEntry | null>(null)

  const loadMemory = useCallback(async () => {
    setMemoryLoading(true)
    setMemoryError('')
    try {
      setMemory(await assistantMemory())
    } catch (failure) {
      setMemoryError((failure as Error).message)
    } finally {
      setMemoryLoading(false)
    }
  }, [])

  useEffect(() => {
    let alive = true
    void assistantOverview().then(value => { if (alive) setOverview(value) }).catch(() => undefined)
    void assistantHistory().then(value => { if (alive) setHistory(value) }).catch(() => undefined)
    return () => { alive = false }
  }, [])

  useEffect(() => { void loadMemory() }, [loadMemory])

  const ask = useCallback(async (text: string) => {
    const value = text.trim()
    if (!value || asking) return
    setAsking(true)
    setError('')
    setAsked(value)
    try {
      const result = await askGuide(value, location.pathname === '/assistant' ? '' : location.pathname)
      setAnswer(result)
      setQuestion('')
      void assistantHistory().then(setHistory).catch(() => undefined)
      void assistantOverview().then(setOverview).catch(() => undefined)
    } catch (failure) {
      setError((failure as Error).message)
      setAnswer(null)
    } finally {
      setAsking(false)
    }
  }, [asking, location.pathname])

  const openCreate = () => { setDraft(EMPTY_DRAFT); setDialogError(''); setDialog({ mode: 'create' }) }
  const openEdit = (entry: AssistantMemoryEntry) => { setDraft(draftFrom(entry)); setDialogError(''); setDialog({ mode: 'edit', entry }) }

  const saveMemory = async () => {
    if (!dialog) return
    if (draft.title.trim().length < 3) { setDialogError('Give the memory entry a title of at least three characters.'); return }
    if (draft.body.trim().length < 10) { setDialogError('Write the rule or explanation the guide must follow (at least ten characters).'); return }
    setSaving(true)
    setDialogError('')
    const payload = {
      title: draft.title.trim(),
      category: draft.category,
      keywords: draft.keywords.trim(),
      body: draft.body.trim(),
      steps: draft.steps.split('\n').map(step => step.trim()).filter(Boolean),
      route: draft.route.trim(),
      permission: draft.permission.trim(),
    }
    try {
      if (dialog.mode === 'edit' && dialog.entry) await updateAssistantMemory(dialog.entry.id, payload)
      else await createAssistantMemory(payload)
      setDialog(null)
      await loadMemory()
      void assistantOverview().then(setOverview).catch(() => undefined)
    } catch (failure) {
      setDialogError((failure as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const removeMemory = async () => {
    if (!pendingDelete) return
    setSaving(true)
    setDialogError('')
    try {
      await deleteAssistantMemory(pendingDelete.id)
      setPendingDelete(null)
      await loadMemory()
      void assistantOverview().then(setOverview).catch(() => undefined)
    } catch (failure) {
      setDialogError((failure as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return memory
      .filter(entry => !onlyWorkspace || !entry.is_system)
      .filter(entry => !needle || `${entry.title} ${entry.body} ${entry.keywords}`.toLowerCase().includes(needle))
      .sort((a, b) => (a.is_system === b.is_system ? a.sort_order - b.sort_order : a.is_system ? 1 : -1))
  }, [memory, search, onlyWorkspace])

  const workspaceCount = memory.filter(entry => !entry.is_system).length
  const quickPrompts = overview?.quick_prompts ?? []

  return <>
    <PageHeading
      eyebrow="Help & guide"
      title="Ask the guide"
      subtitle="The guide answers from recorded application memory and from your own workspace under your permissions. It never guesses a figure, never shows one you may not read, and always names the page that proves its answer."
      action={<>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => {
          void assistantOverview().then(setOverview).catch(() => undefined)
          void assistantHistory().then(setHistory).catch(() => undefined)
          void loadMemory()
        }}>Refresh</Button>
        {canManage && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add workspace memory</Button>}
      </>}
      meta={<>
        <Tag tone="info">{overview ? `${overview.memory_entries} memory entries` : 'Loading memory'}</Tag>
        {overview && overview.workspace_entries > 0 && <Tag tone="success">{overview.workspace_entries} written by this workspace</Tag>}
        {overview && overview.outstanding_checks > 0 && <Tag tone="warning">{overview.outstanding_checks} data checks outstanding</Tag>}
      </>}
    />

    <Tabs value={tab} onChange={(_, value: 'ask' | 'memory') => setTab(value)} sx={{ mb: 2.2 }}>
      <Tab value="ask" label="Ask" icon={<HelpOutlineRounded fontSize="small"/>} iconPosition="start"/>
      <Tab value="memory" label={`Memory (${memory.length})`} icon={<MenuBookOutlined fontSize="small"/>} iconPosition="start"/>
    </Tabs>

    {tab === 'ask' && <Box display="grid" gap={2.2} gridTemplateColumns={{ xs: '1fr', lg: 'minmax(0, 1.85fr) minmax(0, 1fr)' }}>
      <Box display="grid" gap={2} alignContent="start">
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
          <Box
            component="form"
            onSubmit={event => { event.preventDefault(); void ask(question) }}
            display="flex" gap={1.2} alignItems="flex-start" flexWrap={{ xs: 'wrap', sm: 'nowrap' }}
          >
            <TextField
              value={question} onChange={event => setQuestion(event.target.value)}
              placeholder="Ask about a workflow, a calculation, a figure or a page…"
              inputProps={{ maxLength: 500, 'aria-label': 'Your question for the guide' }}
              size="small" fullWidth autoFocus
              InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small"/></InputAdornment> }}
            />
            <Button
              type="submit" variant="contained" startIcon={<SendRounded/>} disabled={asking || !question.trim()}
              sx={{ flex: '0 0 auto', height: 40 }}
            >{asking ? 'Asking…' : 'Ask'}</Button>
          </Box>
          <Box display="flex" alignItems="center" gap={.7} flexWrap="wrap" mt={1.2}>
            <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} textTransform="uppercase" color="text.secondary">Try</Typography>
            {(quickPrompts.length ? quickPrompts : ['How are actual days calculated?', 'What is missing in my workspace?']).slice(0, 4).map(prompt => <Chip
              key={prompt} label={prompt} size="small" clickable onClick={() => void ask(prompt)}
              sx={{ height: 24, fontSize: 11.5, fontWeight: 600 }}
            />)}
          </Box>
        </Paper>

        {error && <ErrorMessage message={error}/>}

        {asking && <Paper variant="outlined" sx={{ p: 3, borderRadius: 2, display: 'flex', alignItems: 'center', gap: 1.4 }}>
          <CircularProgress size={18}/>
          <Box>
            <Typography fontSize={12.8} fontWeight={700}>{asked}</Typography>
            <Typography fontSize={11.5} color="text.secondary">Reading memory and the workspace figures you may see…</Typography>
          </Box>
        </Paper>}

        {!asking && answer && <>
          {asked && <Box display="flex" alignItems="center" gap={.8}>
            <Typography fontSize={11.5} fontWeight={800} letterSpacing={.6} textTransform="uppercase" color="text.secondary">Your question</Typography>
            <Typography fontSize={12.6} fontWeight={600} sx={{ overflowWrap: 'anywhere' }}>{asked}</Typography>
          </Box>}
          <AnswerCard answer={answer} onAsk={next => void ask(next)}/>
        </>}

        {!asking && !answer && !error && <GuideIntro prompts={quickPrompts} onAsk={next => void ask(next)}/>}

        {history.length > 0 && <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2 }}>
          <Typography className="eyebrow" sx={{ mb: .8 }}>Your recent questions</Typography>
          <Box display="flex" gap={.7} flexWrap="wrap">
            {history.slice(0, 8).map((entry, index) => <Chip
              key={`${entry.created_at}-${index}`} label={entry.question} size="small" clickable variant="outlined"
              onClick={() => void ask(entry.question)}
              sx={{ height: 25, fontSize: 11.5 }}
            />)}
          </Box>
          <Typography fontSize={11.5} color="text.secondary" sx={{ mt: 1 }}>
            The transcript is private to you; it is not shared with the workspace.
          </Typography>
        </Paper>}
      </Box>

      <Box display="grid" gap={2} alignContent="start">
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
          <Box display="flex" alignItems="center" justifyContent="space-between" mb={.6}>
            <Typography fontSize={13} fontWeight={800}>What is missing in this workspace</Typography>
            {overview && <Tag tone={overview.outstanding_checks ? 'warning' : 'success'}>
              {overview.outstanding_checks ? `${overview.outstanding_checks} to fill` : 'Nothing blocking'}
            </Tag>}
          </Box>
          <Typography fontSize={11.5} color="text.secondary" sx={{ mb: 1.4 }}>
            Only gaps you can act on appear here; each one blocks a clean cost figure.
          </Typography>
          {!overview && <Box display="flex" alignItems="center" gap={1}><CircularProgress size={14}/><Typography fontSize={11.5}>Checking your registers…</Typography></Box>}
          {overview && overview.checks.length === 0 && <Typography fontSize={12} color="text.secondary">
            Every read check passes: wells have their spud instants, plans are configured and no draft sheet is waiting.
          </Typography>}
          {overview?.checks.map(check => <Box key={check.label} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.1 }}>
            <Box display="flex" alignItems="baseline" justifyContent="space-between" gap={1}>
              <Typography fontSize={12.2} fontWeight={700}>{check.label}</Typography>
              <Typography fontSize={12.2} fontWeight={800} color="warning.main">{check.value}</Typography>
            </Box>
            <Typography fontSize={11.5} color="text.secondary" sx={{ mt: .3, lineHeight: 1.5 }}>{check.hint}</Typography>
            {check.route && <Link component={RouterLink} to={check.route} underline="hover" sx={{ display: 'inline-flex', alignItems: 'center', gap: .3, fontSize: 11.5, fontWeight: 700, mt: .5 }}>
              Fix it here <ArrowForwardRounded sx={{ fontSize: 13 }}/>
            </Link>}
          </Box>)}
        </Paper>

        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
          <Box display="flex" alignItems="center" gap={.8} mb={.8}>
            <MenuBookOutlined sx={{ fontSize: 17, color: 'primary.main' }}/>
            <Typography fontSize={13} fontWeight={800}>Memory</Typography>
          </Box>
          <Typography fontSize={11.5} color="text.secondary" sx={{ mb: 1.2 }}>
            {overview
              ? `${overview.memory_entries} entries: ${overview.memory_entries - overview.workspace_entries} shipped with WellCostIQ and ${overview.workspace_entries} written by this workspace.`
              : 'Reading the guide memory…'}
          </Typography>
          <Button size="small" variant="outlined" startIcon={<TuneRounded/>} onClick={() => setTab('memory')}>Read the memory</Button>
        </Paper>
      </Box>
    </Box>}

    {tab === 'memory' && <Box display="grid" gap={2}>
      <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2 }}>
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
          <TextField
            value={search} onChange={event => setSearch(event.target.value)} size="small" placeholder="Search memory…"
            inputProps={{ 'aria-label': 'Search the guide memory' }}
            sx={{ flex: '1 1 260px', maxWidth: 380 }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small"/></InputAdornment> }}
          />
          <Chip
            label={onlyWorkspace ? 'Workspace entries' : 'All entries'} clickable onClick={() => setOnlyWorkspace(value => !value)}
            variant={onlyWorkspace ? 'filled' : 'outlined'} color={onlyWorkspace ? 'primary' : 'default'}
            sx={{ fontWeight: 700, fontSize: 11.5, height: 28 }}
          />
          <Typography fontSize={11.5} color="text.secondary" sx={{ ml: 'auto' }}>
            {workspaceCount} workspace {workspaceCount === 1 ? 'entry' : 'entries'} · shipped entries cannot be changed
          </Typography>
          {canManage && <Button size="small" variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add</Button>}
        </Box>
      </Paper>

      {memoryError && <ErrorMessage message={memoryError}/>}

      {memoryLoading && memory.length === 0 && <Paper variant="outlined" sx={{ p: 3, borderRadius: 2, display: 'flex', alignItems: 'center', gap: 1.2 }}>
        <CircularProgress size={16}/><Typography fontSize={12.4}>Reading memory…</Typography>
      </Paper>}

      <Box display="grid" gap={1}>
        {filtered.map(entry => <MemoryRow
          key={entry.id} entry={entry} canManage={canManage}
          onEdit={openEdit} onDelete={setPendingDelete}
        />)}
      </Box>

      {!memoryLoading && filtered.length === 0 && <Paper variant="outlined" sx={{ p: 3, borderRadius: 2 }}>
        <Typography fontSize={12.6}>No memory entry matches that search.</Typography>
        {canManage && <Box mt={1.2}>
          <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={openCreate}>Write the rule this workspace needs</Button>
        </Box>}
      </Paper>}

      <Alert severity="info" sx={{ '& .MuiAlert-message': { fontSize: 11.5 } }}>
        A workspace memory entry is quoted by the guide the same way as a shipped one, so write rules that are
        true for every well: a local approval threshold, a cost-code convention, a required sign-off. Give it the
        words people actually type so the guide finds it, and point it at the page where the work happens.
      </Alert>
    </Box>}

    <FormDialog
      open={!!dialog} title={dialog?.mode === 'edit' ? 'Edit workspace memory' : 'Add workspace memory'}
      subtitle="The guide quotes this entry word for word whenever a question matches it. Keep it factual and short."
      onClose={() => setDialog(null)} onSubmit={() => void saveMemory()} busy={saving} submitLabel={dialog?.mode === 'edit' ? 'Save changes' : 'Add memory'}
      maxWidth="md"
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField
          label="Title" fullWidth value={draft.title} inputProps={{ maxLength: 180 }}
          onChange={event => setDraft(current => ({ ...current, title: event.target.value }))}
          helperText="What the entry answers, in one line — also the heading the guide shows."
        />
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
          <TextField
            select label="Category" value={draft.category}
            onChange={event => setDraft(current => ({ ...current, category: event.target.value as AssistantMemoryCategory }))}
          >
            {ASSISTANT_CATEGORIES.map(category => <MenuItem key={category.value} value={category.value}>{category.label}</MenuItem>)}
          </TextField>
          <TextField
            label="Page route (optional)" value={draft.route} placeholder="/afe"
            onChange={event => setDraft(current => ({ ...current, route: event.target.value }))}
            helperText="Where the work happens; the answer links to it."
          />
        </Box>
        <TextField
          label="Match words" fullWidth value={draft.keywords} inputProps={{ maxLength: 400 }}
          onChange={event => setDraft(current => ({ ...current, keywords: event.target.value }))}
          helperText="Space-separated words and short phrases people type: approval threshold sign-off drilling manager."
        />
        <TextField
          label="What the guide must say" fullWidth required multiline minRows={4} value={draft.body}
          inputProps={{ maxLength: 4000 }}
          onChange={event => setDraft(current => ({ ...current, body: event.target.value }))}
        />
        <TextField
          label="Steps (one per line, optional)" fullWidth multiline minRows={3} value={draft.steps}
          onChange={event => setDraft(current => ({ ...current, steps: event.target.value }))}
        />
        <TextField
          label="Required capability (optional)" fullWidth value={draft.permission} placeholder="afe:read"
          onChange={event => setDraft(current => ({ ...current, permission: event.target.value }))}
          helperText="Leave blank so everybody may read it. With a capability, callers without it are told which one is missing."
        />
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={!!pendingDelete} title="Remove this workspace memory?" danger submitLabel="Remove memory"
      subtitle={pendingDelete ? `“${pendingDelete.title}” will no longer be quoted by the guide.` : ''}
      onClose={() => setPendingDelete(null)} onSubmit={() => void removeMemory()} busy={saving} busyLabel="Removing…"
    >
      <Typography fontSize={12.6} color="text.secondary" lineHeight={1.6}>
        The answer it produced is not stored anywhere else, so remove it only when the rule has genuinely
        changed. Shipped memory is unaffected.
      </Typography>
      <ErrorMessage message={dialogError}/>
      <Box display="flex" alignItems="center" gap={.6} mt={1.4}>
        <LockOutlined sx={{ fontSize: 13, color: 'text.disabled' }}/>
        <Typography fontSize={11.5} color="text.secondary">This removal is written to the audit log.</Typography>
      </Box>
    </FormDialog>
  </>
}
