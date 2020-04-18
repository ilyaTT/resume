
import six
from django.utils.text import slugify
from django.db import transaction, models
from django.db.models import SlugField
from django.core.exceptions import ValidationError
from model_clone.utils import (
    clean_value, get_unique_value,
)
from model_clone.mixins.clone import CloneMixin as CloneMixinLib, CloneMetaClass


class CloneMixin(CloneMixinLib):

    class Meta:
        abstract = True

    def _build_values(self):
        defaults = {}
        fields = []

        for f in self._meta.concrete_fields:
            valid = False
            if not f.primary_key:
                if self._clone_model_fields:
                    valid = f.name in self._clone_model_fields
                elif self._clone_excluded_model_fields:
                    valid = f.name not in self._clone_excluded_model_fields
                else:
                    valid = True

            if valid:
                fields.append(f)

        unique_field_names = self.unpack_unique_together(
            opts=self._meta,
            only_fields=[f.attname for f in fields],
        )

        unique_fields = [
            f.name for f in fields
            if not f.auto_created and (f.unique or f.name in unique_field_names)
        ]

        for f in fields:
            if all([
                not f.auto_created,
                f.concrete,
                f.editable,
                f not in self._meta.related_objects,
                f not in self._meta.many_to_many,
            ]):
                value = getattr(self, f.attname, f.get_default())
                if f.attname in unique_fields and isinstance(f, models.CharField):
                    value = clean_value(value, self.UNIQUE_DUPLICATE_SUFFIX)
                    if self.USE_UNIQUE_DUPLICATE_SUFFIX:
                        value = get_unique_value(
                            self,
                            f.attname,
                            value,
                            self.UNIQUE_DUPLICATE_SUFFIX,
                            f.max_length,
                            self.MAX_UNIQUE_DUPLICATE_QUERY_ATTEMPTS
                        )
                    if isinstance(f, SlugField):
                        value = slugify(value)
                defaults[f.attname] = value
        return defaults

    @transaction.atomic
    def _related_copy_to(self, dest, sub_clone=False, clear=False):
        one_to_one_fields = []
        many_to_one_or_one_to_many_fields = []
        many_to_many_fields = []

        for f in self._meta.related_objects:
            if f.one_to_one and f.name in self._clone_one_to_one_fields:
                one_to_one_fields.append(f)

            elif all([
                not self._clone_one_to_one_fields,
                f.one_to_one,
                f not in one_to_one_fields,
                f.name not in self._clone_excluded_one_to_one_fields,
            ]):
                one_to_one_fields.append(f)

            elif all([
                any([f.many_to_one, f.one_to_many]),
                f.name in self._clone_many_to_one_or_one_to_many_fields,
            ]):
                many_to_one_or_one_to_many_fields.append(f)

            elif all([
                not self._clone_many_to_one_or_one_to_many_fields,
                any([f.many_to_one, f.one_to_many]),
                f not in many_to_one_or_one_to_many_fields,
                f.name not in self._clone_excluded_many_to_one_or_one_to_many_fields,
            ]):
                many_to_one_or_one_to_many_fields.append(f)

        for f in self._meta.many_to_many:
            if not sub_clone:
                if f.name in self._clone_many_to_many_fields:
                    many_to_many_fields.append(f)
                elif all([
                    not self._clone_many_to_many_fields,
                    f.name not in self._clone_excluded_many_to_many_fields,
                    f not in many_to_many_fields,
                ]):
                    many_to_many_fields.append(f)

        # Clone one to one fields
        for field in one_to_one_fields:
            rel_object = getattr(self, field.related_name, None)
            if rel_object:
                if hasattr(rel_object, 'make_clone'):
                    rel_object.make_clone(
                        attrs={field.remote_field.name: dest}, sub_clone=True)
                else:
                    rel_object.pk = None
                    setattr(rel_object, field.remote_field.name, dest)
                    rel_object.save()

        # Clone one to many/many to one fields
        for field in many_to_one_or_one_to_many_fields:
            # если указана очистка - выполняем ее
            if clear:
                getattr(dest, field.related_name).all().delete()

            for rel_object in getattr(self, field.related_name).all():
                if hasattr(rel_object, 'make_clone'):
                    rel_object.make_clone(
                        attrs={field.remote_field.name: dest}, sub_clone=True)
                else:
                    rel_object.pk = None
                    setattr(rel_object, field.remote_field.name, dest)
                    rel_object.save()

        # Clone many to many fields
        for field in many_to_many_fields:
            if all([
                field.remote_field.through,
                not field.remote_field.through._meta.auto_created,
            ]):
                # если указана очистка - выполняем ее
                if clear:
                    getattr(dest, field.related_name).clear()

                objs = field.remote_field.through.objects.filter(
                    **{field.m2m_field_name(): self.pk})
                for item in objs:
                    if hasattr(field.remote_field.through, 'make_clone'):
                        item.make_clone(
                            attrs={field.m2m_field_name(): dest}, sub_clone=True)
                    else:
                        item.pk = None
                        setattr(item, field.m2m_field_name(), dest)
                        item.save()
            else:
                source = getattr(self, field.attname)
                destination = getattr(dest, field.attname)
                destination.set(source.all())


    @transaction.atomic
    def make_clone(self, attrs=None, sub_clone=False):
        """
        Creates a clone of the django model instance.

        :param attrs (dict): Dictionary of attributes to be replaced on the cloned object.
        :param sub_clone (bool): Internal boolean used to detect cloning sub objects.
        :rtype: :obj:`django.db.models.Model`
        :return: The model instance that has been cloned.
        """
        attrs = attrs or {}
        if not self.pk:
            raise ValidationError(
                '{}: Instance must be saved before it can be cloned.'
                .format(self.__class__.__name__)
            )
        if sub_clone:
            duplicate = self
            duplicate.pk = None
        else:
            duplicate = self.__class__(**self._build_values())

        # Supports only updating the attributes of the base instance.
        for name, value in attrs.items():
            setattr(duplicate, name, value)

        duplicate.save()

        # копирование всех связнных элементов
        self._related_copy_to(duplicate, sub_clone)

        return duplicate

    @transaction.atomic
    def copy_to(self, dest, attrs=None):
        """
        Creates a clone of the django model instance.

        :param attrs (dict): Dictionary of attributes to be replaced on the cloned object.
        :param sub_clone (bool): Internal boolean used to detect cloning sub objects.
        :rtype: :obj:`django.db.models.Model`
        :return: The model instance that has been cloned.
        """
        attrs = attrs or {}
        if not self.pk:
            raise ValidationError('{}: Instance must be saved before it can be cloned.'.format(self.__class__.__name__))

        # собираем данные для установки в целевой объект
        values = self._build_values()
        values.update(attrs)

        # Supports only updating the attributes of the base instance.
        for name, value in values.items():
            setattr(dest, name, value)

        dest.save()

        # копирование всех связнных элементов
        self._related_copy_to(dest, clear=True)
