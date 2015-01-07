# -*- coding: utf-8 -*-

"""
    Этот класс является примером обратной наследственности: он объединяет все ядро в один ресурс, таким образом обеспечивая доступы к данным через один поток
"""


""" Порядок перечисления модулей имеет важное значение: в таком же порядке будет производится их инициализация """
__all__ = ['Settings', 'News', 'Update', 'Launcher', 'RC', 'Process', 'Tools', 'External', 'LocalFiles']

from threading import Event, _get_ident, Thread
from Queue import Queue
from time import time
import importlib

from BLog import BException, initLog, fatalWrap
import BGlob


log = initLog('shell')


class MetaCore(type):
    """ Все классы, имеющие данный метакласс, получают в распоряжение словарь с объектами модулей ядра """
    
    core = {}
        
    def __new__(cls, name, bases, dicts):        
        dicts['core'] = MetaCore.core        
        return type.__new__(cls, name, bases, dicts)


class MetaInternalCore(MetaCore):     
    """ Устанавливает новый объект в словарь ядра """
    
    """ Очередь запросов к заданиям """  
    _requests__ = Queue()
    """ Словарь ответов вызывающим потокам """  
    _responses__ = {}
    """ Словарь исключений """  
    _exception__ = {}
    
    def __new__(cls, name, bases, dicts):
        
        """ Очередь запросов к заданиям """  
        dicts['_requests__'] = MetaInternalCore._requests__
        """ Словарь ответов вызывающим потокам """  
        dicts['_responses__'] = MetaInternalCore._responses__
        """ Словарь исключений """  
        dicts['_exception__'] = MetaInternalCore._exception__
        
        newCls = MetaCore.__new__(cls, name, bases, dicts)
               
        return newCls



class BaseCore(object):
    """ Базовый класс для всех модулей ядра """
    
    __metaclass__ = MetaInternalCore
    
    def __new__(cls, *args, **kwargs):
        """ Метод сохраняет созданный объект в общем словаре и обеспечивает единичность объекта модуля """ 
        return cls.core.setdefault(cls.__name__, object.__new__(cls, *args, **kwargs))
        
    def loop(self):
        """ Этот метод будет вызываться даже после поднятия флага стоп. Если нужно в определенном модуле не выолнять логику - проверяем ошибку или флаг стоп """
        pass
    
    def stop(self):
        """ Метод вызывается один раз, через ядро. НЕ ДОЛЖЕН ВЫЗЫВАТЬСЯ ЯВНО! Выполняет логику остановки модуля """
        pass
        
    def done(self):
        """ Этот метод вызывается для подтверждения остановки модуля. Может вызываться неограниченное кол-во раз. По умолчанию считаем, что модуль успешно завершился """
        return True
    


def external(func):
    """
        @func - абстрактный внешний слот для приема аргументов и вызова декоратора. Фактический функционал заключается во внутренней функции
    """
    def call(self, *args, **kwargs):       
        """ Если вызов метода происходит в потоке ядра - вызываем метод напрямую """
        if self.core['Core'].threadId == _get_ident():            
            return func(self, *args, **kwargs)
        
        """ Если поток ядра уже завершил работу - вызов функции не имеет смысла и взов уйдет в пустоту, о чем нужно уведомит в логе """
        if not self.core['Core'].isAlive():
            log.error(u"Нарушена последовательность работы программы!")
            return
        
        """ Создаем событие, которые будет синхранизационным механизмом для потоков """
        event = Event()
        """ Пишем в очередь запрос """
        self._requests__.put_nowait({'func':func, 'self':self, 'args':args, 'kwargs':kwargs, 'threadId':_get_ident(), 'event':event})
        """ Ожидаем ответ на этот запрос """
        event.wait()
        
        """ Проверим словарь исключений """
        if _get_ident() in self._exception__:
            raise self._exception__.pop(_get_ident())
        
        """ Возвращаем результат вызова """
        return self._responses__.pop(_get_ident())    
    return call


def internal(func):
    """ Декоратор осуществляет проверку на принадлежность вызывающего потока к потоку ядра """
    def call(self, *args, **kwargs):
        
        """ Если вызов метода происходит в потоке ядра - вызываем метод напрямую """
        if self.core['Core'].threadId == _get_ident():
            func(self, *args, **kwargs)
        else:
            raise Exception(u"Логическая ошибка - вызов метода из недопустимого потока ")

    return call


