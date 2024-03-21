import re

from logging import getLogger

from flask import Response, Blueprint
from ckan.plugins.toolkit import (
    _, config, asbool, request, h, abort, g
)
from ckan.logic import ValidationError, NotAuthorized

from ckanext.excelforms.errors import BadExcelData
from ckanext.excelforms.read_excel import read_excel, get_records
from ckanext.excelforms.write_excel import excel_template

from io import BytesIO

import ckanapi

EXCEL_CT = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

log = getLogger(__name__)

excelforms = Blueprint('excelforms', __name__)


def _get_data_dictionary(lc, resource_id):
    table = lc.action.datastore_info(id=resource_id)
    return table['fields']


@excelforms.route(
    '/dataset/<id>/excelforms/<resource_id>/upload', methods=['POST'])
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

    return h.redirect_to(
        'dataset_resource.read', id=id, resource_id=resource_id)


def _xlsx_response_headers():
    """
    Returns tuple of content type and disposition type.

    If the request is from MS Edge user agent, we force the XLSX
    download to prevent Edge from cowboying into Office Apps Online
    """
    content_type = EXCEL_CT
    disposition_type = 'inline'
    user_agent_legacy = getattr(request, 'headers', {}).get('User-Agent')
    user_agent = getattr(request, 'headers', {}).get('Sec-CH-UA', user_agent_legacy)
    if user_agent and (
        "Microsoft Edge" in user_agent or
        "Edg/" in user_agent or
        "EdgA/" in user_agent
        ):
            # force the XLSX file to be downloaded in MS Edge,
            # and not open in Office Apps Online.
            content_type = 'application/octet-stream'
            disposition_type = 'attachment'
    return content_type, disposition_type


@excelforms.route(
    '/dataset/<id>/excelforms/template-<resource_id>.xlsx', methods=['GET'])
def template(id, resource_id):
    """
    Generate excel template

    POST requests to this endpoint contain primary keys of records that are
    to be included in the excel file
    Parameters:
        _id -> an array of strings, each string contains an _id column value
    """

    lc = ckanapi.LocalCKAN(username=g.user)
    dd = _get_data_dictionary(lc, resource_id)
    resource = lc.action.resource_show(id=resource_id)

    _ids = request.params.getlist('_id')
    records = []

    if _ids:
        filters = {'_id': _ids}

        try:
            result = lc.action.datastore_search(
                resource_id=resource_id,
                filters=filters,
            )
        except NotAuthorized:
            return abort(403, _("Not authorized"))

        records = result['records']

    book = excel_template(resource, dd, records)

    blob = BytesIO()
    book.save(blob)
    response = Response(blob.getvalue())
    content_type, disposition_type = _xlsx_response_headers()
    response.content_type = content_type
    response.headers['Content-Disposition'] = (
        '{0}; filename="template_{1}.xlsx"'.format(disposition_type, resource_id))
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
        raise BadExcelData(_(
            "The server encountered a problem processing the file "
            "uploaded. Please try copying your data into the latest "
            "version of the template and uploading again."
        ))

    if resource_id != res_id:
        raise BadExcelData(
            _("This template is for a different resource: {0}").format(res_id)
        )

    # custom styles or other errors cause columns to be read
    # that actually have no data. strip them here to avoid error below
    while column_names and column_names[-1] is None:
        column_names.pop()

    expected_columns = [f['id'] for f in dd if f['id'] != '_id']
    update_action = False
    if column_names[:1] == ['_id']:
        update_action = True
        del column_names[0]

    if column_names != expected_columns:
        raise BadExcelData(_(
            "This template is out of date. "
            "Please try copying your data into the latest "
            "version of the template and uploading again."
        ))

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
        [f for f in dd if update_action or f['id'] != '_id'],
        pk,
        choice_fields)
    has_pk = any(f.get('tdpkreq') == 'pk' for f in dd)
    method = 'update' if update_action else 'upsert' if has_pk else 'insert'
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
        head, sep, rerr = pgerror.partition('\t')
        if head == 'TAB-DELIMITED' and sep:
            it = iter(rerr.split('\t'))
            pgerror = '; '.join(k + ': ' + e for (k, e) in zip(it, it))
        row = e.error_dict.get('records_row', e.error_dict.get('_records_row'))
        if row is not None:
            raise BadExcelData(
                _(u'Data row {0}:').format(records[row][0])
                + u' ' + pgerror
            )
        raise BadExcelData(
            _(u"Error while importing data: {0}").format(
                pgerror))
