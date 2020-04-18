/**
 * Created by admin on 12.05.2017.
 */

const path = require('path');
const fs = require('fs');
const amqp = require('amqp-connection-manager');
const redis = require('redis');
const argv = require('argv');
const log4js = require('log4js');
const moment = require('moment');
const elasticsearch = require('elasticsearch');
const Raven = require('raven');


// определяем аргументы скрипта
let args = argv.option([{
    name: 'script',
    type: 'string'
}, {
    name: 'queue',
    type: 'string'
}, {
    name: 'photo_path',
    type: 'string'
}, {
    name: 'load_timeout',
    type: 'int'
}, {
    name: 'reload_sleep',
    type: 'int'
}, {
    name: 'flush_timeout',
    type: 'int'
}, {
    name: 'flush_interval',
    type: 'int'
},  {
    name: 'resize_sizes',
    type: 'string'
},  {
    name: 'scroll_size',
    type: 'int'
},  {
    name: 'scroll_time',
    type: 'int'
},  {
    name: 'workers',
    type: 'int'
},  {
    name: 'index_name',
    type: 'string'
}, {
    name: 'elastic_auth',
    type: 'string'
}, {
    name: 'rmq',
    type: 'string'
}, {
    name: 'raven',
    type: 'string'
}, {
    name: 'data_dir',
    type: 'string'
}, {
    name: 'offers',
    type: 'csv'
}, {
    name: 'proxy_attempts',
    type: 'int'
}, {
    name: 'proxy_path',
    type: 'string'
}, {
    name: 'loglevel',
    type: 'string'
}, {
    name: 'sizes',
    type: 'string'
}, {
    name: 's3_endpoint',
    type: 'string'
}, {
    name: 's3_broker',
    type: 'string'
}, {
    name: 's3_reload',
    type: 'int'
}]).run();

// опции
let opts = args.options;

// инициализация Raven
if(opts.raven){
    Raven.config(opts.raven).install();
}
// перехват ошибок
process.on('unhandledRejection', (reason, promise) => {
    console.error('unhandledRejection:', reason);
    if(opts.raven) {
        Raven.captureException(reason, function (sendErr) {
            if (sendErr) {
                console.error('Raven FATAL ERROR:', sendErr);
                console.error('Raven reason:', reason);
            }
        });
    }
    process.exit(1);
});


const logger = log4js.getLogger();
logger.setLevel(opts.loglevel);

// загружаем запрошенный скрипт
const script = require(`./${opts.script}`);
script.setOpts(opts, logger);


// c rabbitmq работаем, только если есть входные параметры для него
if(opts.rmq && opts.queue){
    // подключаемся к пуллу rabbitmq
    let connection = amqp.connect(opts.rmq, {json: true});
    connection.on('connect', () => {
        logger.info('Connected!');
    });
    connection.on('disconnect', (params) => {
        logger.info(`Disconnected. ${params.err.stack}`);
    });

    // канал на отправку сообщений
    let channelSend = connection.createChannel({json: true});

    // канал на приемку сообщений
    let channelRecv = connection.createChannel({
        setup: (channel) => {
            return Promise.all([
                channel.prefetch(script.workers),
                channel.consume(opts.queue, (msg) => {
                    // парсим сообщение
                    let data = msg.content.toString();
                    // логгируем
                    // logger.info(`receiver: got message ${data}`);
                    // десериализуем
                    let message = JSON.parse(data);
                    // получаем задачу
                    let task = message.data;
                    let task_id = script.getId(task);

                    // задача не должна быть в работе
                    if(IN_WORK_REALTIME.has(task_id)){
                        // текущее сообщение отменяем
                        channelRecv.nack(msg);
                        return;
                    }
                    IN_WORK_REALTIME.add(task_id);

                    // обрабатываем задачу
                    task_handler(task).then(result => {
                        // текущее сообщение подтверждаем
                        channelRecv.ack(msg);

                        // если нет ответа - не выполняем дальнейшую обработку
                        if(!result){
                            IN_WORK_REALTIME.delete(task_id);
                            return;
                        }

                        let resp = result.response;

                        // пишем обновленные данные в индекс с немедленным обновлением
                        ES.update({
                            index: opts.index_name,
                            type: '_doc',
                            id: resp._id,
                            body: {doc: resp._source},
                            refresh: 'wait_for'
                        }).then(() => {
                            // если заданы следующие задачи - запускаем их
                            if(result.success){
                                (task._next || []).forEach((next) => {
                                     channelSend.sendToQueue(next.queue, {
                                        data: next.data,
                                        meta: next.meta
                                    }).then(function() {
                                        // logger.info(`sender: send message ${JSON.stringify(next)}`);
                                    });
                                });
                            }
                            IN_WORK_REALTIME.delete(task_id);
                        });
                    });
                })
            ]);
        }
    });

    // ожидаем успешное подключение
    channelRecv.waitForConnect().then(() => {
        logger.info('Listening for messages');
    });

}

