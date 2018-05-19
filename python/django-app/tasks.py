# -*- coding: utf-8 -*-

from __future__ import absolute_import
import traceback
from itertools import chain
import logging
from django.db import transaction
from asuothodi.celery import app as celery_app
from asuothodi.background import *
from asuothodi.utils import camelToSnake, snakeToCamel
from asuothodi.utils_time import nowTime
from asuothodi.models import Task


LOG = logging.getLogger(__name__)


# декоратор реализует передачу управления задачей соответствующему классу
def wrap_task(**opts):
    def decor(func):
        def wrap(*args, **kwargs):
            # из функции берем только название и создаем объект задачи
            globals()[snakeToCamel(func.__name__)].run(*args, **kwargs)
        # навешиваем на обертку все данные задачи
        wrap.__name__ = func.__name__
        wrap.__module__ = func.__module__
        #wrap.__qualname__ = func.__qualname__
        wrap.__doc__ = func.__doc__
        return celery_app.task(wrap, **opts)
    return decor


@wrap_task()
def background_contracts_status(*args, **kwargs): pass

@wrap_task()
def background_contracts_zip(*args, **kwargs): pass

@wrap_task()
def background_build_routes(*args, **kwargs): pass


from django.core.management import call_command

@celery_app.task()
def celery_backup():
    call_command('dbbackup', compress=True)
    call_command('mediabackup', compress=True)


@celery_app.task()
def celery_telemetry():
    # проверяем, что задача не выполняется - иначе - пропускаем
    if len(runnings()[celery_telemetry.__name__]) > 1:
        return
    call_command('telemetry_build')


@celery_app.task()
def celery_scheduler():
    # проверяем, что задача планировщика не выполняется - иначе - пропускаем
    if len(runnings()[celery_scheduler.__name__]) > 1:
        return
    # print 'EXCLUSIVE celery_scheduler'

    # получаем задачи, которые сейчас выполняются по версии БД
    tasks_running = list(Task.objects.filter(state='running'))
    # запрашиваем реально выполняемые задачи
    actives = runnings()
    # находим id реально выполняемых задач
    ids_running = list(chain(*[[c_id for c_id, _, _ in tasks] for task_name, tasks in actives.iteritems()]))
    # print 'celery_scheduler actives:', actives, ids_running

    # убиваем все задачи в бд, которые реально не выполняются
    for task in tasks_running:
        # принудительно завершаем задачи, которые реально больше не выполняются
        if task.celery_id not in ids_running:
            # print 'FATAL running:', nowTime(), task.celery_id
            task.status = u'Необработанное прерывание'
            task.error = u'Задача прервана по неустановленной причине'
            task.state = 'done'
            task.time_finish = nowTime()
            task.save()

    # добавляем стартующие задачи из бд
    for task in Task.objects.filter(state='starting'):
        actives[camelToSnake(task.cls)].add((task.celery_id, unicode(tuple(task.args)), unicode(task.kwargs)))

    # перебираем все задачи, ожидающие запуска
    for task in Task.objects.filter(state='waiting'):
        # загружаем класс задачи
        cls = globals()[task.cls]

        # имя задачи
        task_name = camelToSnake(task.cls)

        # проверка на идентичность
        if any([c_args == unicode(tuple(task.args)) and c_kwargs == unicode(task.kwargs) for c_id, c_args, c_kwargs in actives[task_name]]):
            task.status = u'Задача уже выполняется. Ожидание завершения'
            task.save(update_fields=['status'])
            continue

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################


        # пробуем запустить celery-задачу
        try:
            # получаем функцию задачи
            func = globals()[task_name]
            task.state = 'starting'
            task.save(update_fields=['state'])
            # запускаем
            func.apply_async((task.id,) + tuple(task.args), task.kwargs, task_id=task.celery_id)
        except Exception:
            task.status = u'Ошибка запуска'
            task.error = traceback.format_exc()
            task.time_finish = nowTime()
            task.state = 'done'
            LOG.error(task.error)
            task.save()
        else:
            actives[task_name].add((task.celery_id, unicode(tuple(task.args)), unicode(task.kwargs)))
