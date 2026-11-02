import { Box, Typography } from '@mui/material'
import { brand, fonts, surface } from '../designSystem'
import { useColorMode } from '../context/ThemeContext'
import { APP_NAME, APP_TAGLINE } from '../lib/appInfo'

/**
 * The application lockup: mark, wordmark and the subtitle under it.
 *
 * `WellCost` is set in the interface ink and `IQ` carries the navy accent, so the
 * name reads as one word without needing a second colour block. The subtitle is
 * the product descriptor and is hidden nowhere it fits: it is the line that tells a
 * new user what the tool does.
 */
export function BrandIcon({ size = 46 }: { size?: number }) {
  return <Box component="img" src="/favicon.svg" alt="" aria-hidden="true" sx={{ width: size, height: size, objectFit: 'contain', flex: 'none' }}/>
}

export default function Brand({ light = false, compact = false }: { light?: boolean; compact?: boolean }) {
  const { mode } = useColorMode()
  const dark = light || mode === 'dark'
  const tone = surface(dark ? 'dark' : 'light')
  return <Box display="flex" alignItems="center" gap={compact ? 1 : 1.4} minWidth={0}>
    <BrandIcon size={compact ? 36 : 46}/>
    <Box minWidth={0}>
      <Typography sx={{ display: 'block', fontFamily: fonts.ui, fontWeight: 700, letterSpacing: '-.6px', color: tone.text, lineHeight: 1.1, fontSize: compact ? 22 : { xs: 21, sm: 23, md: 24 } }}>
        WellCost<span style={{ color: dark ? brand[300] : brand[600] }}>IQ</span>
      </Typography>
      <Typography
        component="span"
        title={`${APP_NAME} — ${APP_TAGLINE}`}
        sx={{
          display: 'block',
          color: tone.textMuted,
          letterSpacing: '.1px',
          fontSize: compact ? 11.5 : { xs: 10, sm: 11, md: 12 },
          fontWeight: 600,
          lineHeight: 1.2,
          mt: .4,
          whiteSpace: compact ? 'normal' : 'nowrap',
        }}
      >{APP_TAGLINE}</Typography>
    </Box>
  </Box>
}
