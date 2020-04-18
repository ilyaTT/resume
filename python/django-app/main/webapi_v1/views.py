from django.contrib.auth import login
from django.urls import reverse
from django.db.models import Count, Q, FieldDoesNotExist
from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import action, api_view
from rest_framework.permissions import IsAuthenticated, BasePermission, AllowAny
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.exceptions import ParseError, NotFound, APIException
from rest_framework_json_api.views import ReadOnlyModelViewSet
from rest_framework import generics
from main.views import ProtectedModelViewSet, StatusedModelViewSet
from . import serializers
from main.models import (
    Organization, User, Permission, PermissionUI, PermissionUI2Group, Role, RoleUI, RoleUI2Role,
    Photo, File, Municipality, Status, StatusedModel, Okfs, Fkko,
    License, LicenseAddress, LicenseWaste
)
from main.views import DictModelViewSet
from logistic import models as models_logistic
from main.webapi_v1 import actions as main_actions


class OrganizationViewSet(StatusedModelViewSet):
    queryset = Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    filter_fields = ['name_full', 'inn', 'kpp', 'ogrn']

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.annotate(
            count_wasteplace_all=Count('wasteplace'),
            count_wasteplace_accepted=Count('wasteplace', filter=Q(status_label='accepted')),
            count_facility_all=Count('facility'),
            count_facility_accepted=Count('facility', filter=Q(status_label='accepted')),
            count_vehicle_all=Count('vehicle'),
            count_vehicle_accepted=Count('vehicle', filter=Q(status_label='accepted')),
            count_users=Count('users'),
        )
        return qs

##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class PhotoViewSet(ProtectedModelViewSet):
    queryset = Photo.objects.all()
    serializer_class = serializers.PhotoSerializer


class FileViewSet(ProtectedModelViewSet):
    queryset = File.objects.all()
    serializer_class = serializers.FileSerializer


class MunicipalityViewSet(DictModelViewSet):
    queryset = Municipality.objects.all()
    serializer_class = serializers.MunicipalitySerializer
    search_fields = ['name', 'region', 'oktmo']
    ordering_fields = ['oktmo']
    ordering = ['oktmo']

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        # значения автодополнения
        autocomplete = self.request.query_params.get('autocomplete', None)
        if autocomplete:
            qs = qs.filter(
                Q(name__istartswith=autocomplete) |
                Q(region__istartswith=autocomplete) |
                Q(oktmo__istartswith=autocomplete)
            )
        return qs


class OkfsViewSet(DictModelViewSet):
    queryset = Okfs.objects.all()
    serializer_class = serializers.OkfsSerializer
    search_fields = ['name', 'code']


class FkkoViewSet(DictModelViewSet):
    queryset = Fkko.objects.all()
    serializer_class = serializers.FkkoSerializer
    search_fields = ['name', 'number']


class LicenseViewSet(ProtectedModelViewSet):
    queryset = License.objects.all()
    filter_fields = ['number', 'inn']

    def get_serializer_class(self):
        if hasattr(self, 'action'):
            if self.action == 'list':
                return serializers.LicenseSerializer
        return serializers.LicenseSerializerDetail

##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################