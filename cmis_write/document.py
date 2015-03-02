# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    This module copyright (C) 2014 Savoir-faire Linux
#    (<http://www.savoirfairelinux.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import orm, fields
from openerp.addons.connector.session import ConnectorSession
from openerp.addons.connector.queue.job import job
import base64
from openerp import SUPERUSER_ID
from openerp.tools.translate import _
import logging
_logger = logging.getLogger(__name__)


class document_directory(orm.Model):
    _inherit = 'document.directory'

    _columns = {
        'id_dms': fields.char('Id of Dms', size=256, help="Id of Dms."),
    }

    def create(self, cr, uid, values, context=None):
        cmis_backend_obj = self.pool.get('cmis.backend')
        user_obj = self.pool.get('res.users')
        directory_obj = self.pool.get('document.directory')
        dir_id = super(document_directory, self).create(cr, uid, values,
                                                        context=context)
        # login with the cmis account
        backend_ids = cmis_backend_obj.search(cr, uid, [], context=context)
        repo = cmis_backend_obj._auth(cr, uid, backend_ids, context=context)
        user_login = user_obj.browse(cr, uid, uid, context=context).login
        if not backend_ids:
            return dir_id
        cmis_backend = cmis_backend_obj.browse(cr, uid, backend_ids[0],
                                               context=context)
        folder_path = cmis_backend.initial_directory_write

        if folder_path:
            folder = repo.getObjectByPath(folder_path)
        else:
            folder = repo.rootFolder

        if 'parent_id' in values and values['parent_id']:
            parent_dir = directory_obj.browse(cr, uid, values['parent_id'],
                                              context=context)
            if parent_dir.id_dms:
                folder = repo.getObject(parent_dir.id_dms)

        NewFolder = folder.createFolder(values['name'])

        # TODO: create custom properties on a document (Alfresco)
        # someDoc.getProperties().update(props)
        # Updating ir.attachment object with the new id
        # of document generated by DMS
        self.write(cr, uid, dir_id, {
            'id_dms': NewFolder.getObjectId()}, context=context)
        return True

    def write(self, cr, uid, ids, vals, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        cmis_backend_obj = self.pool.get('cmis.backend')
        user_obj = self.pool.get('res.users')
        directory_obj = self.pool.get('document.directory')
        # login with the cmis account
        backend_ids = cmis_backend_obj.search(cr, uid, [], context=context)
        repo = cmis_backend_obj._auth(cr, uid, backend_ids, context=context)
        super(document_directory, self).write(cr, uid, ids, vals,
                                              context=context)
        cmis_backend = cmis_backend_obj.browse(cr, uid, backend_ids[0],
                                               context=context)
        folder_path = cmis_backend.initial_directory_write

        for dir in self.browse(cr, uid, ids, context=context):
            if dir.id_dms:
                dms_folder = repo.getObject(dir.id_dms)
                if 'parent_id' in vals:
                    current_parent = dms_folder.getParent()
                    if vals['parent_id']:
                        parent_dir = directory_obj.browse(
                            cr, uid, vals['parent_id'], context=context)
                        if parent_dir.id_dms:
                            new_parent = repo.getObject(parent_dir.id_dms)
                        else:
                            if folder_path:
                                new_parent = repo.getObjectByPath(folder_path)
                            else:
                                new_parent = repo.rootFolder
                        dms_folder.move(current_parent, new_parent)
                if 'name' in vals:
                    props = {
                        'cmis:name': vals['name'],
                    }
                    dms_folder.updateProperties(props)
        return True

    def unlink(self, cr, uid, ids, context=None):
        cmis_backend_obj = self.pool.get('cmis.backend')
        # login with the cmis account
        backend_ids = cmis_backend_obj.search(cr, uid, [], context=context)
        repo = cmis_backend_obj._auth(cr, uid, backend_ids, context=context)
        for folder in self.read(cr, uid, ids, ['id', 'id_dms'],
                                context=context):
            super(document_directory, self).unlink(cr, uid, folder['id'],
                                                   context=context)
            id_dms = folder['id_dms']
            if id_dms:
                # Get results from id of document
                object = repo.getObject(id_dms)
                try:
                    object.delete()
                except Exception, e:
                    raise orm.except_orm(_('Error'),
                                         _('Cannot delete the folder in the '
                                           'DMS.\n'
                                           '(%s') % e)


class ir_attachment(orm.Model):
    _inherit = 'ir.attachment'

    def action_download(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        cmis_backend_obj = self.pool.get('cmis.backend')
        # login with the cmis account
        backend_ids = cmis_backend_obj.search(cr, uid, [], context=context)
        repo = cmis_backend_obj._auth(cr, uid, backend_ids, context=context)
        cmis_backend_rec = self.read(
            cr, uid, ids, ['id_dms'], context=context)[0]
        id_dms = cmis_backend_rec['id_dms']
        # Get results from id of document
        result = repo.getObject(id_dms)
        datas = result.getContentStream().read().encode('base64')
        return datas

    def _data_set(self, cr, uid, id, name, value, arg, context=None):
        # We dont handle setting data to null
        if not value:
            return True
        if context is None:
            context = {}
        location = self.pool.get('ir.config_parameter').get_param(
            cr, uid, 'ir_attachment.location')
        file_size = len(value.decode('base64'))
        if location:
            attach = self.browse(cr, uid, id, context=context)
            if attach.store_fname:
                self._file_delete(cr, uid, location, attach.store_fname)
            fname = self._file_write(cr, uid, location, value)
            # SUPERUSER_ID as probably don't have write access,
            # trigger during create
            super(ir_attachment, self).write(
                cr, SUPERUSER_ID, [id],
                {'store_fname': fname, 'file_size': file_size},
                context=context)
        else:
            super(ir_attachment, self).write(
                cr, SUPERUSER_ID, [id],
                {'db_datas': value, 'file_size': file_size}, context=context)
        return True

    def _data_get(self, cr, uid, ids, name, arg, context=None):
        if context is None:
            context = {}
        result = {}
        location = self.pool.get('ir.config_parameter').get_param(
            cr, uid, 'ir_attachment.location')
        bin_size = context.get('bin_size')
        for attach in self.browse(cr, uid, ids, context=context):
            if location and attach.store_fname:
                result[attach.id] = self._file_read(
                    cr, uid, location, attach.store_fname, bin_size)
            elif attach.id_dms:
                datas = self.action_download(
                    cr, uid, attach.id, context=context)
                result[attach.id] = datas
                file_type, index_content = self._index(
                    cr, uid, datas.decode('base64'), attach.datas_fname, None)
                self.write(
                    cr, uid, [attach.id],
                    {'file_type': file_type, 'index_content': index_content},
                    context=context)
            else:
                raise orm.except_orm(_('Access error of document'),
                                     _("Document is not available in DMS; "
                                       "Please try again"))
        return result

    _columns = {
        'id_dms': fields.char('Id of Dms', size=256, help="Id of Dms."),
        'download_id': fields.one2many('ir.attachment.download',
                                       'attachment_id',
                                       'Attachment download'),
        'datas': fields.function(_data_get, fnct_inv=_data_set,
                                 string='File Content',
                                 type="binary", nodrop=True),
    }


class document_file(orm.Model):
    _inherit = 'ir.attachment'

    def create(self, cr, uid, values, context=None):
        cmis_backend_obj = self.pool.get('cmis.backend')
        user_obj = self.pool.get('res.users')
        directory_obj = self.pool.get('document.directory')
        ir_attach_obj = self.pool.get('ir.attachment')
        # login with the cmis account
        backend_ids = cmis_backend_obj.search(cr, uid, [], context=context)
        repo = cmis_backend_obj._auth(cr, uid, backend_ids, context=context)
        user_login = user_obj.browse(cr, uid, uid, context=context).login

        value = {
            'name': values.get('name'),
            'datas_fname': values.get('datas_fname'),
            'file_type': values.get('file_type') or '',
            'datas': values.get('datas'),
            'description': values.get('description') or '',

        }

        values['datas'] = None
        doc_id = super(document_file, self).create(cr, uid, values,
                                                   context=context)
        if not backend_ids:
            return doc_id

        cmis_backend = cmis_backend_obj.browse(cr, uid, backend_ids[0],
                                               context=context)
        # Document properties
        if value['name']:
            file_name = value['name']
        elif value['datas_fname']:
            file_name = value['datas_fname']
        else:
            file_name = value['datas_fname']

        folder_path = cmis_backend.initial_directory_write
        if folder_path:
            folder = repo.getObjectByPath(folder_path)
        else:
            folder = repo.rootFolder

        if 'parent_id' in values and values['parent_id']:
            dir = directory_obj.browse(cr, uid, values['parent_id'],
                                       context=context)
            if dir.id_dms:
                folder = repo.getObject(dir.id_dms)

        doc = folder.createDocumentFromString(file_name,
                                              contentString=base64.b64decode(
                                                  value['datas']),
                                              contentType=value['file_type'])
        # TODO: create custom properties on a document (Alfresco)
        # someDoc.getProperties().update(props)
        # Updating ir.attachment object with the new id
        # of document generated by DMS
        ir_attach_obj.write(cr, uid, doc_id, {
            'id_dms': doc.getObjectId()}, context=context)

        return doc_id

    def unlink(self, cr, uid, ids, context=None):
        cmis_backend_obj = self.pool.get('cmis.backend')
        # login with the cmis account
        backend_ids = cmis_backend_obj.search(cr, uid, [], context=context)
        repo = cmis_backend_obj._auth(cr, uid, backend_ids, context=context)
        for attach in self.read(cr, uid, ids, ['id', 'id_dms'],
                                context=context):
            super(document_file, self).unlink(cr, uid, attach['id'],
                                              context=context)
            id_dms = attach['id_dms']
            if id_dms:
                # Get results from id of document
                object = repo.getObject(id_dms)
                try:
                    object.delete()
                except Exception, e:
                    raise orm.except_orm(_('Error'),
                                         _('Cannot delete the document in the '
                                           'DMS.\n'
                                           '(%s') % e)