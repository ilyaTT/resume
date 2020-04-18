# -*- coding: utf-8 -*-

from __future__ import absolute_import
from time import sleep
from datetime import timedelta
import sys
import os
import psutil
import traceback
import logging
import atexit
from collections import defaultdict
from django.db.models import Q
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from django.db import transaction
from bg.models import Task
from bg import tasks


LOG = logging.getLogger(__name__)


def proc_is_run(pid, find=None):
    # получим объект процесса
    try:
        proc = psutil.Process(int(pid))
    except Exception:
        return False
    if not proc.is_running():
        return False
    if find and find not in ' '.join(proc.cmdline()):
        return False
    return True


def proc_is_zombie(pid, find=None):
    if not proc_is_run(pid, find):
        return False
    if psutil.Process(int(pid)).status() == psutil.STATUS_ZOMBIE:
        return True

    return False


def proc_start(cmd, envs=None):
    env = os.environ.copy()
    env.update(envs or {})
    return psutil.Popen([str(x) for x in cmd], env=env)


def proc_stop(proc, task_id):
    try:
        proc.terminate()
        gone, alive = psutil.wait_procs([proc], timeout=5)
        for p in alive:
            p.kill()
    except psutil.ZombieProcess:
        LOG.error(u'Detected ZombieProcess. Pid: %s. Task ID: %s' % (proc.pid, task_id))
    except psutil.AccessDenied:
        LOG.error(u'AccessDenied. Pid: %s. Task ID: %s' % (proc.pid, task_id))
    except psutil.NoSuchProcess:
        LOG.error(u'NoSuchProcess. Pid: %s. Task ID: %s' % (proc.pid, task_id))


# итератор всех целевых процессов
def iter_bg_tasks():
    for proc in psutil.process_iter():
        try:
            if not ({'manage.py', 'bg-task'} - set(proc.cmdline())):
                yield proc
        except psutil.NoSuchProcess:
            continue


def iter_bg_tasks_id(is_unparent=False):
    for proc in iter_bg_tasks():
        # вернем целевые процессы, которые явно были запущены текущим наблюдателем
        try:
            # фильтрация в зависимости от наличия родителя
            if proc.ppid() == (1 if is_unparent else os.getpid()):
                # получаем task-id процесса
                task_args = [x for x in proc.cmdline() if x.startswith('--task_id=')]
                if task_args:
                    yield proc, int(task_args[0].replace('--task_id=', ''))
        except psutil.NoSuchProcess:
            continue


