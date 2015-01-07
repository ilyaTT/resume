# -*- coding: utf-8 -*-

import sys
import hashlib
import subprocess
import marshal
from time import time

from . import external, internal, BaseCore
import BGlob

from BLog import BException, initLog

log = initLog('shell')

""" Соль для создания хэша для генерации ключа и iv """
SALT = '\xa6\xe1$\x82\x08]\x9a\xe06\xb4Q\xe9\n\xb1\xc1\xb9'


class Process(BaseCore):    
    """ Модуль ядра, отвечающий за работу с объектами заданий, как информационными структурами """
    
    def __init__(self):       
        """ Словарь работающих процессов """
        self.__processes = {}
        """ Словарь загруженных модулей """
        self.__modules = {}


    def __getProc(self, name, *args):
        """ Внутренний метод - возвращает строку запуска процесса в зависимости от среды """        
        if BGlob.B_COMPILE:
            pre = '' if BGlob.B_OS == 'win' else './'
            line = [pre + BGlob.B_NAME_EXE, name]
        else:
            line = ['python', name+'.py']
        
        return line + list(args)
    

    def __getProcess(self, name):
        """ Внутренний метод - проверяет существование процесса и возвращает ссылку на него. Если запрошен несуществующий процесс - это нарушение безопасности """
        task = self.__processes.get(name, None)
                
        if task:
            return task
        else:
            """ Если такого задания нет - баним аккаунт этому юзеру """ 
            self.core['External'].request({'action':'ban', 'reason':BGlob.B_E_PRIVATE_NO_RUN})
            """ Останавливаем шелл с ошибкой """ 
            self.core['Core'].error(BGlob.B_E_WORK)            
            raise
        
    @external
    def load(self, mid, module):
        """ Метод загружает новые модули """       
        self.__modules[mid] = module

    @external
    def countWork(self):
        """ Определяет кол-во работающих заданий """       
        len([1 for x in self.__processes if not x['stop']])

    @external     
    def taskStart(self, name):
        """ Включаем задание, если оно еще не включено """ 
        
        """ Проверяет, задания не должно быть в _works """
        if name not in self.__processes:            
            """ Запускем задание """
            try:                                                       
                proc = subprocess.Popen(self.__getProc('BMainModule', name, BGlob.B_PORT_PRIVATE), close_fds=True)                      
            except Exception:
                """ Если произошла ошибка запуска - киллим процесс, обнуляем флаги """
                try:
                    proc.kill()
                except:
                    pass
                
                """ Сообщаем о произошедшей ошибке """
                self.core['RC'].edit('TaskOutput', name, {'error': u'Ошибка включения задания'})

                """ Логируем ошибку """
                log.warn(u"Ошибка включения задания %s", name)
            else:
                """ сохраняем процесс """                
                self.__processes[name] = {
                    'proc': proc,     
                    'active': False,
                    'stop':False,
                    'pause':False,                               
                }        

    @external  
    def taskStop(self, name):
        """ Метод отмечает задание, как остонавливающееся """        
        if name in self.__processes:
            self.__processes[name]['stop'] = True
            
            
    @external  
    def taskPause(self, name):
        """ Метод отмечает задание, как приостановленное """        
        if name in self.__processes:
            self.__processes[name]['pause'] = True
          
          
    @external  
    def taskStatus(self, name):
        """ Метод возвращает статус процесса """        
        return 0 if name not in self.__processes else (1 if self.__processes[name]['pause'] else 2)
        
        
    @external  
    def taskStopped(self, name):
        """ Сообщает, находится ли процесс в стадии остановки """    
        return False if name not in self.__processes else self.__processes[name]['stop']  


    @external  
    def getAllNames(self):
        """ Метод возвращает имена всех текущих процессов """        
        return self.__processes.keys()


    @internal  
    def loop(self):        
        """ Метод мониторит работающие задания, обновляет информацию о них """        
        
        for name, info in self.__processes.items():
            
            """ Определяем код завершения процесса """
            code = info['proc'].poll()
            
            """ Обрабатываем задания, которые завершились """
            if code is not None:
                """ Параметры для сохранения в объект задания. Сохраняем время завершения """
                args = {'stime': int(time())}
                
                """ Убираем задание из словаря работающих """
                self.__processes.pop(name)
                
                """ В зависимости от кода завершения вносим задание в одно из можеств """
                if code > 0:     
                    """ Сообщаем о произошедшей ошибке """
                    args['error'] = u'Ошибка работы задания'                  

                """ Сохраняем данные в базу """
                self.core['RC'].edit('TaskOutput', name, args)
            
    
    @internal  
    def stop(self):
        """ Выставляем остановку всех заданий """
        for name in self.__processes.keys():
            self.taskStop(name)          

            
    @internal         
    def done(self):
        """ Готовность этого модуля наступает тогда, когда все задания завершат работу """
        return not self.__processes
             
