$.widget("bs.BStaticBlock", {

    // словарь кнопок
    buttons: {},

    _create: function() {
        // скрываем клнтекстное меню при создании
        this.element.css('display', 'none')
    },

    addButton: function(button) {
        this.buttons.push(button)
    },

    removeButton: function(id) {

        for(var i = 0, j =- 1; i < this.buttons.length; i++){
            if(this.buttons[i]['id'] == id){
                j = i;
                break;
            }
        }
        if(j > -1)
            this.buttons.splice(j, 1)
    },

    build: function() {
        // находим ширину кнопки на основании ширины блока кнопок
        var wButton = (($('#fixed').width() - $('#fixed-title').outerWidth(true)) / this.options.buttons.length) - 10,
            button, elem, k

        wButton = parseInt(wButton <= 200 ? wButton : 200);

        this.element.css('display', 'block').empty()
        for(k=0; k<this.options.buttons.length; k++){
            button = this.options.buttons[k]

            elem = $('<li></li>').css('width', wButton)
                .append($('<a></a>',{'id':button['id'], 'class':button['class'], 'title': button.text, 'text':button.text}))
                // установим кастомный обработчик
                .data('call', button.onclick)
                .click(function(e){
                    // вызываем кастомный обработчик, а затем останавливаем стандартные события клика
                    $(this).data('call')(e);
                    e.stopPropagation();
                    return false;
                });

            this.element.append(elem)
        }
        // высота фиксированного блока изменилась
        $('#fixed').BFixedBlock('reHeight')
    },

    clear: function() {
        this.options.buttons = []
        this.element.css('display', 'none').empty()
        // высота фиксированного блока изменилась
        $('#fixed').BFixedBlock('reHeight')
    }
});
