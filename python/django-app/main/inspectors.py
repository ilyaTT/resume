"""
This has been created to answer the following question on stackoverflow
https://stackoverflow.com/questions/46157710/django-swagger-and-json-api-render-issues

This file lives in the folder 'jsonapi'. The following is code is added into the settings.py to enable the
code contained within this file.


# DRF-yasg settings
SWAGGER_SETTINGS = {
    'DEFAULT_MODEL_RENDERING': ['example', ],
    'DEFAULT_PAGINATOR_INSPECTORS': [
        'drf_yasg.inspectors.DjangoRestResponsePagination',
        'jsonapi.inspectors.DjangoRestJsonApiResponsePaginationInspector',
        'drf_yasg.inspectors.CoreAPICompatInspector',
    ],
    'DEFAULT_FIELD_INSPECTORS': [
        # Be careful, you must keep order of inspectors, just remove RelatedFieldInspector
        # and SimpleFieldInspector and put jsonapi inspectors on positions where it commented now
        'drf_yasg.inspectors.CamelCaseJSONFilter',
        # 'jsonapi.inspectors.ModelSerializerInspector',  <- must be set manual
        #  per json+api viewset instead RelatedFieldInspector
        'drf_yasg.inspectors.ReferencingSerializerInspector',
        'drf_yasg.inspectors.RelatedFieldInspector',
        'jsonapi.inspectors.ResourceRelatedFieldAndBaseRelatedFieldInspector',
        'drf_yasg.inspectors.ChoiceFieldInspector',
        'drf_yasg.inspectors.FileFieldInspector',
        'drf_yasg.inspectors.DictFieldInspector',
        'drf_yasg.inspectors.HiddenFieldInspector',
        'drf_yasg.inspectors.RecursiveFieldInspector',
        # 'jsonapi.inspectors.SimpleFieldOmitPKInspector',  <- must be set manual
        # per json+api viewset instead SimpleFieldInspector
        'drf_yasg.inspectors.SimpleFieldInspector',
        'drf_yasg.inspectors.StringDefaultFieldInspector',
    ],
  
"""


from collections import OrderedDict

from rest_framework.pagination import LimitOffsetPagination
from rest_framework_json_api.pagination import JsonApiPageNumberPagination
from rest_framework_json_api import serializers
from rest_framework_json_api.relations import get_resource_type_from_serializer
from rest_framework_json_api.utils import get_related_resource_type
from drf_yasg.codecs import openapi
from drf_yasg.inspectors.base import FieldInspector, PaginatorInspector, NotHandled
from drf_yasg.inspectors.field import get_basic_type_info, RelatedFieldInspector
from rest_framework import generics
from rest_framework.viewsets import mixins, GenericViewSet, ModelViewSet


class SimpleFieldOmitPKInspector(FieldInspector):
    """Inherit SimpleFieldInspector but omit Primary keys
    Right now just omit
    """

    def field_to_swagger_object(self, field, swagger_object_type, use_references, **kwargs):
        # Omit pk fields
        if hasattr(field, 'parent') and isinstance(field.parent, serializers.ModelSerializer):
            parent = field.parent
            meta = getattr(parent, 'Meta', None)
            if meta is not None:
                model = getattr(meta, 'model', None)
                if model is not None:
                    pk_name = model._meta.pk.attname
                    if field.field_name == pk_name:
                        return None
        type_info = get_basic_type_info(field)
        if type_info is None:
            return NotHandled

        SwaggerType, ChildSwaggerType = self._get_partial_types(field, swagger_object_type, use_references, **kwargs)
        return SwaggerType(**type_info)


class ResourceRelatedFieldAndBaseRelatedFieldInspector(RelatedFieldInspector):
    def field_to_swagger_object(self, field, swagger_object_type, use_references, **kwargs):
        if isinstance(field, serializers.ResourceRelatedField) \
                or (isinstance(field, serializers.ManyRelatedField) and
                    isinstance(field.child_relation, serializers.ResourceRelatedField)):
            return None
        else:
            return super().field_to_swagger_object(field, swagger_object_type, use_references, **kwargs)


