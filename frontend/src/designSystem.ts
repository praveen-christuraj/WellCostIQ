/**
 * Design tokens — the single source of truth for the WellCostIQ interface.
 *
 * Aesthetic direction: a "deep petrol instrument panel". Dense, calm and
 * data-first: an ink navigation rail, white working surfaces, petrol-teal as the
 * single action colour and brass reserved for measured emphasis in charts and
 * eyebrows. Hierarchy is carried by weight, size and hairlines rather than by
 * colour, decor or motion.
 *
 * The CSS custom properties in `src/styles.css` (`--wcp-*`) mirror these values so
 * plain CSS (rail, cards, print, scrollbars) stays in sync with the MUI theme.
 * `frontend/src/theme.ts` composes the MUI theme from here; `DataTable` feeds the
 * AG Grid theme from here. Do not hardcode colours in pages — read a token.
 *
 * See `.agent/memory/design-system.md` for the rules that go with these numbers.
 */

export type Mode = 'light' | 'dark'

/**
 * Brand ramp — deep petrol. `700` is the primary action colour in light mode,
 * `300` is the accent in dark mode. The ramp is intentionally blue-green: it
 * reads as technical (drilling fluids, instrumentation) without competing with
 * the green success colour or the amber warning colour.
 */
export const brand = {
  50: '#EEF7F8',
  100: '#D6EBED',
  200: '#AAD5DA',
  300: '#79B9C1',
  400: '#4797A2',
  500: '#2B7B87',
  600: '#1E636E',
  700: '#15515B',
  800: '#103F47',
  900: '#0B3037',
} as const

/** Backwards-compatible alias: older files import the ramp as `navy`. */
export const navy = brand

/** Brass — the one secondary accent, used for eyebrows and chart series only. */
export const brass = {
  50: '#FBF5E9',
  100: '#F3E7CE',
  200: '#E6CFA0',
  300: '#D6B271',
  400: '#C29344',
  500: '#A9782B',
  600: '#8A5F1F',
  700: '#6B4917',
} as const

export const fonts = {
  /** One bundled variable family keeps forms, tables and headings crisp and consistent. */
  ui: '"Inter Variable", Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
  /** Weight, size and spacing carry hierarchy without mixing typefaces. */
  display: '"Inter Variable", Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
  /** Codes, order numbers, checksums, CLI snippets. */
  mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
} as const

/** 4pt rhythm. Every gap/padding in the app is a multiple of 4. */
export const space = { 0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 7: 28, 8: 32, 10: 40 } as const

export const radius = { xs: 4, sm: 6, md: 8, lg: 10, xl: 14, pill: 999 } as const

/**
 * Control heights. The app is zoomed to 87.5%, so these are deliberate.
 * Grid rows are compact (42) so a register shows more records per screen: the
 * tallest cell content is a two-line name/email stack (~36px) or a 31px avatar,
 * and row action buttons are ~30px, so 42 keeps everything tight without
 * clipping. Do not go below 40 without re-checking those cells.
 */
export const control = { compact: 30, standard: 36, comfortable: 44, gridRow: 42, gridHeader: 40 } as const

/** Shell geometry, shared by the Layout and the CSS rail. */
export const layout = { railExpanded: 276, railCollapsed: 78, topBar: 64, pageMax: 1680 } as const

/**
 * Motion is limited to state feedback (hover, focus, press, open/close) and is
 * switched off for `prefers-reduced-motion` in `styles.css`. No decorative or
 * looping motion anywhere in the product.
 */
export const motion = {
  instant: '80ms',
  fast: '120ms',
  base: '160ms',
  slow: '220ms',
  /** Fast in, gentle settle — for anything that appears. */
  enter: 'cubic-bezier(0.16, 1, 0.3, 1)',
  /** Standard for small state changes such as hover and focus. */
  standard: 'cubic-bezier(0.2, 0, 0, 1)',
} as const

/**
 * Printed and on-screen IDVS sheet. The sheet is true black on white in every app theme.
 * Trebuchet MS matches the reference workbook; the PDF uses Helvetica (Arial-metric) because jsPDF
 * bundles only the standard PDF fonts, and its sizes are the reference sizes scaled to fit A4 landscape.
 */
export const idvsSheet = {
  ink: '#000000',
  paper: '#FFFFFF',
  fontFamily: '"Trebuchet MS", Arial, Helvetica, sans-serif',
  excelFontName: 'Trebuchet MS',
  pdfFontFamily: 'helvetica',
  /** Reference workbook point sizes (RIG-11): title 18, headings and body 14, descriptions 13. */
  referencePt: { title: 18, heading: 14, body: 14, description: 13 },
  /** A4 landscape cannot hold the 14pt reference columns at 100%; the PDF applies this factor to the reference sizes. */
  pdfScale: 0.72,
} as const

