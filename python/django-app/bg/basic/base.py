# -*- coding: utf-8 -*-

from __future__ import absolute_import
from time import sleep
import telegram
import traceback
from cStringIO import StringIO
from time import time
import logging
from django.db import transaction
from django.conf import settings
from django.utils.timezone import now
from bg.models import Task


LOG = logging.getLogger(__name__)


class InterruptException(Exception): pass


class BgLogHandler(logging.StreamHandler):

    def __init__(self, io):
        super(BgLogHandler, self).__init__(io)
        # установим форматтер
        self.formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")


class BgBase(object):
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
    # нужно ли обрабатываться в транзакии
    is_transaction = True
    # включено ли логгирование в телеграмм
    telegram_enable = True

    @classmethod
    def delay(cls, *args, **kwargs):
        """
        Данный метод вызывается в контексте приложения
        """
        # пробуем извлечь название
        name = kwargs.pop('name', None)
        # пробуем извлечь переданный файл
        fp = kwargs.pop('fp', None)
        # пробуем извлечь словарь окружения
        envs = kwargs.pop('envs', None)

        # создаем задачу c уникальным id
        task = Task.objects.create(
            name=name or cls.name,
            cls=cls.__name__,
            status=u'ожидание запуска',
            status_history=[],
            args=args,
            kwargs=kwargs,
            envs=envs,
        )
        if fp:
            task.file.save(fp.name, fp)
        return task

    @classmethod
    def delay_sync(cls, *args, **kwargs):
        """
        Запускает и ожидает завершения
        """
        task = cls.delay(*args, **kwargs)
        # ожидаем завершения выполнения
        while not Task.objects.get(id=task.id).state == 'done':
            sleep(1)
        return task

    def __new__(cls, task_id, *args, **kwargs):
        # создаем объект 
        obj = super(BgBase, cls).__new__(cls, *args, **kwargs)
        obj.task_id = task_id
        # получаем задачу
        task = obj.get_task()
        # получаем имя задачи
        obj.task_name = task.name
        # начало этапа
        obj._start = None
        # название этапа
        obj._satus = None
        # таймстамп последнего обновления
        obj._last_sync = None
        # счетчик
        obj._i = None
        # реальное ожидание выполнения
        obj._expected = None
        # реальное значение выполнения
        obj._performed = None
        # создаем логгер именно для указанной задачи
        obj._log = StringIO()
        obj.log = logging.getLogger(task.pid)
        obj.log.setLevel(logging.INFO)
        obj.log.addHandler(BgLogHandler(obj._log))
        # инициализация телеграмма
        if obj.telegram_enable and settings.TG_BOT_TOKEN:
            obj.tg_bot = telegram.Bot(token=settings.TG_BOT_TOKEN)
        else:
            obj.tg_bot = None
        # выполняем легкое обновление задачи
        task.state = 'running'
        task.status = u'запущена'
        task.save(update_fields=['state', 'status'])
        return obj

    @classmethod
    def run(cls, task_id, *args, **kwargs):
        """
        Данный метод вызывается в контексте отдельного процесса
        """
        error = None
        obj = None

        try:
            # создаем объект класса. именно так - для передачи task_id в объект
            obj = cls.__new__(cls, task_id, *args, **kwargs)
            cls.__init__(obj, *args, **kwargs)

            obj.tg_info(u'Запущено')

            # выключаем автокоммит
            if cls.is_transaction:
                transaction.set_autocommit(False)

            # запускаем логику основного класса
            try:
                obj.pre_handle()
                obj.handle()
                obj.post_handle()
            except Exception:
                # откатываемся
                if cls.is_transaction:
                    transaction.rollback()
                raise
            else:
                if cls.is_transaction:
                    transaction.commit()
            finally:
                # включаем автокоммит
                if cls.is_transaction:
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
                    obj.tg_error(u'Неперехваченная ошибка: %s' % traceback.format_exc())
                    obj.excepting()
                except Exception:
                    LOG.fatal('Excepting error in class (%s, %s): %s', cls.__name__, task_id, traceback.format_exc())
        else:
            status = u'завершено'
        finally:
            if obj:
                obj.tg_info(u'Завершено')
                # сохраним последнее состояние статуса
                try:
                    obj._phase_save()
                except Exception:
                    LOG.error('Finish _phase_save error in class (%s, %s): %s', cls.__name__, task_id,
                              traceback.format_exc())

                # даем возможность дочернему классу корректно обработать безусловное завершение
                try:
                    obj.finishing()
                except Exception:
                    LOG.fatal('Finishing error in class (%s, %s): %s', cls.__name__, task_id, traceback.format_exc())

        # получаем задачу для завершения
        task = Task.objects.get(id=task_id)
        task.set_done(status, error)

    def tg_log(self, lvl, msg):
        self.log.log(getattr(logging, lvl.upper()), msg)
        if self.tg_bot:
            try:
                self.tg_bot.sendMessage(settings.TG_CHAT_ID, '[%s][%s]: %s' % (lvl.upper(), self.task_name, msg))
            except Exception as e:
                print 'WARNING! Telegram error:', str(e)

    def tg_info(self, msg):
        self.tg_log('info', msg)

    def tg_warning(self, msg):
        self.tg_log('warning', msg)

    def tg_error(self, msg):
        self.tg_log('error', msg)

    def interrupting(self):
        pass

    def excepting(self):
        pass

    def finishing(self):
        pass

    def get_task(self):
        return Task.objects.get(id=self.task_id)

    def task_update(self, **kwargs):
        # коммитимся для синхронизации бд
        if self.is_transaction:
            transaction.commit()

        # простое обновление
        task = self.get_task()
        for k, v in kwargs.iteritems():
            setattr(task, k, v)

        # реальное обновление только при наличии данных
        if kwargs:
            task.save(update_fields=kwargs.keys())

        # проверим, не прервана ли задача
        if task.interrupt:
            self.log.warning(u'Задача была прервана!')
            raise InterruptException

        # коммитимся
        if self.is_transaction:
            transaction.commit()

        # вернем объект задачи
        return task

    def task_file_save(self, name, fp):
        # сохранение файла
        task = self.get_task()
        task.file.save(name, fp)
        return task

    def task_file_get(self):
        task = self.get_task()
        return task.file.file if task.file else None

    def next_phase(self, status, expected=None):
        """
        Устанавливает новый этап задачи
        """
        # сохраним последнее состояние статуса
        self._phase_save()

        self.task_update(status=status, expected=expected)
        self.log.info(u'%s. Ожидаемое кол-во: %s', status, expected or u'не определено')

        # инициализируем переменные этапа
        self._satus = status
        self._start = now()
        self._last_sync = time()
        self._i = 0
        self._expected = expected
        self._performed = None

    def flush(self):
        # обновляем прогресс, и опционально - можно изменить ожидание
        self.task_update(
            performed=self._performed,
            expected=self._expected,
            log=self._log.getvalue(),
        )
        # обновляем последнее время синхронизации
        self._last_sync = time()

    def progress(self, performed=None, expected=None, d_time=None, d_count=None, need_sync=False):
        # увеличиваем счетчик
        self._i += 1
        # сохраняем реальное выполнение
        self._performed = performed if performed is not None else self._i
        # сохраняем реальное ожидание
        if expected:
            self._expected = expected

        # 3 сек - дефолтный период синхронизации
        d_time = d_time or 3

        # всегда определяемся на основании d_time. Если задан d_count - он ограничивает проверки времени
        if not d_count or (self._i % d_count) == 0:
            need_sync = (time() - self._last_sync) > d_time

        if need_sync:
            self.flush()

    def pre_handle(self):
        pass

    def handle(self):
        raise Exception('handle no implement!')

    def post_handle(self):
        pass

    def _phase_save(self):
        """
        Сохраняем статус в историю со временем его выполнения
        """
        task = self.get_task()
        task.log = self._log.getvalue()

        if self._start:
            task.performed = None
            task.expected = None
            task.status_history.append({
                'status': self._satus,
                'duration': round((now() - self._start).total_seconds(), 1),
                'expected': self._expected,
                'performed': self._performed,
            })
            self.log.info(u'Записан статус: %s', self._satus)

        task.save(update_fields=['performed', 'expected', 'status_history', 'log'])
        # коммитимся
        if self.is_transaction:
            transaction.commit()