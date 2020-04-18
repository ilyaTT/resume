
import os

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from geohash2 import geohash
import geojson
from hashlib import md5
from uuid import uuid4
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField, JSONField
from django.utils.functional import cached_property, lazy
from django.utils.text import slugify
from django.utils.timezone import now
from django.dispatch import receiver
from django.db.models.signals import m2m_changed
from simple_history.models import HistoricalRecords
from main.utils import JsonFieldEncoder, inheritors
from main.fields import ChoiceArrayField
from main.clone_mixin import CloneMixin
from main.signature import Signature, SignatureCheckException
from .permissions import User, Permission


class IPAddressHistoricalModel(models.Model):
    """
    Abstract model for history models tracking the IP address.
    """
    ip_address = models.GenericIPAddressField(default=None, blank=True, null=True)
    is_http = models.NullBooleanField(default=False, blank=True, null=True)

    class Meta:
        abstract = True


class ProtectedModel(CloneMixin, models.Model):
    dt_create = models.DateTimeField('Время добавления', auto_now_add=True)
    dt_update = models.DateTimeField('Время обновления', auto_now=True)
    author = models.ForeignKey(User, related_name='author_%(class)s', blank=True, null=True, on_delete=models.SET_NULL)
    author_updated = models.ForeignKey(User, related_name='author_updated_%(class)s', blank=True, null=True, on_delete=models.SET_NULL)
    org_owner = models.ForeignKey('main.Organization', verbose_name='Организация-владелец', blank=True, null=True, db_index=True, on_delete=models.SET_NULL)
    orgs_access_view = ArrayField(models.BigIntegerField('Допустимые орагнизации на чтение'), blank=True, null=True)
    orgs_access_change = ArrayField(models.BigIntegerField('Допустимые орагнизации на изменение'), blank=True, null=True)
    orgs_access_delete = ArrayField(models.BigIntegerField('Допустимые орагнизации на удаление'), blank=True, null=True)
    history = HistoricalRecords(verbose_name='История Изменений', inherit=True, bases=[IPAddressHistoricalModel, ])

    def __str__(self):
        return '%s: %s' % (self.__class__.__name__, self.pk)

    def save(self, *args, **kwargs):
        # владелец объекта - организация юзера
        if self.author and not self.org_owner:
            self.org_owner = self.author.organization
        super().save(*args, **kwargs)

    class Meta:
        abstract = True


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class Transit(models.Model):
    label = models.CharField(max_length=50, unique=True)
    icon = models.CharField(max_length=50)
    color = models.CharField(max_length=50)
    status_src = models.ForeignKey(Status, on_delete=models.SET_NULL, related_name='get_status_src', null=True)
    status_dst = models.ForeignKey(Status, on_delete=models.SET_NULL, related_name='get_status_dst', null=True)
    name = models.CharField(max_length=100)
    confirm_text = models.CharField('Текст подтверждения при переходе', max_length=100, null=True, blank=True)
    is_need_sign = models.BooleanField('Переход требует наличия подписи у объекта', default=False)
    is_object_duplicate = models.BooleanField('Переход создает дубликат объекта', default=False)

    class Meta:
        verbose_name = 'Переход'
        verbose_name_plural = 'Переходы'

    def __str__(self):
        return self.name


class TransitForModel(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, unique=True)
    transits = models.ManyToManyField(Transit, related_name='transits_model')

    class Meta:
        verbose_name = 'Переход для модели'
        verbose_name_plural = 'Переходы для модели'

    def __str__(self):
        return '{} / {}'.format(self.content_type.app_label, self.content_type.model)


