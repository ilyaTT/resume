
import _ from "underscore"
import Vue from 'vue'
import urlRequest from "../utils/request";
import LookProductComponent from "../components-dynamic/chunks/look-product"


class Look {
    constructor(data) {
        this.id = data.id;
        this.idRead = data.id_read;
        this.isCreating = data.is_creating;
        this.name = data.name;
        this.description = data.description;
        this.photoMain = data.photo_main;
        this.isOwner = data.is_owner;
        this.parent = data.parent;
        this.author = data.user_name;
        this.dtUpdate = data.dt_update;
        this.urlDetail = data.url_detail;
        this.urlEdit = data.url_edit;
        this.products = _.map(data.products, p => new LookProduct(p));
        this.edited = data.edited;
    }
    update({name, description, photo_main, products}){
        if(name !== undefined){
            this.name = name;
        }
        if(description !== undefined){
            this.description = description;
        }
        if(photo_main !== undefined){
            this.photoMain = photo_main;
        }
        if(products !== undefined){
            this.products = _.map(products, p => new LookProduct(p));
        }
        this.setEdited();
    }
    productAdd(product){
        this.products.push(new LookProduct(product));
        this.setEdited();
    }
    productRemove(product){
        this.products.splice(this.products.indexOf(product), 1);
        this.setEdited();
    }
    serialize(){
        return {
            name: this.name,
            description: this.description,
        };
    }
    setEdited(){
        this.edited = true;
    }
}

class LookProduct {
    constructor(data) {
        this.id = data.id;
        this.lookId = data.look;
        this.order = data.order;
        this.pid = data.product_id;
        this.card = data.card;
        this.component = Object.assign({}, LookProductComponent, {template: data.card})
    }
}

// вспомогательная функция для установки мутаций загрузки для лука
const setChanging = (lookId) => {
    return {start: ['look/setChanging', {lookId, flag: true}], finish: ['look/setChanging', {lookId, flag: false}]}
};


