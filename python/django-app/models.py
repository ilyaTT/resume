# -*- coding: utf-8 -*-

import re
import json
import datetime
from time import time
from transliterate import slugify
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.core.validators import RegexValidator
from django.core import files
from django.contrib.gis.db.models.functions import GeoHash
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.db.models import Count
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.dispatch import receiver
from django.conf import settings
from jsonfield import JSONField

from rest_framework.authtoken.models import Token
from asuothodi.utils import parseDecimal

from utils import get_file_path
from asuothodi.imports.models import Source
from asuothodi.utils import get_time_now
from asuothodi.managers import (ContainerPlatformManager,
                                ContainerPlatformCorrectManager,
                                ContainerCorrectManager,
                                EmitterManager, EmitterTmpManager)
from asuothodi.frozen_model import FrozenModel, FrozenModelRelated, AuthorModel
import Geohash


class Config(models.Model):
    CONFIG_TYPE_INT = u'int'
    CONFIG_TYPE_FLOAT = u'float'
    CONFIG_TYPE_STR = u'str'
    CONFIG_TYPE_JSON = u'json'

    CONFIG_TYPES = [
        (CONFIG_TYPE_INT, u'Целое'),
        (CONFIG_TYPE_FLOAT, u'Дробное'),
        (CONFIG_TYPE_STR, u'Текст'),
        (CONFIG_TYPE_JSON, u'Json'),
    ]

    name = models.CharField(max_length=100, verbose_name=u'Параметр')
    slug = models.SlugField(verbose_name=u'Ключ параметра')
    val_int = models.IntegerField(null=True, blank=True, verbose_name=u'Целочисленное значение')
    val_float = models.DecimalField(null=True, blank=True, decimal_places=4, max_digits=14, verbose_name=u'Дробное значение')
    val_str = models.TextField(null=True, blank=True, verbose_name=u'Текстовое значение')
    val_json = models.TextField(null=True, blank=True, verbose_name=u'Сериализованное значение')
    type = models.CharField(max_length=20, choices=CONFIG_TYPES, verbose_name=u'Тип', default=CONFIG_TYPE_INT)

    def clean(self):
        if (self.type == self.CONFIG_TYPE_INT and self.val_int is None) \
                or (self.type == self.CONFIG_TYPE_FLOAT and self.val_float is None) \
                or (self.type == self.CONFIG_TYPE_STR and self.val_str is None) \
                or (self.type == self.CONFIG_TYPE_JSON and self.val_json is None):
            raise ValidationError(u'Некорректно заполнено значение конфига')

        if self.type == self.CONFIG_TYPE_JSON:
            try:
                json.loads(self.val_json)
            except Exception:
                raise ValidationError(u'Некорректный json')

    def val(self):
        if self.type == self.CONFIG_TYPE_INT:
            return self.val_int
        if self.type == self.CONFIG_TYPE_FLOAT:
            return self.val_float
        if self.type == self.CONFIG_TYPE_STR:
            return self.val_str
        if self.type == self.CONFIG_TYPE_JSON:
            return self.val_json
    val.short_description = u'Значение'

    @staticmethod
    def get(slug, default=None):
        cfg = Config.objects.filter(slug=slug).first()
        if cfg:
            return json.loads(cfg.val()) if cfg.type == Config.CONFIG_TYPE_JSON else cfg.val()
        return default

    def __unicode__(self):
        return self.name or self.slug

    class Meta:
        verbose_name = u'Настройка'
        verbose_name_plural = u'Настройки'


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class MixinGeo(models.Model):
    """
    Базоый класс для всех сущностей, которые предположительно могут кластеризоваться
    """
    address = models.CharField(u'Адрес', max_length=255, blank=True, null=True)
    district = models.ForeignKey('District', verbose_name=u'Район', blank=True, null=True)
    district_raw = models.CharField(u'Название района', max_length=255, db_index=True, blank=True, null=True)
    lat = models.DecimalField(u'Широта', max_digits=10, decimal_places=7, blank=True, null=True)
    lon = models.DecimalField(u'Долгота', max_digits=10, decimal_places=7, blank=True, null=True)
    point = models.PointField(u'Точка', blank=True, null=True, db_index=True)
    geohash = models.CharField(u'Гео-хэш', max_length=20, blank=True, null=True, db_index=True)
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
        if self.point is None and self.lat is not None and self.lon is not None:
            self.lat = float(self.lat)
            self.lon = float(self.lon)
            self.point = Point(self.lon, self.lat)

        if self.lat is not None and self.lon is not None:
            self.geohash = Geohash.encode(self.lat, self.lon, precision=10)
            for i in range(1, 11):
                # заполняем соответствующие куски геохэша
                setattr(self, 'hash_level_%s' % i, self.geohash[:i])

    def save(self, *args, **kwargs):
        self.geo_recalc()
        super(MixinGeo, self).save(*args, **kwargs)

    @staticmethod
    def clusters(qs, precision):
        # снимаем возможную сортировку
        qs = qs.filter(point__isnull=False).order_by()
        level = 'hash_level_%s' % precision
        qs_clusters = qs.values(level).annotate(count=Count(level))

        result = [dict({'count': c['count']}, **dict(zip(['lat', 'lon'], map(float, Geohash.decode(c[level]))))) for c in qs_clusters]
        return result

    class Meta:
        abstract = True


