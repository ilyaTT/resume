# -*- coding: utf-8 -*-

"""
    Вспомогательный модуль/прослойка для абстрагирования изображений
"""

from __future__ import absolute_import
import os
import urlparse
import logging
from redis import StrictRedis
from collections import OrderedDict
from hashlib import md5
from django.conf import settings
from catalog.utils import getConfigDict, urlValid
from catalog.amqp import Ampq


LOG = logging.getLogger(__name__)


class ImgsList(object):

    def __init__(self):
        # получаем настройки в виде словаря
        self.cfg = getConfigDict()
        # подключаемся к редису
        self.redis = StrictRedis.from_url(settings.REDIS_IMGS)
        # ключ ресайза для списко-превью
        self.list_key = self.cfg['img_sizes']['list']

    def getStatuses(self, hashes):
        """
        Получение статусов
        Возможные статусы:
        0 - не обработано
        100 - в процессе обработки
        200 - успешно обработано, картинка сохранена
        404 - картинка отсутствует
        500 - ошибка обработки. ожидается повторная обработка
        """
        # собираем ключи
        keys = []
        # в любом случае должен участвовать orign - на его основании делается вывод о 404 статусе
        for key in ['orign', self.list_key]:
            for h in hashes:
                keys.append('%s:%s' % (h, key))

        # запрашиваем статусы
        statuses = [int(s or 0) for s in self.redis.mget(keys)]
        # получаем статусы
        statuses_orign, statuses_resize = statuses[:len(hashes)], statuses[len(hashes):]
        # нормализуем 404 ошибку
        for i, s_o in enumerate(statuses_orign):
            if s_o == 404:
                statuses_resize[i] = 404

        return statuses_orign, statuses_resize

    def checkHashes(self, hashes):
        """
        Опрос хешей на статус
        :param hashes:
        :return:
        """
        # возвращаем словарь статусов
        return {hashes[i]: s for i, s in enumerate(self.getStatuses(hashes)[1])}

    def resolve(self, items):
        # определение приоритета - в теле функции все цифры связаны!
        def calc_priority(i, j):
            # в режиме паука - все равны
            if settings.SPIDER_MODE:
                return 1

            # вычисляем строку
            row = (i / self.cfg['items_in_row']) + 1
            # исходный приоритет
            priority = Ampq.PRIORITY_NUMS
            # загрузка соседнего изображения сильно меньше по приоритету
            priority -= (priority * j / 2)

            # ручное распределение приоритетов
            if 1 <= row <= 2:
                priority -= 0
            elif 3 <= row <= 5:
                priority -= 1
            elif 6 <= row <= 10:
                priority -= 2
            else:
                priority -= 3

            # номер приоритета должен быть больше 0
            return priority if priority > 0 else 1

        # перебираем все товары
        d_imgs = OrderedDict()
        for i, item in enumerate(items):
            # print 'imgs:', item.imgs
            #
            # if item.meta.id == 'lamoda_0801635':
            #     print 'lamoda_0801635 imgs:', item.imgs

            # перебираем imgs товара
            for j, img in enumerate([img for img in item['_source']['imgs'] if urlValid(img)][:2]):
                # определяем хэш - 9-байтовый
                h = md5(img).hexdigest()[:18]
                # определяем расширение img
                ext = os.path.splitext(urlparse.urlparse(img).path)[1]
                # находим папку
                folder = os.path.join(settings.MEDIA_ROOT, 'imgs', h[:2], h[2:4], h[4:6], h[6:8])

                # если для этого хэша еще не создан объект запроса - создаем
                if h not in d_imgs:
                    # добавляем в словарь
                    d_imgs[h] = {
                        'url': img,
                        'priority': calc_priority(i, j),
                        'items': [item],
                        'folder': folder,
                        'path': os.path.join(folder, '%s%s' % (h, ext))
                    }
                # если уже создан - добавляем в список текущий элемент
                else:
                    d_imgs[h]['items'].append(item)

            # сбрасываем imgs
            item['imgs'] = []

        # собираем хэши всех imgs
        hashes = d_imgs.keys()

        # если хэши не переданы - выходим
        if not hashes:
            return

        # выясняем - какой статус у всех хэшей
        statuses_orign, statuses_list = self.getStatuses(hashes)

        # если не все целевые статусы завершенные или обрабатываемые - выполняем вброс в очередь
        if not all([s in (100, 200, 404) for s in statuses_list]):
            # подключаемся
            rmq = Ampq()

            # перебираем статусы превью
            for i, s in enumerate(statuses_list):
                if s not in (100, 200, 404):
                    # хэш по статусу
                    h = hashes[i]
                    # словарь данных
                    d_img = d_imgs[h]

                    # базовое название очереди
                    queue = 'img_resize' if statuses_orign[i] == 200 else 'img_load'
                    # полное название очереди
                    queue_full = '%s_%s' % (('coping' if settings.SPIDER_MODE else 'snapshot'), queue)

                    # полное название след. очереди
                    if queue == 'img_load':
                        queue_next_full = ('%s_%s' % (('coping' if settings.SPIDER_MODE else 'snapshot'), 'img_resize'))
                    else:
                        queue_next_full = None

                    # отправляем сообщение либо в очередь ресайзинга(если оригинал есть), либо на скачивание
                    rmq.pub(queue_full, {
                        'hash': h,
                        'url': d_img['url'],
                        'folder': d_img['folder'],
                        'path': d_img['path'],
                        'priority': d_img['priority'],
                        'resize': self.list_key,
                        'field': '%s:%s' % (h, 'orign' if queue == 'img_load' else self.list_key),
                        'next_queue': queue_next_full,
                        'attempts': 0
                    }, priority=d_img['priority'])

        # навешиваем на товары информацию о состоянии img
        for i, s in enumerate(statuses_list):
            # хэш по статусу
            h = hashes[i]
            # словарь данных
            d_img = d_imgs[h]
            # путь к файлу фото
            img_path = d_img['path'].replace(h, '%s.%s' % (h, self.list_key))

            # добавляем ко всем элементам инфу о фото
            for item in d_img['items']:
                item['imgs'].append({
                    # добавляем url превью
                    'url': os.path.join(settings.MEDIA_URL, os.path.relpath(img_path, settings.MEDIA_ROOT)),
                    'status': s,
                    'hash': h
                })
