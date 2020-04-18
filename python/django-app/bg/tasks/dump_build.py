# -*- coding: utf-8 -*-

from __future__ import absolute_import
import os
import glob
import shutil
from fabric.api import local, settings as fabric_settings
from ..basic.base import BgBase
from main.utils_time import now_slug


class BgDumpBuild(BgBase):
    name = u'Создание дампа'
    parallel = 1

    def __init__(self):
        # определяем путь к папке дампов
        self.path = '%(SHOP_VOL_BACKUP)s/%(dt_label)s' % dict({
            'dt_label': now_slug(),
        }, **os.environ)
        # создаем, если нету
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def local_run(self, *args, **kwargs):
        with fabric_settings(warn_only=True, abort_exception=Exception):
            kwargs['capture'] = True
            out = local(*args, **kwargs)
            if out.failed:
                raise Exception(out.stderr)
            self.log.info(out)
        return out

    def path_to_ssh(self, path):
        # преобразование локального пути в путь на хосте
        host_path = path.replace('%(SHOP_VOL_BACKUP)s' % os.environ, '%(SHOP_HOST_BACKUP_PATH)s' % os.environ)
        # добавляем ssh-данные
        return '%(SHOP_HOST_SSH_USER)s@%(SHOP_HOST_IP)s:%(SHOP_HOST_SSH_PORT)s:%(host_path)s' % dict({
            'host_path': host_path,
        }, **os.environ)

    def db_dump(self, db_name):
        # путь к дампу
        dump_path = '%(path)s/%(db_name)s.dump' % {
            'path': self.path,
            'db_name': db_name,
        }
        self.next_phase(u'Сборка дампа DB: %s -> %s' % (db_name, dump_path))
        # выполняем запрос
        self.local_run(' '.join([
            'PGPASSWORD=%(SHOP_DB_PASSWORD)s',
            'pg_dump -Fc -U %(SHOP_DB_USER)s -h %(SHOP_DB_HOST)s -p %(SHOP_DB_PORT)s %(db_name)s > "%(dump_path)s"',
        ]) % dict({
            'db_name': db_name,
            'dump_path': dump_path,
        }, **os.environ))
        return dump_path

    def media_dump(self):
        # путь к дампу
        dump_path = '%(path)s/media.tar.gz' % {'path': self.path}
        self.next_phase(u'Сборка дампа MEDIA: %s -> %s' % (os.getenv('SHOP_VOL_MEDIA'), dump_path))
        self.local_run('cd %s && tar -zcf %s *' % (os.getenv('SHOP_VOL_MEDIA'), dump_path))
        return dump_path

    def es_dump(self):
        # путь к дампу
        dump_path = '%(path)s/es-dump' % {'path': self.path}
        # создаем, если нету
        if not os.path.exists(dump_path):
            os.makedirs(dump_path)
        self.next_phase(u'Сборка дампа ES: -> %s' % dump_path)
        # выполняем запрос
        self.local_run(' '.join([
            'multielasticdump',
            '--match=^%(SHOP_ES_PREFIX)s.*$',
            '--parallel=1',
            '--direction=dump',
            '--input=http://%(SHOP_ES_HOST)s:%(SHOP_ES_PORT)s',
            '--includeType="data,mapping,settings"',
            '--limit=10000',
            '--output=%(dump_path)s'
        ]) % dict({
            'dump_path': dump_path,
        }, **os.environ))
        return dump_path

    def meta_env(self, **kwargs):
        self.next_phase(u'Сборка meta.env')
        data = {
            'SHOP_RESTORE_BACK_COMMIT': os.getenv('SHOP_BACK_COMMIT'),
            'SHOP_RESTORE_ES_PREFIX': os.getenv('SHOP_ES_PREFIX'),
        }
        data.update(kwargs)
        with open(os.path.join(self.path, 'meta.env'), 'wb') as fp:
            fp.write('\n'.join(['%s=%s' % (k, v) for k, v in data.items()]))

    def handle(self):
        # сброс дампов БД
        db_main_path = self.db_dump(os.getenv('SHOP_DB_MAIN'))
        db_snapshot_path = self.db_dump(os.getenv('SHOP_DB_SNAPSHOT'))

        # сброс медиа
        media_path = self.media_dump()

        # сброс дампов эластика
        es_path = self.es_dump()

        # список индексов
        pathes = {}
        indexes = ['color', 'photo', 'admin_genpage', 'offer', 'snapshot_genpage', 'snapshot_product']
        for idx in indexes:
            es_idx_path = os.path.join(es_path, '%s%s*' % (os.getenv('SHOP_ES_PREFIX'), idx))
            es_files = glob.glob(es_idx_path)
            pathes['SHOP_RESTORE_ES_%s_PATH' % idx.upper()] = self.path_to_ssh(es_idx_path) if es_files else ''

        # сборка meta.env
        self.meta_env(
            SHOP_RESTORE_DB_MAIN_PATH=self.path_to_ssh(db_main_path),
            SHOP_RESTORE_DB_SNAPSHOT_PATH=self.path_to_ssh(db_snapshot_path),
            SHOP_RESTORE_MEDIA_PATH=self.path_to_ssh(media_path),
            **pathes
        )

    def interrupting(self):
        shutil.rmtree(self.path)

    def excepting(self):
        shutil.rmtree(self.path)




