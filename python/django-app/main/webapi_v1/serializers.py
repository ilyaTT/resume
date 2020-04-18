
from itertools import chain
from rest_framework_json_api import serializers
from main.serializers import (
    StatusedModelSerializer, ProtectedModelSerializer, ProtectedModelGeoSerializerMixin, DictModelSerializer
)
from main.models import (
    Organization, Role, RoleUI, User, Permission, PermissionUI, Photo, File, Municipality, Okfs, Fkko,
    License, LicenseAddress, LicenseWaste, PermissionUI2Group
)


class OkfsSerializer(DictModelSerializer):
    class Meta:
        model = Okfs
        fields = ['code']


class FkkoSerializer(DictModelSerializer):
    class Meta:
        model = Fkko
        fields = ['number', 'selected']


class OrganizationSerializer(StatusedModelSerializer):
    aggs = serializers.SerializerMethodField(read_only=True)

    def get_aggs(self, obj):
        return {
            'count_wasteplace_all': getattr(obj, 'count_wasteplace_all', None),
            'count_wasteplace_accepted': getattr(obj, 'count_wasteplace_accepted', None),
            'count_facility_all': getattr(obj, 'count_facility_all', None),
            'count_facility_accepted': getattr(obj, 'count_facility_accepted', None),
            'count_vehicle_all': getattr(obj, 'count_vehicle_all', None),
            'count_vehicle_accepted': getattr(obj, 'count_vehicle_accepted', None),
            'count_users': getattr(obj, 'count_users', None),
        }

    class Meta:
        model = Organization
        fields = ['name_full', 'name_short', 'address_legal', 'address_post_index', 'address_post',
                  'okfs', 'inn', 'kpp', 'ogrn', 'okpo', 'egr', 'okved', 'rs', 'ks', 'bik', 'opf', 'personal_account',
                  'bank_name', 'owner_type', 'justification',
                  'director_name', 'director_position', 'contacts', 'comment', 'license_set']
        meta_fields = ['aggs']
        extra_kwargs = {
            'license_set': {'required': False},
            'okfs': {'required': True},
        }

    class JSONAPIMeta:
        included_resources = ['license_set', 'okfs']

    included_serializers = {
        'license_set': 'main.webapi_v1.serializers.LicenseSerializer',
        'okfs': OkfsSerializer,
    }


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################

class PhotoSerializer(ProtectedModelSerializer):
    class Meta:
        model = Photo
        fields = ['file', 'extra']


class FileSerializer(ProtectedModelSerializer):
    class Meta:
        model = File
        fields = ['title', 'file', 'extra']


class MunicipalitySerializer(DictModelSerializer):
    class Meta:
        model = Municipality
        fields = ['region', 'oktmo', 'parent', 'level']


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################

