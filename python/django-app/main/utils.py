
import json
import datetime
from functools import update_wrapper
import urllib.parse
from django.utils.functional import cached_property
from django.conf import settings
from django.http import HttpRequest


class JsonFieldEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        elif isinstance(obj, datetime.date):
            return obj.strftime('%Y-%m-%d')
        elif isinstance(obj, datetime.time):
            return obj.strftime('%H:%M:%S')
        else:
            return super().default(obj)


def inheritors(klass):
    subclasses = set()
    work = [klass]
    while work:
        parent = work.pop()
        for child in parent.__subclasses__():
            if child not in subclasses:
                subclasses.add(child)
                work.append(child)
    return subclasses


class ViewsetWrap:

    @classmethod
    def init_request(cls, viewset_class, method, action, user, query_params=None, *args, **kwargs):
        # анализируем текущий базовый адрес
        url_base = urllib.parse.urlsplit(settings.PUBLIC_ADDRESS_SITE)
        # создаем кастомный объект запроса
        request = HttpRequest()
        request.META = {
            'HTTP_HOST': url_base.netloc,
            'SERVER_NAME': url_base.hostname,
            'HTTP_ORIGIN': settings.PUBLIC_ADDRESS_SITE,
            'SERVER_PORT': str(url_base.port or ('443' if url_base.scheme == 'https' else '80')),
            'HTTP_X_FORWARDED_PROTO': url_base.scheme,
            'wsgi.url_scheme': url_base.scheme,
        }
        request.user = user
        return cls(viewset_class, method, action, request, query_params, *args, **kwargs)

    def __init__(self, viewset_class, method, action, request, query_params=None, *args, **kwargs):
        # установка статичных гет-параметров
        if query_params:
            request.GET = request.GET.copy()
            request.GET.update(query_params)
        request.method = method

        # служебные параметры rest_framework/viewsets.py:59
        viewset_class.name = None
        viewset_class.description = None
        viewset_class.suffix = None
        viewset_class.detail = None
        viewset_class.basename = None

        # для возможности дальнейших действий нужно сохранить параметры
        self.viewset_class = viewset_class
        self.actions = {method.lower(): action}
        self.request_original = request

        # ручное as_view
        self.viewset = viewset_class()
        self.viewset.action_map = self.actions
        for method, action in self.actions.items():
            handler = getattr(self.viewset, action)
            setattr(self.viewset, method, handler)
        if hasattr(self.viewset, 'get') and not hasattr(self.viewset, 'head'):
            self.viewset.head = self.viewset.get
        self.viewset.request = self.viewset.initialize_request(request, *args, **kwargs)
        self.viewset.args = args
        self.viewset.kwargs = kwargs

    @cached_property
    def response(self):
        # вторая часть as_view - остаточная инициализация
        def view(request, *args, **kwargs):
            return self.viewset.dispatch(request, *args, **kwargs)
        update_wrapper(view, self.viewset_class, updated=())
        update_wrapper(view, self.viewset_class.dispatch, assigned=())
        view.cls = self.viewset_class
        view.initkwargs = {}
        view.actions = self.actions
        # запуск dispatch
        return view(self.request_original, *self.viewset.args, **self.viewset.kwargs)

    @cached_property
    def queryset(self):
        return self.viewset.filter_queryset(self.viewset.get_queryset())

