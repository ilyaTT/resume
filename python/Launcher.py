# -*- coding: utf-8 -*-

import os
from os.path import getmtime
import struct

from . import external, internal, BaseCore
import BGlob

from BLog import BException, initLog, TEXT_MESS

""" Инициализируем лог шелла """
log = initLog('shell')

"""
    TODO: работа с лаунчером должна быть реализована через сокеты
    
    request, response - сырые методы вызываются только пока нет объекта core
"""

MARKER_REQUEST  = "\xaa\x00\x00\x15\x10\x05\xed\x29"
MARKER_RESPONSE = "\x54\x77\x12\x07\x73\x69\xa4\x01"
F_REQUEST       = "%s%s" % (BGlob.B_SOURSE_DIR, 'req.b')
F_RESPONSE      = "%s%s" % (BGlob.B_SOURSE_DIR, 'resp.b')

stRequest = struct.Struct('!8si')
stResponse = struct.Struct('!8sii')
    
    
def rawRequest(): 
    """ Сырой метод получения запроса из лаунчера """
    
    """ Если это сырой запуск - данный метод не употребляется """
    if not BGlob.B_COMPILE:  
        return
     
    if not os.path.exists(F_REQUEST):
        raise Exception('Нарушена структура программы.')
    
    """ Если время последнего изменения файла запроса не изменилось - говорим, что команды не поступало """
    if getattr(rawRequest, '_lasttime', 0) == getmtime(F_REQUEST):
        return

    with open(F_REQUEST, 'rb') as fp: 
        data = fp.read()
        """ Проверяем запрос на длину """
        if len(data) != stRequest.size:
            return                       
        marker, command = stRequest.unpack(data)            
    
    """ В случае ошибки сигнатуры - ничего не делаем """
    if marker != MARKER_REQUEST:
        return
    
    """ Сохраняем время последнего изменения """
    setattr(rawRequest, '_lasttime', getmtime(F_REQUEST))
    
    return command
     
           
def rawResponse(code, **kwargs):  
    """ Сырой метод отправки ответа в лаунчер """
        
    """ Если это сырой запуск - данный метод не употребляется """
    if not BGlob.B_COMPILE: 
        return

    with open(F_RESPONSE, 'wb') as f:
        f.write(stResponse.pack(MARKER_RESPONSE, code, kwargs.get('tasks', 0)))
            
  
  
  
class Launcher(BaseCore):
    """ Класс ядра, обеспечивающий взаимодействие с лаунчером """    
        
    @external
    def request(self):
        """ Метод-обертка для синхронного запроса из лончера """
        return rawRequest()
        
    @external
    def response(self, code, **kwargs):
        """ Метод-обертка для синхронного ответа лончеру """
        rawResponse(code, **kwargs)   

    @internal    
    def loop(self):
        """ Метод периодически выполняет обмен данными с лаунчером, если не поднят флаг остановки """
        if not self.core['Core'].stop():
            
            """ Кол-во работающих заданий """
            countWork = self.core['Process'].countWork()
                         
            """ Пробуем получить команду от лаунчера """
            command = self.request()
            
            if command == BGlob.B_N_START:
                """ Если поступила команда на запуск - сообщаем, что запустились """
                self.response(BGlob.B_N_START_SUCCESS, tasks=countWork)
            elif command == BGlob.B_N_STOP:
                """ Если поступила команда общего завершения - останавливаем ядро """   
                self.core['Core'].stop(True)            
            else:
                """ Сообщаем кол-во работающих заданий """
                self.response(BGlob.B_N_WORK, tasks=countWork)

    @internal
    def stop(self):
        """ Действия по отношению к лаунчеру при завершении работы """
             
        """ Три варианта сообщения в лаунчер: произошедшая ошибка, рестарт либо остановка """
        if self.core['Core'].error():
            message = self.core['Core'].error()        
        if self.core['Core'].restart():
            message = BGlob.B_N_RESTART_SUCCESS
        else:
            message = BGlob.B_N_STOP_SUCCESS

        self.response(message, tasks=0)
            
       
            