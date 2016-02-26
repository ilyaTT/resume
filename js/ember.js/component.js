import Ember from 'ember';
import EmberValidations from 'ember-validations';

export default Ember.Component.extend(EmberValidations.Mixin, {

  // заполняемый объект для EmberValidations.Mixin
  validations: {},

  // заполняемый объект для реализации функционала удаленной валлидации
  loadeds: {},

  // передаваемый извне объект опций настроек каждого поля
  inputs: [],

  // навешивание ошибки на поле
  _errorChange: function(self){
    Ember.set(this, 'error', self.errors[this.name][0]);
  },

  // обработка изменения promise
  _promiseChange: function(input){
    // получаем promise
    var promise = this.get('loadeds.'+input.name);
    // реагируем только если promise активен
    if(Ember.typeOf(promise) === 'object'){
      // активируем спинер
      Ember.set(input, 'loaded', true);
      // после завершения (любого) глушим спинер
      promise.promise.finally(function () {
        Ember.set(input, 'loaded', false);
      });
    }
  },

  // остановка активного promise
  _promiseAbort: function(input){
    var promise = this.get('loadeds.'+input.name);
    if (Ember.typeOf(promise) === 'object') {
      promise.ajax.abort();
    }
  },

  // вспомогательный метод для перебора значений полей и манипупяций с ними
  _iterItemValues: function(callback){
    var values = {};
    this.beginPropertyChanges();
    this.inputs.forEach(function (input) {
      // если передан калбэк - вызовем его
      if(callback !== undefined){
        callback.call(this, input);
      }
      // если в поле установлено значение - активируем поле
      if(input.value){
        Ember.set(input, 'activate', true);
      }
      // выставляем значение
      this.set(input.name, input.value);
      // собираем значения полей
      values[input.name] = input.value;
    }, this);
    this.endPropertyChanges();
    return values;
  },

  // блокировка полей
  _inputsDisable: function(){
    this.inputs.forEach(function(input) {
      // лочим все поля - на время отправки формы редактирование будет запрещено
      Ember.setProperties(input, {
        disabled: true,
        activate: false,
        error: null
      });
      // если на поле повешено promise - стопаем его
      this._promiseAbort(input);
    }, this);
  },

  // разблокировка полей
  _inputsEnable: function(){
    this.inputs.forEach(function(input) {
      // разлочиваем все поля
      Ember.setProperties(input, {
        disabled: false,
        activate: true
      });
    }, this);
  },

  // деактивация полей в случае глобальной ошибки
  _inputsDeactive: function(){
    this.inputs.forEach(function(input) {
      Ember.setProperties(input, {
        disabled: false,
        activate: false
      });
    }, this);
  },

  // установка ошибок напрямую на глобальный объект
  setGlobalErrors: function (errors) {
    this.beginPropertyChanges();
    for(var name in errors){
      if(Ember.isArray(errors[name])){
        this.set('errors.'+name, errors[name]);
      }
    }
    this.endPropertyChanges();
  },

  // своя проверка на валлидность (т.к. либовская опирается на ошибки каждого отдельного валлидатора)
  isInvalidate: function () {
    if(this.inputs.every(function (input) {
        return this.get('errors.'+input.name).length === 0;
      }, this)) {
      return false;
    }
    return true;
  },

  init: function(){
    // первичный проход по полям
    this._iterItemValues(function (input) {
      // собираем валлидаторы
      this.set('validations.'+input.name, input.validations);
    });

    // запускаем логику EmberValidations
    this._super();

    // после всех инициализаций выполняем подписки:
    this.inputs.forEach(function(input) {
      // подписываемся на изменение ошибок полей - за итерацию цикла значение ошибки меняем единожды
      this.addObserver('errors.'+input.name, this, function() {
        Ember.run.once(input, this._errorChange, this);
      });

      // подписываемся на изменение состояний удаленных валлидаторов
      this.addObserver('loadeds.'+input.name, this, function() {
        this._promiseChange(input);
      });
    }, this);
  },

  actions: {

    validStart: function(input){
      // поле активируется
      Ember.set(input, 'activate', true);
      // используется доп. уведомление для того, что бы точно вызвать валлидатор, даже если явно значение не поменялось
      this.set(input.name, input.value).notifyPropertyChange(input.name);
    },

    validStop: function(input){
      // все текущие ошибки удаляются с поля
      this.set('errors.'+input.name, Ember.A());
      // если на поле повешено promise - стопаем его
      this._promiseAbort(input);
    },

    // событие явной отправки формы
    submitBegin: function () {
      // получаем текущие значения полей
      var values = this._iterItemValues(function (input) {
        Ember.set(input, 'activate', true);
      });
      // фактичеки - обеспечение функционала клиентской валлидации при отправке формы
      if(this.isInvalidate()){
        return;
      }
      // поднимаем флаг
      this.set('isLoading', true);
      // блокируем все поля
      this._inputsDisable();
      // отправляем запрос
      this.sendAction('action', values, this);
    },

    submitProcess: function(promise){
      var self = this;
      promise.then(function () {
        // все ок - активируе поля
        self._inputsEnable();
      }).catch(function (reason) {
        if(Ember.typeOf(reason) === 'error'){
          // навешивание глобальных ошибок
          self.setGlobalErrors(reason.errors);
          // ошибки стандартные - активируем поля
          self._inputsEnable();
        }
        else{
          // если ошибка не валлидационная - логгируем ее в консоль
          Ember.Logger.error(reason);
          // все плохо, деактивируем все поля
          self._inputsDeactive();
        }
      }).finally(function () {
        // загрузка завершена, опускаем флаг
        self.set('isLoading', null);
      });
    }
  }

});



