import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material'
import { AnswerCard } from '../../components/assistant/AnswerCard'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { SectionCard } from '../../components/ui/SectionCard'
import { useAuth } from '../../context/AuthContext'
import { askGuide, type AssistantAnswer } from '../../lib/assistant'
import { opsGuide, type OpsGuideTopic } from '../../lib/operations'

export default function OperationsGuide() {
  const { can } = useAuth()
  const [topics, setTopics] = useState<OpsGuideTopic[] | null>(null)
  const [question, setQuestion] = useState(''),
    [answer, setAnswer] = useState<AssistantAnswer | null>(null)
  const [loading, setLoading] = useState(false),
    [error, setError] = useState(''),
    [askError, setAskError] = useState('')
  useEffect(() => {
    let current = true
    opsGuide()
      .then((rows) => {
        if (current) setTopics(rows)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [])
  const ask = async (prompt: string) => {
    setLoading(true)
    setAskError('')
    setAnswer(null)
    setQuestion(prompt)
    try {
      setAnswer(await askGuide(prompt.trim(), '/operations/guide'))
    } catch (e) {
      setAskError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Ask & guide"
        subtitle="Look up the daily workflow, code meanings and the rules behind the numbers."
      />
      {can('assistant:read') && (
        <SectionCard
          title="Ask about Well Operations"
          subtitle="Answers come from the manual and code library. Use the source report or timeline to verify a particular well’s figures."
        >
          <Stack spacing={1.5}>
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
                label="Your question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                fullWidth
                slotProps={{ htmlInput: { maxLength: 500 } }}
              />
              <Button type="submit" variant="contained" disabled={loading || !question.trim()}>
                {loading ? 'Checking…' : 'Ask'}
              </Button>
            </Box>
            {!answer && (
              <Box display="flex" flexWrap="wrap" gap={1}>
                {(topics ?? []).map((t) => (
                  <Button
                    key={t.id}
                    size="small"
                    variant="outlined"
                    disabled={loading}
                    onClick={() => void ask(t.question)}
                  >
                    {t.question}
                  </Button>
                ))}
              </Box>
            )}
            {askError && <ErrorMessage message={askError} />}
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
        Offline AI is opt-in in the daily brief and timeline study. It suggests wording; only reviewed source data is
        used to calculate the figures.
      </Alert>
    </Box>
  )
}