export default {
    namespaced: true,
    modules: {
        edit: {
            namespaced: true,
            state: {
                look: null,
                productsRequest: {},
                isEditMode: false,
                changing: false,
            },
            getters: {
                products(state) {
                    // если нет активного лука - пропускаем
                    if(!state.look){
                        return {};
                    }
                    // собираем id-шники товаров, которые есть в текущем редактируемом луке
                    return _.object(_.map(state.look.products, p => {
                       return [p.pid, p]
                    }));
                },
                productsModeParam(state, getters, rootState, rootGetters){
                    return rootGetters['uri/getJsQuery'](rootState.conf.settings.lookProductsModeParam);
                },
                productsModeLook(state){
                    return state.isEditMode && state.look
                }
            },
            mutations: {
                set(state, look){
                    state.look = look;
                },
                update(state, data){
                    state.look.update(data);
                },
                productAdd(state, product){
                    state.look.productAdd(product);
                },
                productRemove(state, product){
                    state.look.productRemove(product);
                },
                setEditMode(state, flag){
                    state.isEditMode = flag;
                },
                setProductRequest(state, pId){
                    Vue.set(state.productsRequest, pId, true);
                },
                unsetProductRequest(state, pId){
                    Vue.delete(state.productsRequest, pId);
                },
                unsetEdited(state){
                    state.look.edited = false;
                },
                setChanging(state, flag){
                    state.changing = flag;
                },
            },
            actions: {
                // загрузка единственного лука
                async load({commit, state, rootState, dispatch, getters}, lookId){
                    // загружать лук не нужно, если он уже установлен
                    if(getters.productsModeLook){
                        return;
                    }
                    // запрашиваем образы соответствующей страницы, передаем флаг необходимости создания промежуточного объекта только тогда, когда не передан явный id промежуточного лука
                    let look = await urlRequest(`${rootState.conf.api.looks}/${lookId}`, 'get', {
                        params: !getters.productsModeParam ? {dummy_need: 1} : {}
                    }).response();
                    // установим лук
                    commit('set', new Look(look));
                },
                change({commit, dispatch, state, rootState}, data){
                    // именно с этого момента указываем, что данные были изменены
                    commit('setChanging', true);
                    // обновляем данные в реальном времени
                    commit('update', data);
                    // а обновление на сервере делаем асинхронно с задержкой
                    dispatch('changeAsync', data);
                },
                changeAsync: _.debounce(function({commit, state, rootState}, data){
                    // локальные данные больше не изменены
                    commit('setChanging', false);
                    // выполняем запрос на обновление данных лука
                    urlRequest(`${rootState.conf.api.looks}/${state.look.id}`, 'patch', {
                        data: state.look.serialize(),
                    }, setChanging(state.look.id)).response();
                }, 500),
                async photoCreate({commit, state, rootState}, photo){
                    // собираем запрос
                    let request = new FormData();
                    request.set('look', state.look.id);
                    request.append('photo_main', photo);
                    // выполняем запрос на сохранение фото
                    let data = await urlRequest(`${rootState.conf.api.lookPhotos}`, 'post', {
                        data: request,
                        headers: {'Content-Type': 'multipart/form-data'}
                    }, setChanging(state.look.id)).response();
                    // обновим фото
                    commit('update', {photo_main: data.photo_main});
                },
                async productAdd({commit, state, rootState}, pId){
                    // если запрос уже идет - пропускаем
                    if(state.productsRequest[pId]){
                        return;
                    }
                    // выполняем запрос на создание лук-товара
                    let product = await urlRequest(rootState.conf.api.lookProducts, 'post', {
                        data: {
                            product_id: pId,
                            look: state.look.id,
                        }
                    }, [
                        setChanging(state.look.id),
                        {start: ['look/edit/setProductRequest', pId], finish: ['look/edit/unsetProductRequest', pId]}
                    ]).response();
                    // добавляем товар
                    commit('productAdd', product);
                },
                async productRemove({commit, state, getters, rootState}, pId){
                    // если запрос уже идет - пропускаем
                    if(state.productsRequest[pId]){
                        return;
                    }
                    // товар для удаления
                    let product = getters.products[pId];
                    // выполняем запрос на удаление лук-товара
                    await urlRequest(`${rootState.conf.api.lookProducts}/${product.id}`, 'delete', {
                        params: {look: [state.look.id]}
                    }, [
                        setChanging(state.look.id),
                        {start: ['look/edit/setProductRequest', pId], finish: ['look/edit/unsetProductRequest', pId]}
                    ]).perform();
                    // добавляем товар
                    commit('productRemove', product);
                },
                async action({state, dispatch}, action){
                    return await dispatch('look/action', {
                        action: action,
                        lookId: state.look.id,
                    }, {root: true});
                },
                async save({commit, state, dispatch}){
                    // нельзя сохранить без фото или без товаров
                    if(!state.look.photoMain && !state.look.products.length){
                        Vue.notify({
                            group: 'default',
                            type: 'error',
                            title: 'Ошибка сохранения',
                            text: 'Нельзя сохранить образ без фото, или без товаров',
                        });
                        throw(false);
                    }
                    // выполняем сохранение лука
                    await dispatch('action', 'look_save');
                    // сообщаем, что лук больше не находится в состоянии измененности
                    commit('unsetEdited');
                    // сообщение об успешном сохранении
                    Vue.notify({
                        group: 'default',
                        type: 'success',
                        title: 'Успешно',
                        text: 'Образ успешно сохранен',
                    });
                },
                async saveCancel({commit, state, dispatch}){
                    // логика отмены актуальна только пока установлен образ
                    if(state.look){
                        if(state.look.edited){
                            await Vue.dialog.confirm('Образ был отредактирован. Отменить изменения?', {
                                okText: 'Выполнить отмену',
                                cancelText: 'Остаться',
                                reverse: false,
                                customClass: 'shop-dialog shop-dialog_warning'
                            });
                        }
                        // в контексте отмены сохранения не обрабатываются ошибки - любое завершение отмены считаем приемлемым
                        try {
                            await dispatch('action', 'look_save_cancel');
                        }
                        catch (e) {
                            console.error(e);
                        }

                        Vue.notify({
                            group: 'default',
                            type: 'warn',
                            title: 'Отмена',
                            text: state.look.isCreating ? 'Создание образа отменено' : 'Редактирование образа отменено',
                        });
                        // сбрасываем текущий лук
                        dispatch('unset');
                    }
                },
                unset({commit, dispatch}){
                    commit('set', null);
                    dispatch('setEditMode', false);
                },
                setEditMode({commit, getters, rootState}, flag){
                    commit('setEditMode', flag);
                    if(flag){
                        Vue.addAppParams(rootState.conf.settings.lookProductsModeParam, getters.productsModeLook.id);
                    }
                    else{
                        Vue.removeAppParams(rootState.conf.settings.lookProductsModeParam);
                    }
                },
            },
        },
    },
    state: {
         // глобальное изменение инкрементально - на каждый подъем флага обязательно должен быть сброс
         changing: {}
    },
    mutations: {
        setChanging(state, {lookId, flag}){
            // если лук еще не обрабатывался - инициализируем его
            if(!_.has(state.changing, lookId)){
                Vue.set(state.changing, lookId, 0);
            }
            // увеличиваем счетчик конкретного лука
            if(flag){
                Vue.set(state.changing, lookId, state.changing[lookId] + 1);
            }
            else {
                Vue.set(state.changing, lookId, state.changing[lookId] - 1);
            }
            if(state.changing[lookId] == 0){
                Vue.delete(state.changing, lookId);
            }
        }
    },
	actions: {
        // удаление лука
    	async remove({commit, rootState}, lookId){
    	    await Vue.dialog.confirm('Удалить образ?', {
                reverse: false,
                customClass: 'shop-dialog shop-dialog_warning'
            });
            await urlRequest(`${rootState.conf.api.looks}/${lookId}`, 'delete', null, setChanging(lookId)).response();
            // при удалении лука - выполняем контрольное обнуление лука в режиме редактирования
            commit('look/edit/set', null, {root: true});
            Vue.notify({
                group: 'default',
                type: 'warn',
                title: 'Удалено',
                text: 'Образ удален',
            });
		},
        async action({commit, state, rootState}, {action, lookId, data}){
            // выполняем действие сохранения
            let response = await urlRequest(rootState.conf.api.lookAction, 'post', {
                data: {
                    action: action,
                    data: Object.assign({
                        look_id: lookId,
                    }, data || {})
                }
            }, setChanging(lookId)).response();
            return response.look_id;
        },
	}
};
