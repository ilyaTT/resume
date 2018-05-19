# -*- coding: utf-8 -*-

from __future__ import absolute_import
import simplejson as json
import os
import datetime
from collections import OrderedDict, defaultdict
from django.conf import settings
from django.core.cache import cache
from elasticsearch import Elasticsearch
from elasticsearch.client import IndicesClient, SnapshotClient
from elasticsearch.client.utils import _make_path
from elasticsearch.helpers import bulk, scan
from elasticsearch_dsl import Search, Q
from elasticsearch_dsl.query import Query as EsBaseQuery
from elasticsearch.serializer import JSONSerializer
from catalog.utils_time import nowTimeSlug


COMMON_NAME_SNAPSHOT = 'shop_snapshot_%s'


# регистрируем новый "пустой" тип запроса
class MatchNone(EsBaseQuery):
    name = 'match_none'


class JSONEnc(JSONSerializer):

    def default(self, data):
        if isinstance(data, set):
            return list(data)
        if isinstance(data, datetime.datetime):
            return data.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(data, datetime.date):
            return data.strftime("%Y-%m-%d")
        return super(JSONEnc, self).default(data)


def readJsonMap(name):
    """
        Читает json-маппинг
    """
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapping/%s.json' % name)) as f:
        return json.load(f)

def connect():
    """
        Подключение к эластик-серверу
    """
    return Elasticsearch(serializer=JSONEnc(), **settings.ELASTIC)


def setRawQuery(dsl, query):
    return dsl._clone().update_from_dict({'query': query})


class ElasticIndexes(object):

    @staticmethod
    def name(slug):
        return 'offer_%s_%s' % (slug, nowTimeSlug())

    def __init__(self):
        with cache.lock('es_index_lock'):
            # подключение
            conn = connect()
            # модуль управления индексами
            self.es_index = IndicesClient(conn)
            # модуль управления снимками
            self.es_snap = SnapshotClient(conn)
            # создаем репозиторий
            self.es_snap.create_repository('offers', {
                'type': 'fs',
                'settings': {
                    'compress': True,
                    'location': 'offers'
                }
            })

    def clone(self, index, slug):
        """
        Создает клон индекса с текущей временной меткой
        Формат: catalog_dev(2017_12_33_12_23_33)
        :return:
        """
        # имя снимка
        name = self.name(slug)

        with cache.lock('es_index_lock'):
            # выполянем запрос на создание снимка
            self.es_snap.create('offers', name, wait_for_completion=True, body={
                'indices': index,
                'include_global_state': False
            })

            # выполянем запрос на восстановления снимка
            self.es_snap.restore('offers', name, wait_for_completion=True, body={
                'indices': index,
                'include_global_state': False,
                'rename_pattern': '^.*$',
                'rename_replacement': name
            })

            # удаляем снимок
            self.es_snap.delete('offers', name)

        # вернем имя
        return name

    def delete(self, index):
        """
        Удаляет индекс, если он есть
        :param index:
        :return:
        """
        with cache.lock('es_index_lock'):
            if self.es_index.exists(index=index):
                self.es_index.delete(index)

    def mapping(self, indexes):
        return self.es_index.get_mapping(index=indexes)


class ElasticBase(object):
    index = None
    type_product = 'product'

    def __init__(self):
        # создаем инстанс эластика
        self.es = connect()
        # обертка для работы с API индекса
        self.es_index = IndicesClient(self.es)

    def index_settings_update(self, settings):
        self.es_index.put_settings(index=self.index, body={
            "index": settings
        })

    def bulk_send(self, iter_data):
        # собственно данные для отправки
        bulk(self.es, iter_data, index=self.index, doc_type=self.type_product, chunk_size=10000)

    def scan(self, query, preserve_order=False, **kwargs):
        return scan(self.es, query, index=self.index, doc_type=self.type_product, size=100000,
                    preserve_order=preserve_order, **kwargs)

    def dsl(self):
        """
        :return Search instance:
        """
        return Search(using=self.es, index=self.index, doc_type=self.type_product)


class ElasticProduct(ElasticBase):

    def __init__(self, index):
        super(ElasticProduct, self).__init__()
        # индекс должен быть установлен явно
        self.index = index

        # если индекс нет - создадим его и запишем маппинг
        if not self.es_index.exists(index=self.index):
            self.es_index.create(index=self.index, body={
                'settings': readJsonMap('product-settings'),
                'mappings': {
                    self.type_product: readJsonMap('product'),
                }
            })

    def deactive(self, date):
        """
            Метод делает неактивными все документы, которые не присутствовали в текущем импорте
        """
        updated = 0
        if self.es_index.exists(index=self.index):
            # получаем ответ
            response = self.es.update_by_query(self.index, doc_type=self.type_product, timeout='12h', body={
                'script': {
                    'inline': 'ctx._source.available = false'
                },
                'query': {
                    'bool': {
                        'must_not': {
                            'term': {
                                'date': date
                            }
                        }
                    }
                }
            })
            # обновляем стату
            updated = response['updated']

        return updated

    def aggrOptions(self, param, size=100000, query=None):
        """
            Метод выполняет агрегацию по значениям переданного параметра
            :param param:
            :return:
        """
        # собственно объект запроса
        dsl = Search(using=self.es, index=self.index, doc_type=self.type_product)
        # в зависимости от флага активности соответственно агрегируем
        if query:
            dsl = dsl.query(query)
        # сама выдача не нужна
        dsl = dsl[0:0]
        # выгребаем по максимуму параметры
        dsl.aggs.bucket(param, 'terms', field=param, size=size)
        # получаем ответ в виде словаря
        response = dsl.execute().to_dict()
        # собираем набор значений
        return [(r['key'], r['doc_count']) for r in response['aggregations'][param]['buckets']]

    def count(self, query=None):
        return self.dsl().query(query).count()

    def execQuery(self, query=None):
        return self.dsl().query(query).execute()

    def execQueryRaw(self, query):
        return setRawQuery(self.dsl(), query).execute()


