/*
 * py_network.c
 *
 *  Created on: 28.07.2013
 *      Author: Ilya Kharin
 */

// отключаем предупреждения о безопастности функций
#define _CRT_SECURE_NO_WARNINGS 1

#include "zlib.h"
#include <signal.h>
#include "BNetwork.h"

#include "http_parser.c"
#include "cencode.c"
#include "strcasecmp.c"

#include "BEntrypoints.c"
#include "BOutputpoints.c"
#include "BHeader.c"
#include "BTimeouts.c"
#include "BSetCookies.c"
#include "BHttp.c"
#include "BNetEngine.c"
#include "BProxy.c"
#include "BSsl.c"
#include "BDns.c"
#include "BHttpBuilder.c"
#include "BRLink.c"


// ссылка на мастер-поток
BManager *BMaster = NULL;

// кол-во запущенных объектов модуля
static size_t GlobBCount = 0;

/*
 * Метод выставляет флаг остановки для менеджера
 * */
void BStop(BManager *self){
	// под блокировкой стопим цикл опроса
	uv_rwlock_rdlock(&self->stop.lock);
	uv_stop(&self->loop);
	self->stop.flag = 1;
    uv_rwlock_rdunlock(&self->stop.lock);
}


// оберка метода остановки для питона
static PyObject * BManager_func_stop(BManager *self){
	BStop(self);
	Py_RETURN_NONE;
}

// Возвращает кортеж с пpедставлением места последнего исключения
PyObject *BManager_func_getPlaceEx(BManager *self){
	PyObject *ex_tuple = PyTuple_New(3);

	PyTuple_SetItem(ex_tuple, 0, PyInt_FromLong(self->ex.line));
	PyTuple_SetItem(ex_tuple, 1, PyString_FromString(self->ex.func));
	PyTuple_SetItem(ex_tuple, 2, PyString_FromString(self->ex.file));

    return ex_tuple;
}


/*
 * Метод запускает цикл обработки событий, а так же таймер, выполняющий проверку на наличие новых соединений *
 **/
static PyObject * BManager_func_run(BManager *self){
	// инициализируем случайную последовательность для этого потока
	srand((u_int)time(NULL));

	// стартуем таймер опроса соединений
	uv_timer_init(&self->loop, &self->uv.timerHigh);
	uv_timer_start(&self->uv.timerHigh, onTimerHigh, 0, 10); // каждую 0.01 секунды - выход в питон

	// стартуем таймер таймаутов
	uv_timer_init(&self->loop, &self->uv.timerLow);
	uv_timer_start(&self->uv.timerLow, onTimerLow, 0, 1000); // каждую секунду - проверка таймаута

	// если это мастер-поток, стартуем таймер DNS-ов
	if(self == BMaster){
		BStartDNSTimer(self);
	}

	Py_BEGIN_ALLOW_THREADS
	uv_run(&self->loop, UV_RUN_DEFAULT);
	Py_END_ALLOW_THREADS

	// останавливаем все таймеры
	uv_timer_stop(&self->uv.timerHigh);
	uv_timer_stop(&self->uv.timerLow);

	// если это мастер-поток, стопим таймер DNS-ов
	if(self == BMaster){
		BStopDNSTimer(self);
	}

	if(PyErr_Occurred()){
		return 0;
	}
	else{
		Py_RETURN_NONE;
	}
}

// высокочастотный таймер - обеспечивает заполненность слотов
void onTimerHigh(uv_timer_t* handle){
	// получаем менеджер
	BManager *self = (BManager*)handle->loop->data;
	// пробуем заполнить слоты http
	BFillSlots(self, (BNetEntity*)&self->http);
	// пробуем заполнить слоты proxy
	BFillSlots(self, (BNetEntity*)&self->proxy);
}


// низкочастотный таймер - обеспечивает остановку цикла
void onTimerLow(uv_timer_t* handle){
	// получаем менеджер
	BManager *self = (BManager*)handle->loop->data;

	// дергаем метод обработки таймаутов
	onTimeouts(self);

	// имитируем цикл в питоне, если определена соответствующая функция
	if(self->onLoop && self->onLoop != Py_None){
		PyGILState_STATE gstate = PyGILState_Ensure();
		PyObject* isMaster = (self == BMaster) ? Py_True : Py_False;
		Py_INCREF(isMaster);
		// пробуем вызвать калбэк ошибки
		if(PyObject_CallFunctionObjArgs(self->onLoop, isMaster, NULL) == NULL){
			B_SET_EX_PLACE()
			BStop(self);
		}
		Py_DECREF(isMaster);
		PyGILState_Release(gstate);
	}
}


