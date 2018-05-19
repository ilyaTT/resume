

#include "BNetwork.h"


int BSendProxySocks5(BNet *netObj){

	BProxy *proxy = &netObj->proxy;
	// �������� � ������ ������
	size_t sr = 0;
	// ����� ��������
	char data[1024];

	// �������� �������� ������
	proxy->seek = 0;

	// ��� ������� ���������� � ������ ���������
	data[sr++] = 0x05;

	// ���� ��� ����� �������
	switch(netObj->state){
		// ������������� ���������
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

		// ������ �������� �����������
		case B_NST_PROXY_SOCKS5_AUTH:
			// ����� ����� ����� �����
			data[sr++] = proxy->user.len;
			memcpy(data+sr, proxy->user.str, proxy->user.len);

			sr += proxy->user.len;

			// ����� ����� ������ �����
			data[sr++] = proxy->passwd.len;
			memcpy(data+sr, proxy->passwd.str, proxy->passwd.len);

			sr += proxy->passwd.len;

			break;

		// ���������� ������ �� �������
		case B_NST_PROXY_SOCKS5_COMMAND:{
			// ��������������� ��������� �������� ������ �� ��������� �� ip4 ���������
			struct sockaddr_in* addr = (struct sockaddr_in*)&(netObj->url->bin);

			// ����� �������
			data[sr++] = 0x01;
			// ��������������
			data[sr++] = 0x00;
			// ��� - ip4
			data[sr++] = 0x01;
			// ����� ��� ip
			memcpy(data+sr, (char*)&(addr->sin_addr.s_addr), 4);

			sr += 4;

			// ����� ����
			memcpy(data+sr, (char*)&(addr->sin_port), 2);

			sr += 2;

			break;
		}
	}

	// ��������� �������� ���������� ������
	return BWriteBuf(netObj, data, sr);
}


/*
 * ����� ��������� ���������� ������ �� ��������� ��������� socks5
 * */
int BRecvProxySocks5(BNet *netObj, size_t nread){
	BProxy *proxy = &netObj->proxy;
	size_t k;
	int err;
	char ch;

	//BPS("\nRESPONSE: ");

	// ���������� ���������� �����
	for(k=0; k < nread; proxy->seek++, k++){

		// ��������� ������ �� ������ ������ ������
		ch = netObj->rBuf->buf[k];

		//BPS("0x%x ", ch);

		// ��������� ����� ������
		if(proxy->seek == 0 && ch != 0x05){
			B_ERROR(B_E_NET_PROXY_S5_VER, NET);
			return -1;
		}
		else{

			// ��������� ���������� ��������
			switch(proxy->seek){

				case 1:
					// �������������
					if(netObj->state == B_NST_PROXY_SOCKS5_INIT){
						if(ch == 0x00){
							netObj->state = B_NST_PROXY_SOCKS5_COMMAND;
						}
						else if(ch == 0x02){
							// ������ ������� ����������� - ��������� ������� ������ �����������
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

						// ��������� �������� ���������� �������
						return BSendProxySocks5(netObj);
					}
					// �����������
					else if(netObj->state == B_NST_PROXY_SOCKS5_AUTH){
						if(ch == 0x00){
							netObj->state = B_NST_PROXY_SOCKS5_COMMAND;
						}
						else{
							B_ERROR(B_E_NET_PROXY_S5_AUTH, NET);
							return -1;
						}

						// ��������� �������� ���������� �������
						return BSendProxySocks5(netObj);
					}
					// ����������
					else if(netObj->state == B_NST_PROXY_SOCKS5_COMMAND){
						// �������� ����� - �������� ������
						if((err = ch) != 0){
							// ���� �������� ������ �� ���������� - �������� �� � ������������ ��������
							if(err < 1 || err > 9)
								err = 9;

							B_ERROR(B_E_NET_PROXY_S5_CMD_1 - 1 + err, NET);
							return -1;
						}
					}

					break;

				// 3-� ���� ������ �����������
				case 2:
					break;

				// 4-�� - ��� ������
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

				// 5-�� - ������ ���� ������ (��� ���-�� ������ � ������)
				case 4:
					if(proxy->skip == -1){
						proxy->skip = ch;
					}
					else{
						proxy->skip--;
					}

					// ������ �� ���� ���� ��������� � ������������ ����� 2 ����� �����
					proxy->skip += 2;

					break;

				default:
					// ���������� http-������� �������� ������ ����� ��������� ���� ���� �� ����������
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
