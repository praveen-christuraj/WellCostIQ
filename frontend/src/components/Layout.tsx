import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Alert, Avatar, Box, Drawer, IconButton, ListItemIcon, ListItemText, Menu, MenuItem,
  Snackbar, TextField, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import {
  DashboardOutlined, PeopleOutline, AdminPanelSettingsOutlined, VpnKeyOutlined, KeyboardArrowDownRounded,
  ChevronLeftRounded, ChevronRightRounded, LogoutRounded, AccountTreeOutlined, LightModeOutlined,
  DarkModeOutlined, MenuRounded, HistoryOutlined, DataObjectOutlined, DeleteOutlineRounded, TableChartOutlined,
  StorefrontOutlined, DescriptionOutlined, BuildOutlined, GridViewOutlined, PrecisionManufacturingOutlined,
  OpacityOutlined, ListAltOutlined, BusinessOutlined, PublicOutlined, TaskAltOutlined, RequestQuoteOutlined,
  InsightsOutlined, SettingsOutlined, StorageOutlined, PlaylistAddCheckRounded, WaterDropOutlined,
  AssessmentOutlined, LocalGasStationOutlined, ScienceOutlined, Inventory2Outlined, ScheduleRounded,
  FactCheckOutlined, SecurityRounded, NotificationsOutlined, TuneRounded, BackupOutlined, HomeOutlined,
} from '@mui/icons-material'
import Brand from './Brand'
import { FormDialog, ErrorMessage } from './Common'
import { api, body } from '../lib/api'
import { pageTitle } from '../lib/appInfo'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import NotificationBell from './NotificationBell'
import { layout as shell } from '../designSystem'

type NavItem = { label: string; path: string; icon: typeof DashboardOutlined; permission?: string; anyOf?: string[]; requires?: string[] }
type NavModule = { label: string; icon: typeof DashboardOutlined; items: NavItem[] }