class StatusedModel(ProtectedModel):
    status_label = models.CharField('Текущий статус', max_length=50, default='draft')
    status_dt = models.DateTimeField('Время статуса', auto_now_add=True)
    status_history = JSONField('История статусов', encoder=JsonFieldEncoder, blank=True, null=True)
    status_author = models.ForeignKey(User, related_name='status_author_%(class)s', blank=True, null=True,
                                      on_delete=models.SET_NULL)
    signature_sign = models.TextField('Подпись', blank=True, null=True)
    signature_dt = models.DateTimeField('Время подписания', blank=True, null=True)
    signature_author = models.ForeignKey(User, related_name='signature_author_%(class)s', blank=True, null=True,
                                         on_delete=models.SET_NULL)
    signature_json_file = models.FileField('Подписанный json', upload_to=get_signature_json_path, blank=True, null=True)
    signature_invalid = models.BooleanField('Подпись не валлидна', default=False)
    note = models.TextField('Комментарий', blank=True, null=True)
    original = models.OneToOneField('self', related_name='inheritor', blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        abstract = True

    @cached_property
    def transits(self):
        return list(Transit.objects.filter(
            transits_model__content_type__app_label=self._meta.app_label,
            transits_model__content_type__model=self._meta.model_name
        ).select_related('status_src', 'status_dst').distinct('id'))

    def transit_apply(self, transit_label, user, payload=None):
        # проверяем допустимость действия для модели
        try:
            transit = [t for t in self.transits if t.label == transit_label][0]
        except IndexError:
            raise StatusedException('Для этого типа заданное действие запрещено')

        # проверяем допустимость перехода статуса
        if transit.status_src.label != self.status_label:
            raise StatusedException('Переход на целевой статус из текущего не разрешен')

        # проверяем разрешение для юзера на переход
        permissions = Permission.get_permissions(user, 'trans.%s.%s' % (self._meta.model_name, transit.label))
        if not permissions:
            raise StatusedException('Отсутствует разрешение на изменение статуса')

        with transaction.atomic():
            # если переход предполагает наличие подписи
            if transit.is_need_sign:
                # пробуем получить подпись
                signature = payload.get('signature', None)
                if not signature:
                    raise StatusedException('Переход требует наличия подписи')

                # проверяем и устанавливаем подпись в текущий объект
                try:
                    sign = Signature(self, signature, user)
                    if not sign.check_signature():
                        raise StatusedException('Подпись не совпадает')
                    sign.set()
                except SignatureCheckException as e:
                    raise StatusedException(e.args[0])

            # если переход возможен только с копированием - делаем копию
            if transit.is_object_duplicate:
                if getattr(self, 'inheritor', None):
                    raise StatusedException('У объекта уже есть наследник')

                obj = self.make_clone()
                obj.original = self
                obj.save()
            else:
                obj = self

            # пишем текущий статус в историю
            obj.status_history = obj.status_history or []
            obj.status_history.insert(0, {
                'label': obj.status_label,
                'dt': obj.status_dt,
                'author': obj.status_author and self.status_author.get_full_name(),
                'comment': payload.get('comment', None),
            })
            # выполняем перевод статуса
            obj.status_label = transit.status_dst.label
            obj.status_dt = now()
            obj.status_author = user
            obj.save()

            return obj

##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class DictModel(models.Model):
    name = models.CharField('Название', max_length=255)
    dt_create = models.DateTimeField('Время добавления', auto_now_add=True)
    dt_update = models.DateTimeField('Время обновления', auto_now=True)
    author = models.ForeignKey(User, related_name='author_%(class)s', blank=True, null=True, on_delete=models.SET_NULL)
    author_updated = models.ForeignKey(User, related_name='author_updated_%(class)s', blank=True, null=True, on_delete=models.SET_NULL)
    history = HistoricalRecords(verbose_name='История Изменений', inherit=True, bases=[IPAddressHistoricalModel,])

    def __str__(self):
        if self.name:
            return self.name
        return '%s: %s' % (self.__class__.__name__, self.pk)

    class Meta:
        abstract = True


class MixinGeo(models.Model):
    """
    Базовый класс для всех сущностей, которые предположительно могут кластеризоваться
    """
    address = models.CharField('Адрес', max_length=255)
    oktmo = models.CharField('ОКТМО', max_length=255, blank=True, null=True, db_index=True)
    fias = models.CharField('ФИАС', max_length=255, blank=True, null=True, db_index=True)
    lat = models.DecimalField('Широта', max_digits=10, decimal_places=5, null=True, db_index=True)
    lon = models.DecimalField('Долгота', max_digits=10, decimal_places=5, null=True, db_index=True)
    point = models.PointField('Точка', blank=True, null=True, db_index=True)
    geohash = models.CharField('Гео-хэш', max_length=20, blank=True, null=True, db_index=True)
    hash_level_1 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_2 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_3 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_4 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_5 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_6 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_7 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_8 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_9 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    hash_level_10 = models.CharField(max_length=20, blank=True, null=True, db_index=True)

    def geo_recalc(self):
        # расчет точки
        if self.point and self.lat is None and self.lon is None:
            self.lon, self.lat = self.point.tuple
        if self.lat is not None and self.lon is not None:
            self.point = Point(float(self.lon), float(self.lat))
            self.geohash = geohash.encode(self.lat, self.lon, precision=10)
            for i in range(1, 11):
                # заполняем соответствующие куски геохэша
                setattr(self, 'hash_level_%s' % i, self.geohash[:i])

    def save(self, *args, **kwargs):
        self.geo_recalc()
        super().save(*args, **kwargs)

    @cached_property
    def geojson(self):
        return geojson.dumps(Point(self.lon, self.lat))

    class Meta:
        abstract = True

    def __str__(self):
        return self.address


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class Okfs(DictModel):
    class Meta:
        verbose_name = 'ОКФС'
        verbose_name_plural = 'ОКФС'

    class JSONAPIMeta:
        resource_name = 'okfs'

    code = models.CharField('Код ОКФС', max_length=255)


class License(ProtectedModel):
    STATUSES = [
        ('actived', 'Действующий'),
        ('suspended', 'Приостановлен'),
        ('cancelled', 'Аннулирован'),
        ('reissued', 'Переоформлен'),
        ('notactived', 'Недействующий'),
    ]

    class Meta:
        verbose_name = 'Лицензия'
        verbose_name_plural = 'Лицензии'

    class JSONAPIMeta:
        resource_name = 'license'

    number = models.CharField('Номер и дата лицензии', max_length=255)
    issuer = models.CharField('Орган, выдавший', max_length=255, blank=True, null=True)
    status = models.CharField('Статус', max_length=255, choices=STATUSES, default=STATUSES[0][0])
    inn = models.BigIntegerField(u'ИНН', blank=True, null=True, db_index=True)

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        children_need_resave = False
        # по ИНН пробуем присоединить организацию
        if self.inn and not self.org_owner:
            org = Organization.objects.filter(inn=self.inn).first()
            if org:
                self.org_owner = org
                children_need_resave = True
        super().save(*args, **kwargs)

        # выполняем обход вложенных объектов
        if children_need_resave:
            for it in self.addresses.all():
                it.save()
            for it in self.wastes.all():
                it.save()

##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################