// метод проверки редиректа в контексте питона
int BCheckRedirect(BNetHttp *netObj){
	BManager *self = B_SELF;
	int rc = 0;

	// имитируем цикл в питоне, если определена соответствующая функция
	if(self->http.onBeforeRedirect && self->http.onBeforeRedirect != Py_None){
		PyGILState_STATE gstate = PyGILState_Ensure();
		PyObject *result = NULL;
		PyObject *redir = NULL;
		BUrl tmp_us = {0};
		// внутренний резльтат операций
		int rci;
		// указатель на буферы
		char *redir_url = NULL;

		// копируем во временную структуру урла текущую структуру
		memcpy(&tmp_us, netObj->url, sizeof(BUrl));

		// разбираем редирект, и обновляем данными из него текущую структуру урла
		if(rci = BHeaderParserUrl(netObj, netObj->redir, &tmp_us)){
			B_ERROR(rci, NET);
			goto end;
		}

		// собираем полный урл редиректа
		if((redir_url = BGlobBuf(netObj, B_CONST_SIZE_MAX_BUF)) == NULL){
			goto end;
		}

		// пробуем собрать в указанный буфер урл
		rci = BBuildUrl(redir_url, &tmp_us, B_CONST_SIZE_MAX_BUF);
		// проверяем билд урла на ошибки
		if(rci < 0 || rci >= B_CONST_SIZE_MAX_BUF){
			B_ERROR(B_E_NET_BUILD_URL, NET);
			goto end;
		}

		// собираем питон-строку редиректа
		if((redir = PyBuffer_FromMemory(redir_url, rci)) == NULL){
			B_ERROR(B_E_NET_MALLOC, NET);
			goto end;
		}

		// пробуем вызвать калбэк преобработки редиректа
		if((result = PyObject_CallFunctionObjArgs(self->http.onBeforeRedirect, redir, netObj->py[B_PY_KW], netObj->py[B_PY_TRANS], NULL)) == NULL){
			B_SET_EX_PLACE()
			BStop(self);
			goto end;
		}

		// если возвращена строка - это переопределенный урл редиректа
		if(PyString_Check(result)){
			// выделяем буфер для нового урла
			char *dst = BGlobBuf(netObj, PyString_GET_SIZE(result)+1);
			// копируем в него полученный урл
			strcpy(dst, PyString_AS_STRING(result));
			// переприсваиваем его редиректу
			netObj->redir = dst;
			// редирект разрешен
			rc = 1;
		}
		else{
			// результат чекинга
			rc = result == Py_True;
		}

end:
		// результат нужно освободить
		Py_XDECREF(result);
		Py_XDECREF(redir);

		/*Ссылки на аргументы освобождать не нужно - аргументы не создавались, а лишь получили ссылки */

    	PyGILState_Release(gstate);

    	return rc;
	}
	return 1;
}



// метод устанавливает переданный урл как чекер
int BSetUrlChecker(BManager *self, char *url){
	// порт и хост чекера
	char port[6] = {0},
		 host[256] = {0};

	// заполняем резолвинга
	struct addrinfo hints = {0, PF_INET, SOCK_STREAM, IPPROTO_TCP};

	// указатель на результирующий список ответа
	struct addrinfo *resolv = NULL;

	// проверяем урл чекера на переполнение
	if(strlen(url) >= 256){
		PyErr_SetString(PyExc_KeyError, "Overflow checker url!");
		return -1;
	}

	// копируем урл в объект
	strcpy(self->proxy.rawUrl, url);

	// выполянем проверку и разбор урла на состовляющие
	if(BParseUrl(self->proxy.rawUrl, strlen(url), &self->proxy.url)){
		PyErr_SetString(PyExc_KeyError, "Error parse url checker!");
		return -1;
	}

    // помещаем домен в локальную фиксированную переменную
    strncpy(host, self->proxy.url.host.str, self->proxy.url.host.len);

    // закидываем порт в строку
    if(self->proxy.url.port == 0){
    	// выставляем порты по умолчанию в зависимости от протокола
    	if(self->proxy.url.ssl){
    		sprintf(port, "%d", 443);
    	}
    	else{
    		sprintf(port, "%d", 80);
    	}
    }
    else{
    	sprintf(port, "%d", self->proxy.url.port);
    }

	// резолвим синхронно урл чекера
	if(getaddrinfo(host, port, &hints, &resolv)){
		PyErr_SetString(PyExc_KeyError, "Error resolv checker url!");
		return -1;
	}

	// копируем бинарный вид разрезолвенного домена в структуру урла
	memcpy(&self->proxy.url.bin, resolv->ai_addr, sizeof(struct sockaddr));

	// освобождаем память из-под резолв-структур
	freeaddrinfo(resolv);

	return 0;
}


