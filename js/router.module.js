/**
 * Created by admin on 21.11.2016.
 */

var Router = (new function(){

    var self = this;

    // изначально старой версией урла будет урл загрузки страницы
    var last = new URI();
    // текущий урл изначально - урл загрузки страницы
    var now = new URI();
    // изменился ли контекст работы страницы
    var is_change_ctx = false;
    // добавленные параметры
    var search_delta_add = {};
    // удаленные параметры
    var search_delta_remove = {};
    // измененнные параметры
    var search_delta = {};
    // текущий запрос
    var request;

    // проверка на изменение контекста
    var isChangeCtx = function () {
        // получим части пути без страницы
        var segments_now = now.segment();
        if(_.isNumber(_.last(segments_now))){
            segments_now = segments_now.slice(0, -1);
        }
        var segments_last = last.segment();
        if(_.isNumber(_.last(segments_last))){
            segments_last = segments_last.slice(0, -1);
        }

        // если сегменты не совпадают - контекст изменен
        is_change_ctx = !_(segments_now).isEqual(segments_last);
    };

    // дельта запроса
    var searchDelta = function () {
        // получим запрос
        var search_now = now.search(true);
        var search_last = last.search(true);

        // обнуляем накапливаемые параметры
        search_delta_add = {};
        search_delta_remove = {};
        search_delta = {};

        // находим измененные параметры
        _.each(_.union(_.keys(search_now), _.keys(search_last)), function(slug) {
            // получим значения текущего запроса
            var vals_now = search_now[slug] || [];
            vals_now = _.isArray(vals_now) ? vals_now : [vals_now];

            // получаем значения предыдущего урла
            var vals_last = search_last[slug] || [];
            vals_last = _.isArray(vals_last) ? vals_last : [vals_last];

            // находим добавленные, удаленные, измененные значения
            search_delta_add[slug] = _.difference(vals_now, vals_last);
            search_delta_remove[slug] = _.difference(vals_last, vals_now);
            search_delta[slug] = _.union(search_delta_add[slug], search_delta_remove[slug]);
        });
    };

    // навешивает спиннер
    var spinnerOpen = function(selector){
        // элемент для накрытия спиннером
        var elem = $(selector);

        var width = elem.width();
        var height = elem.height();

        $('#loader').appendTo(selector).css({
            display: 'block',
            width: width,
            height: height
        });
    };

    //
    var spinnerClose = function(){
        $('#loader').hide();
    };

    // слушаем глобальное изменение урла
    History.Adapter.bind(window, 'statechange',function(e){
        var State = History.getState();

        // создаем новый объект урла
        now = new URI(State.url);

        // изменен ли контекст
        isChangeCtx();
        // дельта изменения запроса
        searchDelta();

        // в мета всегда передадим флаг изменения контекста
        var meta = is_change_ctx ? {is_change_ctx: true} : {};

        // если запрос был запущен - останавливаем его
        if(request){
            request.abort();
        }

        // создаем объект урла для запроса
        var url_request = now.clone();

        // создаем отложенное событие
        var dfd = $.Deferred();

        // отправляем событие формирования запроса
        $(window).triggerHandler('request_prepare', [dfd.promise(), meta, url_request]);

        // добавляем мета-инфу к запросу
        url_request.addSearch('_meta', $.param(meta, true));

        // в зависимости от измененности контекста накрываем лоадером разные блоки
        spinnerOpen(is_change_ctx ? '#content-collapse' : '#content-main');

        // выполняем запрос
        request = $.getJSON(url_request.toString()).done(function (data) {
            // перезаписываем блоки, ответ которых - строка
            _.each(data, function (val, key) {
                if(typeof val === 'string'){
                    $('#'+key).html(val);
                }
            });
            // передаем ответ в связанный Deferred
            dfd.resolve(data)
        }).fail(function(xhr, text_status, error_thrown) {
            if(text_status != 'abort'){
                console.error(text_status, error_thrown);
                alert('Произошла ошибка загрузки данных!');
            }
            // передаем ошибку в связанный Deferred
            dfd.reject(xhr, text_status, error_thrown)
        }).always(function(xhr, text_status, error_thrown) {
            spinnerClose();
            request = undefined;
        });

        // сохраняем урл как предыдущий
        last = now.clone();
    });

    // вернет текущий объект урла
    this.getNow = function () {
        return now;
    };

    // вернет предыдущий объект урла
    this.getLast = function () {
        return last;
    };

    // проверка на изменение контекста
    this.isChangeCtx = function () {
        return is_change_ctx;
    };

    // проверка на изменение строки запроса
    this.searchDelta = function (type) {
        switch(type){
            case 'add':
                return search_delta_add;
            case 'remove':
                return search_delta_remove;
            default:
                return search_delta
        }
    };

});