// подключение к ES
const ES = new elasticsearch.Client({
    host: [
        {
            host: 'localhost',
            auth: opts.elastic_auth,
            protocol: 'http',
            port: 9200
        }
    ],
    log: 'error',
    requestTimeout: 600000
});

// хэши, которые сейчас в работе
let IN_WORK = new Set();
let IN_WORK_REALTIME = new Set();
let IN_UPDATE = new Set();
let TASK_QUEUE = new Map();
let RESPONSE_QUEUE = new Map();
let SCROLL_ID = null;
let SCROLL_ID_TIME = moment();
let IS_GETTING_ITEMS = false;
let NEXT_FILL_TIME = moment();
let FLUSH_TIME_LAST = moment();

// обработка задачи
let task_handler = async (task) => {
    let task_id = script.getId(task);

    // задача не должна быть в работе
    if(IN_WORK.has(task_id)){
        return;
    }
    // отмечаем, что задача сейчас в работе
    IN_WORK.add(task_id);
    // от внешнего скрипта требуется метод promise, возвращающий объект Promise
    let result = await script.promise(task);
    // убираем задачу из работы
    IN_WORK.delete(task_id);

    if(!result){
        return;
    }
    // в объект результата добавляем время обновления
    result.response = {
        _id: task._id,
        _source: Object.assign({
            datetime_update: moment.utc().format('YYYY-MM-DD HH:mm:ss')
        }, result.response)
    };
    return result;
};


// наполнение очереди
let queue_filling = async () => {
    // проверяем допустимость выполнения запроса по времени
    if(NEXT_FILL_TIME.isAfter()){
        return;
    }

    let response;
    // загрузка начата
    IS_GETTING_ITEMS = true;

    // если не был установлен скролл, либо истекло время непрерывного использования
    if(!SCROLL_ID || moment().diff(SCROLL_ID_TIME, 'seconds') >= opts.scroll_time){
        // выполняем инициализирующий запрос
        response = await ES.search(Object.assign({
            index: opts.index_name,
            scroll: `${opts.scroll_time}s`,
            size: opts.scroll_size,
        }, script.query()));
    }
    else{
        response = await ES.scroll({
          scrollId: SCROLL_ID,
          scroll: `${opts.scroll_time}s`,
        });
    }

    // массив задач
    let tasks = response.hits.hits;

    if(tasks.length){
        // сохраняем скролл id
        SCROLL_ID = response._scroll_id;
        SCROLL_ID_TIME = moment();
        // console.log('dicts:',
        //     JSON.stringify([...TASK_QUEUE.keys()]),
        //     JSON.stringify([...RESPONSE_QUEUE.keys()]),
        //     JSON.stringify([...IN_WORK]),
        //     JSON.stringify([...IN_UPDATE])
        // );

        // оставим только те, которые сейчас не в очередях на выполнение и сброс
        let added = tasks.filter(task => {
            let t_id = script.getId(task);
            return !TASK_QUEUE.has(t_id) && !RESPONSE_QUEUE.has(t_id) && !IN_WORK.has(t_id) && !IN_UPDATE.has(t_id)
        });

        // console.log('added:', JSON.stringify(added));

        // обновляем очередь
        TASK_QUEUE = new Map([...TASK_QUEUE, ...added.map(task => [script.getId(task), task])]);
        // устанавливаем время след. разрешенного запроса
        NEXT_FILL_TIME = moment();
    }
    else {
        // если в ответе было пусто - сбрасываем scroll_id
        SCROLL_ID = null;
        // если предыдущий запрос был пуст, то следующий - через определенное время
        NEXT_FILL_TIME = moment().add(20, 'seconds');
    }

    // загрузка завершена
    IS_GETTING_ITEMS = false;
};