class ModelSerializerInspector(FieldInspector):
    def process_result(self, result, method_name, obj, **kwargs):
        if isinstance(obj, serializers.ModelSerializer) \
                and method_name == 'field_to_swagger_object':
            model_response = self.formatted_model_result(result, obj)
            if obj.parent is None and self.view.action != 'list':
                # It will be top level object not in list, decorate with data
                return self.decorate_with_data(model_response)

            return model_response

        return result

    def generate_relationships(self, obj):
        relationships_properties = []
        for field in obj.fields.values():
            if isinstance(field, serializers.ResourceRelatedField) \
                    or (isinstance(field, serializers.ManyRelatedField) and
                        isinstance(field.child_relation, serializers.ResourceRelatedField)):
                schema = self.generate_relationship(field)
                relationships_properties.append(schema)
        if relationships_properties:
            return openapi.Schema(
                title='Relationships of object',
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict(relationships_properties),
            )

    def generate_relationship(self, field):
        field_schema = openapi.Schema(
            title='Relationship object',
            type=openapi.TYPE_OBJECT,
            properties=OrderedDict((
                ('type', openapi.Schema(
                    type=openapi.TYPE_STRING,
                    title='Type of related object',
                    enum=[get_related_resource_type(field)]
                )),
                ('id', openapi.Schema(
                    type=openapi.TYPE_STRING,
                    title='ID of related object',
                ))
            ))
        )
        is_many = isinstance(field, serializers.ManyRelatedField)
        return field.field_name, self.decorate_with_data(field_schema, is_many)

    def formatted_model_result(self, result, obj):
        return openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['properties'],
            properties=OrderedDict((
                ('type', openapi.Schema(
                    type=openapi.TYPE_STRING,
                    enum=[get_resource_type_from_serializer(obj)],
                    title='Type of related object',
                )),
                ('id', openapi.Schema(
                    type=openapi.TYPE_STRING,
                    title='ID of related object',
                    read_only=True
                )),
                ('attributes', result),
                ('relationships', self.generate_relationships(obj))
            ))
        )

    @staticmethod
    def decorate_with_data(result, is_many=False):
        if is_many is True:
            child_schema = openapi.Schema(
                type=openapi.TYPE_ARRAY,
                items=result,
                unique_items=True
            )
        else:
            child_schema = result
        return openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['data'],
            properties=OrderedDict((
                ('data', child_schema),
            ))
        )


class DjangoRestJsonApiResponsePaginationInspector(PaginatorInspector):
    def get_paginator_parameters(self, paginator):

        # The json api uses different settings for the pagination
        if isinstance(paginator, JsonApiPageNumberPagination):
            return [
                openapi.Parameter(
                    'page[size]', in_=openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                    description="Number of items per page"
                ),
                openapi.Parameter(
                    'page[number]', in_=openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                    description="Page number"
                ),
            ]
        else:
            return [
                openapi.Parameter(
                    'start', in_=openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                    description="Item number to start from"
                ),
                openapi.Parameter(
                    'limit', in_=openapi.IN_QUERY, type=openapi.TYPE_INTEGER,
                    description="Number of items to return"
                ),
            ]

    def get_paginated_response(self, paginator, response_schema):
        paged_schema = None
        if isinstance(paginator, LimitOffsetPagination):
            paged_schema = openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties=OrderedDict((
                    ('links', self.generate_links()),
                    ('data', response_schema),
                    ('meta', self.generate_meta())
                )),
                required=['data']
            )

        return paged_schema

    def generate_links(self):
        return openapi.Schema(
            title='Links',
            type=openapi.TYPE_OBJECT,
            required=['first', 'last'],
            properties=OrderedDict((
                ('first', openapi.Schema(
                    type=openapi.TYPE_STRING, title='Link to first object',
                    read_only=True, format=openapi.FORMAT_URI
                )),
                ('last', openapi.Schema(
                    type=openapi.TYPE_STRING, title='Link to last object',
                    read_only=True, format=openapi.FORMAT_URI
                )),
                ('next', openapi.Schema(
                    type=openapi.TYPE_STRING, title='Link to next object',
                    read_only=True, format=openapi.FORMAT_URI
                )),
                ('prev', openapi.Schema(
                    type=openapi.TYPE_STRING, title='Link to prev object',
                    read_only=True, format=openapi.FORMAT_URI
                ))
            ))
        )

    def generate_meta(self):
        return openapi.Schema(
            title='Meta of result with pagination count',
            type=openapi.TYPE_OBJECT,
            required=['count'],
            properties=OrderedDict((
                ('count', openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    title='Number of results on page',
                )),
            ))
        )
