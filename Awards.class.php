<?php
/**
 * Created by JetBrains PhpStorm.
 * Author: Ilya_TT (ilya.tt07@gmail.com)
 * Date: 14.05.13
 * Time: 14:30
 */

class Awards extends UsersClass{

	protected $history_fields = array(
		'date'=>'Дата',
		'moderator'=>'Модератор',
		'str1'=>'Ник',
		'str2'=>'Login',
		'str4'=>'Тип награды',
		'str5'=>'Значение'
	);

    // метод выода длительности в днях
    private function duration($val){
        // проверка на неограниченность
        if($val == 333333333){
            return 'Не ограничено';
        }
        // получаем кол-во дней
        $days = $val / 86400;

        // находим постфикс
        if($days == 1) $days .= ' день';
        elseif($days == 2 || $days == 3 || $days == 4) $days .= ' дня';
        else  $days .= ' дней';

        return $days;
    }

    // периоды премиум акков
    public function getPremPeriods() {
        $rows = array();
        foreach($this->ctx->replicaGame->All("SELECT spa_premium_account_duration AS dur FROM ShopPremiumAccount ORDER BY dur") as $row){
            $rows[$row['dur']] = $this->duration($row['dur']);
        }
        return $rows;
    }

    // список имен скинов
    public function getCarSkins() {
        $rows = array();
        foreach($this->ctx->replicaGame->All("
        	SELECT cs_id, L1.loc_ru_ru AS got_name, L2.loc_ru_ru AS cs_name FROM CarSkin
        	LEFT JOIN GOType
        		ON got_id = cs_ct_id
        	LEFT JOIN Localization AS L1
        		ON L1.loc_id = got_locale_name_id
        	LEFT JOIN Localization AS L2
        		ON L2.loc_id = cs_locale_name_id
        	WHERE cs_type != 'DEFAULT' AND cs_type != 'DEATH' ORDER BY got_name, cs_name
        ") as $row){
            $rows[$row['cs_id']] =  $row['got_name'].' - '.$row['cs_name'];
        }
        return $rows;
    }

    // список периодов скинов
    public function getCarSkinPeriods() {
        $rows = array();
        foreach($this->ctx->replicaGame->All("SELECT csp_period_in_seconds AS dur FROM CarSkinPeriod ORDER BY dur") as $row){
            $rows[$row['dur']] = $this->duration($row['dur']);
        }
        return $rows;
    }

    // список машин
    public function getCars() {
        $rows = array();
        foreach($this->ctx->replicaGame->All("
        	SELECT ct_got_id, L1.loc_ru_ru AS got_name FROM CarType
        	LEFT JOIN GOType
        		ON got_id = ct_got_id
        	LEFT JOIN Localization AS L1
        		ON L1.loc_id = got_locale_name_id
        	WHERE ct_is_premium = 1 ORDER BY got_name
        ") as $row){
            $rows[$row['ct_got_id']] = $row['got_name'];
        }
        return $rows;
    }

    // список периодов машин
    public function getCarPeriods() {
        $rows = array();
        foreach($this->ctx->replicaGame->All("SELECT DISTINCT src_duration_seconds AS dur FROM ShopRentCar ORDER BY dur") as $row){
            $rows[$row['dur']] = $this->duration($row['dur']);
        }
        return $rows;
    }

    // список айтемов
    public function getItems() {
        $rows = array();
        // расходники
        foreach($this->ctx->replicaGame->All("
        	SELECT got_id,  L1.loc_ru_ru AS got_name FROM BaseEquipmentType
        	LEFT JOIN GOType
        		ON got_id = bet_got_id
        	LEFT JOIN Localization AS L1
        		ON L1.loc_id = got_locale_name_id
        	ORDER BY got_name
        ") as $row){
            $rows[$row['got_id']] = $row['got_name'];
        }
        return $rows;
    }


    private function _updateMoney($user, $gold, $money) {

	$amount = $gold ? $gold/10 : $money/150;

        // начинаем транзакцию
        $this->ctx->mwo->StartTrans();

        // пишем платеж в базу сайта
		$pid = $this->ctx->mwo->Insert("
            INSERT INTO game_pay_stat (
                typeId, amount, gold, money, timeStart, timeFinish, login, loginType, stat, info, sysId, currency, statusStr, statusCode
            )
             (
                 SELECT
                    id, :amount, :gold, :money, :time, :time, :login, :loginType, 3, '', 0, cur, 'BUY_GOLD_FINISH', 'SUCCESS'
                 FROM
                    game_payment
                 WHERE
                    code = 'AWARD'
             )
        ", array(
			':amount'=>$amount,
			':gold'=>$gold,
			':money'=>$money,
			':time'=>time(),
			':login'=>$user['u_login'],
			':loginType'=>$user['u_login_type']
		));

        // id платежа
        if(!$pid){
            // откатываем транзакцию
            $this->ctx->mwo->RollbackTrans();
            throw new Exception("Ошибка записи в локальную базу!");
        }

        try{
            // обновляем серебро/голду
            $response = $this->ctx->soapInfo->updateMoneyGold((object)array(
                'arg0'=>$user['u_login'],
                'arg1'=>$user['u_login_type'],
                'arg2'=>$money * 100,
                'arg3'=>$gold * 100,
                'arg4'=>$pid,
                'arg5'=>101
            ))->return;

            if($response->result != 'SUCCESS'){
                // откатываем транзакцию
				$this->ctx->mwo->RollbackTrans();
                throw new Exception("Ошибка удаленного сервера!");
            }

        }catch(Exception $e){
            // откатываем транзакцию
			$this->ctx->mwo->RollbackTrans();
            throw $e;
        }

        // завершаем транзакцию
		$this->ctx->mwo->EndTrans();
    }


    public function action($type, $user, $params) {
		// текстовой результат запроса
		$result = '';

        // типы наград
        switch($type){

            case 'new_nick':
                // обрабатываем изменение ника
                if(!($new_nick = $params['new_nick'])){
                    throw new Exception("Не указан новый ник");
                }

                // проверим на дубль
                if($this->users($new_nick, UsersClass::FIND_EQ | UsersClass::FIND_BY_NAME | UsersClass::FIND_IN_LOGIN) || $this->users($new_nick, UsersClass::FIND_EQ | UsersClass::FIND_BY_NAME | UsersClass::FIND_IN_GAME)){
                    throw new Exception("Юзер с таким ником уже существует");
                }

                // выполняем смену ника TODO: обработать $response
                if($response = $this->ctx->soapInfo->changeUserName((object)array(
                    'arg0'=>$user['u_id'],
                    'arg1'=>$new_nick
                ))->return){
					//file_put_contents('error-changeUserName-soapInfo', print_r($response, true), FILE_APPEND);
                    throw new Exception("Ошибка изменения ника");
                };

				$result = $new_nick;

                break;

            case 'gold':
                // обрабатываем начисление голды
                if(!($gold = $params['gold'])){
                    throw new Exception("Не указано кол-во голды");
                }
                // начисляем голду
                $this->_updateMoney($user, $gold, 0);

				$result = $gold;

                break;

            case 'money':
                // обрабатываем начисление голды
                if(!($money = $params['money'])){
                    throw new Exception("Не указано кол-во серебра");
                }
                // начисляем голду
                $this->_updateMoney($user, 0, $money);

				$result = $money;

                break;

            case 'premium':
                // обрабатываем начисление премиума
                if(!($duration = $params['premium_duration'])){
                    throw new Exception("Не указана длительность премиум-аккаунта");
                }

                // собственно накидываем премиум
                $response = $this->ctx->soapInfo->updatePremiumAccount((object)array(
                    'arg0'=>$user['u_id'],
                    'arg1'=>$duration,
                    'arg2'=>$this->moderator
                ));

				$result = $this->duration($duration);

                break;

            case 'skin':
                // обрабатываем выставление скина
                if(!($skinId = $params['car_skin_id']) || !($duration = $params['car_skin_duration'])){
                    throw new Exception("Не указаны данные для скина");
                }

                // получаем скин
                if(!($skin = $this->ctx->replicaGame->One("
					SELECT cs_id, L1.loc_ru_ru AS got_name, L2.loc_ru_ru AS cs_name FROM CarSkin
					LEFT JOIN GOType
						ON got_id = cs_ct_id
					LEFT JOIN Localization AS L1
						ON L1.loc_id = got_locale_name_id
					LEFT JOIN Localization AS L2
						ON L2.loc_id = cs_locale_name_id
					WHERE cs_id = ?
                ", array($skinId)))){
                    throw new Exception("Не найден скин");
                }

                // собственно накидываем премиум
                $this->ctx->soapInfo->updateCarSkin((object)array(
                    'arg0'=>$user['u_id'],
                    'arg1'=>$skin['cs_id'],
                    'arg2'=>$duration,
                    'arg3'=>$this->moderator
                ));

                // инфа для логинга
				$result = $skin['got_name'].' - '.$skin['cs_name'].' ('.$this->duration($duration).')';

                break;

            case 'car':
                // обрабатываем выставление скина
                if(!($carId = $params['car_id']) || !($duration = $params['car_duration'])){
                    throw new Exception("Не указаны данные для машины");
                }

                // получаем машину
                if(!($car = $this->ctx->replicaGame->One("SELECT * FROM GOType LEFT JOIN Localization AS L1 ON L1.loc_id = got_locale_name_id WHERE got_id = ?", array($carId)))){
                    throw new Exception("Не найдена машина");
                }

                // собственно накидываем машину
                $this->ctx->soapInfo->updateCar((object)array(
                    'arg0'=>$user['u_id'],
                    'arg1'=>$carId,
                    'arg2'=>$duration,
                    'arg3'=>$this->moderator
                ));

                // инфа для логинга
				$result = $car['loc_ru_ru'].' ('.$this->duration($duration).')';

                break;

            case 'item':
                // обрабатываем начисление айтема
                if(!($itemId = $params['item_id']) || !($count = $params['item_count'])){
                    throw new Exception("Не указаны данные для айтема");
                }

                // получаем айтем
                if(!($item = $this->ctx->replicaGame->One(" SELECT * FROM BaseEquipmentType LEFT JOIN GOType ON bet_got_id = got_id  LEFT JOIN Localization AS L1 ON L1.loc_id = got_locale_name_id WHERE got_id = ?", array($itemId)))){
                    throw new Exception("Не найден айтем");
                }

                // собственно накидываем айтем
                $this->ctx->soapInfo->changeDepotItemCount((object)array(
                    'arg0'=>$user['u_id'],
                    'arg1'=>$itemId,
                    'arg2'=>$count,
                    'arg3'=>$this->moderator
                ));

                // инфа для логинга
				$result = $item['loc_ru_ru'].' ('.$count.')';

                break;
        }

		// запишем действие
		$lid = $this->ctx->mwo->InsertArray('moderators_history', array(
			'moderator'=>$this->moderator,
			'section'=>get_class($this),
			'str1'=>$user['u_name'],
			'str2'=>$user['u_login'],
			'str3'=>bin2hex($user['u_uuid']),
			'str4'=>$type,
			'str5'=>$result
		));

        // извлечем лог - для вывода в браузер
		$info = $this->ctx->mwo->One("SELECT * FROM moderators_history WHERE id = ?", array($lid));

        // преобразовываем лог для корректного разбора на стороне js
        $response = array();
        foreach(array_keys($this->history_fields) as $colum){
            $response[] = array(
                'colum'=>$colum,
                'val'=>$info[$colum]
            );
        }

        // вернем лог, как подтверждение
        return $response;
    }

	// получаем юзера по uuid
	public function userInfo($user) {
		// получаем общие данные о юзере
		$response = parent::userInfo($user);

		// данные о финансовом состоянии
		$fields = array(
			'u_money' => 'Серебро',
			'u_gold' => 'Золото',
			'u_premium_expires_in' => 'Вип истекает',
		);

		foreach($fields as $colum=>$name){
			if(in_array($colum, array('u_money', 'u_gold'))){
				$response[$name] = $user->field($colum) / 100;
			}
			else{
				$response[$name] = $user->field($colum);
			}
		}

		return $response;
	}

	// вернет имя раздела
	public function getTitle(){
		return "Выдача наград";
	}

}
