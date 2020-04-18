# -*- coding: utf-8 -*-

import os
import marshal
import struct
import zlib


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

    def restore(self):
        self.fp.seek(self.fp_pos, 0)

    def seek(self, size):
        # TODO: важная особенность: cachesize должен быть всегда больше, чем любой size, иначе будет отрицательное смещение в выборке
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

    def __init__(self, fn, cachesize=50000, cachesize_out=2**24):
        # название файла
        self.fn = fn
        # смещения записей в дисковом файле
        self.seeks = {}
        # хранение локального кэша в памяти
        self.mem_cache = {}
        # хранение "легких" вариантов объектов
        self.lights = {}
        # размер кэша
        self.cachesize = cachesize
        # размер байтового кэша чтения файла
        self.cachesize_out = cachesize_out
        # открываем файл
        self.fp = open(fn, 'a+b')

    def __contains__(self, key):
        key = str(key)
        return (key in self.mem_cache) or (key in self.seeks)

    def get(self, key, default=None):
        key = str(key)
        # ищем указанный key в памяти
        item = self.mem_cache.get(key, None)
        if item:
            return item

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

    def get_light(self, key, default=None):
        # ищем сохраненную в памяти часть объекта
        item = self.lights.get(str(key), None)
        if item:
            return marshal.loads(zlib.decompress(item))
        else:
            return self.get(key, default)

    def set_light(self, key, item_light):
        self.lights[str(key)] = zlib.compress(marshal.dumps(item_light))

    def __setitem__(self, key, value):
        key = str(key)
        # пишем в только в память
        self.mem_cache[key] = value
        # из смещений выбрасываем это значение
        self.seeks.pop(key, None)
        # если размер памяти превышает доступный - сброс в файл
        if len(self.mem_cache) >= self.cachesize:
            self.flush()

    def set(self, key, item, keys_light=None):
        # стандартно сохраняем объект
        self[key] = item
        # если заданы ключи для "легкого" объекта - создаем по ним "легкий" объект
        if keys_light:
            self.set_light(key, {k: item[k] for k in keys_light if k in item})

    def __len__(self):
        return len(self.mem_cache) + len(self.seeks)

    def flush(self):
        # пишем в конец файла
        self.fp.seek(0, 2)

        tmp = bytearray()
        tell = self.fp.tell()

        # перебираем все данные
        for k, v in self.mem_cache.iteritems():
            # сериализация перед записью
            v = marshal.dumps(v)

            # текущее смещение
            seek = tell
            # сохраняем смещение и размер
            self.seeks[k] = (seek, len(v))

            # пишем данные в файл, вместе с метаданными
            try:
                buff = v + struct.pack('!H', len(v)) + k + struct.pack('!H', len(k))
                tmp.extend(buff)
                tell += len(buff)
            except Exception:
                print 'flush Exception:', k, v
                raise

        self.fp.write(tmp)

        # зануляем кэш
        self.mem_cache = {}

    def extract(self):
        def items():
            # сначала сбрасываем все из кэша
            for k, v in self.mem_cache.iteritems():
                yield (k, v)

            # объект управления выводом
            out = Out(self.fp, cachesize=self.cachesize_out)

            while not out.eof:
                # на всякий случай - восстановим смещение файла
                out.restore()
                # размер ключа
                size = out.readSize()
                # читаем ключ
                key = out.readText(size)
                # читаем длину текста
                size = out.readSize()

                # только если этот ключ еще актуален - считываем сообщение
                if self.seeks.pop(key, None):
                    # вернем объект
                    yield (key, marshal.loads(out.readText(size)))
                else:
                    # иначе - просто сместимся
                    out.readText(size, is_unpack=False)

        for k, it in items():
            if k in self.lights:
                it.update(self.get_light(k))
            yield (k, it)

    def vacuum(self):
        for k, it in self.extract():
            self[k] = it
        # сбрасываем все в файл
        self.flush()
        # очищаем все легкие данные
        self.lights = {}

    def __del__(self):
        # при закрытии объекта удаляем файл базы
        if self.fp:
            self.fp.close()
            os.unlink(self.fn)