// метод устанавливает параметры
PyObject *BManager_func_setParams(BManager *self, PyObject *args, PyObject *kwargs){

    // параметры инициализатора
    static char *kwList[] = {
    	"slotsHttp", 			// новое кол-во слотов http
    	"slotsProxy", 			// новое кол-во слотов для прокси-чекера
    	"checkUrl", 			// урл, по которому будут проходить проверки прокси
    	NULL
    };

	// адрес урла для тестирования http-прокси. Должен так же включать в себя ip локального адреса в параметре пути
	char *url = NULL;

	// локальные значения
    int slotsHttp = 0,
    	slotsProxy = 0;

	// производим разбор аргументов инициализатора
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|iis:set_params", kwList,
    		&slotsHttp,
    		&slotsProxy,
    		&url
    	)) {
    	Py_RETURN_NONE;
    }

    // настройка http-слотов
    if(slotsHttp){
    	// уменьшаем/увеличиваем текущие слоты
    	self->http.slots += self->http.slotsRaw - slotsHttp;
    	// сохраняем новое значение
    	self->http.slotsRaw = slotsHttp;
    }

    // настройка proxy-слотов
    if(slotsProxy){
    	// уменьшаем/увеличиваем текущие слоты
    	self->proxy.slots += self->proxy.slotsRaw - slotsProxy;
    	// сохраняем новое значение
    	self->proxy.slotsRaw = slotsProxy;
    }

    // настройка урл-чекера
    if(url){
    	if(BSetUrlChecker(self, url) != 0){
    		return NULL;
    	}
    }

	Py_RETURN_NONE;
}



