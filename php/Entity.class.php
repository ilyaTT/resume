<?php

/*
 * EXAMPLE! 
 * Файл содержит урезанную версию класса для демонстрации общего стиля кода
 * 
 * Пример реализации контроллера
 *
 * */

/**
 * Created by JetBrains PhpStorm.
 * Author: Ilya_TT (ilya.tt07@gmail.com)
 * Date: 21.09.13
 * Time: 5:59
 */

namespace Controllers;

use \Boot\Globs;

Globs::ImportController('GameServers');


abstract class Entity extends GameServers {

    public function _Process(){

        // объект сущности
        $entity = $this->Modeling('Entities/'.Globs::GetClass($this));

        // объект представления
        $view = $this->Viewer('Entity');

        // опредлим тип вложенности (фактически - окна, в котором откроется список элементов)
        $view->typeWindow = Globs::VarData('w');

        // тип действия
        $action = Globs::VarData('action');

        // если это сохранение данных
        if(in_array($action, array('create', 'update'))){
            // для сохранения будут переданы только предназначенные для этого данные
            $data = array();
            foreach(Globs::VarData() as $k=>$d){
                if(substr_count($k, '_')){
                    $data[$k] = $d;
                }
            }

            // id сохраняемого элемента
            $id = $action == 'create' ? NULL : Globs::VarData('id');

            // стартуем транзакцию
            $entity->db->StartTrans();

            // выполняем все запросы
            try {
                // пробуем выполнить сохранение
                $entity->Save($id, $data, Globs::VarData('rootId'));
                // если запросы выполнились успешно - комиттим их
                $entity->db->EndTrans();
            }
            catch(\Exception $e) {
                // откатываем транзакции
                $entity->db->RollbackTrans();
                // сохраняем глобальную ошибку
                Globs::$error = $e->getMessage();
            }

            /* результат обработки сохранения в любом случае передается через ajax */

            // если возникла ошибка - отображаем ее и предзаполняем поля уже введенными данными
            if(Globs::$error){
                exit(json_encode(array('error'=>Globs::$error)));
            }
            // если в ходе сохранения не возникло ошибок - выполняем запрошенное действие (пока редирект переданный урл)
            else{
                exit(json_encode(array('location'=>$_SERVER['REQUEST_URI'])));
            }
        }


        // если это запрос на удаление
        if($action == 'remove'){
            // стартуем транзакцию
            $entity->db->StartTrans();

            // выполняем все запросы
            try {
                // пробуем выполнить сохранение
                $entity->Remove(Globs::VarData('id'));
                // если запросы выполнились успешно - комиттим их
                $entity->db->EndTrans();
            }
            catch(\Exception $e) {
                // откатываем транзакции
                $entity->db->RollbackTrans();
                // сохраняем глобальную ошибку
                Globs::$error = $e->getMessage();
            }

            /* результат обработки удаления в любом случае передается через ajax */

            // если возникла ошибка - отображаем ее и предзаполняем поля уже введенными данными
            if(Globs::$error){
                exit(json_encode(array('error'=>Globs::$error)));
            }
            // если в ходе сохранения не возникло ошибок - выполняем запрошенное действие (пока редирект переданный урл)
            else{
                exit(json_encode(array('location'=>$_SERVER['REQUEST_URI'])));
            }
        }

        if($action == 'xml'){
            // выполняем перегенерацию xml
            $entity->db->XML();
            exit(json_encode(array('location'=>$_SERVER['REQUEST_URI'])));
        }


        // передаем в представление данные
        switch($action){

            case 'blank':
                // передаем в представление структуру сущности
                $view->Edit($entity->GetMeta(), array(), NULL, $entity->baseType);
                break;

            case 'edit':
                // передаем в представление структуру сущности
                $id = Globs::VarData('id');
                $view->Edit($entity->GetById($id), array(), $id, $entity->baseType);
                break;

            // передаем в представление структуру сущности
            case 'all':
            default:
                // если тип выборки не обозначен - получаем все
                if(!$view->typeWindow){
                    $items = $entity->GetAll();
                }
                // если он ограничен - производим выборку по ограничивающему кастомному запросу
                else{
                    $items = $entity->DependAll(Globs::VarData());
                }

                // проверим возможность редактирования данного класса
                $fWrite = !($entity instanceof \Models\Depend) || ($entity->flags & F_WRITE);

                // производим рендеринг списка элементов
                $view->All($items, $entity->GetMeta(), $fWrite);
                break;
        }

        // вернем объект представления
        return $view;
    }
}