def cron(_interval, first=True):
    """ Декоратор позволяет ограничивать вызов метода до одного раза в _interval сек """
    def decor(func):        
        def clean():
            """ функция цеплятеся к переданной и позволяет очистить стартовое значение таймера """
            try:
                delattr(func, '_last')
            except:
                pass
        
        def call(self, *args, **kwargs):
            """ Определяем стартовое значение: если поднят флаг первого вызова, то первый вызов метода произойдет сразу, а затем будет повторятся через указанные интервалы  """
            response = None            
            start = 0 if first else time()
            if time() >= getattr(func, '_last', start) + _interval:           
                response = func(self, *args, **kwargs)
                setattr(func, '_last', time())
            return response
        
        call.clean = clean
        
        return call   
    return decor   


class Core(BaseCore, Thread):
    
    def __init__(self):        
        Thread.__init__(self)
        """ Текущая ошибка """        
        self.__error = None
        """ Событие запуска ядра """
        self.__start = Event()        
        """ Флаг рестарта """     
        self.__restart = False 
        """ Флаг остановки ядра """
        self.__stop = False      
        """ Список инициализированных модулей """
        self._modules = []
        """ Идентификатор потока ядра """
        self.threadId = None       
        """ Производим импортирование модулей """
        for mod in __all__:                   
            """ Импортируем класс """
            importlib.import_module('.'+mod, 'BShell.Core')                    

        
    def start(self):
        """ Переопределяем стартовый метод потока """  
        Thread.start(self)        
        """ Псоле запуска потока ожидаем инициализации моудлей """
        self.__start.wait()

    @fatalWrap(log)
    @external  
    def error(self, error=None):        
        """ Метод устанавливает/возвращает текущую ошибку. При установке уже выставленная ошибка имеет приоритет и не перезаписывается """  
        if error is None:
            return self.__error            
        elif self.__error is None:
            self.__error = error
        """ Если устанавливается ошибка - поднимаем флаг остановки цикла ядра """
        self.stop(True)

    @external
    def restart(self, restart=None): 
        """ Метод устанавливает/возвращает флаг рестарта """  
        if restart is None:
            return self.__restart
        else:
            self.__restart = restart
            
    @external
    def stop(self, stop=None):       
        """ Метод устанавливает/возвращает текущий статус остановки. Актуален только первый вызов, остальные - игнорируются """  
        if stop is None:
            return self.__stop        
        elif not self.__stop: 
            """ Если остановка еще не инициализирована - поднимаем флаг и стопим модули """  
            self.__stop = True                   
            """ Завершаем каждый инициализированный ресурс """
            for mod in self._modules:
                mod.stop()              

    def run(self):
        """ Инициализация всех ресурсов должна происходить тут - в области видимости основного потака ресурсов """
        
        """ Запоминаем id потока ядра """
        self.threadId = _get_ident()
        
        """ Производим непосредственную инициализацию всех классов """
        try:
            for mod in __all__:                
                """ Запуск модулей возможен только в случае отсутсвия флага остановки """
                if not self.stop():                  
                    """ Инициализируем объект основногоо класса модуля """
                    self._modules.append(getattr(globals()[mod], mod)())   
        except Exception:
            self.error(BGlob.B_E_START)
        
        """ Сообщаем, что инициализирование ресурсов завершено """    
        self.__start.set()
        
        """ Входим в основной цикл ядра """
        while True:                      
            """ Проверяем условие полной остановки - это поднятый флаг остановки и завершенная работа всех модулей """
            if self.stop():
                for mod in self._modules:
                    """ ВНИМАНИЕ! Метод done можт выполнятся неограниченное кол-во раз! """
                    if not mod.done():
                        break
                else:
                    break
            
            try:
                """ Получаем запрос, либо блокируем поток до поступления запроса на 1 сек """
                req = self._requests__.get(True, 1)
            except Exception:
                """ Для каждого объекта ядра вызываем метод периодического опроса. Будет вызван только при выполнении условия ожидания запроса """
                try:
                    for mod in self._modules:
                        """ ВНИМАНИЕ! Метод loop можт выполнятся неограниченное кол-во раз даже после остановки или поднятия ошибки! """
                        mod.loop()
                except Exception:
                    self.error(BGlob.B_E_WORK)
            else:                
                """ Если запрос поступил - обрабатываем его """
                try:
                    result = req['func'](req['self'], *req['args'], **req['kwargs'])
                except Exception as e: 
                    log.error(u'Функциональная ошибка')                                    
                    self._exception__[req['threadId']] = e
                else:                
                    """ Метод отработал - результат закладываем в словарь ответов для запрашиваемого потока """
                    self._responses__[req['threadId']] = result
                
                """ Разблокируем вызывающий поток """
                req['event'].set()    