static int BManager_tp_init(BManager *self, PyObject *args, PyObject *kwargs){

    // параметры инициализатора
    static char *kwInter[] = {
    	"onLoop", 			// метод вызывается каждую секунду
    	"onRequestError",	// метод будет вызван при ошибке разбора словаря параметров
    	"http", 			// словарь настроек для http-запроса
    	"proxy", 			// словарь настроек для proxy-запроса
    	NULL
    };

    // параметры http-протокола
    static char *kwHttp[] = {
    	"onRequest",		// метод вызывается для выборки запроса из питона
    	"onResponse",		// метод вызывается в ответ на завершение обработки http-запроса
    	"slots",			// кол-во одновременных http-запросов
    	"dns",				// список dns серверов вида [('8.8.4.4', 53), ('8.8.8.8', 53), ('4.2.2.4', 53)]
    	"repeatsDns",		// кол-во повторов, в случае ошибки ответа dns
    	"maxPage",			// максимальный размер http-страницы
    	"onBeforeRedirect",	// метод вызывается перед редиректом для валлидации урла, на который будет совершен переход
    	NULL
    };

    // параметры прокси-протокола
    static char *kwProxy[] = {
    	"onRequest",		// метод вызывается для выборки запроса из питона
    	"onResponse",		// метод вызывается в ответ на завершение обработки прокси-запроса
    	"slots",			// кол-во одновременных прокси-запросов
    	"checkUrl", 		// урл, по которому будут проходить проверки прокси
    	NULL
    };

    // словарь параметров обработки http-запроса
    PyObject *httpDict = NULL;

    // словарь параметров обработки прокси-запроса
    PyObject *proxyDict = NULL;

    // список кортежей с адресами dns-серверов
    PyObject *dns = NULL;

    // ошибка инициализатора
    int err = 0;

    struct BManager_http *http = &self->http;
    struct BManager_proxy *proxy = &self->proxy;

    // инициируем случайную последовательность для потока запуска менеджера
    srand((u_int)time(NULL));

	// проверим на инициализацию
	if(self->init){
		PyErr_SetString(PyExc_RuntimeError, "Object was already initialized");
		return -1;
	}

#ifndef B_CONST_USE_THREAD
	// в случае неиспользования многопоточности может быть создан только один экземпляр
	if(GlobBCount > 0){
		PyErr_SetString(PyExc_RuntimeError, "Only one NET-object can be created!");
		return -1;
	}
#endif

	// производим разбор аргументов инициализатора
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|OOO!O!:__init__", kwInter,
    		&self->onLoop,
    		&self->onRequestError,
    		&PyDict_Type, &httpDict,
    		&PyDict_Type, &proxyDict
    	)) {
		return -1;
    }

    // должен быть установлен либо http-запрос либо прокси-запрос
    if(httpDict == NULL && proxyDict == NULL){
		PyErr_SetString(PyExc_KeyError, "Error parse arguments!");
		return -1;
    }

    // порты начинаются со случайного значения
    self->uv.port = (u_short)BRand(B_CONST_PORT_START, B_CONST_PORT_END);

	// максимальный размер принимаемой страницы (дефолтное значение)
    http->maxPage = B_CONST_MAX_PAGE;

    // указатели на списки аргументов
    http->keysArg = keysArgHttp;
    proxy->keysArg = keysArgProxy;

    // типы
    http->type = B_NET_HTTP;
    proxy->type = B_NET_PROXY;

    // если установлен http-запрос - разбираем его
    if(httpDict != NULL){
        if (!PyArg_ParseTupleAndKeywords(args, httpDict, "OOIO!|IIO", kwHttp,
        		&http->onRequest,
        		&http->onResponse,
        		&http->slotsRaw,
        		&PyList_Type, &dns,
        		&http->dns.repeats,
        		&http->maxPage,
        		&http->onBeforeRedirect
        	)) {
    		return -1;
        }

        // записываем начальные значения слотов
        if((http->slots = http->slotsRaw) > B_CONST_MAX_SLOTS){
    		PyErr_SetString(PyExc_ValueError, "Overflow slots number!");
    		return -1;
        }

        // обратные вызовы должны жить!
        Py_XINCREF(http->onRequest);
        Py_XINCREF(http->onResponse);
        Py_XINCREF(http->onBeforeRedirect);

    	// устанавливаем сервера DNS. если произошла ошибка - обрабатываем ее
    	if(err = BSetServersDNS(self, dns)){
    		// ошибка памяти
    		if(err == -1){
    			goto memerror;
    		}
    		// выходим
    		return -1;
    	}

        // инициализация контекстов
        if(BSslInitCtx(&self->ssl)){
        	goto memerror;
        }

        // буфер для текста заголовка
        if(!(http->fbuf_bufs[B_FINAL_HEAD] = (char*)malloc(B_CONST_SIZE_BUF_HEADER))){
			goto memerror;
		}
        // буфер для текста тела
        if(!(http->fbuf_bufs[B_FINAL_BODY] = (char*)malloc(http->maxPage))){
			goto memerror;
		}
    }

    // если установлен прокси-запрос - разбираем его
    if(proxyDict != NULL){
    	// адрес урла для тестирования http-прокси. Должен так же включать в себя ip локального адреса в параметре пути
    	char *urlChecker = NULL;

    	if (!PyArg_ParseTupleAndKeywords(args, proxyDict, "OOI|s", kwProxy,
        		&proxy->onRequest,
        		&proxy->onResponse,
        		&proxy->slotsRaw,
        		&urlChecker
        	)) {
    		return -1;
        }

        // записываем начальные значения слотов
        if((proxy->slots = self->proxy.slotsRaw) > B_CONST_MAX_SLOTS){
    		PyErr_SetString(PyExc_ValueError, "Overflow slots number!");
    		return -1;
        }

        // настройка урл-чекера
        if(urlChecker){
        	if(BSetUrlChecker(self, urlChecker) != 0){
        		return -1;
        	}
        }

        // обратные вызовы должны жить!
        Py_INCREF(proxy->onRequest);
        Py_INCREF(proxy->onResponse);
    }


    // инициализируем цикл
	if((err = uv_loop_init(&self->loop))){
		PyErr_SetString(PyExc_KeyError, uv_strerror(err));
		return -1;
	}

    // инициализируем блокировку на остановку цикла
    uv_rwlock_init(&self->stop.lock);

	// сообщаем, что менеджер уже инициализирован
	self->init = 1;

	// сохраняем указатель на менеджер
	self->loop.data = (void*)self;

	// инициализация стеков (коннектов, буферов, куков)
	B_MEM_INIT_SIZE(BNetHttp, B_CONST_MAX_SLOTS*2);
	B_MEM_INIT_SIZE(BNetProxy, B_CONST_MAX_SLOTS*2);
	B_MEM_INIT_SIZE(BRLink, 524288);
	B_MEM_INIT_SIZE(BCookie, 524288);
	B_MEM_INIT_SIZE(BWriteS, 524288);
	B_MEM_INIT_SIZE_BUF();

	// увеличиваем кол-во запущенных объектов NET
	GlobBCount++;

	// определяем мастер-поток
	if(BMaster == NULL){
		BMaster = self;
		// максимальное кол-во блоков должно для страховки превышать допустимое кол-во в 2 раза
		B_MEM_INIT_SIZE(BCacheDNS, B_DNS_CACHE*2);
	}

	// методы обратных вызовов должен жить
	Py_XINCREF(self->onLoop);
	Py_XINCREF(self->onRequestError);

	return 0;

