import { useCallback, useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { Alert, Box, Button, Tooltip, Typography } from '@mui/material'
import { CloseRounded } from '@mui/icons-material'
import { useAuth } from '../../context/AuthContext'
import {
  cautionSignature, dismissCaution, dismissedCautionCount, isCautionDismissed,
  onCautionsChanged, pruneCaution, restorePageCautions, type CautionSeverity,
} from '../../lib/cautions'

export type CautionProps = {
  /** Stable identity of this advisory on its page, e.g. `daily-cost-missing-plan`. */
  cautionKey: string
  /** The surface the caution belongs to, e.g. `daily-cost`. */
  page: string
  /** The prose on screen. It is part of the signature: new wording = shown again. */
  children: ReactNode
  /**
   * Everything else the caution currently says (counts, amounts, codes). Changing
   * any of these brings a dismissed caution back, because it is now a new fact.
   */
  signature?: (string | number | null | undefined)[]
  severity?: CautionSeverity
  /** Actions beside the message (a link to the page that fixes it, and so on). */
  action?: ReactNode
  icon?: ReactNode | false
  /**
   * Set for a message that blocks the next action (a failed save, a validation
   * error inside a dialog) or that the user can already close themselves. Those
   * are notices, not cautions: they keep their own close button and are never
   * remembered as dismissed.
   */
  transient?: boolean
  /** Optional plain-text version of `children`, used for the dismissal signature. */
  text?: string
  sx?: object
}

/**
 * A standing advisory with a dismissal control.
 *
 * The reader dismisses it with the close button (it stays dismissed for this
 * workspace until the facts change), and **Show dismissed cautions** on the page
 * brings every one of them back. The component renders nothing once dismissed,
 * so its grid slot collapses with it.
 */
export function Caution({
  cautionKey, page, children, signature = [], severity = 'warning', action, icon,
  transient = false, text, sx,
}: CautionProps) {
  const { user } = useAuth()
  const scope = useMemo(
    () => ({ organizationSlug: user?.organization_slug, page }),
    [user?.organization_slug, page],
  )
  const prose = text ?? (typeof children === 'string' || typeof children === 'number' ? String(children) : '')
  const signatureKey = cautionSignature(...(signature ?? []))
  const ownSignature = useMemo(
    () => cautionSignature(cautionKey, prose, signatureKey),
    [cautionKey, prose, signatureKey],
  )
  const [dismissed, setDismissed] = useState(() => !transient && isCautionDismissed(cautionKey, ownSignature, scope))

  // Re-read on every (re)mount, whenever the scope or the facts change, and when
  // **Show dismissed cautions** clears the notes on this page.
  useEffect(() => {
    if (transient) return undefined
    const read = () => {
      setDismissed(isCautionDismissed(cautionKey, ownSignature, scope))
      // A note that no longer matches these facts is stale; forget it so the
      // page's dismissal count describes only what is hidden now.
      pruneCaution(cautionKey, ownSignature, scope)
    }
    read()
    return onCautionsChanged(read)
  }, [cautionKey, ownSignature, scope, transient])

  const dismiss = useCallback(() => {
    dismissCaution(cautionKey, ownSignature, scope)
    setDismissed(true)
  }, [cautionKey, ownSignature, scope])

  if (transient) {
    return <Alert severity={severity} icon={icon} action={action} sx={sx}>{children}</Alert>
  }
  if (dismissed) return null
  return <Alert
    severity={severity}
    icon={icon}
    action={<>
      {action}
      <Tooltip title="Dismiss this caution — it comes back if the facts change">
        <Button
          size="small"
          color="inherit"
          aria-label="Dismiss this caution"
          onClick={dismiss}
          sx={{ minWidth: 0, px: .6, color: 'inherit' }}
        >
          <CloseRounded sx={{ fontSize: 17 }}/>
        </Button>
      </Tooltip>
    </>}
    sx={{ alignItems: 'center', '& .MuiAlert-action': { alignItems: 'center', gap: .5, pt: 0 }, ...sx }}
  >
    {children}
  </Alert>
}

/**
 * The "bring the cautions back" affordance. It renders only when this page has at
 * least one dismissal recorded in this workspace, so a page that has never been
 * dismissed stays exactly as quiet as before.
 */
export function RestoreCautions({ page, label = 'Show dismissed cautions', onRestored }: {
  page: string
  label?: string
  /** Called after the notes are cleared so the page can re-read its cautions. */
  onRestored?: () => void
}) {
  const { user } = useAuth()
  const scope = useMemo(
    () => ({ organizationSlug: user?.organization_slug, page }),
    [user?.organization_slug, page],
  )
  const [count, setCount] = useState(() => dismissedCautionCount(scope))
  const headingId = useId()

  useEffect(() => {
    const read = () => setCount(dismissedCautionCount(scope))
    read()
    return onCautionsChanged(read)
  }, [scope])

  if (!count) return null
  return <Box display="flex" alignItems="center" gap={.7} sx={{ mb: 1.2 }} aria-live="polite">
    <Typography id={headingId} fontSize={11} color="text.secondary">
      {count} caution{count === 1 ? '' : 's'} dismissed on this page.
    </Typography>
    <Button
      size="small"
      variant="text"
      aria-describedby={headingId}
      onClick={() => {
        restorePageCautions(scope)
        setCount(0)
        onRestored?.()
      }}
      sx={{ textTransform: 'none', fontSize: 11.5, py: 0 }}
    >
      {label}
    </Button>
  </Box>
}