let flush_response = () => {
    // собираем данные к отправке в индекс
    let bulk_data = [];
    let in_update = new Set();

    RESPONSE_QUEUE.forEach((task, task_id) => {
        bulk_data.push({update: {_index: opts.index_name, _type: '_doc', _id: task._id}});
        bulk_data.push({doc: task._source});
        in_update.add(task_id);
    });

    // добавляем обновляемые задачи
    IN_UPDATE = new Set([...IN_UPDATE, ...in_update]);

    // сброс в индекс
    if(bulk_data.length > 0){
        // сброс с ожиданием сообщения об обновлении данных
        ES.bulk({body: bulk_data, timeout: `${opts.flush_timeout}s`, refresh: 'wait_for'}).then((resp) => {
            // проверим ошибки
            if(resp.errors){
                console.log('ES.bulk:', JSON.stringify(resp));
            }
            // хак для обхода замедленного обновления индекса: ждем еще 5 сек
            setTimeout(() => {
                IN_UPDATE = new Set([...IN_UPDATE].filter(task_id => !in_update.has(task_id)));
                FLUSH_TIME_LAST = moment();
            }, 5000);
        });
    }

    // обнуление очереди
    RESPONSE_QUEUE.clear();
};


// время последнего сброса статы
let STAT_TIME_START = moment();
let STAT_TIME_LAST = moment();

// обработка очереди
let queue_handler = () => {
    // проверяем свободные воркеры
    while(IN_WORK.size < opts.workers){

        // если пришло время сбросить стату
        if(moment().diff(STAT_TIME_LAST, 'seconds') > 10){
            let stat = script.getStat();
            stat.meta = {
                time: moment().format('YYYY-MM-DD HH:mm:ss'),
                start_time: STAT_TIME_START.format('YYYY-MM-DD HH:mm:ss')
            };

            fs.writeFile(path.join(opts.data_dir, `${opts.script}.stat.json`), JSON.stringify(stat), null, (err) => {
                if (err) {
                    throw `Error write stat script!`;
                }
            });
            STAT_TIME_LAST = moment();
        }

        // если очередь почти пустая и не идет загрузка данных - пробуем их подгрузить
        if((TASK_QUEUE.size < (opts.scroll_size/10)) && !IS_GETTING_ITEMS){
            // контрольный сброс в индекс
            if(RESPONSE_QUEUE.size > 0){
                flush_response();
            }
            queue_filling();
        }

        // получаем следуюшую задачу
        let task_pair = TASK_QUEUE.entries().next().value;
        if(!task_pair){
            break;
        }

        let [task_id, task] = task_pair;
        TASK_QUEUE.delete(task_id);

        task_handler(task).then(result => {
            if(!result){
                return;
            }
            // результат выполнения задачи
            let task_resp = result.response;
            // аккумулируем ответы
            RESPONSE_QUEUE.set(script.getId(task), task_resp);

            // ожидаем следующий сброс данных по времени
            if(moment().diff(FLUSH_TIME_LAST, 'seconds') > opts.flush_interval){
                flush_response();
            }
        });
    }

    // чуть ждем, и заходим снова
    setTimeout(queue_handler, 100);
};

// выполняем инициализирующмй запуск, с проверкой существования индекса
ES.indices.exists({index: opts.index_name}, (err, exist, status) => {
    if(!exist){
        throw `No exist index: ${opts.index_name}`;
    }
    queue_handler();
});



