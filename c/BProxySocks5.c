

#include "BNetwork.h"


int BSendProxySocks5(BNet *netObj){

	BProxy *proxy = &netObj->proxy;
	// смещение в буфере записи
	size_t sr = 0;
	// буфер отправки
	char data[1024];

	// обнуляем смещение прокси
	proxy->seek = 0;

	// все запросы начинаются с версии протокола
	data[sr++] = 0x05;

	// если это старт запроса
	switch(netObj->state){
		// инициализация протокола
		case B_NST_PROXY_SOCKS5_INIT:
			if(proxy->user.len){
				data[sr++] = 0x02;
				data[sr++] = 0x00;
				data[sr++] = 0x02;
			}
			else{
				data[sr++] = 0x01;
				data[sr++] = 0x00;
			}
			break;

		// сервер запросил авторизацию
		case B_NST_PROXY_SOCKS5_AUTH:
			// пишем длину имени юзера
			data[sr++] = proxy->user.len;
			memcpy(data+sr, proxy->user.str, proxy->user.len);

			sr += proxy->user.len;

			// пишем длину пароля юзера
			data[sr++] = proxy->passwd.len;
			memcpy(data+sr, proxy->passwd.str, proxy->passwd.len);

			sr += proxy->passwd.len;

			break;

		// отправляем запрос на коннект
		case B_NST_PROXY_SOCKS5_COMMAND:{
			// преобразовываем указатель бинарных данных на указатель на ip4 структуру
			struct sockaddr_in* addr = (struct sockaddr_in*)&(netObj->url->bin);

			// пишем команду
			data[sr++] = 0x01;
			// зарезервирован
			data[sr++] = 0x00;
			// тип - ip4
			data[sr++] = 0x01;
			// пишем сам ip
			memcpy(data+sr, (char*)&(addr->sin_addr.s_addr), 4);

			sr += 4;

			// пишем порт
			memcpy(data+sr, (char*)&(addr->sin_port), 2);

			sr += 2;

			break;
		}
	}

	// выполняем отправку собранного буфера
	return BWriteBuf(netObj, data, sr);
}


/*
 * Метод разбирает постпившие данные на основании протокола socks5
 * */
int BRecvProxySocks5(BNet *netObj, size_t nread){
	BProxy *proxy = &netObj->proxy;
	size_t k;
	int err;
	char ch;

	//BPS("\nRESPONSE: ");

	// перебираем полученный буфер
	for(k=0; k < nread; proxy->seek++, k++){

		// очередной символ из потока ответа прокси
		ch = netObj->rBuf->buf[k];

		//BPS("0x%x ", ch);

		// проверяем номер версии
		if(proxy->seek == 0 && ch != 0x05){
			B_ERROR(B_E_NET_PROXY_S5_VER, NET);
			return -1;
		}
		else{

			// выполняем побайтовую проверку
			switch(proxy->seek){

				case 1:
					// инициализация
					if(netObj->state == B_NST_PROXY_SOCKS5_INIT){
						if(ch == 0x00){
							netObj->state = B_NST_PROXY_SOCKS5_COMMAND;
						}
						else if(ch == 0x02){
							// сервер требует авторизации - проверяем наличие данных авторизации
							if(proxy->user.len == 0){
								B_ERROR(B_E_NET_PROXY_S5_NEED_AUTH, NET);
								return -1;
							}

							netObj->state = B_NST_PROXY_SOCKS5_AUTH;
						}
						else{
							B_ERROR(B_E_NET_PROXY_S5_TYPEAUTH, NET);
							return -1;
						}

						// выполняем отправку очередного запроса
						return BSendProxySocks5(netObj);
					}
					// авторизация
					else if(netObj->state == B_NST_PROXY_SOCKS5_AUTH){
						if(ch == 0x00){
							netObj->state = B_NST_PROXY_SOCKS5_COMMAND;
						}
						else{
							B_ERROR(B_E_NET_PROXY_S5_AUTH, NET);
							return -1;
						}

						// выполняем отправку очередного запроса
						return BSendProxySocks5(netObj);
					}
					// соединение
					else if(netObj->state == B_NST_PROXY_SOCKS5_COMMAND){
						// значение байта - значение ошибки
						if((err = ch) != 0){
							// если значение ошибки не определено - приводим ее к корректоному значению
							if(err < 1 || err > 9)
								err = 9;

							B_ERROR(B_E_NET_PROXY_S5_CMD_1 - 1 + err, NET);
							return -1;
						}
					}

					break;

				// 3-й байт всегда неопределен
				case 2:
					break;

				// 4-ый - тип адреса
				case 3:
					if(ch == 0x01){
						proxy->skip = 4;
					}
					else if(ch == 0x03){
						proxy->skip = -1;
					}
					else if(ch == 0x04){
						proxy->skip = 16;
					}
					else{
						B_ERROR(B_E_NET_PROXY_S5_ADDR, NET);
						return -1;
					}

					break;

				// 5-ый - первый байт адреса (или кол-во байтов в домене)
				case 4:
					if(proxy->skip == -1){
						proxy->skip = ch;
					}
					else{
						proxy->skip--;
					}

					// именно на этом шаге добавляем в пропускаемые байты 2 байта порта
					proxy->skip += 2;

					break;

				default:
					// выполнение http-запроса возможно только после прочтения всех байт из соединения
					if(--(proxy->skip) == 0){
						return BProxyTunnelReady(netObj);
					}
					break;
			}
		}
	}

	//BPS("\n");

	return 0;
}
