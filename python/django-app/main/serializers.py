import json
import rsa
from django.db import transaction
from django.core.exceptions import FieldDoesNotExist
from django.utils.timezone import now
from django.core.files.base import ContentFile
from django.db.models.fields import NOT_PROVIDED
from rest_framework_json_api import serializers
from rest_framework_json_api.renderers import JSONRenderer
from main.views import ProtectedModelViewSet, StatusedModelViewSet


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class StatusedModelSerializer(ProtectedModelSerializer):
    status_author = serializers.PrimaryKeyRelatedField(read_only=True)
    allow_transits = serializers.SerializerMethodField(read_only=True)
    versioning = serializers.SerializerMethodField(read_only=True)
    inheritor = serializers.SerializerMethodField(read_only=True)

    def get_allow_actions(self, obj):
        if isinstance(self.context['view'], StatusedModelViewSet) and hasattr(self.context['view'], 'obj_actions'):
            return StatusedModelViewSet.obj_actions(self.context['view'], obj)

    def get_allow_transits(self, obj):
        if isinstance(self.context['view'], StatusedModelViewSet) and hasattr(self.context['view'], 'obj_transits'):
            return StatusedModelViewSet.obj_transits(self.context['view'], obj)

    def get_versioning(self, obj):
        # тип объекта
        obj_type = getattr(type(obj), 'JSONAPIMeta').resource_name
        # проматываем до корневого объекта
        root = obj
        while getattr(root, 'inheritor', None):
            root = root.inheritor
        # собираем версии
        obj = root
        items = []
        while obj:
            items.append({
                'id': obj.id,
                'type': obj_type,
                'status_history': obj.status_history,
            })
            obj = obj.original
        return items

    def get_inheritor(self, obj):
        # тип объекта
        obj_type = getattr(type(obj), 'JSONAPIMeta').resource_name
        return {
            'data': {
                'id': obj.inheritor.id,
                'type': obj_type,
            } if getattr(obj, 'inheritor', None) else None
        }

    class Meta(ProtectedModelSerializer.Meta):
        meta_fields = ProtectedModelSerializer.Meta.meta_fields + ['allow_transits']

    def __init__(self, *args, **kwargs):
        meta = getattr(self, 'Meta')
        meta_fields = getattr(meta, 'meta_fields', None)
        if not meta_fields:
            setattr(meta, 'meta_fields', [])
            meta_fields = getattr(meta, 'meta_fields')

        if 'allow_transits' not in meta_fields:
            meta_fields.append('allow_transits')

        # версионность добавляется только в несписковые сериализаторы
        if 'context' in kwargs and 'view' in kwargs['context'] and kwargs['context']['view'].action != 'list':
            if 'versioning' not in meta_fields:
                meta_fields.append('versioning')
            if 'inheritor' not in meta_fields:
                meta_fields.append('inheritor')

        super().__init__(*args, **kwargs)

        fields = self.fields
        fields['note'] = serializers.CharField(required=False, allow_blank=True, allow_null=True)
        fields['status_author'] = serializers.PrimaryKeyRelatedField(read_only=True)
        fields['status_author_name'] = serializers.ReadOnlyField(source='status_author.get_full_name')
        fields['status_label'] = serializers.CharField(read_only=True)
        fields['status_dt'] = serializers.DateTimeField(read_only=True)
        fields['status_history'] = serializers.JSONField(read_only=True)
        fields['signature_sign'] = serializers.CharField(read_only=True)
        fields['signature_dt'] = serializers.DateTimeField(read_only=True)
        fields['signature_author_name'] = serializers.ReadOnlyField(source='signature_author.get_full_name')
        fields['signature_json_file'] = serializers.FileField(read_only=True)
        fields['signature_invalid'] = serializers.BooleanField(read_only=True)
        fields['original'] = serializers.PrimaryKeyRelatedField(read_only=True)


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################