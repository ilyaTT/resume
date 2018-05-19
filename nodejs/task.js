/**
 * Created by admin on 12.05.2017.
 */

const amqp = require('amqp-connection-manager');
const redis = require('redis');
const argv = require('argv');
const log4js = require('log4js');

// определяем аргументы скрипта
let args = argv.option([{
    name: 'amqp',
    short: '-a',
    type: 'csv,string'
}, {
    name: 'redis',
    short: '-r',
    type: 'string'
}, {
    name: 'queue',
    short: '-q',
    type: 'string'
}, {
    name: 'script',
    short: '-s',
    type: 'string'
}, {
    name: 'threads',
    short: '-t',
    type: 'int'
}, {
    name: 'img_delays',
    type: 'csv,int'
}, {
    name: 'loglevel',
    short: '-l',
    type: 'string'
}]).run();

// опции
let opts = args.options;


const logger = log4js.getLogger();
logger.setLevel(opts.loglevel);

// временные очереди и максимальная очередь
let img_delays = opts.img_delays.sort((a, b) => a - b);
let img_delays_max = Math.max.apply(null, img_delays);
// ожидание для уже обрабатывающегося хэша
let img_delays_wait = opts.img_delays[1];


logger.info(`img_delays. ${img_delays}, ${img_delays_max}, ${img_delays_wait}`);



// загружаем запрошенный скрипт
const script = require(`./${opts.script}`);

// подключаемся к редису
let redis_client = redis.createClient({
    url: opts.redis,
    retry_strategy: function (options) {
        // логгируем ошибку
        logger.warning('Redis reconnect');
        // логгируем ошибку
        if (options.error) {
            logger.error(`Redis connect error: ${options.error.code}`);
        }
        // 100 попыток - достаточно
        if (options.attempt > 100) {
            // End reconnecting with built in error
            return undefined;
        }
        // reconnect after 1 sec
        return 1000;
    }
});


// подключаемся к пуллу rabbitmq
let connection = amqp.connect(opts.amqp, {json: true});
connection.on('connect', () => {
    logger.info('Connected!');
});
connection.on('disconnect', (params) => {
    logger.info(`Disconnected. ${params.err.stack}`);
});

// канал на отправку сообщений
let channelSend = connection.createChannel({json: true});

// Handle an incomming message.
let onMessage = (msg) => {
    // парсим сообщение
    let data = msg.content.toString();
    // логгируем
    logger.info(`receiver: got message ${data}`);
    // десериализуем
    let message = JSON.parse(data);
    // получаем собственно данные сообщения
    let m_data = message.data;

    // получаем уже имеющийся статус
    redis_client.get(m_data.field, function(err, status) {
        // получаем числовой статус
        status = parseInt(status || '0');
        // только если статус "необработанный" или "ошибочный" - обрабатываем
        if(status == 0 || status == 500){
            // выставляем статус обработки на пол мин
            redis_client.set(m_data.field, 100, 'EX', 30);

            // от внешнего скрипта требуется метод promise, возвращающий объект Promise
            script.promise(m_data, message.meta).then(resp => {
                // распаковка аргументов
                let [code, task] = resp;
                // пишем в редис статус
                redis_client.set(m_data.field, code);
                // если получена задача - запускаем ее в работу
                if(task){
                    channelSend.sendToQueue(task.queue, {
                        data: task.data,
                        meta: task.meta
                    }).then(function() {
                        logger.info(`sender: send message ${JSON.stringify(task)}`);
                    }).catch(function(err) {
                        // тут ошибка не предполагается - аварийно завершаемся
                        channelRecv.nack(msg);
                        logger.error(`Fatal error: ${err}`);
                        process.exit();
                    });
                }
                // если успешно обработано - отмечаем сообщение, как обработанное
                channelRecv.ack(msg);
            }).catch(resp => {
                // распаковка аргументов
                let [code, error, type] = resp;
                // обнуляем статус поля
                redis_client.set(m_data.field, code);

                // текущее кол-во повторений
                let attempts = m_data.attempts;

                // в зависимости от кол-ва повторений - разная задержка
                let delay = attempts < img_delays.length ? img_delays[attempts] : img_delays_max;
                // в зависимости от кол-ва повторений - разная очередь задержек
                let queue = `${opts.queue}_${delay}`;

                // увеличиваем счетчик попыток
                m_data.attempts++;

                // перезабрасываем сообщение в очередь задержки
                channelSend.sendToQueue(queue, {
                    data: m_data,
                }).then(function() {
                    logger.info(`resend message (${queue}): ${JSON.stringify(m_data)}`);
                    // текущее сообщение подтверждаем
                    channelRecv.ack(msg);
                }).catch(function(err) {
                    // тут ошибка не предполагается - аварийно завершаемся
                    channelRecv.nack(msg);
                    logger.error(`Fatal error: ${err}`);
                    process.exit();
                });

                // логгируем ошибку
                logger.error(error);
                // если ошибка фатальная - выходим из процесса
                if(type == 'FATAL'){
                    process.exit();
                }
            });
        }
        else if(status == 100){
            let queue = `${opts.queue}_${img_delays_wait}`;

            // если сообщение с таким хэшем обрабатывается - кидаем сообщение на ожидание
            channelSend.sendToQueue(queue, {
                data: m_data,
            }).then(function() {
                logger.info(`wait message (${queue}): ${JSON.stringify(m_data)}`);
                // текущее сообщение подтверждаем
                channelRecv.ack(msg);
            }).catch(function(err) {
                // тут ошибка не предполагается - аварийно завершаемся
                channelRecv.nack(msg);
                logger.error(`Fatal error: ${err}`);
                process.exit();
            });
        }
        else{
            // текущее сообщение подтверждаем
            channelRecv.ack(msg);
        }
    });
};

// канал на приемку сообщений
let channelRecv = connection.createChannel({
    setup: (channel) => {
        return Promise.all([
            channel.prefetch(opts.threads),
            channel.consume(opts.queue, onMessage)
        ]);
    }
});

// ожидаем успешное подключение
channelRecv.waitForConnect().then(() => {
    logger.info('Listening for messages');
});


