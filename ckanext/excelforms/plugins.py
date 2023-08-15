import importlib
import os
import uuid

from ckan.plugins.toolkit import _, h, asbool
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
        p.toolkit.add_resource('assets', 'ckanext-excelforms')

    def get_blueprint(self):
        return blueprint.excelforms

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
