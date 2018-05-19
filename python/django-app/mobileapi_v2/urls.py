# -*- coding: utf-8 -*-

from django.conf.urls import url
from rest_framework.routers import DefaultRouter
from rest_framework_extensions.routers import NestedRouterMixin
from asuothodi.mobileapi_v2 import views
from asuothodi.webapi_v2 import views as views_webapi
from asuothodi.mobileapi.auth import ObtainAuthTokenForDriver


class NestedDefaultRouter(NestedRouterMixin, DefaultRouter):
    pass


urlpatterns = [
    url(r'^token-auth/', ObtainAuthTokenForDriver.as_view()),
    url(r'^platform-cluster/', views.PlatformClustersView.as_view()),
    url(r'^dict/transport-type/', views_webapi.DictTransportTypeView.as_view()),
    url(r'^dict/platform-restrict/', views_webapi.DictPlatformRestrictView.as_view()),
    url(r'^dict/container-type/', views_webapi.DictContainerTypeView.as_view()),
]

router = DefaultRouter()
nested_router = NestedDefaultRouter()

trip_router = nested_router.register(r'trip', views.TripViewSet, base_name='trip')


platform_report_router = trip_router.register(
    r'report-platform',
    views.ReportPlatformViewSet,
    base_name='report-platform',
    parents_query_lookups=['trip']
)
platform_report_router.register(
    r'photo-before',
    views.PhotoViewSet,
    base_name='report-platform-photo-before',
    parents_query_lookups=['reportplatform_before__trip', 'reportplatform_before']
)
platform_report_router.register(
    r'photo-after',
    views.PhotoViewSet,
    base_name='report-platform-photo-after',
    parents_query_lookups=['reportplatform_after__trip', 'reportplatform_after']
)


container_report_router = platform_report_router.register(
    r'report-container',
    views.ReportContainerViewSet,
    base_name='report-container',
    parents_query_lookups=['report_platform__trip', 'report_platform']
)
container_report_router.register(
    r'photo-before',
    views.PhotoViewSet,
    base_name='report-container-photo-before',
    parents_query_lookups=['reportcontainer_before__report_platform__trip', 'reportcontainer_before__report_platform',
                           'reportcontainer_before']
)
container_report_router.register(
    r'photo-after',
    views.PhotoViewSet,
    base_name='report-container-photo-after',
    parents_query_lookups=['reportcontainer_after__report_platform__trip', 'reportcontainer_after__report_platform',
                           'reportcontainer_after']
)

landfill_report_router = trip_router.register(
    r'report-landfill',
    views.ReportLandfillViewSet,
    base_name='report-landfill',
    parents_query_lookups=['trip']
)
landfill_report_router.register(
    r'photo-before',
    views.PhotoViewSet,
    base_name='report-landfill-photo-before',
    parents_query_lookups=['reportlandfill_before__trip', 'reportlandfill_before']
)
landfill_report_router.register(
    r'photo-after',
    views.PhotoViewSet,
    base_name='report-landfill-photo-after',
    parents_query_lookups=['reportlandfill_after__trip', 'reportlandfill_after']
)


depot_report_router = trip_router.register(
    r'report-depot',
    views.ReportDepotViewSet,
    base_name='report-depot',
    parents_query_lookups=['trip']
)
depot_report_router.register(
    r'photo-before',
    views.PhotoViewSet,
    base_name='report-depot-photo-before',
    parents_query_lookups=['reportdepot_before__trip', 'reportdepot_before']
)
depot_report_router.register(
    r'photo-after',
    views.PhotoViewSet,
    base_name='report-depot-photo-after',
    parents_query_lookups=['reportdepot_after__trip', 'reportdepot_after']
)


platform_router = nested_router.register(r'platform', views.PlatformViewSet, base_name='platform')
platform_router.register(
    r'container',
    views.ContainerViewSet,
    base_name='platform-container',
    parents_query_lookups=['platform']
)

urlpatterns += router.urls + nested_router.urls