import { useCallback, useEffect, useState } from 'react'
import { Link as RouterLink, useLocation } from 'react-router-dom'
import {
  CloseRounded, MenuBookOutlined, OpenInNewRounded, SendRounded, SupportAgentOutlined,
} from '@mui/icons-material'
import {
  Box, Button, Chip, CircularProgress, Divider, Drawer, Fab, IconButton, InputAdornment,
  Link, TextField, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import { ErrorMessage } from '../Common'
import { AnswerCard } from './AnswerCard'
import { useAuth } from '../../context/AuthContext'
import { askGuide, assistantOverview, type AssistantAnswer, type AssistantOverview } from '../../lib/assistant'

/**
 * "Ask the guide" from anywhere in the workspace.
 *
 * The drawer keeps the page the user is on (`route`) so a question like "what is
 * this figure?" is answered with the page's own memory entry ranked first. It is
 * deliberately the same service and the same answer card as the full page: there
 * is no second, weaker assistant hidden in a corner.
 */
export default function AssistantLauncher() {
  const { can } = useAuth()
  const location = useLocation()
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const [open, setOpen] = useState(false)
  const [overview, setOverview] = useState<AssistantOverview | null>(null)
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('')
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    let alive = true
    void assistantOverview().then(value => { if (alive) setOverview(value) }).catch(() => undefined)
    return () => { alive = false }
  }, [open])

  // Alt+G opens the guide from anywhere, the same way the tooltip promises.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || event.ctrlKey || event.metaKey) return
      if (event.key.toLowerCase() !== 'g') return
      event.preventDefault()
      setOpen(value => !value)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const ask = useCallback(async (text: string) => {
    const value = text.trim()
    if (!value || asking) return
    setAsking(true)
    setError('')
    setAsked(value)
    try {
      setAnswer(await askGuide(value, location.pathname))
      setQuestion('')
    } catch (failure) {
      setError((failure as Error).message)
      setAnswer(null)
    } finally {
      setAsking(false)
    }
  }, [asking, location.pathname])

  if (!can('assistant:read')) return null

  return <>
    <Tooltip title="Ask the guide (Alt+G)" placement="left">
      <Fab
        color="primary" size="medium" aria-label="Ask the guide" onClick={() => setOpen(true)}
        sx={{ position: 'fixed', right: { xs: 16, sm: 24 }, bottom: { xs: 16, sm: 24 }, zIndex: 1150, boxShadow: 6 }}
      >
        <SupportAgentOutlined/>
      </Fab>
    </Tooltip>
    <Drawer anchor="right" open={open} onClose={() => setOpen(false)}
      PaperProps={{ sx: { width: fullScreen ? '100%' : 430, display: 'flex', flexDirection: 'column' } }}
      ModalProps={{ keepMounted: true }}
    >
      <Box display="flex" alignItems="center" gap={1} sx={{ px: 2, py: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}>
        <MenuBookOutlined sx={{ fontSize: 19, color: 'primary.main' }}/>
        <Box minWidth={0} flex={1}>
          <Typography fontSize={13.6} fontWeight={800}>Ask the guide</Typography>
          <Typography fontSize={11.5} color="text.secondary" noWrap>
            Recorded memory · your workspace · your permissions
          </Typography>
        </Box>
        <IconButton size="small" onClick={() => setOpen(false)} aria-label="Close the guide"><CloseRounded fontSize="small"/></IconButton>
      </Box>

      <Box sx={{ flex: 1, overflowY: 'auto', p: 2, display: 'grid', gap: 1.6, alignContent: 'start' }}>
        {overview && overview.outstanding_checks > 0 && <Box sx={{
          border: '1px solid', borderColor: 'divider', borderRadius: 1.6, p: 1.2, bgcolor: 'action.hover',
        }}>
          <Typography fontSize={11.5} fontWeight={700}>
            {overview.outstanding_checks} data {overview.outstanding_checks === 1 ? 'check needs' : 'checks need'} attention
          </Typography>
          <Typography fontSize={11.5} color="text.secondary" sx={{ mt: .2 }}>
            Ask “what is missing in my workspace?” for the list and the pages to fix it.
          </Typography>
        </Box>}

        {asked && <Box>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} textTransform="uppercase" color="text.secondary">You asked</Typography>
          <Typography fontSize={12.4} fontWeight={600} sx={{ overflowWrap: 'anywhere' }}>{asked}</Typography>
        </Box>}

        {asking && <Box display="flex" alignItems="center" gap={1.2} sx={{ py: 2 }}>
          <CircularProgress size={16}/>
          <Typography fontSize={11.5} color="text.secondary">Reading memory and your figures…</Typography>
        </Box>}

        {error && <ErrorMessage message={error}/>}

        {!asking && answer && <AnswerCard answer={answer} onAsk={next => void ask(next)}/>}

        {!asking && !answer && !error && <Box>
          <Typography fontSize={11.5} color="text.secondary" sx={{ lineHeight: 1.6, mb: 1 }}>
            The guide answers about workflows, calculations, data entry, navigation and this workspace's own
            figures. It never invents an answer and never shows a figure your role may not read.
          </Typography>
          <Box display="flex" gap={.7} flexWrap="wrap">
            {(overview?.quick_prompts ?? ['How are actual days calculated?', 'What is missing in my workspace?']).slice(0, 4).map(prompt => <Chip
              key={prompt} label={prompt} size="small" variant="outlined" clickable onClick={() => void ask(prompt)}
              sx={{ height: 25, fontSize: 11.5, fontWeight: 600 }}
            />)}
          </Box>
        </Box>}
      </Box>

      <Divider/>
      <Box sx={{ p: 1.6 }}>
        <Box
          component="form" display="flex" gap={1} alignItems="flex-start"
          onSubmit={event => { event.preventDefault(); void ask(question) }}
        >
          <TextField
            value={question} onChange={event => setQuestion(event.target.value)} size="small" fullWidth
            placeholder="Ask about this page, a figure or a rule…" inputProps={{ maxLength: 500, 'aria-label': 'Your question for the guide' }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SupportAgentOutlined fontSize="small"/></InputAdornment> }}
          />
          <IconButton type="submit" color="primary" disabled={asking || !question.trim()} aria-label="Send question">
            <SendRounded/>
          </IconButton>
        </Box>
        <Box display="flex" alignItems="center" justifyContent="space-between" mt={.8} gap={1}>
          <Link component={RouterLink} to="/assistant" onClick={() => setOpen(false)} underline="hover"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: .4, fontSize: 11.5, fontWeight: 700 }}
          >
            Open the full guide <OpenInNewRounded sx={{ fontSize: 13 }}/>
          </Link>
          <Button size="small" onClick={() => { setAnswer(null); setAsked(''); setError('') }}>Clear</Button>
        </Box>
      </Box>
    </Drawer>
  </>
}
