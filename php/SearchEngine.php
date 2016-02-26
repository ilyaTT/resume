<?php

/*
 * EXAMPLE! 
 * Файл содержит урезанную версию класса для демонстрации общего стиля кода
 * 
 * Пример реализации фильтра Sphinx
 *
 * */

defined("SYSPATH") or die;

class Model_SearchEngine extends Model {

    public function __construct($search_str, $_cat, $age=false, $gender=false) {
        $this->base_cat = $_cat;

        $all_cats = ORM::factory("Category")->get_categories();
        $index    = new Helper_RecursiveCatIndex($all_cats);

		// установим пол и возраст
		$this->age = $age;
		$this->gender = $gender;

        if ($_cat != 0) {
            $this->active_cat_ids = $index->get_children_ids($_cat);
        }

        // конфиг сфинкса
        $s_conf = Kohana::$config->load('sphinx');

		// чистим поисковой запрос
		$search_str = str_replace(str_split('#?*/'), ' ', $search_str);
		$this->src_str = trim(str_replace('!', '\!', $search_str));

		// если он пуст - кидаем соответствующее исключение
		if(!$this->src_str && !$_cat){
			throw new Exception('Request is empty!');
		}

        // создаем подключение к сфинксу
        $this->sphinx = $s = new SphinxClient();
        $s->SetServer($s_conf->get('host'), $s_conf->get('port'));
        $s->SetMatchMode(SPH_MATCH_EXTENDED2);
        $s->SetRankingMode(SPH_RANK_PROXIMITY_BM25);
    }

	/*
	 * метод применяет основные фильтры.
	 * */
	public function commonFilter($exclude='') {
		// сбрасываем предыдущие фильры и группировки
		$this->sphinx->resetFilters();
		$this->sphinx->resetGroupBy();
		// в любом случае ограничиваем выборку текущей категорией, если она есть
		if($this->active_cat_ids){
			$this->sphinx->SetFilter('category_id', $this->active_cat_ids);
		}
		// категория товара не должна быть 0
		$this->sphinx->SetFilter('category_id', array(0), true);
		// статус оффера должен быть активным
		$this->sphinx->SetFilter('offer_status', array(1));
		// статус товара должен быть активен
		$this->sphinx->SetFilter('enable', array(1));

		// пол
		if($this->age){
			$this->sphinx->SetFilter('age', array($this->age));
		}
		// возраст
		if($this->gender){
			$this->sphinx->SetFilter('gender', array($this->gender));
		}

		// применяем фильтры
		$filters = Session::instance()->get("filters", array ());

		// удаляем указанный фильтр
		if($exclude){
			unset($filters[$exclude]);
		}

		// работаем с фильтром цвета
		if(@$filters['color']){
			// собираем словарь цветов
			$colors_dict = array();
			foreach(DB::select()->from("color_dictionary")->as_object()->execute() as $row){
				$colors_dict[$row->name] = $row->id;
			}
			// собираем список фильтра
			$colors_filters = array();
			foreach ($filters["color"] as $color) {
				$colors_filters[] = $colors_dict[$color];
			}
			// применяем фильтр
			$this->sphinx->SetFilter('color', $colors_filters);
		}

		// работаем с фильтром сезона
		if(@$filters['season']){
			// собираем словарь сезонов
			$seasons_dict = array();
			foreach(DB::select()->from("season_dictionary")->as_object()->execute() as $row){
				$seasons_dict[$row->name] = $row->id;
			}

			// собираем список фильтра
			$seasons_filters = array();
			foreach ($filters["season"] as $season) {
				$seasons_filters[] = $seasons_dict[$season];
			}
			// применяем фильтр
			$this->sphinx->SetFilter('season', $seasons_filters);
		}

		// работа с брендами
		if(@$filters['vendor']){
			$this->sphinx->SetFilter('vendor_id', $filters["vendor"]->ids);
		}

		// работа с офферами
		if(@$filters['offer']){
			$this->sphinx->SetFilter('offer_id', $filters["offer"]->ids);
		}

		// работа с ценой
		if(@$filters['price']){
			$this->sphinx->SetFilterRange('price', $filters["price"]->min, $filters["price"]->max);
		}

		// работа со скидками
		if(@$filters['discount']){
			$this->sphinx->SetFilterRange('discount', $filters["discount"]->min, $filters["discount"]->max);
		}

	}
}
