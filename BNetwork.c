/*
 * py_network.c
 *
 *  Created on: 28.07.2013
 *      Author: Ilya Kharin
 */

// ��������� �������������� � ������������� �������
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


#include "BPCRE.c"
#include "BLibxml.c"

// ������ �� ������-�����
BManager *BMaster = NULL;

// ���-�� ���������� �������� ������
static size_t GlobBCount = 0;

/*
 * ����� ���������� ���� ��������� ��� ���������
 * */
void BStop(BManager *self){
	// ��� ����������� ������ ���� ������
	uv_rwlock_rdlock(&self->stop.lock);
	uv_stop(&self->loop);
	self->stop.flag = 1;
    uv_rwlock_rdunlock(&self->stop.lock);
}


// ������ ������ ��������� ��� ������
static PyObject * BManager_func_stop(BManager *self){
	BStop(self);
	Py_RETURN_NONE;
}


/*
 * ����� ��������� ���� ��������� �������, � ��� �� ������, ����������� �������� �� ������� ����� ���������� *
 **/
static PyObject * BManager_func_run(BManager *self){
	// �������������� ��������� ������������������ ��� ����� ������
	srand((u_int)time(NULL));

	// �������� ������ ������ ����������
	uv_timer_init(&self->loop, &self->uv.timerHigh);
	uv_timer_start(&self->uv.timerHigh, onTimerHigh, 0, 10); // ������ 0.01 ������� - ����� � �����

	// �������� ������ ���������
	uv_timer_init(&self->loop, &self->uv.timerLow);
	uv_timer_start(&self->uv.timerLow, onTimerLow, 0, 1000); // ������ ������� - �������� ��������

	// ���� ��� ������-�����, �������� ������ DNS-��
	if(self == BMaster){
		BStartDNSTimer(self);
	}

	Py_BEGIN_ALLOW_THREADS
	uv_run(&self->loop, UV_RUN_DEFAULT);
	Py_END_ALLOW_THREADS

	// ������������� ��� �������
	uv_timer_stop(&self->uv.timerHigh);
	uv_timer_stop(&self->uv.timerLow);

	// ���� ��� ������-�����, ������ ������ DNS-��
	if(self == BMaster){
		BStopDNSTimer(self);
	}

	Py_RETURN_NONE;
}


// ��������������� ������ - ������������ ������������� ������
void onTimerHigh(uv_timer_t* handle){

	// �������� ��������
	BManager *self = (BManager*)handle->loop->data;
	// ���-�� ������, ������� ����� ���� ���������. ���������� � �����
	PyObject *slots = NULL;

	// ��������� http-�������
    if(self->http.slots > 0){
    	PyGILState_STATE gstate = PyGILState_Ensure();
    	// ���������� ������������� ���-�� ������
    	slots = PyInt_FromLong(self->http.slots);
    	// ����� ������������ ������
    	B_CALL_PYTHON(self->http.onRequest B_COMMA slots);
    	// ��������� �����-�����
    	Py_DECREF(slots);
    	PyGILState_Release(gstate);
    }

    // ��������� proxy-�������
    if(self->proxy.slots > 0){
    	PyGILState_STATE gstate = PyGILState_Ensure();
    	// ���������� ������������� ���-�� ������
    	slots = PyInt_FromLong(self->proxy.slots);
    	// ����� ������������ ������
    	B_CALL_PYTHON(self->proxy.onRequest B_COMMA slots);
    	// ��������� �����-�����
    	Py_DECREF(slots);
    	PyGILState_Release(gstate);
    }
}


// �������������� ������ - ������������ ��������� �����
void onTimerLow(uv_timer_t* handle){

	// �������� ��������
	BManager *self = (BManager*)handle->loop->data;

	// ������� ����� ��������� ���������
	onTimeouts(self);

	// ��������� ���� � ������, ���� ���������� ��������������� �������
	if(self->onLoop){
		PyGILState_STATE gstate = PyGILState_Ensure();
		PyObject* isMaster = (self == BMaster) ? Py_True : Py_False;
		Py_INCREF(isMaster);
		B_CALL_PYTHON(self->onLoop B_COMMA isMaster);
		Py_DECREF(isMaster);
		PyGILState_Release(gstate);
	}
}


