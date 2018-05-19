# -*- coding: utf-8 -*-

from __future__ import absolute_import
import sys
from cStringIO import StringIO
from time import time, sleep
import traceback
from celery import uuid
import logging
from django.db import transaction
from asuothodi.models import Task
from asuothodi.utils_time import nowTime, nowTimeSlug


LOG = logging.getLogger(__name__)


class InterruptException(Exception): pass


class BackgroundLogHandler(logging.StreamHandler):

    def __init__(self, io):
        super(BackgroundLogHandler, self).__init__(io)
        # установим форматтер
        self.formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")


class BackgroundBase(object):
    # русское название задачи
    name = None
    # кол-во одновременно выполняемых задач
    parallel = 1
    # задачи, блокирующие выполнение
    blocked = []
    # словарь именования
    d_names = {
        '': u'Выполнение'
    }

    @classmethod
    def delay(cls, *args, **kwargs):
        """
        Данный метод вызывается в контексте приложения
        """
        # создаем задачу c уникальным id
        return Task.objects.create(
            cls=cls.__name__,
            status=u'ожидание запуска',
            celery_id=uuid(),
            status_history=[],
            args=args,
            kwargs=kwargs,
        )

    @classmethod
    def run(cls, task_id, *args, **kwargs):
        """
        Данный метод вызывается в контексте celery
        """
        error = None
        obj = None

        try:
            # создаем объект класса
            obj = cls(*args, **kwargs)
            # инициализируем базовый класс
            obj.initBase(task_id)

            # выключаем автокоммит
            transaction.set_autocommit(False)

            # запускаем логику основного класса
            try:
                obj.handle()
            except Exception:
                # откатываемся
                transaction.rollback()
                raise
            else:
                transaction.commit()
            finally:
                # включаем автокоммит
                transaction.set_autocommit(True)
        except InterruptException:
            status = u'прервано'
            # даем возможность дочернему классу корректно обработать прерывание
            if obj:
                try:
                    obj.interrupting()
                except Exception:
                    LOG.fatal('Interrupting error in class (%s, %s): %s', cls.__name__, task_id, traceback.format_exc())
        except Exception:
            status = u'ошибка'
            error = traceback.format_exc()
            LOG.fatal('Exception in class (%s, %s): %s', cls.__name__, task_id, error)
            # даем возможность дочернему классу корректно обработать исключение
            if obj:
                try:
                    obj.excepting()
                except Exception:
                    LOG.fatal('Excepting error in class (%s, %s): %s', cls.__name__, task_id, traceback.format_exc())

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################

    def interrupting(self):
        pass

    def excepting(self):
        pass

    def finishing(self):
        pass

    def initBase(self, task_id):
        """
        Инициализатор базового класса
        """
        # сохраняем только id задачи
        self.task_id = task_id

        # получаем задачу
        task = self.taskUpdate(state='running', status=u'запущена')

        # создаем логгер именно для указанной задачи
        self._log = StringIO()
        self.log = logging.getLogger(task.celery_id)
        self.log.setLevel(logging.INFO)
        self.log.addHandler(BackgroundLogHandler(self._log))

        self.log.info(u'Задача запущена')

        # результат пакетной обработки
        self._bulk_result = []
        # начало этапа
        self._start = None
        # название этапа
        self._satus = None
        # таймстамп последнего обновления
        self._last_sync = None
        # счетчик
        self._i = None
        # реальное ожидание выполнения
        self._expected = None
        # реальное значение выполнения
        self._performed = None

    def taskUpdate(self, **kwargs):
        # простое обновление
        task = Task.objects.get(id=self.task_id)
        for k, v in kwargs.iteritems():
            setattr(task, k, v)

        # реальное обновление только при наличии данных
        if kwargs:
            task.save(update_fields=kwargs.keys())
        # проверим, не прервана ли задача
        if task.interrupt:
            self.log.warning(u'Задача была прервана!')
            raise InterruptException
        # вернем объект задачи
        return task

    def taskFileSave(self, name, fp):
        # сохранение файла
        task = Task.objects.get(id=self.task_id)
        task.file.save(name, fp)
        return task

    def nextPhase(self, status, expected=None):
        """
        Устанавливает новый этап задачи
        """
        # сохраним последнее состояние статуса
        self._statusSave()

        self.taskUpdate(status=status, expected=expected)
        self.log.info(u'%s. Ожидаемое кол-во: %s', status, expected or u'не определено')
        # коммитимся
        transaction.commit()

        # инициализируем переменные этапа
        self._satus = status
        self._start = nowTime()
        self._last_sync = time()
        self._i = 0
        self._expected = expected
        self._performed = None

    def progress(self, performed=None, expected=None, label=None, error=None, d_time=3, d_count=None):
        # увеличиваем счетчик
        self._i += 1
        # сохраняем реальное выполнение
        self._performed = performed if performed is not None else self._i
        # сохраняем реальное ожидание
        if expected:
            self._expected = expected

        if label:
            self._bulk_result.append({
                'id': label,
                'errors': error if error else []
            })

        # определяем необходимость синхронизации с бд
        if d_count:
            need_sync = (self._i % d_count) == 0
        else:
            need_sync = (time() - self._last_sync) > d_time

        if need_sync:
            update_data = {'performed': self._performed, 'log': self._log.getvalue()}
            ##################################
            ## Часть кода пропущена в целях соблюдения конфидентиальности
            ##################################

    def handle(self):
        raise Exception('handle no implement!')

    def _statusSave(self):
        """
        Сохраняем статус в историю со временем его выполнения
        """
        if self._start:
            task = Task.objects.get(id=self.task_id)
            task.performed = None
            task.expected = None
            task.log = self._log.getvalue()
            ##################################
            ## Часть кода пропущена в целях соблюдения конфидентиальности
            ##################################