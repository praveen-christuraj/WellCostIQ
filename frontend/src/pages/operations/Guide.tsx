import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AutoAwesomeOutlined, WifiFindRounded } from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { AiStatusAlert } from '../../components/assistant/AiStatusAlert'
import { AnswerCard } from '../../components/assistant/AnswerCard'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { useAuth } from '../../context/AuthContext'
import type { AiConnectionStatus } from '../../lib/ai'
import { askGuide, type AssistantAnswer } from '../../lib/assistant'
import { opsAiStatus, opsGuide, type OpsGuideTopic } from '../../lib/operations'
import { WAT_LABEL } from '../../lib/time'

const DNC_SAMPLE_PROMPTS = [
  'How many daily operation reports are in the workspace?',
  'Show NPT breakdown across all wells',
  'What are MD, TVD, bit depth and DLS?',
  'What causes differential and mechanical stuck pipe?',
  'Explain LOT, FIT, MAASP and Driller’s Method',
  'How do completion packers, SCSSV and tubing testing work?',
]

export default function OperationsGuide() {
  const { can } = useAuth()
  const [topics, setTopics] = useState<OpsGuideTopic[] | null>(null)
  const [question, setQuestion] = useState('')
  const [useAi, setUseAi] = useState(false)
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null)
  const [aiCheck, setAiCheck] = useState<AiConnectionStatus | null>(null)
  const [checkingAi, setCheckingAi] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [askError, setAskError] = useState('')

  useEffect(() => {
    let current = true
    opsGuide()
      .then((rows) => {
        if (current) setTopics(rows)
      })
      .catch((e) => {
        if (current) setError((e as Error).message)
      })
    return () => {
      current = false
    }
  }, [])

  const ask = async (prompt: string, aiOverride?: boolean) => {
    const trimmed = prompt.trim()
    if (!trimmed) return
    const wantAi = aiOverride ?? useAi
    setLoading(true)
    setAskError('')
    setAnswer(null)
    setQuestion(trimmed)
    try {
      setAnswer(await askGuide(trimmed, '/operations/guide', wantAi))
    } catch (e) {
      setAskError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const checkAi = async () => {
    setCheckingAi(true)
    setAskError('')
    try {
      setAiCheck(await opsAiStatus())
    } catch (e) {
      setAskError((e as Error).message)
    } finally {
      setCheckingAi(false)
    }
  }

  return (
    <Box display="grid" gap={2}>
      <PageHeading
        eyebrow="Well Operations"
        title="Ask & guide"
        subtitle={`Query live Well Operations records, Drilling & Completion engineering standards, OpenWells codes, and daily workflows (${WAT_LABEL}). Enable Offline AI to run grounded LAN Ollama analysis.`}
      />
      {can('assistant:read') && (
        <SectionCard
          title="Ask Well Operations & Drilling/Completion AI"
          subtitle="Searches your RBAC-authorized Well Operations database (depths MD/TVD, ROP, NPT/UPA, surveys, plans), OpenWells codes, and the D&C engineering reference. Toggle Offline AI for richer synthesis from your local LAN Ollama model."
          action={
            <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
              <FormControlLabel
                control={<Switch size="small" checked={useAi} onChange={(_, v) => setUseAi(v)} disabled={loading} />}
                label={
                  <Typography fontSize={12.5} fontWeight={600}>
                    Offline AI (Ollama)
                  </Typography>
                }
              />
              <Button
                size="small"
                variant="outlined"
                startIcon={checkingAi ? <CircularProgress size={13} color="inherit" /> : <WifiFindRounded fontSize="small" />}
                disabled={checkingAi || loading}
                onClick={() => void checkAi()}
              >
                {checkingAi ? 'Checking…' : 'Check AI'}
              </Button>
            </Stack>
          }
        >
          <Stack spacing={1.5}>
            {aiCheck && aiCheck.reachable && aiCheck.model_available && (
              <Alert severity="success" onClose={() => setAiCheck(null)}>
                Offline AI ready — model <strong>{aiCheck.model}</strong> reachable at <code>{aiCheck.endpoint}</code>.
              </Alert>
            )}
            {aiCheck && (!aiCheck.reachable || !aiCheck.model_available) && (
              <AiStatusAlert
                message={aiCheck.message}
                errorCode={aiCheck.error_code}
                model={aiCheck.model}
                endpoint={aiCheck.endpoint}
                busy={checkingAi}
                onCheckConnection={() => void checkAi()}
                onDismiss={() => setAiCheck(null)}
              />
            )}

            <Box
              component="form"
              display="flex"
              gap={1}
              alignItems="flex-start"
              onSubmit={(e) => {
                e.preventDefault()
                void ask(question)
              }}
            >
              <TextField
                label="Ask about a well's MD/TVD, ROP, NPT, surveys, OpenWells code, or D&C engineering"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                fullWidth
                slotProps={{ htmlInput: { maxLength: 500 } }}
              />
              <Button
                type="submit"
                variant="contained"
                startIcon={
                  loading ? (
                    <CircularProgress size={14} color="inherit" />
                  ) : useAi ? (
                    <AutoAwesomeOutlined fontSize="small" />
                  ) : undefined
                }
                disabled={loading || !question.trim()}
              >
                {loading ? (useAi ? 'Thinking…' : 'Checking…') : useAi ? 'Ask AI' : 'Ask'}
              </Button>
            </Box>

            <Box display="flex" flexWrap="wrap" gap={0.85}>
              {DNC_SAMPLE_PROMPTS.map((prompt) => (
                <Button
                  key={prompt}
                  size="small"
                  variant="outlined"
                  disabled={loading}
                  onClick={() => void ask(prompt)}
                >
                  {prompt}
                </Button>
              ))}
              {(topics ?? []).map((t) => (
                <Button
                  key={t.id}
                  size="small"
                  variant="text"
                  disabled={loading}
                  onClick={() => void ask(t.question)}
                >
                  {t.question}
                </Button>
              ))}
            </Box>

            {askError && <ErrorMessage message={askError} />}
            {answer?.ai_error && (
              <AiStatusAlert
                message={answer.ai_error}
                errorCode={answer.ai_error_code}
                model={answer.ai_model}
                busy={loading}
                fallbackNote="Verified workspace database and D&C reference answer is displayed below."
                onRetry={() => void ask(question, true)}
                onCheckConnection={() => void checkAi()}
              />
            )}
            {answer && <AnswerCard answer={answer} onAsk={(p) => void ask(p)} />}
          </Stack>
        </SectionCard>
      )}

      {error && <ErrorMessage message={error} />}
      {!topics && !error && <Typography role="status">Loading Well Operations manual…</Typography>}
      {topics?.map((topic) => (
        <SectionCard
          key={topic.id}
          title={topic.title}
          action={
            <Button component={RouterLink} to={topic.route}>
              Open related page
            </Button>
          }
        >
          <Typography variant="body2">{topic.body}</Typography>
          <Box component="ol" sx={{ my: 1.5, pl: 3 }}>
            {topic.steps.map((step) => (
              <Typography key={step} component="li" variant="body2" sx={{ mb: 0.75 }}>
                {step}
              </Typography>
            ))}
          </Box>
        </SectionCard>
      ))}
      <Alert severity="info">
        All offline AI queries run exclusively against your organization’s local LAN Ollama server (zero public cloud
        egress), enforce every Well Operations RBAC capability, and keep verified database calculations intact when the
        AI model is unavailable. All operational timestamps are displayed in {WAT_LABEL}.
      </Alert>
    </Box>
  )
}
