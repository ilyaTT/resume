
from main.serializers import (
    SignatureSerializer, SignatureDictModelSerializer
)
from main.models import Organization, Photo, Municipality, Okfs


class OkfsSerializer(SignatureDictModelSerializer):
    class Meta:
        ref_name = 'SignatureOkfs'
        model = Okfs
        fields = ['code']


class OrganizationSerializer(SignatureSerializer):
    class Meta:
        ref_name = 'SignatureOrganization'
        model = Organization
        fields = ['name_full', 'name_short', 'address_legal', 'address_post_index', 'address_post',
                  'okfs', 'inn', 'kpp', 'ogrn', 'okpo', 'egr', 'okved', 'rs', 'ks', 'bik', 'opf', 'personal_account',
                  'bank_name', 'owner_type', 'justification',
                  'director_name', 'director_position', 'contacts', 'comment']

    class JSONAPIMeta:
        included_resources = ['okfs']

    included_serializers = {
        'okfs': OkfsSerializer,
    }


class PhotoSerializer(SignatureSerializer):
    class Meta:
        ref_name = 'SignaturePhoto'
        model = Photo
        fields = ['file', 'extra']


class MunicipalitySerializer(SignatureDictModelSerializer):
    class Meta:
        ref_name = 'SignatureMunicipality'
        model = Municipality
        fields = ['region', 'oktmo']

