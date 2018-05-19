# -*- coding: utf-8 -*-

from __future__ import absolute_import
import os
from time import sleep
import traceback
import zipfile
from cStringIO import StringIO
from django.core.exceptions import ValidationError
from asuothodi.models import Contract
from .base import BackgroundBase


class BackgroundContractsStatus(BackgroundBase):
    name = u'Формирование договоров'
    parallel = 1

    def __init__(self, ids, status):
        self.ids = ids
        self.status = status

    def handle(self):
        qs = Contract.objects.filter(id__in=self.ids)

        self.nextPhase(u'Изменение статусов', qs.count())

        # формируем архив
        zip_fp = StringIO()
        with zipfile.ZipFile(zip_fp, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            # подсчитываем кол-во товаров по категориям
            for i, contract in enumerate(qs):
                f = None
                error = None
                try:
                    if contract.status != self.status:
                        contract.status = self.status

                        ##################################
                        ## Часть кода пропущена в целях соблюдения конфидентиальности
                        ##################################

                    if self.status == 'printed' and contract.docx:
                        f = contract.docx.file.file
                        f_content = f.read()
                        title = contract.docx.title
                        f_name, f_ext = os.path.splitext(title)
                        z.writestr('%s.1%s' % (f_name, f_ext), f_content)
                        z.writestr('%s.2%s' % (f_name, f_ext), f_content)
                except ValidationError as e:
                    error = list(e)
                except Exception:
                    error = traceback.format_exc()
                finally:
                    if f:
                        f.close()

                self.progress(label=contract.id, error=error, d_time=5)

        if self.status == 'printed':
            self.taskFileSave('zip', zip_fp)