memerror:
	// если были выделены большие буефры - освобождаем их
	if(http->fbuf_bufs[B_FINAL_HEAD]){ free(http->fbuf_bufs[B_FINAL_HEAD]);}
	if(http->fbuf_bufs[B_FINAL_BODY]){ free(http->fbuf_bufs[B_FINAL_BODY]);}

	PyErr_NoMemory();
	return -1;
}


// служебные методы класса
static PyObject *BManager_tp_new(PyTypeObject *type, PyObject *args, PyObject *kwargs){
	BManager *self = (BManager *)PyType_GenericNew(type, args, kwargs);
    if (!self) {
        return NULL;
    }
    return (PyObject *)self;
}

static int BManager_tp_traverse(BManager *self, visitproc visit, void *arg){
	Py_VISIT(self->onLoop);
	Py_VISIT(self->http.onRequest);
	Py_VISIT(self->http.onResponse);
    if(self->http.onBeforeRedirect){
    	Py_VISIT(self->http.onBeforeRedirect);
    }
	Py_VISIT(self->proxy.onRequest);
	Py_VISIT(self->proxy.onRequest);
    return 0;
}

static int BManager_tp_clear(BManager *self){
	Py_CLEAR(self->onLoop);
	Py_CLEAR(self->http.onRequest);
	Py_CLEAR(self->http.onResponse);
    if(self->http.onBeforeRedirect){
    	Py_CLEAR(self->http.onBeforeRedirect);
    }
	Py_CLEAR(self->proxy.onRequest);
	Py_CLEAR(self->proxy.onRequest);
    return 0;
}

static void BManager_tp_dealloc(BManager *self){
	int i;

	// принудительно вызываем обнуление объектов питона
	BManager_tp_clear(self);

	// в случае ошибки выделения памяти - освобождаем прежде выделенную
	for(i=0; i<B_FINAL_BODY; i++){
		if(self->http.fbuf_bufs[i]) free(self->http.fbuf_bufs[i]);
	}

	// освободим стековые структуры
	B_STACK_CLEAR(BNetHttp);
	B_STACK_CLEAR(BNetProxy);
	B_STACK_CLEAR(BRLink);
	B_STACK_CLEAR(BCookie);
	B_STACK_CLEAR(BWriteS);
	B_STACK_CLEAR_BUF();

	// очищаем память из-под DNS
	if(self == BMaster){
		B_STACK_CLEAR(BCacheDNS);
		BMaster = NULL;
	}

    // освобождаем лок
	uv_rwlock_destroy(&self->stop.lock);

	// освободим днс
	if(self->http.dns.servers){
		free(self->http.dns.servers);
	}

	// разустановим ssl
	if(self->ssl){
		NSS_ShutdownContext(self->ssl);
	}

	// закрываем цикл
	uv_loop_close(&self->loop);

	//BManager_tp_clear(self);
    Py_TYPE(self)->tp_free(self);
}


