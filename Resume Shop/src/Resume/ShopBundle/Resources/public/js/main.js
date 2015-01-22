/**
 * Created with JetBrains PhpStorm.
 * User: admin
 * Date: 21.01.15
 * Time: 22:58
 * To change this template use File | Settings | File Templates.
 */


$(function() {

    JsonAjax = function(url){
        History.pushState(null, document.title, url);
    }

    History.Adapter.bind(window, 'statechange', function(e){
        // затеняем окно
        $('#loading').modal('show')

        // убираем текущие активные фильтры
        $('li', $('.sidebar')).removeClass('active')

        // собственно запрос
        $.ajax({
            url: History.getState().url,
            type : "GET",
            cache: false,
            dataType: 'json',
            complete: function(){
                $('#loading').modal('hide')
            },
            success: function(data){
                // редактируем страницу на основании пришедших данных
                $('.content').html(data['content'])
                $('title').html(data['title'])
                $('#search-form input[name="search"]').val(data['search'])
                // навешиваем метки на активные фильтры
                for(var filter in data['actives_id']){
                    $('#'+filter+'_'+data['actives_id'][filter]).addClass('active')
                }
            }
        });
    });

    // обработка ссылок
    $('.container').on('click', 'a', function(){
        JsonAjax($(this).attr('href'));
        return false;
    });

    // обработка поиска
    $('#search-form').on('submit', function(){
        JsonAjax('?search='+$('#search-form input[name="search"]').val()+'&_r='+Math.random());
        return false;
    });

});