/** Type scale. Sizes assume the 87.5% app density already applied on `#root`. */
export const typeScale = {
  h1: { fontFamily: fonts.display, fontSize: 32, lineHeight: 1.18, fontWeight: 750, letterSpacing: '-0.028em' },
  h2: { fontFamily: fonts.display, fontSize: 26, lineHeight: 1.22, fontWeight: 750, letterSpacing: '-0.024em' },
  h3: { fontFamily: fonts.display, fontSize: 21, lineHeight: 1.28, fontWeight: 750, letterSpacing: '-0.02em' },
  h4: { fontFamily: fonts.display, fontSize: 18, lineHeight: 1.32, fontWeight: 750, letterSpacing: '-0.015em' },
  h5: { fontFamily: fonts.display, fontSize: 15.5, lineHeight: 1.4, fontWeight: 700, letterSpacing: '-0.01em' },
  h6: { fontFamily: fonts.ui, fontSize: 13.5, lineHeight: 1.45, fontWeight: 700, letterSpacing: 0 },
  subtitle1: { fontFamily: fonts.ui, fontSize: 14, lineHeight: 1.45, fontWeight: 600, letterSpacing: 0 },
  subtitle2: { fontFamily: fonts.ui, fontSize: 12.5, lineHeight: 1.45, fontWeight: 650, letterSpacing: 0 },
  body1: { fontFamily: fonts.ui, fontSize: 14, lineHeight: 1.55, fontWeight: 400, letterSpacing: 0 },
  body2: { fontFamily: fonts.ui, fontSize: 13, lineHeight: 1.5, fontWeight: 400, letterSpacing: 0 },
  caption: { fontFamily: fonts.ui, fontSize: 11.5, lineHeight: 1.4, fontWeight: 600, letterSpacing: 0 },
  overline: { fontFamily: fonts.ui, fontSize: 10, lineHeight: 1.4, fontWeight: 750, letterSpacing: '1.4px' },
} as const

export type SurfaceTokens = {
  /** Page canvas, card surface, and the raised surface above it (menus, dialogs). */
  canvas: string
  paper: string
  raised: string
  hover: string
  selected: string
  /** Hairline rules; `strong` is for control borders that must read on their own. */
  divider: string
  dividerStrong: string
  text: string
  textMuted: string
  textDisabled: string
  /** Keyboard focus ring, drawn outside the control. */
  focus: string
  focusSoft: string
  /** Tinted field used behind KPI/stat icons and the login panel. */
  accentSurface: string
  accentForeground: string
  mutedSurface: string
  /** Ink navigation rail; identical role in both themes, deeper in dark mode. */
  rail: string
  railRaised: string
  railText: string
  railMuted: string
  railLine: string
  railHover: string
  railActive: string
  railActiveText: string
  railAccent: string
}

export const surface = (mode: Mode): SurfaceTokens =>
  mode === 'dark'
    ? {
        canvas: '#08111A',
        paper: '#0F1B22',
        raised: '#15252C',
        hover: '#182B33',
        selected: '#1E343D',
        divider: '#22343C',
        dividerStrong: '#334A53',
        text: '#E7EFF1',
        textMuted: '#9FB3BA',
        textDisabled: '#768B93',
        focus: brand[300],
        focusSoft: 'rgba(121, 185, 193, 0.26)',
        accentSurface: '#123039',
        accentForeground: '#8ACBD4',
        mutedSurface: '#15232A',
        rail: '#060D12',
        railRaised: '#0B161C',
        railText: '#DCE9EC',
        railMuted: '#7E959D',
        railLine: 'rgba(255, 255, 255, 0.08)',
        railHover: 'rgba(255, 255, 255, 0.055)',
        railActive: 'rgba(121, 185, 193, 0.16)',
        railActiveText: '#BFE8ED',
        railAccent: brand[300],
      }
    : {
        canvas: '#F3F6F6',
        paper: '#FFFFFF',
        raised: '#FFFFFF',
        hover: '#F0F5F5',
        selected: '#E2EEEF',
        divider: '#DFE7E8',
        dividerStrong: '#C2CFD1',
        text: '#0D1B22',
        textMuted: '#52666D',
        textDisabled: '#84969D',
        focus: brand[700],
        focusSoft: 'rgba(21, 81, 91, 0.16)',
        accentSurface: '#E7F2F3',
        accentForeground: brand[700],
        mutedSurface: '#F3F6F6',
        rail: '#0A1A21',
        railRaised: '#0E2229',
        railText: '#DCE9EC',
        railMuted: '#8399A0',
        railLine: 'rgba(255, 255, 255, 0.09)',
        railHover: 'rgba(255, 255, 255, 0.06)',
        railActive: 'rgba(121, 185, 193, 0.15)',
        railActiveText: '#C6EAEE',
        railAccent: brand[300],
      }