PyObject *BManager_func_set_params(BManager *self, PyObject *args, PyObject *kwargs){

    // ��������� ��������������
    static char *kwList[] = {
    	"slotsHttp", 			// ����� ���������� ������ �������
    	"slotsProxy", 			// ������� �������� ��� http-�������
    	"checkUrl", 			// ������� �������� ��� proxy-�������
    	NULL
    };

	// ����� ���� ��� ������������ http-������. ������ ��� �� �������� � ���� ip ���������� ������ � ��������� ����
	char *url = NULL;

	// ��������� ��������
    int slotsHttp = 0,
    	slotsProxy = 0,
    	slotsDelta = 0;

	// ���������� ������ ���������� ��������������
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|iis:set_params", kwList,
    		&slotsHttp,
    		&slotsProxy,
    		&url
    	)) {
    	Py_RETURN_NONE;
    }

    // ��������� http-������
    if(slotsHttp){
    	// ���������/����������� ������� �����
    	self->http.slots += self->http.slotsRaw - slotsHttp;
    	// ��������� ����� ��������
    	self->http.slotsRaw = slotsHttp;
    }

    // ��������� proxy-������
    if(slotsProxy){
    	// ���������/����������� ������� �����
    	self->proxy.slots += self->proxy.slotsRaw - slotsProxy;
    	// ��������� ����� ��������
    	self->proxy.slotsRaw = slotsProxy;
    }

    // ��������� ���-������
    if(url){
    	// ���� � ���� ������
    	char port[6] = {0},
    		 host[256] = {0};

    	// ��������� ����������
    	struct addrinfo hints = {0, PF_INET, SOCK_STREAM, IPPROTO_TCP};

    	// ��������� �� �������������� ������ ������
    	struct addrinfo *resolv = NULL;

    	// ��������� ��� ������ �� ������������
    	if(strlen(url) >= 256){
    		PyErr_SetString(PyExc_KeyError, "Overflow checker url!");
    		return NULL;
    	}

    	// �������� ��� � ������
    	strcpy(self->proxy.rawUrl, url);

    	// ��������� �������� � ������ ���� �� ������������
    	if(BParseUrl(self->proxy.rawUrl, strlen(url), &self->proxy.url)){
    		PyErr_SetString(PyExc_KeyError, "Error parse url checker!");
    		return NULL;
    	}

        // �������� ����� � ��������� ������������� ����������
        strncpy(host, self->proxy.url.host.str, self->proxy.url.host.len);

        // ���������� ���� � ������
        if(self->proxy.url.port == 0){
        	// ���������� ����� �� ��������� � ����������� �� ���������
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

    	// �������� ��������� ��� ������
    	if(getaddrinfo(host, port, &hints, &resolv)){
    		PyErr_SetString(PyExc_KeyError, "Error resolv checker url!");
    		return NULL;
    	}

    	// �������� �������� ��� ��������������� ������ � ��������� ����
    	memcpy(&self->proxy.url.bin, resolv->ai_addr, sizeof(struct sockaddr));

    	// ����������� ������ ��-��� ������-��������
    	freeaddrinfo(resolv);
    }

	Py_RETURN_NONE;
}