class Command(BaseCommand):
    # файл-метка запуска шедаллера
    start_fn = '%(SHOP_VOL_PROC)s/%(SHOP_PROC_BG_START)s.%(SHOP_PROJECT_UNIQ_NAME)s' % os.environ
    # файл-метка остановки шедаллера
    stop_fn = '%(SHOP_VOL_PROC)s/%(SHOP_PROC_BG_STOP)s.%(SHOP_PROJECT_UNIQ_NAME)s' % os.environ

    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        with open(self.start_fn, 'wb') as fp:
            fp.write('')

    def stop_check(self):
        if os.path.exists(self.stop_fn):
            return True

    def stop_clear(self):
        if os.path.exists(self.stop_fn):
            os.unlink(self.stop_fn)

    def handle(self, **kwargs):
        while True:
            # максимальное кол-во фоновых задач
            max_bg_total_process = os.getenv('max_bg_total_process', 5)

            # явно выключаем все задачи в бд, которые реально не выполняются
            for task in Task.objects.filter(state__in=['running', 'starting']):
                # принудительно завершаем задачи, которые реально больше не выполняются
                if not proc_is_run(task.pid, find='--task_id=%s' % task.id):
                    task.status = u'Необработанное прерывание'
                    task.error = u'Задача прервана по неустановленной причине'
                    task.state = 'done'
                    task.time_finish = now()
                    task.save()

                # отдельно отмечаем зомби-процессы
                if proc_is_zombie(task.pid, find='--task_id=%s' % task.id):
                    task.status = u'Зомби-процесс'
                    task.error = u'Процесс задачи находится в зомби-состоянии'
                    task.state = 'done'
                    task.time_finish = now()
                    task.save()

            # собираем выполняющиеся задачи по версии бд
            actives_cls = defaultdict(set)
            for t in Task.objects.filter(state__in=['running', 'starting']):
                actives_cls[t.cls].add(t)

            # собираем задачи, отслеживаемые в бд, которые могут реально выполняться
            tasks_pid = {t.pid: t for t in Task.objects.filter(
                Q(state__in=['running', 'starting', 'done']) &
                Q(
                    Q(time_finish__gt=now() - timedelta(seconds=10)) |
                    Q(time_finish=None)
                )
            )}

            # все запущенные процессы должны иметь отображение на бд
            for proc, task_id in iter_bg_tasks_id():
                # если же процесс отсутствует в бд - гасим его
                if str(proc.pid) not in tasks_pid or tasks_pid[str(proc.pid)].id != task_id:
                    LOG.warning(u'Обнаружен неотслеживаемый в бд процесс. Pid: %s. Task ID: %s' % (proc.pid, task_id))
                    proc_stop(proc, task_id)

            # останавливаем процессы, которые по какой-либо причине отвалились от наблюдателя
            for proc, task_id in iter_bg_tasks_id(is_unparent=True):
                # если же процесс отсутствует в бд - гасим его
                LOG.warning(u'Обнаружен процесс без родителя. Pid: %s. Task ID: %s' % (proc.pid, task_id))
                proc_stop(proc, task_id)

            # если есть сигнал к остановке, и нет реальных выполняющихся процессов - останавливаемся
            if self.stop_check():
                if not list(iter_bg_tasks()):
                    break
            # запуск новых процессов, только если нет сигнала к завершению
            else:
                # процессы к запуску после транзакции
                runnings = []
                # перебираем все задачи, ожидающие запуска
                with transaction.atomic():
                    for task in Task.objects.select_for_update(skip_locked=True).filter(state='waiting'):
                        # загружаем класс задачи
                        cls = getattr(tasks, task.cls, None)
                        if not cls:
                            LOG.error(u'Не найден класс %s', task.cls)
                            continue

                        # если задача уже прервана - закрываем ее
                        if task.interrupt:
                            task.set_done(u'прервано')
                            continue

                        # статус отклонения
                        status_reject = None

                        # проверка на глобальное кол-во задач
                        if (len(list(iter_bg_tasks())) + len(runnings)) >= max_bg_total_process:
                            status_reject = u'Не более %s одновременных задач' % max_bg_total_process
                        # проверка на идентичность
                        elif any([t.args == task.args and t.kwargs == task.kwargs for t in actives_cls[task.cls]]):
                            status_reject = u'Задача уже выполняется. Ожидание завершения'
                        # если кол-во активных задач превысило допустимый уровень
                        elif len(actives_cls[task.cls]) >= cls.parallel:
                            status_reject = u'Максимум %s однотипных задач' % cls.parallel
                        else:
                            # определяем блокирующие задачи
                            blocked = [cls_block for cls_block in cls.blocked if len(actives_cls[cls_block]) > 0]
                            if blocked:
                                status_reject = u'Ожидание завершения задач: %s' % ', '.join([globals()[b].name or b for b in blocked])

                        # если есть статус отклонения, и текущий статус задачи не такой - обновляем статус
                        if status_reject:
                            # обновим статус, только если он был изменен
                            if task.status != status_reject:
                                task.status = status_reject
                                task.save(update_fields=['status'])
                            continue

                        # отмечаем задачу к запуску
                        task.state = 'starting'
                        task.save(update_fields=['state'])

                        # запись для процесса к запуску
                        runnings.append({
                            'args': [sys.executable, 'manage.py', 'bg-task', '--task_id=%s' % task.id],
                            'envs': task.envs or {},
                            'task_id': task.id
                        })
                        actives_cls[task.cls].add(task)
                        LOG.info(u'Новая задача: %s', unicode(task))

                # реальный запуск процессов
                for running in runnings:
                    task = Task.objects.get(id=running['task_id'])

                    try:
                        proc = proc_start(running['args'], envs=running['envs'])
                    except Exception:
                        task.set_done(u'Ошибка запуска', traceback.format_exc())
                        LOG.error(task.error)
                    else:
                        task.pid = proc.pid
                        task.save(update_fields=['pid'])

            sleep(1)

        # выполняем очистку флага остановки
        self.stop_clear()


@atexit.register
def goodbye():
    if os.path.exists(Command.start_fn):
        os.unlink(Command.start_fn)