/**
 * Status colours live as `--wcp-tone-<name>-{bg,fg,border}` custom properties in
 * `styles.css` (neutral / info / success / warning / error). They are CSS variables
 * rather than JS tokens because status chips are also rendered inside AG Grid cell
 * renderers, where the React theme context is not guaranteed to be present.
 * Every tone `fg` on its own `bg` clears WCAG AA for the small label text.
 */

/** Semantic palette for MUI (`error`, `warning`, `success`, `info` all follow it). */
export const semantic = (mode: Mode) =>
  mode === 'dark'
    ? {
        error: { main: '#F1B5B1', dark: '#E79C97', light: '#33201E', contrastText: '#33201E' },
        warning: { main: '#E9C583', dark: '#D9AC56', light: '#2E2718', contrastText: '#2E2718' },
        success: { main: '#84C9A4', dark: '#5FBF8F', light: '#162E22', contrastText: '#162E22' },
        info: { main: brand[300], dark: brand[400], light: brand[900], contrastText: brand[900] },
      }
    : {
        error: { main: '#A3211A', dark: '#821912', light: '#FBEAE8', contrastText: '#FFFFFF' },
        warning: { main: '#8A5A0B', dark: '#6F4800', light: '#F8F1E2', contrastText: '#FFFFFF' },
        success: { main: '#1B6B46', dark: '#145635', light: '#E7F2EC', contrastText: '#FFFFFF' },
        info: { main: brand[700], dark: brand[800], light: brand[100], contrastText: '#FFFFFF' },
      }

/**
 * Visualization-only colour order. Charts need more categorical separation than
 * the application chrome: planned, actual and adjusted retain stable semantic
 * colours, while multi-series visuals may use the extended colour-blind-aware
 * sequence. These colours are not application action or status colours.
 */
export const chartPalette = (mode: Mode) => {
  const s = surface(mode)
  return {
    planned: mode === 'dark' ? brand[300] : brand[700],
    actual: mode === 'dark' ? brass[300] : brass[500],
    adjusted: mode === 'dark' ? brand[200] : brand[400],
    series: mode === 'dark'
      ? [
          '#79B9C1', '#F2C14E', '#5CD6B0', '#FF8A65', '#85C8F5', '#E59BC5',
          '#B89AE8', '#B7D66B', '#FF9C86', '#70D6DF', '#AAB8C2', '#D6B271',
        ]
      : [
          '#15515B', '#B87503', '#087F5B', '#C34A17', '#297DA6', '#A83F82',
          '#6C4AB6', '#5B7F17', '#B23A48', '#087E8B', '#64748B', '#8A5F1F',
        ],
    axis: s.textMuted,
    grid: s.divider,
    surface: s.paper,
  }
}

/**
 * Shadows are deliberately shallow: hairline borders carry structure, elevation
 * only says "this floats above the page". Never stack two elevated surfaces.
 */
export const shadow = (mode: Mode) => {
  const dark = mode === 'dark'
  return {
    /** Cards and outlined paper. */
    subtle: dark ? '0 1px 2px rgba(0, 0, 0, 0.34)' : '0 1px 2px rgba(13, 27, 34, 0.045), 0 1px 3px rgba(13, 27, 34, 0.035)',
    /** App bar and sticky toolbars. */
    bar: dark ? '0 1px 0 rgba(0, 0, 0, 0.4)' : '0 1px 2px rgba(13, 27, 34, 0.04)',
    /** Menus, selects, popovers. */
    raised: dark
      ? '0 2px 6px rgba(0, 0, 0, 0.44), 0 14px 34px rgba(0, 0, 0, 0.38)'
      : '0 2px 4px rgba(13, 27, 34, 0.06), 0 10px 26px rgba(13, 27, 34, 0.10)',
    /** Dialogs and the modal backdrop edge. */
    overlay: dark
      ? '0 4px 12px rgba(0, 0, 0, 0.5), 0 28px 64px rgba(0, 0, 0, 0.5)'
      : '0 12px 32px rgba(9, 24, 30, 0.20), 0 2px 6px rgba(9, 24, 30, 0.10)',
  }
}

/** AG Grid theming params, kept here so the grid always matches the MUI surfaces. */
export const gridThemeParams = (mode: Mode) => {
  const s = surface(mode)
  const dark = mode === 'dark'
  return {
    accentColor: dark ? brand[300] : brand[700],
    backgroundColor: s.paper,
    borderColor: s.divider,
    foregroundColor: s.text,
    headerBackgroundColor: dark ? '#101E25' : '#F6F8F8',
    headerTextColor: dark ? '#A9C2C8' : '#455B62',
    headerFontWeight: 700,
    fontFamily: fonts.ui,
    fontSize: 12,
    rowHoverColor: s.hover,
    oddRowBackgroundColor: dark ? '#0C181E' : '#FBFCFC',
    chromeBackgroundColor: s.paper,
    // 8 (not the quartz default 10) tightens cell padding and the pagination
    // bar to match the compact row height above.
    spacing: 8,
  }
}
