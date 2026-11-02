import { useCallback, useEffect, useMemo, useState } from 'react'
import { AddRounded, DeleteOutlineRounded, EditOutlined, RestoreOutlined } from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { ErrorMessage, FormDialog, Tag, useFormDirty } from './Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import {
  emptyVendorServiceSubcategoryForm,
  type Vendor,
  type VendorServiceSubcategory,
  type VendorServiceSubcategoryPayload,
} from '../lib/vendorMaster'

/**
 * Manage one vendor's service subcategories (Halliburton → RDT Service, Liner
 * Service, DD, MWD …). These are the rows a well sub activity picks from when
 * it names its responsible party, and what NPT/UPA reporting rolls up by.
 */
export function VendorServiceSubcategoriesDialog({ vendor, open, onClose, onChanged }: {
  vendor: Vendor | null
  open: boolean
  onClose: () => void
  onChanged?: () => void
}) {
  const { can } = useAuth()
  const [rows, setRows] = useState<VendorServiceSubcategory[]>([])
  const [deletedRows, setDeletedRows] = useState<VendorServiceSubcategory[]>([])
  const [showDeleted, setShowDeleted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<VendorServiceSubcategory | null>(null)
  const [form, setForm] = useState<VendorServiceSubcategoryPayload>(emptyVendorServiceSubcategoryForm())
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const formDirty = useFormDirty(form, formOpen)

  const canCreate = can('master-data:create')
  const canUpdate = can('master-data:update')
  const canDelete = can('master-data:delete')
  const canRestore = can('master-data:restore')

  const load = useCallback(async () => {
    if (!vendor) return
    setLoading(true)
    setError('')
    try {
      const [active, deleted] = await Promise.all([
        api<VendorServiceSubcategory[]>(`/master-data/vendor-service-subcategories?vendor_id=${encodeURIComponent(vendor.id)}`),
        api<VendorServiceSubcategory[]>(`/master-data/vendor-service-subcategories?vendor_id=${encodeURIComponent(vendor.id)}&include_deleted=true`),
      ])
      setRows(active)
      setDeletedRows(deleted.filter(row => row.is_deleted))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Service subcategories could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [vendor])

  useEffect(() => {
    if (!open) {
      setRows([])
      setDeletedRows([])
      setShowDeleted(false)
      setNotice('')
      setError('')
      return
    }
    void load()
  }, [open, load])

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptyVendorServiceSubcategoryForm())
    setFormError('')
    setFormOpen(true)
  }

  const openEdit = (record: VendorServiceSubcategory) => {
    setFormRecord(record)
    setForm({ subcategory_code: record.subcategory_code, subcategory_name: record.subcategory_name, description: record.description })
    setFormError('')
    setFormOpen(true)
  }

  const save = async () => {
    if (!vendor) return
    setSaving(true)
    setFormError('')
    const payload = {
      subcategory_code: form.subcategory_code.trim(),
      subcategory_name: form.subcategory_name.trim(),
      description: form.description.trim(),
    }
    try {
      if (formRecord) {
        await api(`/master-data/vendor-service-subcategories/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`Service subcategory ${payload.subcategory_code} updated.`)
      } else {
        await api('/master-data/vendor-service-subcategories', {
          method: 'POST', body: body({ ...payload, vendor_id: vendor.id }),
        })
        setNotice(`Service subcategory ${payload.subcategory_code} added to ${vendor.vendor_name}.`)
      }
      setFormOpen(false)
      setFormRecord(null)
      await load()
      onChanged?.()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this service subcategory')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (record: VendorServiceSubcategory) => {
    setError('')
    try {
      await api(`/master-data/vendor-service-subcategories/${record.id}`, { method: 'DELETE' })
      setNotice(`Service subcategory ${record.subcategory_code} moved to deleted entries.`)
      await load()
      onChanged?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not move this service subcategory to deleted entries')
    }
  }

  const restore = async (record: VendorServiceSubcategory) => {
    setError('')
    try {
      await api(`/master-data/vendor-service-subcategories/${record.id}/restore`, { method: 'POST' })
      setNotice(`Service subcategory ${record.subcategory_code} restored.`)
      await load()
      onChanged?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not restore this service subcategory')
    }
  }

  const visibleRows = showDeleted ? deletedRows : rows
  const heading = useMemo(
    () => vendor ? `${vendor.vendor_code} — ${vendor.vendor_name}` : 'Vendor service subcategories',
    [vendor],
  )

  return <>
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" aria-labelledby="vendor-subcategories-title">
      <DialogTitle id="vendor-subcategories-title" sx={{ px: 3, pt: 3, pb: 1 }}>
        <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px' }}>Service subcategories</Box>
        <Typography component="span" display="block" color="text.secondary" fontSize={12.5} mt={.6}>
          {heading} · the distinct services this vendor delivers. Well sub activities pick one of them, so NPT/UPA and cost reporting can be read per vendor and per vendor service.
        </Typography>
      </DialogTitle>
      <DialogContent sx={{ px: 3, pb: 1 }}>
        {vendor?.status === 'blocked' && <Alert severity="warning" sx={{ mb: 1.5 }}>
          This vendor is blocked. Existing records stay intact, but new PO/SO orders are refused.
        </Alert>}
        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
        <ErrorMessage message={error}/>
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={1.4} flexWrap="wrap">
          <Box display="flex" gap={1}>
            <Button size="small" variant={showDeleted ? 'outlined' : 'contained'} onClick={() => setShowDeleted(false)}>
              Active ({rows.length})
            </Button>
            <Button size="small" variant={showDeleted ? 'contained' : 'outlined'} onClick={() => setShowDeleted(true)} disabled={!deletedRows.length}>
              Deleted ({deletedRows.length})
            </Button>
          </Box>
          {canCreate && !showDeleted && <Button size="small" variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>
            Add service subcategory
          </Button>}
        </Box>
        {loading ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : visibleRows.length === 0 ? (
          <Box sx={{ border: '1px dashed', borderColor: 'divider', borderRadius: 1.5, p: 3, textAlign: 'center' }}>
            <Typography fontSize={13} fontWeight={700}>No service subcategories {showDeleted ? 'in deleted entries' : 'configured yet'}.</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.5}>
              {showDeleted
                ? 'Deleted subcategories can be restored while they are not referenced by an active sub activity.'
                : 'Add the services this vendor delivers, for example RDT Service, Liner Service, DD or MWD.'}
            </Typography>
          </Box>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>CODE</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>SERVICE SUBCATEGORY</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>DESCRIPTION</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11, textAlign: 'right' }}>SUB ACTIVITIES</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11, textAlign: 'right' }}>ACTIONS</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map(record => <TableRow key={record.id} hover>
                <TableCell sx={{ fontSize: 12.5 }}>{record.subcategory_code}</TableCell>
                <TableCell sx={{ fontSize: 12.5, fontWeight: 700 }}>{record.subcategory_name}</TableCell>
                <TableCell sx={{ fontSize: 12, color: 'text.secondary' }}>{record.description || '—'}</TableCell>
                <TableCell sx={{ fontSize: 12.5, textAlign: 'right' }}>
                  {showDeleted ? <Tag tone="warning">Deleted</Tag> : record.sub_activity_count}
                </TableCell>
                <TableCell sx={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  {!showDeleted && canUpdate && <Button size="small" startIcon={<EditOutlined sx={{ fontSize: 15 }}/>} onClick={() => openEdit(record)}>Edit</Button>}
                  {!showDeleted && canDelete && <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>} onClick={() => void remove(record)}>Delete</Button>}
                  {showDeleted && canRestore && <Button size="small" startIcon={<RestoreOutlined sx={{ fontSize: 15 }}/>} onClick={() => void restore(record)}>Restore</Button>}
                </TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        )}
        <Divider sx={{ my: 2 }}/>
        <Typography color="text.secondary" fontSize={11.5}>
          A service subcategory is unique per vendor in this workspace. Deleting one keeps historical sub activities and reports readable; an active sub activity must be reassigned before its subcategory can be deleted.
        </Typography>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5 }}>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>

    <FormDialog
      open={formOpen}
      title={formRecord ? `Edit service subcategory ${formRecord.subcategory_code}` : `Add service subcategory · ${vendor?.vendor_code ?? ''}`}
      subtitle="Codes are upper-cased and unique within this vendor. This is the service line shown in sub activity and NPT/UPA reporting."
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={() => void save()}
      busy={saving}
      dirty={formDirty}
      submitDisabled={!form.subcategory_code.trim() || !form.subcategory_name.trim()}
      submitLabel={formRecord ? 'Save changes' : 'Add service subcategory'}
      maxWidth="sm"
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Subcategory code" required fullWidth value={form.subcategory_code}
          onChange={event => setForm({ ...form, subcategory_code: event.target.value })}
          inputProps={{ maxLength: 50 }} helperText="For example RDT, LINER, DD, MWD. Upper-cased, unique per vendor."/>
        <TextField label="Service subcategory name" required fullWidth value={form.subcategory_name}
          onChange={event => setForm({ ...form, subcategory_name: event.target.value })}
          inputProps={{ maxLength: 150 }} helperText="For example Halliburton — Liner Service."/>
        <TextField label="Description" fullWidth multiline minRows={2} value={form.description}
          onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 500 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>
  </>
}
