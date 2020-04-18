
from main.views import SignatureStatusedModelViewSet
from . import serializers
from main.models import Organization


class OrganizationViewSet(SignatureStatusedModelViewSet):
    queryset = Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