const modules: NavModule[] = [
  { label: 'User Management', icon: PeopleOutline, items: [
    { label: 'Dashboard', path: '/dashboard', icon: DashboardOutlined },
    { label: 'Users', path: '/users', icon: PeopleOutline, permission: 'users:read' },
    { label: 'Roles', path: '/roles', icon: AdminPanelSettingsOutlined, permission: 'roles:read' },
    { label: 'Permissions', path: '/permissions', icon: VpnKeyOutlined, permission: 'permissions:read' },
    { label: 'Assignments', path: '/assignments', icon: AccountTreeOutlined, permission: 'assignments:write', requires: ['users:read', 'roles:read', 'permissions:read'] },
    // The reset queue is readable with security:password-reset alone, so a reviewer
    // reaches the page without needing the wider register capability.
    { label: 'Security centre', path: '/security', icon: SecurityRounded, anyOf: ['security:read', 'security:password-reset', 'security:unlock'] },
  ] },
  { label: 'Master Data Management', icon: DataObjectOutlined, items: [
    { label: 'Overview', path: '/master-data', icon: DataObjectOutlined, permission: 'master-data:read' },
    { label: 'Master data', path: '/master-data/records', icon: TableChartOutlined, permission: 'master-data:read' },
    { label: 'Services', path: '/master-data/services', icon: BuildOutlined, permission: 'master-data:read' },
    { label: 'Vendors', path: '/master-data/vendors', icon: StorefrontOutlined, permission: 'master-data:read' },
    { label: 'PO/SO Orders', path: '/master-data/po-so-orders', icon: DescriptionOutlined, permission: 'master-data:read' },
    { label: 'Tangibles', path: '/master-data/tangibles', icon: PrecisionManufacturingOutlined, permission: 'master-data:read' },
    { label: 'Consumables', path: '/master-data/consumables', icon: OpacityOutlined, permission: 'master-data:read' },
    { label: 'Catalogue lists', path: '/master-data/catalogue-lists', icon: ListAltOutlined, permission: 'master-data:read' },
    { label: 'Deleted entries', path: '/master-data/deleted', icon: DeleteOutlineRounded, permission: 'master-data:read' },
  ] },
  { label: 'Rig & Well Management', icon: BusinessOutlined, items: [
    { label: 'Overview', path: '/rig-well', icon: BusinessOutlined, permission: 'rig-well:read' },
    { label: 'Blocks', path: '/rig-well/blocks', icon: GridViewOutlined, permission: 'rig-well:read' },
    { label: 'Rigs', path: '/rig-well/rigs', icon: BusinessOutlined, permission: 'rig-well:read' },
    { label: 'Wells', path: '/rig-well/wells', icon: PublicOutlined, permission: 'rig-well:read' },
    { label: 'Well sub activities', path: '/rig-well/sub-activities', icon: TaskAltOutlined, permission: 'rig-well:read' },
    { label: 'Deleted entries', path: '/rig-well/deleted', icon: DeleteOutlineRounded, permission: 'rig-well:read' },
  ] },
  { label: 'AFE Management', icon: DescriptionOutlined, items: [
    { label: 'Overview', path: '/afe', icon: DashboardOutlined, permission: 'afe:read' },
    { label: 'AFE & cost estimation', path: '/afe/register', icon: DescriptionOutlined, permission: 'afe:read' },
    { label: 'Reusable costing sets', path: '/costing-sets', icon: PlaylistAddCheckRounded, permission: 'costing-sets:read' },
  ] },
  { label: 'Daily Cost Management', icon: RequestQuoteOutlined, items: [
    { label: 'Daily cost register', path: '/daily-cost', icon: RequestQuoteOutlined, permission: 'daily-cost:read' },
    { label: 'Mud Cost Analysis', path: '/daily-cost/mud-cost-analysis', icon: WaterDropOutlined, permission: 'daily-cost:read' },
    { label: 'LIH Cost Register', path: '/daily-cost/lih-register', icon: PlaylistAddCheckRounded, permission: 'daily-cost:read' },
    { label: 'Fuel Cost Register', path: '/daily-cost/fuel-cost-register', icon: LocalGasStationOutlined, permission: 'daily-cost:read' },
    { label: 'NDT Inspection Register', path: '/daily-cost/ndt-inspections', icon: FactCheckOutlined, permission: 'daily-cost:read' },
    { label: 'Well Cost Analysis', path: '/daily-cost/analysis', icon: InsightsOutlined, permission: 'daily-cost:read' },
  ] },
  { label: 'Reports', icon: AssessmentOutlined, items: [
    { label: 'Overview', path: '/reports', icon: AssessmentOutlined, anyOf: ['rig-well:read', 'afe:read', 'daily-cost:read', 'report-builder:read', 'custom-reports:read'] },
    { label: 'Report Builder', path: '/reports/builder', icon: TuneRounded, anyOf: ['report-builder:read', 'report-builder:create', 'report-builder:update'] },
    { label: 'Custom Reports', path: '/reports/custom', icon: AssessmentOutlined, permission: 'custom-reports:read' },
    { label: 'Well-wise cost comparisons', path: '/reports/well-cost-comparison', icon: InsightsOutlined, requires: ['rig-well:read'], anyOf: ['afe:read', 'daily-cost:read'] },
    { label: 'Consumption and losses', path: '/reports/consumption-losses', icon: WaterDropOutlined, permission: 'daily-cost:read' },
    { label: 'Mud chemicals usage', path: '/reports/mud-chemicals-usage', icon: ScienceOutlined, permission: 'daily-cost:read' },
    { label: 'Drill bits usage', path: '/reports/drill-bits-usage', icon: PrecisionManufacturingOutlined, permission: 'daily-cost:read' },
    { label: 'Tangibles usage', path: '/reports/tangibles-usage', icon: Inventory2Outlined, permission: 'daily-cost:read' },
    { label: 'Service-wise cost', path: '/reports/service-wise-cost', icon: BuildOutlined, permission: 'daily-cost:read' },
    { label: 'Vendor/company-wise cost', path: '/reports/vendor-wise-cost', icon: StorefrontOutlined, permission: 'daily-cost:read' },
    { label: 'NPT/UPA report', path: '/reports/npt-upa', icon: ScheduleRounded, permission: 'daily-cost:read' },
  ] },
  { label: 'Other Managements', icon: SettingsOutlined, items: [
    { label: 'Overview', path: '/other-management', icon: DashboardOutlined, anyOf: ['audit:read', 'database-browser:read', 'tasks:read', 'backup:read'] },
    { label: 'Task Manager', path: '/other-management/tasks', icon: TaskAltOutlined, permission: 'tasks:read' },
    { label: 'Notifications', path: '/other-management/notifications', icon: NotificationsOutlined },
    { label: 'Audit Log', path: '/other-management/audit', icon: HistoryOutlined, permission: 'audit:read' },
    { label: 'Database Browser', path: '/other-management/database', icon: StorageOutlined, permission: 'database-browser:read' },
    // Backup & Recovery opens for anybody who can do any of its actions; each
    // button inside is separately gated by its own capability.
    { label: 'Backup & Recovery', path: '/other-management/backup', icon: BackupOutlined, anyOf: ['backup:read', 'backup:create', 'backup:delete', 'backup:settings', 'backup:restore-request', 'backup:restore-approve', 'backup:restore-execute'] },
  ] },
]