class BasePatternDict(models.Model):
    slug = models.SlugField(u'Метка', unique=True, max_length=255, null=True, blank=True)
    name = models.CharField(u'Название', max_length=255)
    pattern = models.CharField(u'Паттерн соответствия', max_length=255, null=True, blank=True)
    is_default = models.BooleanField(u'Дефолтное значение', default=False)

    def __unicode__(self):
        return self.name

    class Meta:
        abstract = True


class BaseParentDict(BasePatternDict):
    parent = models.ForeignKey('self', verbose_name=u'Родитель', related_name='children', blank=True, null=True)

    class Meta:
        abstract = True


class UserMode(BasePatternDict):
    class Meta:
        verbose_name = u'режим юзера'
        verbose_name_plural = u'режимы юзеров'

    description = models.TextField(u'Описание режима', null=True, blank=True)
    users = models.ManyToManyField(User, blank=True, verbose_name=u'Юзеры', related_name='modes')

    def __unicode__(self):
        return self.name


class ItemsSet(models.Model):
    """
        Модель состояния запроса рабочей области
    """
    state = models.ForeignKey('WorkspaceState', on_delete=models.CASCADE)
    ids = JSONField(u'Набор id выборкм', blank=True, null=True)
    created = models.DateTimeField(u'Дата создания', auto_now_add=True)


class ExportDaysDict(BaseParentDict):
    """
    Словарь дней недели
    """
    label = models.SlugField(u'Внутренее обозначение', max_length=50)

    class Meta:
        verbose_name = u'День вывоза'
        verbose_name_plural = u'Дни выврза'

    @staticmethod
    def parseDaysExport(data):
        """
        Выполняет разбор строки в системные обозначения дней вывоза.
        Корректный разбор основывается на предположении, что данные были записаны скриптом инициализации
        :param data:
        :return:
        """
        if not data:
            return

        # проверка на чет/нечет
        if u'нечет' in data:
            yield ExportDaysDict.objects.get(label='odd')
            return
        elif u'чет' in data:
            yield ExportDaysDict.objects.get(label='even')
            return

        def date_day_norm(day):
            try:
                return str(int(day))
            except Exception:
                return day

        # список дней
        days = ExportDaysDict.objects.exclude(parent=None)
        # словарь дней
        d_days = {(d.pattern if d.pattern else d.name): d for d in days}

        # дробим строку на составляющие
        export_days = set(re.split('\W+', data, flags=re.I | re.U))
        export_days = {date_day_norm(d) for d in export_days}

        # ищем дни недели
        for day in (export_days & set(d_days.keys())):
            yield d_days[day]


