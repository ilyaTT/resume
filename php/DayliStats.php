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
 * Date: 14.01.15
 * Time: 16:23
 */

namespace app\models;

use app\models\BaseRemote;

class DayliStats extends BaseRemote{

	// сохраненный ресурс запроса
	private static $dayli_query = null;

	/*
	 * Методы-агрегаторы определенных данных
	 * */

	public static function dayliDefaultData($param){
		return self::_dayliArray( self::_dayliQuery()->select('Date, '.$param)->all() );
	}

	// метод извлекает данные, как обычные массивы
	private static function _dayliArray(array $array){
		// собираем словарь данных относительно даты
		$result = array();
		$start = reset($array[0]);
		$end = reset($array[sizeof($array)-1]);

		foreach($array as $row){
			$result[reset($row)] = end($row);
		}

		// создаем массив заглушек для дат без данных
		$cap = range($start, $end, 86400);
		$cap = array_combine($cap, array_fill(0, sizeof($cap), 0));

		return array_values(array_replace($cap, $result));
	}

	// метод подготовки стандартного запроса к дейлику
	private static function _dayliQuery(){
		// если подготовленного запроса нет - готовим его
		if(!self::$dayli_query){
			self::$dayli_query = self::find()
				->andWhere(['>=', 'Date', parent::getFilter('from') ])
				->andWhere(['<=', 'Date', parent::getFilter('to') ])
				->andWhere(['DeviceType' => parent::getFilter('device')])
				->andWhere(['CountryID' => parent::getFilter('country')])
				->andWhere(['SourceID' => parent::getFilter('source')])
				->andWhere(['CampaignID' => parent::getFilter('campaign')])
				->andWhere(['SubCampaignID' => parent::getFilter('subcampaign')])
				->orderBy('Date ASC')
				->asArray();
		}

		return self::$dayli_query;
	}

	// переопределяем имя таблицы
	public static function tableName(){
		return 'local_stat_schema.daily_stats';
	}

}