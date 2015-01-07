# -*- coding: utf-8 -*-

from collections import OrderedDict
import time
import marshal
import urllib
from itertools import chain, imap

import BGlob 
from BLog import BException, initLog, ExApprove, ExErrors

from . import external, BaseCore
from copy import deepcopy

log = initLog('shell')


""" Отдельные существующие сущности """
RESOURSES = ('TaskInput', 'TaskOutput', 'ResultInput', 'ResultOutput', 'Tpattern', 'Rpattern')

INPUTS = ('Task', 'Result', 'TPattern', 'RPattern')
OUTPUTS = ('Task', 'Result')


class RC(BaseCore):    
    """ Модуль ядра, отвечающий за работу с объектами заданий, как информационными структурами """

    
    def __init__(self):       
        """ Модули """        
        self._envs = {}

        
        """ Словарь объектов, вида {rc: {mid: {name1:obj1, name2:obj2}}}  """  
        self._objs = {rc: {} for rc in RC.RESOURSES}
        """ Словарь примитивов, вида {rc: {mid: dum}}  """  
        self._dumms = {rc: {} for rc in RC.RESOURSES}

    @external
    def load(self, mid, module):
        """ Метод загружает новые модули """
       
        """ загружаем код настройщика в спец. область """            
        exec marshal.loads(module) in self._envs.setdefault(mid, {})

        """ Создаем объекты ресурсов с помощью фабричных методов модулей  """
        for rc in INPUTS: 
            """ Загружаем объекты, обеспечивая безопастность загрузки """
            try:    
                env = self._envs[mid]
                
                """ Загружаем объекты  """                 
                env[env['META']['RC']['Inputs'][rc]].Loads()
                            
                """ Загружаем в эту структуру старые объекты только что загруженного модуля """
                env[rc].Loads(self._objs[rc])

                """ Сортируем объекты по времени создания """
                self._objs[rc] = OrderedDict(sorted(self._objs[rc].items(), key=lambda args: args[1].get('nctime', 0)))
            
                """ Если ресурс является входящим - создаем/заменяем базовый (дефолтный) объект """
                if rc.endswith('Input'):   
                    self._dumms[rc][mid] = self._modules[mid]['M'+rc]()
                
                    print 'self._dumms[mid]', self._dumms[rc][mid], mid, rc
                    
            except Exception:
                log.error(u'Ошибка загрузки модуля %s', mid) 
                
                
        """ Создаем объекты ресурсов с помощью фабричных методов модулей  """
        for rc in RC.RESOURSES: 
            """ Загружаем объекты, обеспечивая безопастность загрузки """
            try:                
                """ Загружаем в эту структуру старые объекты только что загруженного модуля """
                self._envs[mid]['M'+rc].Loads(self._objs[rc])

                """ Сортируем объекты по времени создания """
                self._objs[rc] = OrderedDict(sorted(self._objs[rc].items(), key=lambda args: args[1].get('nctime', 0)))
            
                """ Если ресурс является входящим - создаем/заменяем базовый (дефолтный) объект """
                if rc.endswith('Input'):   
                    self._dumms[rc][mid] = self._modules[mid]['M'+rc]()
                
                    print 'self._dumms[mid]', self._dumms[rc][mid], mid, rc
                    
            except Exception:
                log.error(u'Ошибка загрузки модуля %s', mid) 
        
    @external
    def unload(self, mid):
        """ Метод выгружает объекты неактуального модуля """

        for rc in RC.RESOURSES:                
            """ Удаляет примитив объекта, если есть """
            self._dumms.setdefault(rc, {}).pop(mid, None)
                              
            """ закрываем объекты. Удаляем словарь объектов """
            for name, obj in self._objs[rc].items():
                if obj.mid == mid:
                    try:  
                        obj.Close()                            
                    except Exception:
                        log.error(u'Произошла ошибка выгрузки модуля %s', mid)
                        
                    self._objs[rc].pop(name)
                        
     
    @external
    def get(self, rc, name):
        """ Метод возвращает объект или None в случае его отсутствия """                
        return self._objs[rc].get(name, None)
        
        
    @external
    def create(self, _type, name, mid, approve, args, files):
        """ Метод создает объект. По дефолту игнорирует все предупреждения """  
        
        if mid not in self._envs:
            raise ExErrors('Модуль %s не существует' % mid)
        
        if _type == 'Task':
            if self.has('TaskInput', name):
                raise ExErrors(u'Задание с именем "%s" уже существует"' % name)
            
            """ Создаем непосредственно объекты. Если во время их создания произошли ошибки - удаляем созданные объекты """
            try:
                w1, n1 = self._create('TaskInput', name, mid, approve, args, files)
                w2, n2 = self._create('TaskOutput', name, mid, approve, {}, files)
                                
                """ Получаем наборы предупреждений и сообщений """    
                warnings, notices = [list(chain(*x)) for x in imap(None, (w1, n1), (w2, n2) )]
            
            except Exception as e:
                log.error(u'Ошибка сохранения задания %s', name)
                self.delete('TaskOutput', name, mid)   
                self.delete('TaskInput', name, mid)                 
                raise e

        return warnings, notices
             
             
    @external
    def _create(self, rc, name, mid, approve, args, files):
        """ Метод создает объект. По дефолту игнорирует все предупреждения """  
        
        if mid not in self._modules:
            raise Exception('Модуль %s не существует' % mid)
                
        """ Находим класс сохранения ресурса """
        cls = self._modules[mid]['M'+rc]
        
        """ Создаем объект через фабричный метод """  
        obj = cls.Create(name)
        
        """ Если создать объект удалось - сохраняем его, т.к. после создания удалить объект можно только через общий метод удаления, а для этого объект должен находится в общем словаре """
        self._objs[rc][name] = obj
        
        """ Нельзя изменять параметры напрямую, работаем только с копией """
        args = deepcopy(args)
        
        """ Записываем время создания и имя объекта, как поле """
        args['nctime'] = int(time.time())
        args['name'] = name
        
        """ Обновляем объект с новыми данными """ 
        return obj.Saves(approve, args)
   
    @external
    def edit(self, rc, name, mid, approve, args, files):
        """ Метод изменяет объект задания. По дефолту игнорирует все предупреждения """  
        
        """ Получаем текущий объект задания из памяти """
        obj = self._objs[rc].get(name, None)
        
        if obj is None:
            raise Exception('Задание %s не существует' % name)

        """ Сохраняем новые данные """         
        return obj.Saves(approve, args)
    
    
    @external    
    def has(self, rc, name):
        """ Метод проверяет, существует ли такой объкт. Объект уникален по имени в контексте одного ресурса """              
        return self._objs[rc].get(name, False)      

        
    @external        
    def names(self, rc, mid=None):
        """ Словарь либо список имен объектов """       
        
        """ Объекты выбранного ресурса """  
        objs = self._objs[rc]
        
        """ Сортировка по времени создания """  
        _sort = lambda args: args[1].get('nctime', 0)
        
        """ В зависимости от запроса получаем либо имена конкретного модуля, либо словарь списков имен """
        if mid:
            names = [name for name, obj in sorted(objs.items(), key=_sort, reverse=True) if obj.mid == mid]
        else:
            names = {}
            for name, obj in sorted(objs.items(), key=_sort, reverse=True):  
                names.setdefault(obj.mid, []).append(name)

        return names


    @external   
    def dummies(self, rc): 
        """
            @rc - тип
            Метод возвращает все дефолтные объекты ресурса
        """
        objs = {}
        for mid, obj in self._dumms[rc].items():
            """ Генерируем дефолтное имя на основании текущей даты """
            obj.items['name']['value'] = time.strftime("%d.%m.%y %H-%M-%S", time.localtime())
            """ Серилизуем объект """
            objs[mid] = obj.Json() 

        return objs    

    @external   
    def json(self, rc, name):     
        """ json-представление объекта """       
        obj = self._objs[rc].get(name, None)        
        if obj: return obj.Json() 
        return None    

    
    @external  
    def delete(self, rc, name, mid): 
        """ Удаление объекта """  
        obj = self._objs[rc].get(name, None) 
        
        if obj is None:
            return
        
        try:
            obj.Remove()
        finally:
            """ Удаляем объект задания """
            self._objs[rc].pop(name, None)
    

    def __getTask(self, name, input, output):
        """ Метод получает заполненнное представление задания для интерфейса """
                
        """ Определяем словарь таски """
        task = {
            'status': self.core['Process'].taskStatus(name),
            'stopped': self.core['Process'].taskStopped(name),
            'error': output.get('error', ''),
            'items':{}
        }
        
        """ Перебираем переданные объекты ресурсов """
        for obj in [obj for obj in (input, output) if obj]:  
            """ На основании заголовков собираем значения """ 
            for key in obj.headers.keys():               
                task['items'][key] = {
                    'sort': urllib.quote(str(obj[key])), 
                    'val': obj._items[key]['commonView'](obj, key) if 'commonView' in obj._items[key] else obj[key]
                }
        
        return task
        
        
    @external 
    def getAllTasks(self):
        """ Метод вернет все задания """ 
        
        """ Словарь заданий, который будет передан в шаблон """ 
        blocksTask = {}
        
        for name, input in self._objs['TaskInput'].items():
            
            """ Объект исходящих параметров """
            output = self._objs['TaskOutput'][name]
            
            """ Если модуль еще не встречался - создаем каркас для него """
            blocksTask.setdefault(input.mid, {
                'sorted':None, 
                'headers':{
                    'inputs': input.headers,
                    'outputs': output.headers
                }, 
                'tasks':{}
            })
            
            """ Добавляем задание в список заданий определенного блока """  
            blocksTask[input.mid]['tasks'][name] = self.__getTask(name, input, output)
        
        print blocksTask
        
        """ Вернем все блоки """  
        return blocksTask


    @external 
    def getCheckTasks(self, names):
        """ Метод вернет заголовочные исходящие данные для запрошенных заданий + работающие задания """        
        return {name: self.__getTask(name, None, self._objs['TaskOutput'][name]) for name in set(names + self.core['Process'].getAllNames())}