/**
 * Pages that live under a register route but deserve their own name in the top
 * bar and the tab title. Longest prefix wins, so the order here matters.
 */
const DETAIL_LABELS: { prefix: string; label: string }[] = [
  { prefix: '/afe/estimate/', label: 'AFE cost estimate' },
  { prefix: '/daily-cost/entries/', label: 'Daily cost sheet' },
  { prefix: '/daily-cost/analysis/', label: 'Well cost analysis' },
  { prefix: '/reports/builder/', label: 'Report designer' },
  { prefix: '/reports/custom/', label: 'Custom report' },
  { prefix: '/reports/custom-report/', label: 'Custom report' },
  { prefix: '/other-management/database/', label: 'Table view' },
]

function initials(name?: string) {
  return (name ?? '').split(' ').filter(Boolean).map(value => value[0]).slice(0, 2).join('').toUpperCase() || '—'
}

export default function Layout() {
  const { user, can, logout } = useAuth()
  const { mode, toggle } = useColorMode()
  const mui = useTheme()
  const desktop = useMediaQuery(mui.breakpoints.up('md'))
  const navigate = useNavigate()
  const location = useLocation()
  const [moduleAnchor, setModuleAnchor] = useState<{ el: HTMLElement; module: NavModule } | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [navExpanded, setNavExpanded] = useState(() => localStorage.getItem('wcp-nav-expanded') !== 'false')
  const [openModules, setOpenModules] = useState<string[]>([])
  const [accountAnchor, setAccountAnchor] = useState<null | HTMLElement>(null)
  const [passwordDialog, setPasswordDialog] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [apiNotice, setApiNotice] = useState<{ message: string; status: number } | null>(null)

  const changePassword = async () => {
    setSavingPassword(true)
    setPasswordError('')
    try {
      await api('/auth/change-password', { method: 'POST', body: body({ current_password: currentPassword, new_password: newPassword }) })
      setPasswordDialog(false)
      setCurrentPassword('')
      setNewPassword('')
      await logout()
    } catch (error) {
      setPasswordError((error as Error).message)
    } finally {
      setSavingPassword(false)
    }
  }

  const visible = (item: NavItem) => (!item.permission || can(item.permission)) && (!item.anyOf || item.anyOf.some(can)) && (!item.requires || item.requires.every(can))
  const showBusinessDashboard = can('rig-well:read') || can('afe:read') || can('daily-cost:read')
  const businessDashboardActive = location.pathname.startsWith('/business-dashboard')
  const modulesForUser = useMemo(
    () => modules.map(module => ({ ...module, items: module.items.filter(visible) })).filter(module => module.items.length > 0),
    [user], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const currentModule = modulesForUser.find(module => module.items.some(item => location.pathname === item.path || location.pathname.startsWith(`${item.path}/`)))
  const currentItem = modulesForUser.flatMap(module => module.items)
    .filter(item => location.pathname === item.path || location.pathname.startsWith(`${item.path}/`))
    .sort((a, b) => b.path.length - a.path.length)[0]
  const detailLabel = DETAIL_LABELS.find(entry => location.pathname.startsWith(entry.prefix))?.label
  const pageLabel = detailLabel ?? currentItem?.label ?? (businessDashboardActive ? 'Operations dashboard' : location.pathname === '/' ? 'Home' : 'Workspace')
  const sectionLabel = currentModule?.label ?? (businessDashboardActive ? 'Home' : location.pathname === '/' ? 'Workspace' : 'Workspace')

  useEffect(() => { localStorage.setItem('wcp-nav-expanded', String(navExpanded)) }, [navExpanded])
  useEffect(() => {
    if (currentModule) setOpenModules(values => values.includes(currentModule.label) ? values : [...values, currentModule.label])
    setMobileOpen(false)
  }, [location.pathname, currentModule?.label]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // One pop-up per distinct message: background polling must not stack duplicates,
    // and a repeated failure keeps a single readable notice on screen.
    const show = (event: Event) => {
      const detail = (event as CustomEvent<{ message?: string; status?: number }>).detail
      const message = detail?.message?.trim()
      if (!message || detail?.status === 401) return
      setApiNotice(current => current?.message === message ? current : { message, status: detail?.status ?? 0 })
    }
    window.addEventListener('api-error', show)
    return () => window.removeEventListener('api-error', show)
  }, [])
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 6)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    document.title = pageTitle(detailLabel ?? (businessDashboardActive ? 'Operations dashboard' : currentItem?.label ?? (location.pathname === '/' ? 'Home' : undefined)))
  }, [detailLabel, businessDashboardActive, currentItem?.label, location.pathname])

  const toggleModule = (label: string) => setOpenModules(values => values.includes(label) ? values.filter(value => value !== label) : [...values, label])
  const go = (path: string) => { navigate(path); setMobileOpen(false); setModuleAnchor(null) }

  const navWidth = navExpanded ? shell.railExpanded : shell.railCollapsed

  const navigation = (temporary = false) => {
    const showText = navExpanded || temporary
    return <Box component="nav" aria-label="Primary navigation" className="app-rail" display="flex" flexDirection="column" height="100%" sx={{ overflow: 'hidden' }}>
      <Box className="rail-brand" display="flex" alignItems="center" justifyContent={showText ? 'space-between' : 'center'} gap={1}>
        {showText ? <Brand light/> : <Box component="img" src="/favicon.svg" alt="WellCostIQ" sx={{ width: 44, height: 44, objectFit: 'contain' }}/>}
        {!temporary && <Tooltip title={navExpanded ? 'Collapse navigation' : 'Expand navigation'} placement="right">
          <IconButton
            size="small" onClick={() => setNavExpanded(value => !value)}
            aria-label={navExpanded ? 'Collapse navigation' : 'Expand navigation'}
            sx={{ color: 'var(--wcp-rail-muted)', ml: showText ? 0 : 'auto', '&:hover': { color: 'var(--wcp-rail-text)', bgcolor: 'var(--wcp-rail-hover)' } }}
          >
            {navExpanded ? <ChevronLeftRounded fontSize="small"/> : <ChevronRightRounded fontSize="small"/>}
          </IconButton>
        </Tooltip>}
      </Box>

      {showText && <Box className="rail-workspace">
        <Typography className="rail-workspace__label">Workspace</Typography>
        <Typography className="rail-workspace__name" title={user?.organization_name}>{user?.organization_name || 'No workspace'}</Typography>
      </Box>}

      <Box className="rail-scroll" sx={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', py: .5 }}>
        <Box className="rail-nav">
          {showText && <Typography component="div" className="rail-section-label">Workspace</Typography>}
          {showBusinessDashboard && <Tooltip title={!showText ? 'Operations dashboard' : ''} placement="right">
            <RouterLink to="/business-dashboard" onClick={() => setMobileOpen(false)} className={`rail-item${businessDashboardActive ? ' rail-item--active' : ''}`} aria-current={businessDashboardActive ? 'page' : undefined} style={{ justifyContent: showText ? 'flex-start' : 'center', textDecoration: 'none' }}>
              <span className="rail-item__icon"><HomeOutlined sx={{ fontSize: 19 }}/></span>
              {showText && <span className="rail-item__label">Operations dashboard</span>}
            </RouterLink>
          </Tooltip>}

          {showText && <Typography component="div" className="rail-section-label">Modules</Typography>}
          {modulesForUser.map(module => {
            const ModuleIcon = module.icon
            const active = currentModule?.label === module.label
            const open = openModules.includes(module.label)
            return <Box key={module.label} sx={{ mb: .25 }}>
              <Tooltip title={!showText ? module.label : ''} placement="right">
                <button
                  type="button"
                  className={`rail-item${active && !showText ? ' rail-item--active' : ''}${active ? ' rail-item--parent-active' : ''}`}
                  onClick={event => showText ? toggleModule(module.label) : setModuleAnchor({ el: event.currentTarget, module })}
                  aria-expanded={showText ? open : undefined}
                  aria-haspopup={!showText ? 'menu' : undefined}
                  style={{ justifyContent: showText ? 'flex-start' : 'center' }}
                >
                  <span className="rail-item__icon"><ModuleIcon sx={{ fontSize: 19 }}/></span>
                  {showText && <>
                    <span className="rail-item__label" style={{ color: active ? 'var(--wcp-rail-text)' : undefined }}>{module.label}</span>
                    <span className="rail-item__chevron">{open ? <KeyboardArrowDownRounded sx={{ fontSize: 17, transform: 'rotate(180deg)' }}/> : <KeyboardArrowDownRounded sx={{ fontSize: 17 }}/>}</span>
                  </>}
                </button>
              </Tooltip>
              {showText && open && <div className="rail-children" role="group" aria-label={`${module.label} pages`}>
                {module.items.map(item => {
                  const selected = location.pathname === item.path || location.pathname.startsWith(`${item.path}/`)
                  return <RouterLink
                    key={item.path}
                    to={item.path}
                    onClick={() => setMobileOpen(false)}
                    className={`rail-child${selected ? ' rail-child--active' : ''}`}
                    aria-current={selected ? 'page' : undefined}
                  >
                    <span className="rail-child__dot" aria-hidden="true"/>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.label}</span>
                  </RouterLink>
                })}
              </div>}
            </Box>
          })}
        </Box>
      </Box>

      <Box className="rail-footer">
        <Avatar sx={{ width: 30, height: 30, bgcolor: 'var(--wcp-rail-raised)', color: 'var(--wcp-rail-active-text)', fontSize: 10.5, fontWeight: 750, border: '1px solid var(--wcp-rail-line)' }}>{initials(user?.full_name)}</Avatar>
        {showText && <>
          <Box className="rail-footer__meta">
            <Typography className="rail-footer__name">{user?.full_name}</Typography>
            <Typography className="rail-footer__role">{user?.organization_name}</Typography>
          </Box>
          <Tooltip title="Sign out"><IconButton size="small" onClick={() => void logout()} aria-label="Sign out" sx={{ color: 'var(--wcp-rail-muted)', '&:hover': { color: 'var(--wcp-rail-text)', bgcolor: 'var(--wcp-rail-hover)' } }}><LogoutRounded sx={{ fontSize: 18 }}/></IconButton></Tooltip>
        </>}
      </Box>
    </Box>
  }

  return <Box display="flex" minHeight="100vh" sx={{ bgcolor: 'background.default' }}>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    {desktop ? <Box component="aside" sx={{ width: navWidth, flex: '0 0 auto', transition: 'width 160ms cubic-bezier(0.2, 0, 0, 1)' }}>
      <Box sx={{ position: 'fixed', inset: '0 auto 0 0', width: navWidth, zIndex: 1200, transition: 'width 160ms cubic-bezier(0.2, 0, 0, 1)' }}>{navigation()}</Box>
    </Box> : <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} ModalProps={{ keepMounted: true }} PaperProps={{ sx: { width: 292, border: 0 } }}>{navigation(true)}</Drawer>}

    <Box display="flex" flexDirection="column" minWidth={0} flex={1}>
      <Box component="header" className={`app-topbar${scrolled ? ' app-topbar--scrolled' : ''}`} sx={{ position: 'sticky', top: 0, zIndex: 1100 }}>
        <Box display="flex" alignItems="center" gap={{ xs: 1, sm: 1.5 }} sx={{ minHeight: { xs: 58, sm: shell.topBar }, px: { xs: 1.5, sm: 2.5, lg: 3 } }}>
          {!desktop && <IconButton onClick={() => setMobileOpen(true)} aria-label="Open navigation" aria-expanded={mobileOpen}><MenuRounded/></IconButton>}
          <Box minWidth={0} sx={{ flex: 1 }}>
            <nav className="breadcrumb-trail" aria-label="Breadcrumb">
              <RouterLink to="/">
                <HomeOutlined sx={{ fontSize: 13 }}/>
                <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>WellCostIQ</Box>
              </RouterLink>
              <span className="sep" aria-hidden="true">/</span>
              {businessDashboardActive || !currentModule
                ? <span className="current" aria-current="page">{pageLabel}</span>
                : <>
                  <span>{sectionLabel}</span>
                  <span className="sep" aria-hidden="true">/</span>
                  <span className="current" aria-current="page">{pageLabel}</span>
                </>}
            </nav>
            <Typography sx={{ display: { xs: 'block', sm: 'none' }, fontSize: 12.5, fontWeight: 700, mt: .3 }} noWrap>{pageLabel}</Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={{ xs: .5, sm: 1 }} ml="auto" sx={{ flex: '0 0 auto' }}>
            <NotificationBell/>
            <Tooltip title={mode === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}>
              <IconButton onClick={toggle} size="small" aria-label="Toggle color theme" sx={{ color: 'text.secondary' }}>{mode === 'light' ? <DarkModeOutlined sx={{ fontSize: 20 }}/> : <LightModeOutlined sx={{ fontSize: 20 }}/>}</IconButton>
            </Tooltip>
            <Box sx={{ width: '1px', height: 24, bgcolor: 'divider', mx: .5, display: { xs: 'none', sm: 'block' } }}/>
            <Tooltip title="Account menu">
              <button
                type="button"
                onClick={event => setAccountAnchor(event.currentTarget)}
                aria-label="Account menu"
                aria-haspopup="menu"
                aria-expanded={!!accountAnchor}
                className="rail-item"
                style={{ width: 'auto', color: 'var(--wcp-text)', background: 'transparent', padding: '4px 6px' }}
              >
                <Avatar sx={{ width: 30, height: 30, bgcolor: 'primary.light', color: 'primary.main', fontSize: 11, fontWeight: 750 }}>{initials(user?.full_name)}</Avatar>
                <Box sx={{ display: { xs: 'none', md: 'block' }, textAlign: 'left', lineHeight: 1.25 }}>
                  <Typography sx={{ fontSize: 12, fontWeight: 700, color: 'text.primary' }}>{user?.full_name}</Typography>
                  <Typography sx={{ fontSize: 10.5, color: 'text.secondary' }}>{user?.organization_name}</Typography>
                </Box>
                <KeyboardArrowDownRounded sx={{ color: 'text.secondary', fontSize: 17 }}/>
              </button>
            </Tooltip>
          </Box>
        </Box>
      </Box>

      <Menu anchorEl={moduleAnchor?.el} open={!!moduleAnchor} onClose={() => setModuleAnchor(null)}>
        {moduleAnchor?.module.items.map(item => <MenuItem key={item.path} selected={location.pathname === item.path} onClick={() => go(item.path)}>
          <item.icon sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>{item.label}
        </MenuItem>)}
      </Menu>
      <Menu anchorEl={accountAnchor} open={!!accountAnchor} onClose={() => setAccountAnchor(null)}>
        <Box sx={{ px: 2, py: 1.2, minWidth: 220 }}>
          <Typography fontSize={12.5} fontWeight={700}>{user?.full_name}</Typography>
          <Typography fontSize={11.5} color="text.secondary">{user?.email ?? user?.organization_name}</Typography>
        </Box>
        <Box sx={{ borderTop: '1px solid', borderColor: 'divider', my: .5 }}/>
        <MenuItem onClick={() => { setAccountAnchor(null); setPasswordDialog(true); setPasswordError('') }}>
          <ListItemIcon><VpnKeyOutlined sx={{ fontSize: 18 }}/></ListItemIcon>
          <ListItemText primaryTypographyProps={{ fontSize: 13 }}>Change password</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { setAccountAnchor(null); void logout() }}>
          <ListItemIcon><LogoutRounded sx={{ fontSize: 18 }}/></ListItemIcon>
          <ListItemText primaryTypographyProps={{ fontSize: 13 }}>Sign out</ListItemText>
        </MenuItem>
      </Menu>

      <Box component="main" id="main-content" tabIndex={-1} sx={{ flexGrow: 1, minWidth: 0, width: '100%', overflowX: 'clip', '&:focus': { outline: 'none' } }}>
        <Box className="page-shell" sx={{ px: { xs: 2, sm: 3, lg: 4 }, py: { xs: 2.5, sm: 3.5 } }}><Outlet/></Box>
      </Box>
    </Box>

    <Snackbar open={!!apiNotice} onClose={() => setApiNotice(null)} anchorOrigin={{ vertical: 'top', horizontal: 'right' }} sx={{ mt: 7, maxWidth: 480 }}>
      <Alert severity={apiNotice && apiNotice.status === 403 ? 'warning' : 'error'} variant="filled" onClose={() => setApiNotice(null)}
        sx={{ width: '100%', boxShadow: 8, alignItems: 'center' }}>{apiNotice?.message}</Alert>
    </Snackbar>

    <FormDialog open={passwordDialog} title="Change your password" subtitle="You will be signed out of all sessions after updating." onClose={() => setPasswordDialog(false)} onSubmit={changePassword} busy={savingPassword} submitLabel="Update password">
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Current password" type="password" fullWidth autoComplete="current-password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)}/>
        <TextField label="New password" type="password" fullWidth autoComplete="new-password"
          helperText="12–128 characters, at least three of lowercase, uppercase, number and symbol. The last five passwords cannot be reused."
          value={newPassword} onChange={event => setNewPassword(event.target.value)}/>
        <ErrorMessage message={passwordError}/>
      </Box>
    </FormDialog>
  </Box>
}