static PyMethodDef BManager_tp_methods[] = {
    { "setParams", (PyCFunction)BManager_func_setParams, METH_KEYWORDS, "Set params to BManager object" },
    { "run", (PyCFunction)BManager_func_run, METH_NOARGS, "Run uv loop" },
    { "stop", (PyCFunction)BManager_func_stop, METH_NOARGS, "Stop uv loop" },
    { "getPlaceEx", (PyCFunction)BManager_func_getPlaceEx, METH_NOARGS, "Get exception place" },
    { NULL }
};


PyObject *BNetwork_func_BGetStrError(BManager *self, PyObject *args){

	uint32_t errorType = 0;
	int error = 0;
	const char *errorStr = NULL;
	PyObject *errorStrPy = NULL;

	if (!PyArg_ParseTuple(args, "Ii", &errorType, &error)) {
		return NULL;
	}

	// получаем строку ошибки
	errorStr = BErrorStr(errorType, error);

	// получаем питон-бъект строки ошибки
    if (!(errorStrPy = PyString_FromString(errorStr))){
    	return NULL;
    }

    return errorStrPy;
}


static PyMethodDef BNetwork_tp_methods[] = {
    { "BGetStrError", (PyCFunction)BNetwork_func_BGetStrError, METH_VARARGS, "Adds a new http-connection" },
    { NULL }
};


#define _B_SIGNAL_HANDLER(sig)	\
	void _raise_##sig(int signum){	\
		BPS(#sig " FAIL!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n");	\
		signal(signum, SIG_DFL);	\
	}

#define _B_SIGNAL_RAISE(sig) signal(sig, _raise_##sig);


_B_SIGNAL_HANDLER(SIGABRT)
_B_SIGNAL_HANDLER(SIGFPE)
_B_SIGNAL_HANDLER(SIGHUP)
_B_SIGNAL_HANDLER(SIGILL)
_B_SIGNAL_HANDLER(SIGINT)
_B_SIGNAL_HANDLER(SIGKILL)
_B_SIGNAL_HANDLER(SIGSEGV)
_B_SIGNAL_HANDLER(SIGTERM)


