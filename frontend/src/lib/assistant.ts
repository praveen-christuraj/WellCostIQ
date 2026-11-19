// Typed contract for the in-application guide.
//
// An answer is always four things the page can render without interpretation:
// the sentence, the facts behind it (each with the permission that guards it and
// the page that proves it), the steps to follow, and where to read more. There is
// no generated prose to escape and no figure that is not labelled.

import { api, body } from './api'
import type { AiConnectionStatus, AiErrorCode } from './ai'

export type AssistantConfidence = 'high' | 'medium' | 'low'

export type AssistantMemoryCategory = 'workflow' | 'calculation' | 'data-entry' | 'navigation' | 'faq' | 'policy'

export const ASSISTANT_CATEGORIES: { value: AssistantMemoryCategory; label: string }[] = [
  { value: 'workflow', label: 'Workflow' },
  { value: 'calculation', label: 'Calculation' },
  { value: 'data-entry', label: 'Data entry' },
  { value: 'navigation', label: 'Navigation' },
  { value: 'faq', label: 'FAQ' },
  { value: 'policy', label: 'Policy' },
]

export type AssistantFact = {
  label: string
  value: string
  hint: string
  route: string
  permission: string
}

export type AssistantSource = { label: string; route: string }

export type AssistantTable = {
  title: string
  columns: string[]
  rows: string[][]
  numeric?: number[]
  footer?: string
  note?: string
}

export type AssistantAnswer = {
  answer: string
  verified_answer?: string
  intent: string
  confidence: AssistantConfidence
  category: AssistantMemoryCategory
  memory_key: string
  facts: AssistantFact[]
  tables?: AssistantTable[]
  steps: string[]
  sources: AssistantSource[]
  follow_ups: string[]
  ai_used?: boolean
  ai_model?: string
  ai_duration_ms?: number | null
  ai_error?: string
  ai_error_code?: AiErrorCode
}

export type AssistantOverview = {
  enabled: boolean
  can_manage: boolean
  memory_entries: number
  workspace_entries: number
  outstanding_checks: number
  checks: AssistantFact[]
  quick_prompts: string[]
  recent_questions: string[]
  ai?: AiConnectionStatus
}

export type AssistantMemoryEntry = {
  id: string
  memory_key: string
  title: string
  category: AssistantMemoryCategory
  keywords: string
  body: string
  steps: string[]
  route: string
  permission: string
  is_system: boolean
  is_active: boolean
  sort_order: number
  created_by_name: string
  updated_at: string
}

export type AssistantMemoryInput = {
  title: string
  category?: AssistantMemoryCategory
  memory_key?: string
  keywords?: string
  body: string
  steps?: string[]
  route?: string
  permission?: string
  is_active?: boolean
  sort_order?: number
}

export type AssistantConversation = {
  question: string
  intent: string
  memory_key: string
  route: string
  created_at: string
}

export const assistantOverview = () => api<AssistantOverview>('/assistant/overview', { silent: true })

export const assistantAiStatus = (probe = false) =>
  api<AiConnectionStatus>(`/assistant/ai-status${probe ? '?probe=true' : ''}`, {
    silent: true,
    action: 'Check AI model connection',
  })

export const askGuide = (question: string, route = '', useAi = false) =>
  api<AssistantAnswer>('/assistant/ask', {
    method: 'POST',
    body: body(useAi ? { question, route, use_ai: true } : { question, route }),
    action: useAi ? 'Ask the AI guide' : 'Ask the guide',
  })

export const assistantMemory = () => api<AssistantMemoryEntry[]>('/assistant/memory')

export const createAssistantMemory = (input: AssistantMemoryInput) =>
  api<AssistantMemoryEntry>('/assistant/memory', { method: 'POST', body: body(input), action: 'Save guide memory' })

export const updateAssistantMemory = (id: string, input: Partial<AssistantMemoryInput>) =>
  api<AssistantMemoryEntry>(`/assistant/memory/${id}`, { method: 'PATCH', body: body(input), action: 'Update guide memory' })

export const deleteAssistantMemory = (id: string) =>
  api<void>(`/assistant/memory/${id}`, { method: 'DELETE', action: 'Remove guide memory' })

export const assistantHistory = () => api<AssistantConversation[]>('/assistant/history', { silent: true })

/** How sure the guide is, in words a reader can act on. */
export function confidenceLabel(value: AssistantConfidence): string {
  return value === 'high' ? 'From recorded memory' : value === 'medium' ? 'Best match' : 'Not sure'
}

/** Why an answer was refused, kept separate so pages never dress it up as advice. */
export function isPermissionAnswer(answer: AssistantAnswer): boolean {
  return answer.intent === 'permission'
}