static int BManager_tp_init(BManager *self, PyObject *args, PyObject *kwargs){

    // ��������� ��������������
    static char *kwInter[] = {
    	"onLoop", 			// ����� ���������� ������ �������
    	"http", 			// ������� �������� ��� http-�������
    	"proxy", 			// ������� �������� ��� proxy-�������
    	NULL
    };

    // ��������� http-���������
    static char *kwHttp[] = {
    	"onRequest",		// ����� ���������� ��� ������� ������� �� ������
    	"onResponse",		// ����� ���������� � ����� �� ���������� ��������� http-�������
    	"slots",			// ���-�� ������������� http-��������
    	"dns",				// ������ dns �������� ���� [('8.8.4.4', 53), ('8.8.8.8', 53), ('4.2.2.4', 53)]
    	"repeatsDns",		// ���-�� ��������, � ������ ������ ������ dns
    	"maxPage",			// ������������ ������ http-��������
    	"xmlHandler",		// ���������� html-������
    	NULL
    };

    // ��������� ������-���������
    static char *kwProxy[] = {
    	"onRequest",		// ����� ���������� ��� ������� ������� �� ������
    	"onResponse",		// ����� ���������� � ����� �� ���������� ��������� ������-�������
    	"slots",			// ���-�� ������������� ������-��������
    	NULL
    };

    // ������� ���������� ��������� http-�������
    PyObject *httpDict = NULL;

    // ������� ���������� ��������� ������-�������
    PyObject *proxyDict = NULL;

    // ������ �������� � �������� dns-��������
    PyObject *dns = NULL;

    // ������ ��������������
    int err = 0;

    struct BManager_http *http = &self->http;

    // ���������� ��������� ������������������ ��� ������ ������� ���������
    srand((u_int)time(NULL));

	// �������� �� �������������
	if(self->init){
		PyErr_SetString(PyExc_RuntimeError, "Object was already initialized");
		return -1;
	}

#ifndef B_CONST_USE_THREAD
	// � ������ ��������������� ��������������� ����� ���� ������ ������ ���� ���������
	if(GlobBCount > 0){
		PyErr_SetString(PyExc_RuntimeError, "Only one NET-object can be created!");
		return -1;
	}
#endif

	// ���������� ������ ���������� ��������������
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|OO!O!:__init__", kwInter,
    		&self->onLoop,
    		&PyDict_Type, &httpDict,
    		&PyDict_Type, &proxyDict
    	)) {
		return -1;
    }

    // ������ ���� ���������� ���� http-������ ���� ������-������
    if(httpDict == NULL && proxyDict == NULL){
		PyErr_SetString(PyExc_KeyError, "Error parse arguments!");
		return -1;
    }

    // ����� ���������� �� ���������� ��������
    self->uv.port = (u_short)BRand(B_CONST_PORT_START, B_CONST_PORT_END);

	// ������������ ������ ����������� �������� (��������� ��������)
    http->maxPage = B_CONST_MAX_PAGE;

    // ���� ���������� http-������ - ��������� ���
    if(httpDict != NULL){
        if (!PyArg_ParseTupleAndKeywords(args, httpDict, "OOIO!|IIO!", kwHttp,
        		&http->onRequest,
        		&http->onResponse,
        		&http->slotsRaw,
        		&PyList_Type, &dns,
        		&http->dns.repeats,
        		&http->maxPage,
        		&BXmlHandType, &http->xmlHand
        	)) {
    		return -1;
        }

        // ���������� ���-�� ������ �� ����������
        Py_XINCREF(http->xmlHand);

        //DEBUG!!!!!!!!!!!
        BXMLInit(http->xmlHand);

        // ���������� ��������� �������� ������
        if((http->slots = http->slotsRaw) > B_CONST_MAX_SLOTS){
    		PyErr_SetString(PyExc_ValueError, "Overflow slots number!");
    		return -1;
        }

        // �������� ������ ������ ����!
        Py_INCREF(http->onRequest);
        Py_INCREF(http->onResponse);

    	// ������������� ������� DNS. ���� ��������� ������ - ������������ ��
    	if(err = BSetServersDNS(self, dns)){
    		// ������ ������
    		if(err == -1){
    			goto memerror;
    		}
    		// �������
    		return -1;
    	}

        // ������������� ����������
        if(BSslInitCtx(&self->ssl)){
        	goto memerror;
        }

        // �������� ������ ��� ������ ������� �������
        do{
        	int i = 0, j = 0;
        	for(; i<B_FINAL_BODY; i++){
        		// ������� �������� ������� ������
                if(!(http->fbuf_bufs[i] = (char*)malloc(i == B_FINAL_HEAD ? B_CONST_SIZE_BUF_HEADER : http->maxPage))){
                	// � ������ ������ ��������� ������ - ����������� ������ ����������
                	for(; j<B_FINAL_BODY; j++){
                		if(http->fbuf_bufs[j]) free(http->fbuf_bufs[j]);
                	}
                	// �������� �� ������
                	goto memerror;
                }
        	}
        }while(0);
    }

    // ���� ���������� ������-������ - ��������� ���
    if(proxyDict != NULL){
    	if (!PyArg_ParseTupleAndKeywords(args, proxyDict, "OOI", kwProxy,
        		&self->proxy.onRequest,
        		&self->proxy.onResponse,
        		&self->proxy.slots
        	)) {
    		return -1;
        }

        // ���������� ��������� �������� ������
        if((self->proxy.slots = self->proxy.slotsRaw) > B_CONST_MAX_SLOTS){
    		PyErr_SetString(PyExc_ValueError, "Overflow slots number!");
    		return -1;
        }

        // �������� ������ ������ ����!
        Py_INCREF(self->proxy.onRequest);
        Py_INCREF(self->proxy.onResponse);
    }


    // �������������� ����
	if((err = uv_loop_init(&self->loop))){
		PyErr_SetString(PyExc_KeyError, uv_strerror(err));
		return -1;
	}

    // �������������� ���������� �� ��������� �����
    uv_rwlock_init(&self->stop.lock);

	// ��������, ��� �������� ��� ���������������
	self->init = 1;

	// ��������� ��������� �� ��������
	self->loop.data = (void*)self;

	// ������������� ������ (���������, �������, �����)
	B_MEM_INIT_SIZE(BNetHttp, B_CONST_MAX_SLOTS*2);
	B_MEM_INIT_SIZE(BNetProxy, B_CONST_MAX_SLOTS*2);
	B_MEM_INIT_SIZE(BRLink, 524288);
	B_MEM_INIT_SIZE(BCookie, 524288);
	B_MEM_INIT_SIZE(BWriteS, 524288);
	B_MEM_INIT_SIZE_BUF();

	// ����������� ���-�� ���������� �������� NET
	GlobBCount++;

	// ���������� ������-�����
	if(BMaster == NULL){
		BMaster = self;
		// ������������ ���-�� ������ ������ ��� ��������� ��������� ���������� ���-�� � 2 ����
		B_MEM_INIT_SIZE(BCacheDNS, B_DNS_CACHE*2);
	}

	// ����� ���������� ����� ������ ����
	Py_XINCREF(self->onLoop);

	return 0;