class ElasticSnapshot(ElasticBase):

    def __init__(self, reset=False):
        super(ElasticSnapshot, self).__init__()
        # индекс должен быть установлен явно
        self.index = COMMON_NAME_SNAPSHOT % settings.SNAPSHOT_LABEL

        if reset and self.es_index.exists(index=self.index):
            self.es_index.delete(self.index)

        # если индекс нет - создадим его и запишем маппинг
        if not self.es_index.exists(index=self.index):
            self.es_index.create(index=self.index, body={
                'settings': readJsonMap('snapshot-settings'),
                'mappings': {
                    self.type_product: readJsonMap('snapshot'),
                }
            })

    def get(self, product_id):
        return self.es.get(self.index, product_id)


class MultiQuery(object):
    """
        Класс реализует функционал сборки мультизапроса
    """

    @staticmethod
    def split(m_query, bound):
        """
        Режет мультизапрос на два
        :return:
        """
        part_1 = m_query.global_queries[:bound]
        part_2 = m_query.global_queries[bound:]

        m_query.global_queries = part_1

        m_query_2 = MultiQuery()
        m_query_2.global_queries = part_2

        return m_query, m_query_2

    def __init__(self):
        # глобальный набор запросов
        self.global_queries = []

    def clone(self):
        m_query_new = MultiQuery()
        m_query_new.global_queries = self.global_queries[:]
        return m_query_new

    def is_filled(self):
        return any(self.global_queries)

    def add(self, filter):
        """
        Добавляет запрос в последний слой
        :param query:
        :param bool_cond:
        :param label:
        :param parent:
        :return:
        """
        # билдим запрос
        self.global_queries[-1].append(filter)

    def addLevel(self):
        """
        Добавляет очередной слой запросов
        :return:
        """
        self.global_queries.append([])

    def build(self):
        """
            Возвращает собраннный мультизапрос

            Q('bool', must=[
                Q('term', gender='Мужской'),
                Q('term', age='Взрослый'),
                Q('bool',
                    should=[
                        Q('match', name='джинсы'),
                        Q('match', name='штаны'),
                    ],
                    must=[
                        Q('bool', should=[
                            Q('match', color='белый')
                        ])
                    ]
                ])
            ])

            Q('bool', must=[
                Q('term', gender='Мужской'),
                Q('bool', must=[
                    Q('term', age='Взрослый'),
                    Q('bool', should=[
                        Q('match', name='джинсы'),
                        Q('bool', should=[
                            Q('match', name='штаны'),
                            Q('bool', must=[
                                Q('match', description='джинсы'),
                                Q('match', color='белый')
                            ])
                        ])
                    ])
                ])
            ])
        """

        # обработка одного слоя
        def level_exec(filters):
            # базовая нода слоя
            base_node = {
                'children': OrderedDict()
            }

            # будем собирать дерево запросов
            tree = {0: base_node}
            flat = {0: base_node}

            for f in filters:
                # создаем ноду
                node = {
                    'filter': f,
                    'children': OrderedDict()
                }
                # заносим в плоский словарь
                flat[f.id] = node
                # получаем родительскую ноду
                flat[f.parent_id or 0]['children'][f.id] = node

            # итерационный метод по сборке булевого запроса
            def bool_build(nodes, kwargs=None):
                # варианты исходных наборов
                subqueries = defaultdict(list)
                # если переданы параметры - обновляем ими исходные наборы
                if kwargs:
                    subqueries.update(kwargs)

                # перебираем все запросы
                for i, (label, data) in enumerate(nodes.items()):
                    # объект фильтра
                    f = data['filter']
                    # текущий запрос
                    query = f.buildQuery()
                    # булево условие, по которому запрос будет вложен на текущем уровне
                    bool_cond = f.cond_single

                    # если у него есть дочерние запросы - сворачиваем их в единый групповой запрос
                    if data['children']:
                        query = bool_build(data['children'], {f.cond_single: [query]})
                        bool_cond = f.cond_group

                    # остальные запросы попадают в соответствии со своими булами
                    subqueries[bool_cond].append(query)

                if any(subqueries.values()):
                    subqueries = dict(subqueries)

                    # если есть should - добавлеям спец. параметр
                    if subqueries.get('should', None):
                        subqueries['minimum_should_match'] = 1

                    return Q('bool', **subqueries)

            # перебираем дерево, строим вложенные запросы
            return bool_build(tree[0]['children'])

        def level_build(lvl):
            # выполняем обработку уровня
            query = level_exec(self.global_queries[lvl])

            # если есть след. уровень - создаем отдельный must для текущего уровня и вложенного
            if len(self.global_queries) - 1 > lvl:
                # в единый must завертываем текущий и новый левел-билд
                lvl_must = [q for q in [query, level_build(lvl + 1)] if q]

                # добавляем must, только если он не пуст
                if lvl_must:
                    query = Q('bool', must=lvl_must)
                else:
                    query = None

            # вернем булевый запрос уровня
            return query

        # как правило 0-ой уровень будет пустым, т.к. будет включать в себя все товары
        return level_build(0)


def countByTerms(index, terms):
    """
    Получаем кол-во для указанного индекса по указанным условиям
    :param index:
    :param terms:
    :return:
    """
    queries = [Q('term', **{term['key']: term['value']}) for term in terms]
    return ElasticProduct(index).dsl().query(Q('bool', must=queries))[:0].execute().hits.total