void initBNetwork(void) {
	PyObject *mod;

	if(BInitSSl()){
		return;
	}

	// инициализация DNS-модуля
	BInitDNSModule();

	// инициализация лока для памяти
	B_MALLOC_INITLOCK;

    /* Initialize GIL */
    PyEval_InitThreads();

	mod = Py_InitModule("BNetwork", BNetwork_tp_methods);

	// подготавливаем класс
    if (PyType_Ready(&BManagerType)) {
        return;
    }
	// ссылка перехватывается методом добавления, поэтому увеличиваем счетчик ссылок
    Py_INCREF(&BManagerType);
    // добавляем класс NetManager в модуль
    if (PyModule_AddObject(mod, "BManager", (PyObject *)&BManagerType)) {
        Py_DECREF(&BManagerType);
        return;
    }

    // добавлем макросы имен параметров
    PyModule_AddIntConstant(mod, "BA_URL", BA_URL);
    PyModule_AddIntConstant(mod, "BA_ACTION", BA_ACTION);
    PyModule_AddIntConstant(mod, "BA_DATA", BA_DATA);
    PyModule_AddIntConstant(mod, "BA_ZIP", BA_ZIP);
    PyModule_AddIntConstant(mod, "BA_UAGENT", BA_UAGENT);
    PyModule_AddIntConstant(mod, "BA_REFERER", BA_REFERER);
    PyModule_AddIntConstant(mod, "BA_CONNECT", BA_CONNECT);
    PyModule_AddIntConstant(mod, "BA_HEADER", BA_HEADER);
    PyModule_AddIntConstant(mod, "BA_PROXY", BA_PROXY);
    PyModule_AddIntConstant(mod, "BA_N_REDIR", BA_N_REDIR);
    PyModule_AddIntConstant(mod, "BA_COOKS", BA_COOKS);
    PyModule_AddIntConstant(mod, "BA_BANN", BA_BANN);
    PyModule_AddIntConstant(mod, "BA_TRANS", BA_TRANS);
    PyModule_AddIntConstant(mod, "BA_TOUT_CONNECT", BA_TOUT_CONNECT);
    PyModule_AddIntConstant(mod, "BA_TOUT_READY", BA_TOUT_READY);
    PyModule_AddIntConstant(mod, "BA_TOUT_DNS", BA_TOUT_DNS);


    // добавлем макросы типов коннектов в модуль
    PyModule_AddIntConstant(mod, "BH_GET", B_HTTP_GET);
    PyModule_AddIntConstant(mod, "BH_POST", B_HTTP_POST);
    PyModule_AddIntConstant(mod, "BH_HEAD", B_HTTP_HEAD);
    PyModule_AddIntConstant(mod, "BH_EMUL_HEAD", B_HTTP_EMUL_HEAD); // спец. вариант запроса, при котором посылается запрос GET, но ответ будет оборван после получения хедера
    PyModule_AddIntConstant(mod, "BH_CONNECT", B_HTTP_CONNECT);

    // добавлем макросы типов коннекта в модуль
    PyModule_AddIntConstant(mod, "BH_CLOSE", B_HTTP_CLOSE);
    PyModule_AddIntConstant(mod, "BH_KEEP", B_HTTP_KEEP);

    // добавлем макросы типов прокси в модуль
    PyModule_AddIntConstant(mod, "BP_HTTP", B_PROXY_HTTP);
    PyModule_AddIntConstant(mod, "BP_HTTPS", B_PROXY_HTTPS);
    PyModule_AddIntConstant(mod, "BP_SOCKS4", B_PROXY_SOCKS4);
    PyModule_AddIntConstant(mod, "BP_SOCKS5", B_PROXY_SOCKS5);

    // типы NET-объектов
    PyModule_AddIntConstant(mod, "B_NET_HTTP", B_NET_HTTP);
    PyModule_AddIntConstant(mod, "B_NET_PROXY", B_NET_PROXY);

    // Инициализируем константы ошибок
    B_INIT_ERROR_GEN

    _B_SIGNAL_RAISE(SIGABRT)
    _B_SIGNAL_RAISE(SIGFPE)
    _B_SIGNAL_RAISE(SIGHUP)
    _B_SIGNAL_RAISE(SIGILL)
    _B_SIGNAL_RAISE(SIGINT)
    _B_SIGNAL_RAISE(SIGKILL)
    _B_SIGNAL_RAISE(SIGSEGV)
    _B_SIGNAL_RAISE(SIGTERM)
}


static PyTypeObject BManagerType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "BNetwork.BManager",                                         	/*tp_name*/
    sizeof(BManager),                                            	/*tp_basicsize*/
    0,                                                              /*tp_itemsize*/
    (destructor)BManager_tp_dealloc,                             	/*tp_dealloc*/
    0,                                                              /*tp_print*/
    0,                                                              /*tp_getattr*/
    0,                                                              /*tp_setattr*/
    0,                                                              /*tp_compare*/
    0,                                                              /*tp_repr*/
    0,                                                              /*tp_as_number*/
    0,                                                              /*tp_as_sequence*/
    0,                                                              /*tp_as_mapping*/
    0,                                                              /*tp_hash */
    0,                                                              /*tp_call*/
    0,                                                              /*tp_str*/
    0,                                                              /*tp_getattro*/
    0,                                                              /*tp_setattro*/
    0,                                                              /*tp_as_buffer*/
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE | Py_TPFLAGS_HAVE_GC,  /*tp_flags*/
    0,                                                              /*tp_doc*/
    (traverseproc)BManager_tp_traverse,                          	/*tp_traverse*/
    (inquiry)BManager_tp_clear,                                  	/*tp_clear*/
    0,                                                              /*tp_richcompare*/
    0,                                                              /*tp_weaklistoffset*/
    0,                                                              /*tp_iter*/
    0,                                                              /*tp_iternext*/
    BManager_tp_methods,                                         	/*tp_methods*/
    0,                                                              /*tp_members*/
    0,                                                              /*tp_getsets*/
    0,                                                              /*tp_base*/
    0,                                                              /*tp_dict*/
    0,                                                              /*tp_descr_get*/
    0,                                                              /*tp_descr_set*/
    0,                                                              /*tp_dictoffset*/
    (initproc)BManager_tp_init,                                  	/*tp_init*/
    0,                                                              /*tp_alloc*/
    BManager_tp_new,                                             	/*tp_new*/
};
