import importlib
import inspect
import json

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as AuthUserAdmin
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.core.exceptions import FieldDoesNotExist
from django.utils.translation import ugettext_lazy as _
from django_better_admin_arrayfield.admin.mixins import DynamicArrayMixin
from jsoneditor.forms import JSONEditor
from simple_history.admin import SimpleHistoryAdmin
from . import models
from atom.sets_order import OrderedSet
from .models import StatusedModel, Status


class AuthorAdminMixin:
    def get_readonly_fields(self, request, obj=None):
        return tuple(OrderedSet(super().get_readonly_fields(request, obj) + (
            'dt_create', 'dt_update', 'author', 'author_updated'
        )))


class DictModelAdminMixin(AuthorAdminMixin):
    def get_list_display(self, request):
        return tuple(OrderedSet(('id',) + super().get_list_display(request)))

    def get_search_fields(self, request):
        return tuple(OrderedSet(super().get_search_fields(request) + ('name',)))


class ProtectedModelAdminMixin(AuthorAdminMixin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(OrderedSet(super().get_readonly_fields(request, obj) + (
            'orgs_access_view', 'orgs_access_change', 'orgs_access_delete',
        )))

    def get_list_display(self, request):
        return tuple(OrderedSet(('id',) + super().get_list_display(request) + ('org_owner',)))

    def get_list_filter(self, request):
        return tuple(OrderedSet(super().get_list_filter(request) + ('org_owner',)))

    def get_autocomplete_fields(self, request):
        return tuple(OrderedSet(super().get_autocomplete_fields(request) + ('org_owner',)))


class GeoAdminMixin:
    def get_readonly_fields(self, request, obj=None):
        return tuple(OrderedSet(super().get_readonly_fields(request, obj) + (
            'hash_level_1', 'hash_level_2', 'hash_level_3', 'hash_level_4', 'hash_level_5',
            'hash_level_6', 'hash_level_7', 'hash_level_8', 'hash_level_9', 'hash_level_10',
        )))



class M2mThroughMixin:
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        db_field.remote_field.through._meta.auto_created = True
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class StatusedModelAdminMixin(ProtectedModelAdminMixin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(OrderedSet(super().get_readonly_fields(request, obj) + ('status_label', 'status_dt', 'status_history', 'status_author')))

    def get_list_display(self, request):
        return tuple(OrderedSet(super().get_list_display(request) + ('status_label',)))

    def get_search_fields(self, request):
        return tuple(OrderedSet(super().get_search_fields(request) + ('status_label',)))


class AuthorAdmin(AuthorAdminMixin, SimpleHistoryAdmin):
    def save_model(self, request, obj, form, change):
        if not obj.author:
            obj.author = request.user
        else:
            obj.author_updated = request.user
        return super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if not obj.author:
                obj.author = request.user
            else:
                obj.author_updated = request.user
            obj.save()
        formset.save_m2m()


class DictModelAdmin(DictModelAdminMixin, AuthorAdmin):
    pass


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################