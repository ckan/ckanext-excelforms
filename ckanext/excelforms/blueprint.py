import re
from collections import OrderedDict
import simplejson as json

from logging import getLogger

from flask import Response, Blueprint
from ckan.plugins.toolkit import (_, config, asbool, aslist, render,
    request, h, abort, g)
from ckan.logic import ValidationError, NotAuthorized

from ckanext.excelforms.errors import BadExcelData
from ckanext.excelforms.read_excel import read_excel, get_records
from ckanext.excelforms.write_excel import excel_template, append_data

from io import BytesIO

log = getLogger(__name__)

import ckanapi

excelforms = Blueprint('excelforms', __name__)

def _get_data_dictionary(lc, resource_id):
    table = lc.action.datastore_search(
        resource_id=resource_id,
        limit=0,
        include_total=False)
    return table['fields']

@excelforms.route('/dataset/<id>/excelforms/<resource_id>/upload', methods=['POST'])
def upload(id, resource_id):
    """
    View for downloading Excel templates and
    uploading packages via Excel .xls files
    """
    lc = ckanapi.LocalCKAN(username=g.user)
    dd = _get_data_dictionary(lc, resource_id)
    dry_run = 'validate' in request.form
    try:
        if not request.files['xls_update']:
            raise BadExcelData(_('You must provide a valid file'))

        _process_upload_file(
            lc,
            resource_id,
            request.files['xls_update'],
            dd,
            dry_run)

        if dry_run:
            h.flash_success(_(
                "No errors found."
                ))
        else:
            h.flash_success(_(
                "Your file was successfully uploaded."
                ))

    except BadExcelData as e:
        h.flash_error(e.message)

    return h.redirect_to('dataset_resource.read', id=id, resource_id=resource_id)


@excelforms.route('/dataset/<id>/excelforms/template-<resource_id>.xlsx', methods=['GET'])
def template(id, resource_id):
    """
    Generate excel template

    POST requests to this endpoint contain primary keys of records that are to be included in the excel file
    Parameters:
        bulk-template -> an array of strings, each string contains primary keys separated by commas
    """

    lc = ckanapi.LocalCKAN(username=g.user)
    dd = _get_data_dictionary(lc, resource_id)
    resource = lc.action.resource_show(id=resource_id)

    book = excel_template(resource, dd)

    if request.method == 'POST':
        filters = {}
        primary_keys = request.POST.getall('bulk-template')

        record_data = []

        for keys in primary_keys:
            temp = keys.split(",")
            for f, pkf in zip(temp, pk_fields):
                filters[pkf['datastore_id']] = f
            try:
                result = lc.action.datastore_search(resource_id=resource_id,filters = filters)
            except NotAuthorized:
                abort(403, _("Not authorized"))
            record_data += result['records']

        append_data(book, record_data, dd)

    blob = BytesIO()
    book.save(blob)
    response = Response(blob.getvalue())
    # (canada fork only): modify response headers for Microsoft Edge
    content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    disposition_type = 'inline'
    user_agent_legacy = request.get('headers', {}).get('User-Agent')
    user_agent = request.get('headers', {}).get('Sec-CH-UA', user_agent_legacy)
    if user_agent and (
        "Microsoft Edge" in user_agent or
        "Edg/" in user_agent or
        "EdgA/" in user_agent
        ):
            content_type = 'application/octet-stream'
            disposition_type = 'attachment'
    response.content_type = content_type
    response.headers['Content-Disposition'] = (
        '{}; filename="template_{0}.xlsx"'.format(disposition_type, resource_id))
    return response


def _process_upload_file(lc, resource_id, upload_file, dd, dry_run):
    """
    Use lc.action.datastore_upsert to load data from upload_file

    raises BadExcelData on errors.
    """
    upload_data = read_excel(upload_file)
    total_records = 0
    try:
        sheet_name, res_id, column_names, rows = next(upload_data)
    except BadExcelData as e:
        raise e
    except Exception:
        # unfortunately this can fail in all sorts of ways
        if asbool(config.get('debug', False)):
            # on debug we want the real error
            raise
        raise BadExcelData(
            _("The server encountered a problem processing the file "
            "uploaded. Please try copying your data into the latest "
            "version of the template and uploading again."))

    if resource_id != res_id:
        raise BadExcelData(
            _("This template is for a different resource: {0}").format(res_id)
        )

    # custom styles or other errors cause columns to be read
    # that actually have no data. strip them here to avoid error below
    while column_names and column_names[-1] is None:
        column_names.pop()

    # XXX
    expected_columns = [f['id'] for f in dd if f['id'] != '_id']
    if column_names != expected_columns:
        raise BadExcelData(
            _("This template is out of date. "
            "Please try copying your data into the latest "
            "version of the template and uploading again."))

    pk = []
#    pk = chromo.get('datastore_primary_key', [])
    choice_fields = {}
#    choice_fields = {
#        f['datastore_id']:
#            'full' if f.get('excel_full_text_choices') else True
#        for f in chromo['fields']
#        if ('choices' in f or 'choices_file' in f)}

    records = get_records(
        rows,
        [f for f in dd if f['id'] != '_id'],
        pk,
        choice_fields)
    method = 'upsert' if any(f.get('info',{}).get('pk') for f in dd) else 'insert'
    total_records += len(records)
    if not records:
        raise BadExcelData(_("The template uploaded is empty"))
    try:
        lc.action.datastore_upsert(
            method=method,
            resource_id=resource_id,
            records=[r[1] for r in records],
            dry_run=dry_run,
            force=True,
            )
    except ValidationError as e:
        if 'info' in e.error_dict:
            # because, where else would you put the error text?
            # XXX improve this in datastore, please
            pgerror = e.error_dict['info']['orig'][0].decode('utf-8')
        elif 'records' in e.error_dict:
            pgerror = e.error_dict['records'][0]
        else:
            assert 0, e.error_dict
        if isinstance(pgerror, dict):
            pgerror = u'; '.join(
                k + u': ' + u', '.join(v)
                for k, v in pgerror.items())
        else:
            # remove some postgres-isms that won't help the user
            # when we render this as an error in the form
            pgerror = re.sub(r'\nLINE \d+:', '', pgerror)
            pgerror = re.sub(r'\n *\^\n$', '', pgerror)
        if '_records_row' in e.error_dict:
            raise BadExcelData(_(u'Sheet {0} Row {1}:').format(
                sheet_name, records[e.error_dict['_records_row']][0])
                + u' ' + pgerror)
        raise BadExcelData(
            _(u"Error while importing data: {0}").format(
                pgerror))
