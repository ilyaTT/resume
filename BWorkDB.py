# -*- coding: utf-8 -*-

import sqlite3

class DB(object):
    
    """ Словарь указателей на базы """
    hand = {}
    
    def __init__(self, path):
        """
            @path - путь к базе
            -> объект базы данных
        """ 
        
        """ Сохрагняем путь к бд """
        self.path = path
        
        """ Если эта бд еще не была инициализирована - инициализируем ее """
        if path not in DB.hand:                         
            DB.hand[path] = {
                'db': sqlite3.connect(path, timeout = 10, isolation_level='IMMEDIATE'),
                'count':1
            }            
        else:
            """ Увеличиваем кол-во ссылок на эту бд """
            DB.hand[path]['count'] += 1
            
        """ Получаем ссылку на бд """
        self.db = DB.hand[path]['db']


    def create(self, table, fields=False): 
        """
            @table - имя таблицы
            @fields - итерируемый объект названий и параметров полей таблицы
            
            -> void
        """        
        if not fields: return False
        
        with self.db: 
            self.db.execute('CREATE TABLE IF NOT EXISTS `{table}` (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, {fields})'.format(table=str(table), fields=', '.join(fields)))        
       
        
    def insert(self, table, fields=False, values=False, ignore=''): 
        """
            @table - имя таблицы
            @fields - итерируемый объект названий полей таблицы
            @values - список итерируемых значений вставки
            @ignore - значение игнорирования дублирующихся значений при вставке 
            
            -> количество вставленных элементов
        """
        if not fields or not values: return False

        cursor = self.db.cursor()
        
        cursor.executemany("INSERT {ignore} INTO `{table}` ({fields}) VALUES ({values})"\
                           .format(ignore=ignore, table=str(table), fields=','.join(fields), values=('?,'*len(fields))[:-1]), values)
        self.db.commit()     
        return cursor.rowcount 

    
    def delete(self, table, where=''):
        """
            @table - имя таблицы
            @where - условие удаления
            
            -> количество удаленных элементов
        """
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM `{table}` {where}".format(table=str(table), where=where))
        self.db.commit()     
        return cursor.rowcount 
    
    
    def select(self, table, fields=('*',), where='', isOne=False, distinct=False):
        """
            @table - имя таблицы
            @fields - итерируемый объект названий полей таблицы
            @where - условие выборки
            @isOne - флаг для уточнения единичности выборки. При поднятом возвращается именование параметры 
            
            -> результат выборки
        """
        distinct = ' DISTINCT ' if distinct else ''
        isOne = ' LIMIT 1 ' if isOne else ''
        cursor = self.db.cursor()
  
        cursor.execute("SELECT {distinct} {fields} FROM `{table}` {where} {isOne}".format(fields=','.join(fields), table=str(table), where=where, isOne=isOne, distinct=distinct))
        if isOne:
            """ Если выставлен флаг единичности выборки - создаем словарь, именованный полями """
            result = cursor.fetchone()
            result = {descr[0]:result[i] for i, descr in enumerate(cursor.description)} if result else {}
        else:
            result = cursor.fetchall()
            """ Если к выборке ожидается одно поле - преобразовываем выдачу """
            if len(fields) == 1 and '*' not in fields:
                result = [n[0] for n in result]
        
        return result
    
    
    def update(self, table, fields={}, where=''):
        """
            @table - имя таблицы
            @fields - словарь обновляемых полей и их значений
            @where - условие выборки
            
            -> количество обновленных элементов
        """
        if not fields: return False
        cursor = self.db.cursor()    
        
        fields = fields.items()
        
        cursor.execute("UPDATE `{table}` SET {fields} {where}".format(table=str(table), fields=','.join(['%s=?' % x for x, _ in fields]), where=where), tuple(y for _, y in fields))                
        self.db.commit()     
        return cursor.rowcount 
    
    def truncate(self, table):
        """
            @table - имя таблицы
            
            Очищает таблицу и скидывает автоинкремент 
        """
        self.delete(table)        
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='{table}'".format(table=str(table)))
        self.db.commit()     
    
    
    def close(self):
        """
            Закрывает сеанс работы с бд
        """
        """ Уменьшаем счетчик ссылок """
        DB.hand[self.path]['count'] -= 1
        
        """ Если ссылок больше нет - закрываем базу и удаляем кэш """
        if DB.hand[self.path]['count'] == 0:        
            self.db.close()
            del(DB.hand[self.path])


    def size(self, table):
        """
            @table - имя таблицы
            
            Выводит кол-во всех записей в таблице
        """
        result = self.select(table, fields=('id',), where='ORDER BY id DESC', isOne=True)
        
        if result:
            return result['id']
        else:
            return 0



class Init(DB):
    """ Класс является интерфейсом к базе банных проекта """

    def __init__(self, folder):
        DB.__init__(self, folder + '/project.bs')

