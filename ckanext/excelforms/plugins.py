import importlib
import os
import uuid

from paste.deploy.converters import asbool
from ckan.plugins.toolkit import _, h
import ckan.plugins as p
from ckan.lib.plugins import DefaultDatasetForm, DefaultTranslation

from ckanext.excelforms import blueprint

def excelforms_language_text(f, field, lang=None):
    if not lang:
        lang = h.lang()
    return f.get(field + '_' + lang, f.get(field, ''))


class ExcelFormsPlugin(p.SingletonPlugin, DefaultTranslation):
    p.implements(p.IConfigurer)
    p.implements(p.IBlueprint)
    p.implements(p.ITemplateHelpers, inherit=True)
    p.implements(p.ITranslation)

    def update_config(self, config):
        # add our templates
        p.toolkit.add_template_directory(config, 'templates')
        p.toolkit.add_public_directory(config, 'public')

    def get_blueprint(self):
        return blueprint.excelforms

    def before_map(self, map):
        map.connect('/recombinant/upload/{id}', action='upload',
            conditions=dict(method=['POST']),
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('/recombinant/delete/{id}/{resource_id}',
            action='delete_records',
            conditions=dict(method=['POST']),
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('recombinant_template',
            '/recombinant-template/{dataset_type}_{lang}_{owner_org}.xlsx',
            action='template',
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('recombinant_data_dictionary',
            '/recombinant-dictionary/{dataset_type}',
            action='data_dictionary',
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('recombinant_schema_json',
            '/recombinant-schema/{dataset_type}.json',
            action='schema_json',
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('recombinant_resource',
            '/recombinant/{resource_name}/{owner_org}',
            action='preview_table',
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('recombinant_type',
            '/recombinant/{resource_name}',
            action='type_redirect',
            controller='ckanext.recombinant.controller:UploadController')
        return map

    def get_helpers(self):
        return {
            'excelforms_language_text': excelforms_language_text,
            }


def generate_uuid(value):
    """
    Create an id for this dataset earlier than normal.
    """
    return str(uuid.uuid4())


def value_from_id(key, converted_data, errors, context):
    """
    Copy the 'id' value from converted_data
    """
    converted_data[key] = converted_data[('id',)]
