# -*- coding: utf-8 -*-

from django.contrib.gis.geos import Polygon
from django.utils.dateparse import parse_date
from rest_framework.views import APIView
from rest_framework.viewsets import mixins, GenericViewSet, ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_extensions.mixins import NestedViewSetMixin
from asuothodi.utils import get_time_now
from asuothodi import models
from asuothodi.mobileapi_v2 import serializers


class TripViewSet(NestedViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet):
    serializer_class = serializers.TripSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        # определяем переданную дату
        dt = self.request.query_params.get('date', None)
        # сегодняшняя дата
        date_now = get_time_now().date()
        # пробуем найти переданную дату, или устанавливаем текущую
        date = parse_date(dt) if dt else date_now
        # выборка
        return models.Trip.objects.filter(
            trip_group__date=date,
            trip_group__approve=True,
            driver__user=self.request.user
        )


class ReportPlatformViewSet(NestedViewSetMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.ReportPlatform.objects
    serializer_class = serializers.ReportPlatformSerializer
    filter_fields = ['platform', 'plan_platform']


class ReportContainerViewSet(NestedViewSetMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.ReportContainer.objects
    serializer_class = serializers. ReportContainerSerializer
    filter_fields = ['container', 'report_platform']


class ReportLandfillViewSet(NestedViewSetMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.ReportLandfill.objects
    serializer_class = serializers.ReportLandfillSerializer
    filter_fields = ['landfill', 'plan_landfill']


class ReportDepotViewSet(NestedViewSetMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.ReportDepot.objects
    serializer_class = serializers.ReportDepotSerializer
    filter_fields = ['depot', 'type']


class PlatformMixin(object):
    permission_classes = (IsAuthenticated,)
    queryset = models.ContainerPlatform.objects

    def get_queryset(self):
        # основная выдача
        qs = self.queryset.all()

        # пробуем получить ограничивающую зону из GET - она имеет приоритет над остальными
        bounds = self.request.query_params.get('bounds', None)
        if bounds:
            qs = qs.filter(point__within=Polygon.from_bbox(map(float, bounds.split(','))))
        return qs


class PlatformClustersView(PlatformMixin, APIView):

    def get(self, request, *args, **kwargs):
        # определяем запрос
        qs = self.get_queryset()
        # вернем инфу о выборке
        return Response(
            models.ContainerPlatform.clusters(qs, int(self.request.query_params.get('precision', 1))),
        )


class PlatformViewSet(NestedViewSetMixin, PlatformMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet):
    serializer_class = serializers.PlatformSerializer


class ContainerViewSet(NestedViewSetMixin, mixins.ListModelMixin, GenericViewSet):
    queryset = models.Container.objects
    permission_classes = (IsAuthenticated,)
    serializer_class = serializers.ContainerSerializer


class PhotoViewSet(NestedViewSetMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.Photo.objects
    serializer_class = serializers.PhotoSerializer

