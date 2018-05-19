# -*- coding: utf-8 -*-

from collections import defaultdict
from asuothodi.celery import app
from .contracts_status import BackgroundContractsStatus
from .contracts_zip import BackgroundContractsZip
from .build_routes import BackgroundBuildRoutes

def runnings():
    # объект испектора
    inspect = app.control.inspect()
    # активные задачи
    tasks = defaultdict(set)
    for worker in inspect.active().values():
        for t in worker:
            tasks[t['name'].replace('asuothodi.tasks.', '')].add((t['id'], t['args'], t['kwargs']))
    return tasks

