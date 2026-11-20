import { Link as RouterLink } from 'react-router-dom'
import {
  Alert, Box, Chip, Divider, Link, List, ListItem, ListItemText, Paper,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import { ArrowForwardRounded, CheckCircleOutlined, MenuBookOutlined, LockOutlined, RouteRounded } from '@mui/icons-material'
import { Tag } from '../Common'
import { AiStatusAlert } from './AiStatusAlert'
import { formatAiDuration } from '../../lib/ai'
import { confidenceLabel, isPermissionAnswer, type AssistantAnswer } from '../../lib/assistant'

/**
 * One answer, rendered exactly as the service returned it.
 *
 * Nothing here rephrases or rounds a figure: the sentence is the memory entry,
 * the computed statement, or the offline Ollama reply grounded in workspace data,
 * `facts` are the labelled numbers behind it, `steps` the order of work, and
 * `sources` the pages that prove it. A permission refusal is styled as a refusal
 * so it can never be mistaken for a figure.
 */
export function AnswerCard({ answer, onAsk, onRetryAi, onCheckAi }: {
  answer: AssistantAnswer
  /** Follow-up questions the caller can click, answered in place. */
  onAsk?: (question: string) => void
  onRetryAi?: () => void
  onCheckAi?: () => void
}) {
  const refused = isPermissionAnswer(answer)
  const pageSources = answer.sources.filter(source => source.route)
  const referenceSources = answer.sources.filter(source => !source.route)
  const aiTiming = answer.ai_used ? formatAiDuration(answer.ai_duration_ms) : ''
  return <Paper variant="outlined" sx={{ p: { xs: 2, sm: 2.4 }, borderRadius: 2, bgcolor: 'background.paper' }}>
    {answer.ai_error && <Box sx={{ mb: 1.6 }}>
      <AiStatusAlert
        message={answer.ai_error}
        errorCode={answer.ai_error_code}
        model={answer.ai_model}
        fallbackNote="Showing the local database and memory answer below."
        onRetry={onRetryAi}
        onCheckConnection={onCheckAi}
      />
    </Box>}

    <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1.4}>
      <Tag tone={refused ? 'warning' : answer.confidence === 'low' ? 'neutral' : 'success'}>
        {refused ? 'Not permitted' : confidenceLabel(answer.confidence)}
      </Tag>
      {answer.ai_used && <Tag tone="info">{`AI · ${answer.ai_model || 'Ollama'}${aiTiming ? ` (${aiTiming})` : ''}`}</Tag>}
      {answer.ai_error && <Tag tone="warning">Local fallback</Tag>}
      {answer.memory_key && <Chip size="small" variant="outlined" label={answer.memory_key} sx={{ height: 22, fontSize: 10.5, fontFamily: 'monospace' }}/>}
      {answer.intent === 'data_health' && <Tag tone="info">Data health</Tag>}
      {(answer.intent === 'price_lookup' || answer.intent === 'cost_search' || answer.intent === 'cost_position' || answer.intent === 'well_comparison') && <Tag tone="info">Live data</Tag>}
      {answer.intent === 'well_comparison' && <Tag tone="info">Well comparison</Tag>}
      {answer.category === 'calculation' && <Tag tone="info">Calculation</Tag>}
    </Box>

    {answer.verified_answer && <Box sx={{ mb: 1.5 }}>
      <Typography className="eyebrow" sx={{ mb: .6 }}>Verified workspace result</Typography>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>{answer.verified_answer}</Typography>
    </Box>}
    {answer.ai_used && <Typography className="eyebrow" sx={{ mb: .6 }}>AI interpretation · verify against sources</Typography>}
    <Typography sx={{ whiteSpace: 'pre-line', fontSize: 13.6, lineHeight: 1.65, color: 'text.primary' }}>
      {answer.answer}
    </Typography>

    {answer.facts.length > 0 && <Box sx={{ mt: 2 }}>
      <Typography className="eyebrow" sx={{ mb: .8 }}>The figures behind it</Typography>
      <Box display="grid" gap={1} gridTemplateColumns={{ xs: '1fr', sm: 'repeat(auto-fit, minmax(210px, 1fr))' }}>
        {answer.facts.map((fact, index) => {
          const content = <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.6, p: 1.35, height: '100%' }}>
            <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
              <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} textTransform="uppercase" color="text.secondary">{fact.label}</Typography>
              {fact.permission && <LockOutlined sx={{ fontSize: 13, color: 'text.disabled' }} titleAccess={`Requires ${fact.permission}`}/>}
            </Box>
            <Typography sx={{ fontSize: 19, fontWeight: 800, mt: .5, mb: fact.hint ? .4 : 0, lineHeight: 1.2 }}>{fact.value}</Typography>
            {fact.hint && <Typography fontSize={11.5} color="text.secondary" sx={{ lineHeight: 1.5 }}>{fact.hint}</Typography>}
          </Box>
          return fact.route
            ? <Link key={`${fact.label}-${index}`} component={RouterLink} to={fact.route} underline="none" sx={{ '&:hover > div': { borderColor: 'primary.main' } }}>{content}</Link>
            : <Box key={`${fact.label}-${index}`}>{content}</Box>
        })}
      </Box>
    </Box>}

    {(answer.tables?.length ?? 0) > 0 && <Box sx={{ mt: 2, display: 'grid', gap: 1.5 }}>
      {answer.tables!.map((tbl, tIdx) => {
        const numericSet = new Set(tbl.numeric ?? [])
        return <Box key={`${tbl.title}-${tIdx}`}>
          {tbl.title && <Typography className="eyebrow" sx={{ mb: .7 }}>{tbl.title}</Typography>}
          <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.6 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {tbl.columns.map((col, cIdx) => (
                    <TableCell
                      key={`${col}-${cIdx}`}
                      align={numericSet.has(cIdx) ? 'right' : 'left'}
                      sx={{ fontWeight: 800, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em', py: .85 }}
                    >
                      {col}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {tbl.rows.map((row, rIdx) => (
                  <TableRow key={rIdx} hover>
                    {row.map((cell, cIdx) => (
                      <TableCell
                        key={cIdx}
                        align={numericSet.has(cIdx) ? 'right' : 'left'}
                        sx={{ fontSize: 12.2, fontVariantNumeric: numericSet.has(cIdx) ? 'tabular-nums' : undefined }}
                      >
                        {cell}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {(tbl.footer || tbl.note) && <Typography fontSize={11.2} color="text.secondary" sx={{ mt: .55 }}>{tbl.footer || tbl.note}</Typography>}
        </Box>
      })}
    </Box>}

    {answer.steps.length > 0 && <Box sx={{ mt: 2 }}>
      <Typography className="eyebrow" sx={{ mb: .6 }}>What to do</Typography>
      <List dense disablePadding>
        {answer.steps.map((step, index) => <ListItem key={index} disableGutters sx={{ alignItems: 'flex-start', py: .35 }}>
          <Box sx={{
            width: 18, height: 18, flex: '0 0 auto', mr: 1, mt: '1px', borderRadius: '50%', fontSize: 10.5,
            fontWeight: 800, display: 'grid', placeItems: 'center', bgcolor: 'action.hover', color: 'text.secondary',
          }}>{index + 1}</Box>
          <ListItemText primaryTypographyProps={{ fontSize: 12.6, lineHeight: 1.55 }} primary={step}/>
        </ListItem>)}
      </List>
    </Box>}

    {pageSources.length > 0 && <Box sx={{ mt: 1.6 }}>
      <Divider sx={{ mb: 1 }}/>
      <Box display="flex" alignItems="center" gap={.7} flexWrap="wrap">
        <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} textTransform="uppercase" color="text.secondary">Open</Typography>
        {pageSources.map((source, index) => <Link
          key={`${source.route}-${index}`} component={RouterLink} to={source.route} underline="hover"
          sx={{ display: 'inline-flex', alignItems: 'center', gap: .4, fontSize: 12, fontWeight: 600 }}
        >
          {source.label || source.route}
          <ArrowForwardRounded sx={{ fontSize: 13 }}/>
        </Link>)}
      </Box>
    </Box>}

    {referenceSources.length > 0 && <Box sx={{ mt: 1.6 }}>
      {/* Two kinds of block source reach this list: an excerpt retrieved from a
          workspace PDF index, and a printed page in a study book. They are cited
          differently — a PDF index names the file and page, a study book names
          the author, the work, the section and the page — so the heading follows
          the content rather than the transport. */}
      <Typography className="eyebrow" sx={{ mb: .6 }}>
        {referenceSources.some(source => /Well Engineering & Construction|Drilling Engineering Workbook/.test(source.label))
          ? 'From the drilling engineering study books'
          : 'PDF reference excerpts provided to AI'}
      </Typography>
      {referenceSources.map(source => <Typography key={source.label} variant="caption" display="block">
        {source.label}
      </Typography>)}
    </Box>}

    {answer.follow_ups.length > 0 && onAsk && <Box sx={{ mt: 1.6 }}>
      <Box display="flex" alignItems="center" gap={.7} flexWrap="wrap">
        <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} textTransform="uppercase" color="text.secondary">Ask next</Typography>
        {answer.follow_ups.map(question => <Chip
          key={question} label={question} size="small" clickable onClick={() => onAsk(question)}
          sx={{ height: 24, fontSize: 11.5, fontWeight: 600 }}
        />)}
      </Box>
    </Box>}

    {refused && <Alert severity="info" icon={<LockOutlined fontSize="small"/>} sx={{ mt: 1.6, py: .2 }}>
      <Typography fontSize={11.5}>
        The guide shows only what your role may read. Ask an administrator for the capability named above
        if this figure is part of your job.
      </Typography>
    </Alert>}
  </Paper>
}

/** The empty state: what this guide is, and the four things worth asking first. */
export function GuideIntro({ prompts, onAsk }: { prompts: string[]; onAsk?: (question: string) => void }) {
  return <Paper variant="outlined" sx={{ p: 2.4, borderRadius: 2 }}>
    <Box display="flex" alignItems="center" gap={1} mb={1}>
      <MenuBookOutlined sx={{ fontSize: 19, color: 'primary.main' }}/>
      <Typography fontWeight={800} fontSize={14}>The guide answers from recorded memory, not from guesses</Typography>
    </Box>
    <Typography fontSize={12.6} color="text.secondary" sx={{ lineHeight: 1.6, mb: 1.6 }}>
      Every workflow, calculation, data-entry rule and navigation path in WellCostIQ is written down once, in
      the memory below, and the guide quotes it. Operational questions are answered from your own workspace
      under your permissions — a figure you may not read is never shown. An answer it does not know is
      reported as unknown, with the topics it can help with.
    </Typography>
    <Box display="flex" gap={.8} flexWrap="wrap">
      {(prompts.length ? prompts : [
        'How are actual days calculated?',
        'What is missing in my workspace?',
        'Where do I enter a daily cost sheet?',
      ]).map(prompt => <Chip
        key={prompt} label={prompt} clickable={!!onAsk} onClick={() => onAsk?.(prompt)} variant="outlined"
        sx={{ height: 26, fontSize: 11.5, fontWeight: 600 }}
      />)}
    </Box>
    <Box display="flex" alignItems="center" gap={.6} mt={1.6}>
      <CheckCircleOutlined sx={{ fontSize: 13, color: 'text.disabled' }}/>
      <Typography fontSize={11.5} color="text.secondary">
        No model is called: the same question always produces the same, checkable answer.
      </Typography>
    </Box>
    <Box display="flex" alignItems="center" gap={.6} mt={.6}>
      <RouteRounded sx={{ fontSize: 13, color: 'text.disabled' }}/>
      <Typography fontSize={11.5} color="text.secondary">
        Answers carry the page that proves them, so a figure can always be traced to its register.
      </Typography>
    </Box>
  </Paper>
}