class District(FrozenModel):
    class Meta:
        verbose_name = u'Район'
        verbose_name_plural = u'Районы'
        ordering = ['name']

    name = models.CharField(verbose_name=u'Название', max_length=255)

    def __unicode__(self):
        return self.name


class Locality(FrozenModel):
    class Meta:
        verbose_name = u'Округ'
        verbose_name_plural = u'Округа'
        ordering = ['name']

    name = models.CharField(verbose_name=u'Название', max_length=255)
    district = models.ForeignKey(District, verbose_name=u'Район', max_length=255)

    def __unicode__(self):
        return self.name


class File(FrozenModel):
    class Meta:
        verbose_name = u'Файл'
        verbose_name_plural = u'Файлы'

    title = models.CharField(max_length=255, blank=True, null=True)
    file = models.FileField(upload_to=get_file_path)
    comment = models.TextField(u'Комментарий', blank=True, null=True)

    def __unicode__(self):
        return self.file.name


class ImageFieldFree(models.ImageField):
    default_validators = []

class Photo(FrozenModel):
    class Meta:
        verbose_name = u'Фото'
        verbose_name_plural = u'Фото'

    file = ImageFieldFree(upload_to=get_file_path)

    def __unicode__(self):
        return self.file.name


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class Person(MixinGeo, FrozenModel):
    class Meta(MixinGeo.Meta):
        verbose_name = u'Физ.лицо'
        verbose_name_plural = u'Физ.лица'

    user = models.OneToOneField(User, related_name='person', blank=True, null=True)
    name = models.CharField(u'ФИО', max_length=255, db_index=True)
    position = models.CharField(u'Должность', max_length=255, blank=True, null=True)
    basis = models.CharField(u'Основание действия', max_length=255, blank=True, null=True)
    passport = models.TextField(u'Паспортные данные', blank=True, null=True)
    phone = models.CharField(u'Телефон', max_length=255, blank=True, null=True)
    fax = models.CharField(u'Факс', max_length=255, blank=True, null=True)
    email = models.CharField(u'Email', max_length=255, blank=True, null=True)
    comment = models.TextField(u'Комментарий', blank=True, null=True)
    photo = models.ForeignKey('Photo', verbose_name='Фото', blank=True, null=True)
    zones = models.ManyToManyField('ZonePerson', verbose_name=u'Зоны инспекторов', related_name='persons',
                                   blank=True)
    def __unicode__(self):
        return self.name


class Organization(MixinGeo, FrozenModel):
    """
    В контексте данной модели делается допущение, что объект - это отдельно стоящее гео-строение
    Вполне возможно, что будет еще один объект с аналогичными реквизитами
    """
    class Meta(MixinGeo.Meta):
        verbose_name = u'Организация'
        verbose_name_plural = u'Организации'
        unique_together = [('inn', 'kpp')]

    name = models.CharField(u'Название', max_length=255, db_index=True)
    owned = models.CharField(u'Тип собственности', max_length=255, blank=True, null=True, db_index=True)
    basis = models.CharField(u'Основание действия', max_length=255, blank=True, null=True)
    person = models.ForeignKey(Person, verbose_name=u'Физ. лицо', related_name='organizations', blank=True, null=True)
    address_legal = models.CharField(u'Юр. адрес', max_length=255, blank=True, null=True)
    contacts = JSONField(u'Контакты', blank=True, null=True)
    inn = models.CharField(u'ИНН', max_length=255, blank=True, null=True, db_index=True)
    kpp = models.CharField(u'КПП', max_length=255, blank=True, null=True, db_index=True)
    ogrn = models.CharField(u'ОГРН', max_length=255, blank=True, null=True, db_index=True)
    okpo = models.CharField(u'ОКПО', max_length=255, blank=True, null=True, db_index=True)
    oktmo = models.CharField(u'ОКТМО', max_length=255, blank=True, null=True, db_index=True)
    rs = models.CharField(u'Р/с', max_length=255, blank=True, null=True)
    ks = models.CharField(u'К/с', max_length=255, blank=True, null=True)
    bank = models.CharField(u'Наименование банка', max_length=255, blank=True, null=True)
    bik = models.CharField(u'БИК', max_length=255, blank=True, null=True)
    comment = models.TextField(u'Комментарий', blank=True, null=True)

    def __unicode__(self):
        return self.name