memerror:
	PyErr_NoMemory();
	return -1;
}


// ��������� ������ ������
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
	Py_VISIT(self->http.xmlHand);
	Py_VISIT(self->proxy.onRequest);
	Py_VISIT(self->proxy.onRequest);
    return 0;
}

static int BManager_tp_clear(BManager *self){
	Py_CLEAR(self->onLoop);
	Py_CLEAR(self->http.onRequest);
	Py_CLEAR(self->http.onResponse);
	Py_CLEAR(self->http.xmlHand);
	Py_CLEAR(self->proxy.onRequest);
	Py_CLEAR(self->proxy.onRequest);
    return 0;
}

static void BManager_tp_dealloc(BManager *self){
	int i;

	// ������������� �������� ��������� �������� ������
	BManager_tp_clear(self);

	// � ������ ������ ��������� ������ - ����������� ������ ����������
	for(i=0; i<B_FINAL_BODY; i++){
		if(self->http.fbuf_bufs[i]) free(self->http.fbuf_bufs[i]);
	}

	// ��������� �������� ���������
	B_STACK_CLEAR(BNetHttp);
	B_STACK_CLEAR(BNetProxy);
	B_STACK_CLEAR(BRLink);
	B_STACK_CLEAR(BCookie);
	B_STACK_CLEAR(BWriteS);
	B_STACK_CLEAR_BUF();

	// ������� ������ ��-��� DNS
	if(self == BMaster){
		B_STACK_CLEAR(BCacheDNS);
		BMaster = NULL;
	}

    // ����������� ���
	uv_rwlock_destroy(&self->stop.lock);

	// ��������� ���
	if(self->http.dns.servers){
		free(self->http.dns.servers);
	}

	// ������������ ssl
	if(self->ssl){
		NSS_ShutdownContext(self->ssl);
	}

	// ��������� ����
	uv_loop_close(&self->loop);

	//BManager_tp_clear(self);
    Py_TYPE(self)->tp_free(self);
}


