import { useMemo, useState } from 'react'
import { Box, Button, Chip, IconButton, Typography } from '@mui/material'
import { ExpandLessRounded, ExpandMoreRounded } from '@mui/icons-material'
import { Tag, type Tone } from '../Common'
import { fonts, radius, space } from '../../designSystem'

/**
 * One node of the schematic. The tree is data, not markup: the page builds it
 * from the same records the table shows, so the two views can never disagree.
 */
export type TreeNode = {
  id: string
  label: string
  /** Secondary text (a printed meaning, a scope, a note). */
  meta?: string
  tone?: Tone
  children?: TreeNode[]
  /** The correlation / code link that this node came from, for inline actions. */
  rule?: { type: 'correlation' | 'link'; id: string }
  /** A workspace code, so the node can start a new correlation or link. */
  code?: { criterion: string; id: string; label: string; library: string }
}

type Handlers = {
  onEditRule?: (type: 'correlation' | 'link', id: string) => void
  onUnlink?: (type: 'correlation' | 'link', id: string) => void
  onCorrelateCode?: (node: NonNullable<TreeNode['code']>) => void
  onLinkCode?: (node: NonNullable<TreeNode['code']>) => void
  busy?: boolean
}

function Row({ node, depth, handlers, openAll }: { node: TreeNode; depth: number; handlers: Handlers; openAll: boolean }) {
  const [open, setOpen] = useState(depth < 3)
  const expanded = openAll || open
  const hasChildren = Boolean(node.children?.length)
  return (
    <Box component="li" sx={{ listStyle: 'none', m: 0, p: 0 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          minHeight: 32,
          pl: `${depth * 18}px`,
          pr: 1,
          borderLeft: depth ? '1px solid' : 'none',
          borderColor: 'divider',
          borderRadius: `${radius.xs}px`,
          '&:hover': { bgcolor: 'action.hover' },
        }}
      >
        {hasChildren ? (
          <IconButton
            size="small"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.label}`}
            aria-expanded={expanded}
            onClick={() => setOpen(!expanded)}
            sx={{ p: 0.25 }}
          >
            {expanded ? <ExpandLessRounded fontSize="inherit" /> : <ExpandMoreRounded fontSize="inherit" />}
          </IconButton>
        ) : (
          <Box sx={{ width: 26, flex: '0 0 auto' }} />
        )}
        {node.tone ? <Tag tone={node.tone}>{node.label}</Tag> : <Typography fontSize={12.5} fontWeight={hasChildren ? 700 : 500}>{node.label}</Typography>}
        {node.meta ? (
          <Typography fontSize={11.5} color="text.secondary" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.meta}
          </Typography>
        ) : null}
        <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5, flex: '0 0 auto' }}>
          {node.rule && handlers.onEditRule && handlers.onUnlink ? (
            <>
              <Button size="small" sx={{ minWidth: 0, fontSize: 11 }} disabled={handlers.busy} onClick={() => handlers.onEditRule?.(node.rule!.type, node.rule!.id)}>
                Edit
              </Button>
              <Button
                size="small"
                color="error"
                sx={{ minWidth: 0, fontSize: 11 }}
                disabled={handlers.busy}
                onClick={() => handlers.onUnlink?.(node.rule!.type, node.rule!.id)}
              >
                Unlink
              </Button>
            </>
          ) : null}
          {node.code ? (
            <>
              <Button size="small" sx={{ minWidth: 0, fontSize: 11 }} disabled={handlers.busy} onClick={() => handlers.onCorrelateCode?.(node.code!)}>
                Correlate
              </Button>
              <Button size="small" sx={{ minWidth: 0, fontSize: 11 }} disabled={handlers.busy} onClick={() => handlers.onLinkCode?.(node.code!)}>
                Link
              </Button>
            </>
          ) : null}
        </Box>
      </Box>
      {hasChildren && expanded ? (
        <Box component="ul" sx={{ m: 0, p: 0 }}>
          {node.children!.map((child) => (
            <Row key={child.id} node={child} depth={depth + 1} handlers={handlers} openAll={openAll} />
          ))}
        </Box>
      ) : null}
    </Box>
  )
}

/**
 * A read-only schematic of the same rules the tables edit. Rows are token-styled
 * so a printed family, a workspace code and a rule kind stay visually distinct;
 * every node keeps its inline edit / unlink / correlate / link action so the
 * schematic is a working surface, not a picture.
 */
export function CorrelationTree({ root, handlers, label }: { root: TreeNode; handlers: Handlers; label: string }) {
  const count = useMemo(() => {
    const walk = (node: TreeNode): number => 1 + (node.children ?? []).reduce((n, c) => n + walk(c), 0)
    return walk(root)
  }, [root])
  const [openAll, setOpenAll] = useState(false)
  return (
    <Box
      role="tree"
      aria-label={label}
      sx={{
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 2,
        bgcolor: 'background.paper',
        px: 1.25,
        py: 1,
        fontFamily: fonts.ui,
      }}
    >
      <Box display="flex" alignItems="center" gap={1} mb={0.5} px={0.5}>
        <Chip size="small" variant="outlined" label={`${count} node${count === 1 ? '' : 's'}`} sx={{ height: 20, fontSize: 10.5 }} />
        <Box sx={{ ml: 'auto' }}>
          <Button size="small" sx={{ fontSize: 11 }} onClick={() => setOpenAll(!openAll)}>
            {openAll ? 'Collapse all' : 'Expand all'}
          </Button>
        </Box>
      </Box>
      <Box component="ul" sx={{ m: 0, p: 0, pb: space[1] }}>
        <Row node={root} depth={0} handlers={handlers} openAll={openAll} />
      </Box>
    </Box>
  )
}
