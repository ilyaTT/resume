# -*- coding: utf-8 -*-

from copy import deepcopy

from . import external, cron, BaseCore
from collections import OrderedDict

import BGlob
from BLog import BException, initLog

log = initLog('shell')

class News(BaseCore):
    """ Класс реадизует синхронный доступ к новостям. Структура новости: {title:'', text:'', date:'', status:''} """
    
    def __init__(self):        
        """ Словарь новостей: id=>содержимое новости """
        self._news = OrderedDict()
        """ Список id новостей, прочтенных за сессию """
        self._reads = []

    @external
    def loads(self, news):   
        """ Метод загружает новости """  
        log.info(u"Загружено %s новостей. Из них не прочитано - %s", len(news), len([1 for new in news if not new['read']]))   
        self._news.update([(new['id'], new) for new in news])
        
    @external
    def unloads(self, newsId):  
        """ Метод выгружает новости """     
        for nid in newsId:        
            self._news.pop(nid)

    @external
    def getAll(self):  
        """ Метод возвращает полную копию новостей """     
        return self._news.values()

    @external
    def get(self, nid):  
        """ Метод возвращает конкретную новость """     
        return deepcopy(self._news[nid])
        
    @external
    def setRead(self, nid):  
        """ Метод устанавливает прочтенную новость """     
        self._reads.append(nid)
        self._news[nid]['read'] = True
    
    @external
    def popsReads(self): 
        """ Метод вынимает список прочтенных за сессию новостей """         
        reads = self._reads
        self._reads = []
        return reads
    
    @external
    def getUnreadCount(self): 
        """ Получаем кол-во непрочитанных новостей """         
        return len([1 for new in self._news.values() if not new['read']])
    
