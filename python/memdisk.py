# -*- coding: utf-8 -*-

import os
import marshal
import struct


class Out(object):

    def __init__(self, fp, cachesize=2 ** 24):
        self.fp = fp
        # смещаемся в конец файла
        self.fp.seek(0, 2)
        self.fp_pos = self.fp.tell()

        self.cachesize = cachesize
        self.pos = 0
        self.data = ''
        self.sizer = struct.Struct('!H')
        self.sizer_size = self.sizer.size

    def seek(self, size):
        # проверка на достаточность потока для чтения
        if self.pos < size:
            # проверка файла
            if self.fp.tell() < self.cachesize:
                self.cachesize = self.fp.tell()
            # смещаемся к началу блока для чтения
            self.fp.seek(-self.cachesize, 1)
            # сохраняем смещение исходного файла
            self.fp_pos = self.fp.tell()
            # дочитываем поток
            buf = self.fp.read(self.cachesize)
            # смещаемся обратно к началу блока
            self.fp.seek(-self.cachesize, 1)
            self.data = buf + self.data[:self.pos]
            self.pos = len(self.data)

        self.pos -= size

    @property
    def eof(self):
        # проверка на конец чтения
        return self.pos == 0 and self.fp_pos == 0

    def readSize(self):
        size = self.sizer_size
        # смещаемся
        self.seek(size)
        # считываем размер
        return self.sizer.unpack_from(buffer(self.data, self.pos, size))[0]

    def readText(self, size, is_unpack=True):
        # смещаемся
        self.seek(size)
        # считываем текст
        if is_unpack:
            return struct.unpack_from('!%ss' % size, buffer(self.data, self.pos, size))[0]


class Memdisk(object):

    def __init__(self, fn, cachesize=100000, cachesize_out=2**24):
        # название файла
        self.fn = fn
        # смещения записей в дисковом файле
        self.seeks = {}
        # хранение локального кэша в памяти
        self.mem_cache = {}
        # размер кэша
        self.cachesize = cachesize
        # размер байтового кэша чтения файла
        self.cachesize_out = cachesize_out
        # открываем файл
        self.fp = open(fn, 'a+b')

    def get(self, key, default=None):
        # ищем указанный key в памяти
        item = self.mem_cache.get(key, None)
        if item:
            return marshal.loads(item)

        # ищем указанный key в словаре смещений
        data = self.seeks.get(key, None)
        if not data:
            return default

        # распаковывеам инфу по файлу
        seek, size = data
        # смещаемся в файле
        self.fp.seek(seek)
        # считываемся из файла
        item = self.fp.read(size)
        # вернем объект
        return marshal.loads(item)

    def __setitem__(self, key, value):
        # пишем в только в память
        self.mem_cache[key] = marshal.dumps(value)
        # если размер памяти превышает доступный - сброс в файл
        if len(self.mem_cache) >= self.cachesize:
            self.flush()

    def __len__(self):
        return len(self.mem_cache) + len(self.seeks)

    def flush(self):
        # смещаемся в конец файла
        self.fp.seek(0, 2)
        # перебираем все данные
        for k, v in self.mem_cache.iteritems():
            # текущее смещение
            seek = self.fp.tell()
            # сохраняем смещение и размер
            self.seeks[k] = (seek, len(v))

            # пишем данные в файл, вместе с метаданными
            self.fp.write(v + struct.pack('!H', len(v)) + k + struct.pack('!H', len(k)))
        # зануляем кэш
        self.mem_cache = {}

    def extract(self):
        # сначала сбрасываем все из кэша
        for v in self.mem_cache.itervalues():
            yield marshal.loads(v)

        # объект управления выводом
        out = Out(self.fp, cachesize=self.cachesize_out)

        while not out.eof:
            # размер ключа
            size = out.readSize()
            # читаем ключ
            key = out.readText(size)
            # читаем длину текста
            size = out.readSize()
            # только если этот ключ еще актуален - считываем сообщение
            if self.seeks.pop(key, None):
                # вернем объект
                yield marshal.loads(out.readText(size))
            else:
                # иначе - просто сместимся
                out.readText(size, is_unpack=False)

    def __del__(self):
        # при закрытии объекта удаляем файл базы
        if self.fp:
            self.fp.close()
            os.unlink(self.fn)




def __example_usage__():

    # перебираем все категории
    for cat_id, query in genCatQueries():
        # получаем итератор продуктов
        for item in es.scan({'query': query, 'sort': [{'available': 'desc'}, '_score']},
                            preserve_order=True, track_scores=True):
            # пробуем получить объект продукта
            prod = memdisk.get(str(item['_id']), None)

            # если удалось - просто добавляем категорию
            if prod:
                # товар не может попадать в разное, если он уже в бд
                if cat_id == 0:
                    self.log.warning(u'Товар попал в "разное", уже находясь в категории. %s', prod)
            else:
                # иначе - создаем новый продукт
                prod = prod_build(item)

            # устанавливаем категорию
            prod['_source']['cat'].append(cat_id)

            # для корневой категории вводим основу для статической сортировки
            if cat_id in [0, root_cat_id]:
                prod['_source'].update({
                    'offer_group_order': meta_offers.getGroupOrder(prod['_source']['offer']),
                })
            # для остальных категорий - динамическая сортировка
            else:
                prod['_source'].update({
                    ('cat_order_%s' % cat_id): meta_offers.getGroupOrder(prod['_source']['offer'], cat_id),
                })

            # получаем id страниц
            pages = list(page_ids(prod['_source'], cat_id))
            if pages:
                prod['_source']['page_%s' % cat_id] = pages

            # запишем продукт в бд
            memdisk[str(item['_id'])] = prod

            self.progress(d_count=100)

    # объект эластика
    es = ElasticSnapshot(reset=True)

    self.nextPhase(u'Сброс данных в эластик', expected=len(memdisk))

    # итератор только значений продуктов
    def iterProd():
        for prod in memdisk.extract():
            self.progress(d_count=100)
            yield prod

    # собственно запись
    es.bulk_send(iterProd())