class PlatformRestrict(BasePatternDict):
    class Meta:
        verbose_name = u'ограничение площадки'
        verbose_name_plural = u'ограничения площадки'


class ContainerPlatform(MixinGeo, FrozenModel):
    STATUSES = (
        ('new', u'Новая'),
        ('tocheck', u'Заявка на проверку'),
        ('fact', u'Фактическая'),
        ('checked', u'Проверенная'),
        ('active', u'Действующая'),
        ('changed', u'Изменена'),
        ('closed', u'Закрыта'),
        ('planed', u'Плановая'),
        ('unknown', u'Неизвестная'),
    )

    TYPES = (
        ('opened', u'открытая'),
        ('closed', u'закрытая'),
        ('covered', u'с навесом'),
        ('chute', u'мусоропровод'),
    )

    SURFACES = (
        ('priming', u'грунт'),
        ('asphalt', u'асфальт'),
        ('concrete', u'с бетон'),
        ('firm', u'с твердое'),
        ('other', u'с другое'),
    )

    FENCES = (
        ('missing', u'отсутствует'),
        ('clamp', u'скоба'),
        ('sash', u'со створками'),
        ('grid', u'сетка'),
        ('proflist', u'профлист'),
        ('concrete', u'бетон'),
        ('other', u'другое'),
    )

    class Meta(MixinGeo.Meta):
        verbose_name = u'площадка'
        verbose_name_plural = u'площадки'
        unique_together = [('lat', 'lon')]

    name = models.CharField(verbose_name=u'Название', max_length=255, blank=True, null=True)
    restricts = models.ManyToManyField('PlatformRestrict', blank=True,
                                               verbose_name=u'Ограничения площадки')
    status = models.CharField(verbose_name=u'Статус', max_length=20, choices=STATUSES, default=STATUSES[0][0])
    type = models.CharField(verbose_name=u'Вид площадки', max_length=20, choices=TYPES, blank=True, null=True)
    surface = models.CharField(verbose_name=u'Тип поверхности', max_length=20, choices=SURFACES, blank=True, null=True)
    fence = models.CharField(verbose_name=u'Тип ограждения', max_length=20, choices=FENCES, blank=True, null=True)
    place_kgm = models.BooleanField(verbose_name=u'Наличие места для КГМ', default=False)
    need_photo_before = models.BooleanField(verbose_name=u'Обязательные фото перед выгрузкой', default=False)
    need_photo_after = models.BooleanField(verbose_name=u'Обязательные фото после выгрузки', default=False)
    organization_exploiting = models.ForeignKey(Organization, verbose_name=u'Организация, эксплуатирующая площадку',
                                                blank=True, null=True, related_name='container_platforms_exploiting',
                                                on_delete=models.SET_NULL)
    organization_balance = models.ForeignKey(Organization, verbose_name=u'Организация-балансодержатель площадки',
                                                blank=True, null=True, related_name='container_platforms_balance',
                                                on_delete=models.SET_NULL)
    comment = models.CharField(verbose_name=u'Комментарий', max_length=255, blank=True, null=True)
    photo = models.ForeignKey('Photo', verbose_name='Фото', blank=True, null=True)
    ext_id = models.CharField(u'ID внешней системы', max_length=255, db_index=True, blank=True, null=True)
    carrier = models.ForeignKey('Carrier', verbose_name='Перевозчик', blank=True, null=True)

    def __unicode__(self):
        return u'Контейнерная площадка №%s (%s, %s)' % (self.pk, self.lat, self.lon)


