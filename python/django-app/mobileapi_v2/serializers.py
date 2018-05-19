# -*- coding: utf-8 -*-

from rest_framework import serializers
from asuothodi import models
from asuothodi.frozen_model import FrozenModelSerializer


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class ContainerSerializer(FrozenModelSerializer):
    type = ContainerTypeSerializer()

    class Meta:
        model = models.Container
        fields = ['id', 'type', 'number']


class PlatformSerializer(FrozenModelSerializer):
    class Meta:
        model = models.ContainerPlatform
        fields = ['id', 'address', 'lat', 'lon', 'restricts', 'need_photo_before', 'need_photo_after', 'comment']


class LandfillSerializer(FrozenModelSerializer):
    class Meta:
        model = models.Landfill
        fields = ['id', 'address', 'lat', 'lon']


class BasePlanSerializer(FrozenModelSerializer):
    status = serializers.SerializerMethodField()
    actual_time_visit = serializers.SerializerMethodField()

    def get_status(self, plan):
        return plan.report.status if hasattr(plan, 'report') else 'wait'

    def get_actual_time_visit(self, plan):
        return plan.report.time_visit if hasattr(plan, 'report') else None

    class Meta:
        fields = ['id', 'status', 'time_visit', 'actual_time_visit']


class PlanDepotSerializer(BasePlanSerializer):
    depot = DepotSerializer()

    class Meta:
        model = models.PlanDepot
        fields = BasePlanSerializer.Meta.fields + ['type', 'depot']

class PlanPlatformSerializer(BasePlanSerializer):
    platform = PlatformSerializer()
    containers = ContainerSerializer(many=True)

    class Meta:
        model = models.PlanPlatform
        fields = BasePlanSerializer.Meta.fields + ['platform', 'containers']

class PlanLandfillSerializer(BasePlanSerializer):
    landfill = LandfillSerializer()

    class Meta:
        model = models.PlanLandfill
        fields = BasePlanSerializer.Meta.fields + ['landfill']


class TripSerializer(FrozenModelSerializer):
    transport = TransportSerializer()
    plan_depots = PlanDepotSerializer(many=True)
    plan_platforms = PlanPlatformSerializer(many=True)
    plan_landfills = PlanLandfillSerializer(many=True)
    telegram = serializers.SerializerMethodField()

    def get_telegram(self, trip):
        dispatcher = self.get_obj_uniq(trip.driver.dispatchers.all(), 'dispatcher')
        if dispatcher:
            return dispatcher.user.profile.telegram

    class Meta:
        model = models.Trip
        fields = ['id', 'name', 'telegram', 'transport', 'plan_depots', 'plan_platforms', 'plan_landfills']


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################

class PhotoSerializer(FrozenModelSerializer):
    class Meta:
        model = models.Photo
        fields = ['id', 'file']

    def create(self, validated_data):
        photo = super(PhotoSerializer, self).create(validated_data)
        # словарь окружения
        query_dict = self.context['view'].get_parents_query_dict()
        if query_dict:
            # получаем непосредственного родителя
            parent_key = [k for k in query_dict.keys() if '__' not in k][0]
            # создаем связь
            getattr(photo, parent_key).add(query_dict[parent_key])
        return photo