static PyMethodDef BManager_tp_methods[] = {
    { "queries_http", (PyCFunction)BManager_func_queries_http, METH_KEYWORDS, "Adds a new http-connection" },
    { "queries_proxy", (PyCFunction)BManager_func_queries_proxy, METH_KEYWORDS, "Adds a new proxy for checker" },
    { "set_params", (PyCFunction)BManager_func_set_params, METH_KEYWORDS, "Set params to BManager object" },
    { "run", (PyCFunction)BManager_func_run, METH_NOARGS, "Run uv loop" },
    { "stop", (PyCFunction)BManager_func_stop, METH_NOARGS, "Stop uv loop" },
    { NULL }
};


PyObject *BNetwork_func_BGetStrError(BManager *self, PyObject *args){

	u_long errorType = 0;
	int error = 0;
	const char *errorStr = NULL;
	PyObject *errorStrPy = NULL;

	if (!PyArg_ParseTuple(args, "Ii", &errorType, &error)) {
		return NULL;
	}

	// �������� ������ ������
	errorStr = BErrorStr(errorType, error);

	// �������� �����-����� ������ ������
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

	// ������������� DNS-������
	BInitDNSModule();

	// ������������� ���� ��� ������
	B_MALLOC_INITLOCK;

    /* Initialize GIL */
    PyEval_InitThreads();

	mod = Py_InitModule("BNetwork", BNetwork_tp_methods);

	// �������������� ����� �����������
    if (PyType_Ready(&BXmlHandType)) {
        return;
    }
	// ������ ��������������� ������� ����������, ������� ����������� ������� ������
    Py_INCREF(&BXmlHandType);
    // ��������� ����� NetManager � ������
    if (PyModule_AddObject(mod, "BXmlHand", (PyObject *)&BXmlHandType)) {
        Py_DECREF(&BXmlHandType);
        return;
    }

	// �������������� �����
    if (PyType_Ready(&BManagerType)) {
        return;
    }
	// ������ ��������������� ������� ����������, ������� ����������� ������� ������
    Py_INCREF(&BManagerType);
    // ��������� ����� NetManager � ������
    if (PyModule_AddObject(mod, "BManager", (PyObject *)&BManagerType)) {
        Py_DECREF(&BManagerType);
        return;
    }

    // �������� ������� ���� ����������
    PyModule_AddIntConstant(mod, "BA_URL", BA_URL);
    PyModule_AddIntConstant(mod, "BA_ACTION", BA_ACTION);
    PyModule_AddIntConstant(mod, "BA_DATA", BA_DATA);
    PyModule_AddIntConstant(mod, "BA_ZIP", BA_ZIP);
    PyModule_AddIntConstant(mod, "BA_UAGENT", BA_UAGENT);
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


    // �������� ������� ����� ��������� � ������
    PyModule_AddIntConstant(mod, "BH_GET", B_HTTP_GET);
    PyModule_AddIntConstant(mod, "BH_POST", B_HTTP_POST);
    PyModule_AddIntConstant(mod, "BH_HEAD", B_HTTP_HEAD);
    PyModule_AddIntConstant(mod, "BH_EMUL_HEAD", B_HTTP_EMUL_HEAD); // ����. ������� �������, ��� ������� ���������� ������ GET, �� ����� ����� ������� ����� ��������� ������
    PyModule_AddIntConstant(mod, "BH_CONNECT", B_HTTP_CONNECT);

    // �������� ������� ����� �������� � ������
    PyModule_AddIntConstant(mod, "BH_CLOSE", B_HTTP_CLOSE);
    PyModule_AddIntConstant(mod, "BH_KEEP", B_HTTP_KEEP);

    // �������� ������� ����� ������ � ������
    PyModule_AddIntConstant(mod, "BP_HTTP", B_PROXY_HTTP);
    PyModule_AddIntConstant(mod, "BP_HTTPS", B_PROXY_HTTPS);
    PyModule_AddIntConstant(mod, "BP_SOCKS4", B_PROXY_SOCKS4);
    PyModule_AddIntConstant(mod, "BP_SOCKS5", B_PROXY_SOCKS5);


    // �������������� ��������� ������
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

