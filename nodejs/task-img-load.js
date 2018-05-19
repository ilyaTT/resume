/**
 * Created by admin on 16.05.2017.
 */
const url = require('url');
const URI = require('urijs');
const querystring = require('querystring');
const extend = require('extend');
const path = require('path');
const rp = require('request-promise');
const fs = require('fs');
const mkdirp = require('mkdirp');
const ProxyAgent = require('proxy-agent');
const SocksProxyAgent = require('./socks-proxy-agent');

const fix_socks = {
    socks: SocksProxyAgent,
    socks4: SocksProxyAgent,
    socks4a: SocksProxyAgent,
    socks5: SocksProxyAgent,
    socks5h: SocksProxyAgent,
};


let PROXIES_PATH = path.resolve('../../data/img_proxies.txt');

// читаем и приводим в порядок прокси
let PROXIES = [];
try {
    PROXIES = fs.readFileSync(PROXIES_PATH).toString().split("\n");
    PROXIES = PROXIES.map(s => s.trim());
}catch(e){}

function getRandProxy() {
    return PROXIES[Math.floor(Math.random() * PROXIES.length)];
}


// собираем след. сообщение
function buildMsg(msg) {
    // переопределяем название целевого поля
    return{
        data: Object.assign({}, msg, {
			field: `${msg.hash}:${msg.resize}`,
			next_queue: null
		}),
        queue: msg.next_queue,
        meta: {
            priority: msg.priority
        }
    }
}

module.exports = {

    promise: (msg, meta) => {
        return new Promise((resolve, reject) => {
            // проверка файла на сущестоввание
            fs.access(msg.path, fs.constants.F_OK, (no_exist) => {
                // если файл не существует - выполянем запрос
                if(no_exist){
                    // создаем объект рабочего урла
                    let uriObj = URI(msg.url);
                    // выполняем кодирование частей пути и query
                    let uri = uriObj.segmentCoded(uriObj.segmentCoded()).search(querystring.stringify(uriObj.search(true))).toString();

                    // основной запрос
                    let request = {
                        uri: uri,
                        encoding: null,
                        simple: false,
                        resolveWithFullResponse: true,
                        timeout: 3000,
                        insecure: true,
                        strictSSL: false
                    };

                    let proxy = null;

                    // если есть прокси - работаем через них
                    if(PROXIES.length){
                        proxy = getRandProxy();
                        request.agent = new ProxyAgent(extend({proxies: fix_socks}, url.parse(proxy)))
                    }

                    // собственно выполнение запроса
                    rp(request).then(resp => {
                        // тело ответа
                        let data = resp.body;
                        // код ответа
                        let code = resp.statusCode;

                        // только в случае корректного кода пишем тело в файл
                        if(code >= 200 && code < 300){
                            // пробуем создать папку
                            mkdirp(msg.folder, (err) => {
                                if(err){
                                    reject([0, `Error create folder ${msg.folder}. Error: ${err}`, 'FATAL']);
                                }
                                else{
                                    // проверка на нулевой размер данных
                                    if(Buffer.byteLength(data) == 0){
                                        reject([500, `Error in msg.url: ${uri}. (${msg.url}) Error: null size response!`, 'ERROR']);
                                    }
                                    else{
                                        fs.writeFile(msg.path, data, null, (err) => {
                                            if(err){
                                                reject([0, `Error create file path ${msg.path}. Error: ${err}`, 'FATAL']);
                                            }
                                            else{
                                                // скачано, теперь передаем задачу на ресайзинг
                                                resolve([200, buildMsg(msg)]);
                                            }
                                        });
                                    }
                                }
                            });
                        }
                        // если изображение отсутствует - отмесаем, что выполнено успешно, но со статусом отсутствия
                        else if(code == 404){
                            reject([404, `Error code: ${code}. Proxy: ${proxy} Url: ${uri} (${msg.url})`, 'ERROR']);
                        }
                        else{
                            reject([500, `Error code: ${code}. Proxy: ${proxy} Url: ${uri} (${msg.url})`, 'ERROR']);
                        }
                    })
                    .catch((err) => {
                        reject([500, `Error response: ${err}. Proxy: ${proxy} Url: ${uri} (${msg.url})`, 'ERROR']);
                    });
                }
                else{
                    console.log('FILE ALREADY EXIST');
                    // файл есть, теперь передаем задачу на ресайзинг
                    resolve([200, buildMsg(msg)]);
                }
            });
        });
    }
};