class ContainerType(FrozenModel):
    class Meta:
        verbose_name = u'тип контейнера'
        verbose_name_plural = u'типы контейнеров'
        ordering = ['name']

    name = models.CharField(u'Название', max_length=255)
    slug = models.SlugField(u'Метка', unique=True, null=True, blank=True)
    material = models.CharField(verbose_name=u'Материал контейнера', max_length=255, blank=True, null=True)
    capacity = models.FloatField(verbose_name=u'Вместимость контейнера', blank=True, null=True)
    is_portable = models.BooleanField(u'Съемный контейнер', default=False)
    work_time = models.IntegerField(u'Время работы с контейнером', default=300)

    def __unicode__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, 'ru')
        super(ContainerType, self).save(*args, **kwargs)


class RfidValidator(RegexValidator):
    regex = r'^[0-9a-f]{24}$'
    message = u'RFID не соответствует требуемому формату'


class Container(FrozenModel):
    STATUSES = (
        ('clarify', u'Требует уточнения'),
        ('missing', u'Отсутствует'),
        ('success', u'Функционирует'),
    )

    type = models.ForeignKey(ContainerType, verbose_name=u'Тип контейнера', blank=True, null=True,
                             related_name='containers', on_delete=models.SET_NULL)
    platform = models.ForeignKey(ContainerPlatform, verbose_name=u'Контейнерная площадка', related_name='containers',
                                 blank=True, null=True)
    status = models.CharField(u'Статус', max_length=20, choices=STATUSES, default=STATUSES[0][0])
    number = models.CharField(u'Номер контейнера', max_length=255, blank=True, null=True)
    capacity = models.FloatField(u'Вместимость контейнера', blank=True, null=True)
    is_missing = models.BooleanField(u'Отсутствует', default=False)
    is_infact = models.BooleanField(u'Объем по факту', default=False)
    bid_only = models.BooleanField(u'Вывоз только по заявкам', default=False)
    rfid = models.CharField(u'RF-метка', max_length=255, blank=True, null=True, unique=True, validators=[RfidValidator()])
    organization_balance = models.ForeignKey(Organization, verbose_name=u'Организация-балансодержатель контейнера',
         blank=True, null=True, related_name='container_balance', on_delete=models.SET_NULL)

    export_days = models.ManyToManyField(ExportDaysDict, verbose_name=u'Дни вывоза', blank=True, related_name='containers')
    export_disable = models.BooleanField(u'Вывоз запрещен', default=False)

    class Meta:
        verbose_name = u'контейнер'
        verbose_name_plural = u'контейнеры'
        ordering = ['number']

    def __unicode__(self):
        return u'[%s] Контейнерная площадка №%s. Контейнер №%s' % (self.id, self.platform.pk, self.number)

    def get_fill(self):
        return (float(self.capacity) / 10.00) * 100


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################


class PlanPlatform(FrozenModel):
    class Meta:
        verbose_name = u'запланированное посещение контейнерной площадки'
        verbose_name_plural = u'запланированные посещения контейнерной площадки'
        ordering = ['time_visit']

    platform = models.ForeignKey(ContainerPlatform, related_name='plans', verbose_name=u'Контейнерная площадка')
    containers = models.ManyToManyField('Container', related_name='plans',  verbose_name=u'Плановые контейнеры', blank=True)
    trip = models.ForeignKey(Trip, related_name='plan_platforms', verbose_name=u'Рейс')
    time_visit = models.DateTimeField(verbose_name=u'Время посещения')

    def __unicode__(self):
        return u'%s будет посещена в %s согласно плану %s' % (self.platform, self.time_visit, self.trip)


##################################
## Часть кода пропущена в целях соблюдения конфидентиальности
##################################