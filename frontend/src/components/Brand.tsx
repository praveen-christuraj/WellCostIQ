import { Box, Typography } from '@mui/material'
import { brand, surface } from '../designSystem'
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
export default function Brand({ light = false, rigMark = false }: { light?: boolean; rigMark?: boolean }) {
  const { mode } = useColorMode()
  const dark = light || mode === 'dark'
  const tone = surface(dark ? 'dark' : 'light')
  return <Box display="flex" alignItems="center" gap={1.4}>
    {rigMark
      ? <Box component="img" src="/favicon.svg" alt="" aria-hidden="true" sx={{ width: 46, height: 46, objectFit: 'contain', flex: 'none' }}/>
      : <Box className="brand-mark"><span className="brand-line"/><span className="brand-dot"/></Box>}
    <Box>
      <Typography sx={{ display: 'block', fontFamily: '"Inter Variable", Inter, sans-serif', fontWeight: 700, letterSpacing: '-.6px', color: tone.text, lineHeight: 1.1, fontSize: { xs: 21, sm: 23, md: 24 } }}>
        WellCost<span style={{ color: dark ? brand[300] : brand[600] }}>IQ</span>
      </Typography>
      <Typography
        component="span"
        title={`${APP_NAME} — ${APP_TAGLINE}`}
        sx={{
          display: 'block',
          color: tone.textMuted,
          letterSpacing: '.1px',
          fontSize: { xs: 10, sm: 11, md: 12 },
          fontWeight: 600,
          lineHeight: 1.2,
          mt: .4,
          whiteSpace: 'nowrap',
        }}
      >{APP_TAGLINE}</Typography>
    </Box>
  </Box>
}
