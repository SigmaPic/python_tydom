import asyncio
import websockets
import http.client
from requests.auth import HTTPDigestAuth
import os
import base64
import ssl
from io import BytesIO
import json
import aiohttp
import re

# def print(*args,**kwargs):
#     pass


class BytesIOSocket:
    def __init__(self, content):
        self.handle = BytesIO(content)

    def makefile(self, mode):
        return self.handle



class Tydom():

    def __init__(self, mac, password, host='mediation.tydom.com', request_handler=None):

        self.password = password
        self.mac = mac
        self.host = host
        self.connection = None
        self.ssl_context = None
        self.cmd_prefix = "\x02"
        self._is_connected = False
        self.lock = None 
        self._request_handler = request_handler
        self._keep_alive_task_object = None
        self._receive_task_object = None

        # Set Host, ssl context and prefix for remote or local connection
        if self.host == "mediation.tydom.com":
            self.remote_mode = True
            self.ssl_context = None # None = check ssl
            self.cmd_prefix = "\x02"
            self.ping_timeout = 40
        else:
            self.remote_mode = False
            self.ssl_context = False # False = do not check ssl
            self.cmd_prefix = ""
            self.ping_timeout = None

    ###############################################################
    # Private                                                     #
    ###############################################################
 
    def _generate_random_key(self):
        '''
        Generate 16 bytes random key for Sec-WebSocket-Keyand convert it to base64
        '''
        return base64.b64encode(os.urandom(16))

    def _build_digest_headers(self, nonce):
        '''
        Build the headers of Digest Authentication
        '''
        digestAuth = HTTPDigestAuth(self.mac, self.password)
        chal = dict()
        chal["nonce"] = nonce[2].split('=', 1)[1].split('"')[1]
        chal["realm"] = "ServiceMedia" if self.remote_mode is True else "protected area"
        chal["qop"] = "auth"
        digestAuth._thread_local.chal = chal
        digestAuth._thread_local.last_nonce = nonce
        digestAuth._thread_local.nonce_count = 1
        return digestAuth.build_digest_header('GET', "https://{}:443/mediation/client?mac={}&appli=1".format(self.host, self.mac))


    async def _send_message(self, method, msg):
        '''
        Send message to tydom server and wait response
        Return response as a dict or None if response has no data
        '''
        txt = self.cmd_prefix + method +' ' + msg +" HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        a_bytes = bytes(txt, "ascii")
        if not 'pwd' in msg:
            print('>>>>>> Send Request:', method, msg)
        else:
            print('>>>>>> Send Request:', method, 'secret msg')

        await self.connection.send(a_bytes)

        # get response from response queue
        return await self._response_queue.get()   
 
    async def _receive_task(self):
        '''
        Manage incoming requests and responses
        - responses are pushed in _response_queue
        - requests are decoded and configured callback is called
        '''
        while True:
            # read response
            raw_resp = await self.connection.recv()
                        
            # remove prefix
            raw_resp = raw_resp[len(self.cmd_prefix):]
            
            if raw_resp[0:4].decode("utf-8") == 'HTTP':
                self._decode_response(raw_resp)
            else:
                self._decode_request(raw_resp)
    
    def _decode_request(self, raw):
        print('<<<<<< Receive Request:', raw)
    
        if self._request_handler is not None:
            # extract uri
            uri = re.search(b'PUT (.*) HTTP/1.1', raw).group(1)
            uri = uri.decode("utf-8")
            
            # convert request into response in order to parse it with HTTPResponse
            raw = re.sub(b'PUT .* HTTP/1.1', b'HTTP/1.1 200 OK', raw)
            
            # create fake socket
            sock = BytesIOSocket(raw)
            response = http.client.HTTPResponse(sock)
            
            response.begin()
            
            # read content
            content = response.read(len(raw))
            
            data = content.decode("utf-8")
            
            if data != '':
                data = json.loads(data)
            else:
                data = None
        
            self._request_handler(uri, data)
        
    
    def _decode_response(self, raw):
        print('<<<<<< Receive Response:', raw)
        
        # create fake socket
        sock = BytesIOSocket(raw)
        response = http.client.HTTPResponse(sock)
        
        response.begin()
        
        # read content
        content = response.read(len(raw))
        
        data = content.decode("utf-8")
        
        if data != '':
            data = json.loads(data)
        else:
            data = None
    
        self._response_queue.put_nowait(data)
    
    async def _async_keep_alive_task(self):
        '''
        This task manages keep alive by periodically sending a ping command to keep the connection alive.
        Open a new connection if ping fails.
        '''
        while True:
            try:
                await self.get_ping()
            except Exception as e:
                print('Keep alive failed. Try to reconnect.')
                await asyncio.sleep(2)
                await self.connect(self.keep_alive_delay)

            await asyncio.sleep(self.keep_alive_delay)

    

    ###############################################################
    # Public                                                      #
    ###############################################################

    def is_connected(self):
        return self._is_connected
 
     
 
    async def connect(self, keep_alive_delay=None):
        
        if self.lock is None:
            self.lock = asyncio.Lock()
             
        async with self.lock:
            print('Connecting to tydom', self.host)

            self._is_connected = False
     
            httpHeaders =  {"Connection": "Upgrade",
                            "Upgrade": "websocket",
                            "Host": self.host + ":443",
                            "Accept": "*/*",
                            "Sec-WebSocket-Key": self._generate_random_key(),
                            "Sec-WebSocket-Version": "13"
                            }
             
            # Get authentication
            async with aiohttp.ClientSession() as session:
                async with session.get("https://{}/mediation/client?mac={}&appli=1".format(self.host, self.mac), ssl=self.ssl_context) as r:
                    nonce = r.headers["WWW-Authenticate"].split(',', 3)
     
            # Build websocket headers
            websocketHeaders = {'Authorization': self._build_digest_headers(nonce)}
     
            if self.ssl_context is False:
                websocket_ssl_context = ssl._create_unverified_context()
            else:
                websocket_ssl_context = True # Verify certificate
                 
            self.connection = await websockets.client.connect('wss://{}:443/mediation/client?mac={}&appli=1'.format(self.host, self.mac),
                                                                extra_headers=websocketHeaders, ssl=websocket_ssl_context, ping_timeout=self.ping_timeout)
            
            # setup receiver task
            if self._receive_task_object is not None:
                self._receive_task_object.cancel()
            
            self._receive_task_object = asyncio.get_event_loop().create_task(self._receive_task())
            
            self._response_queue = asyncio.Queue(maxsize=1)
            
            # setup keep alive
            self.keep_alive_delay = keep_alive_delay
            
            if self._keep_alive_task_object is not None:
                self._keep_alive_task_object.cancel()
            
            if keep_alive_delay is not None:
                self._keep_alive_task_object = asyncio.get_event_loop().create_task(self._async_keep_alive_task())
 
 
            self._is_connected = True
  
    # Get some information on Tydom
    async def get_info(self):
        async with self.lock:
            msg_type = '/info'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)

    # Refresh (all)
    async def post_refresh(self):
        async with self.lock:
            # print("Refresh....")
            msg_type = '/refresh/all'
            req = 'POST'
            return await self._send_message(method=req, msg=msg_type)

    # Get the moments (programs)
    async def get_moments(self):
        async with self.lock:
            msg_type = '/moments/file'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)

    # Get the scenarios
    async def get_scenarii(self):
        async with self.lock:
            msg_type = '/scenarios/file'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)


    # Get a ping (pong should be returned)
    async def get_ping(self):
        async with self.lock:
            msg_type = '/ping'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)


    # Get all devices metadata
    async def get_devices_meta(self):
        async with self.lock:
            msg_type = '/devices/meta'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)


    # Get all devices data
    async def get_devices_data(self):
        async with self.lock:
            msg_type = '/devices/data'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)


    # List the device to get the endpoint id
    async def get_configs_file(self):
        async with self.lock:
            msg_type = '/configs/file'
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)

    async def get_data(self):
        async with self.lock:
            await self.get_configs_file()
            await asyncio.sleep(1)
            await self.get_devices_data()

    # GET tydom device data/state
    async def get_device_data(self, id):
        async with self.lock:
            msg_type = '/devices/{}/endpoints/{}/data'.format(id, id)
            req = 'GET'
            return await self._send_message(method=req, msg=msg_type)
    



def  callback(uri, data):
    print(uri, data)


async def demo():
    # create tydom instance
    tydom = Tydom("00ABCDEF1234", "123456", host='192.168.0.3', request_handler=callback)

    # connect to tydom
    await tydom.connect(keep_alive_delay=None)
    
    # get data
    while True:
        data = await tydom.get_device_data(0)
        print(data)
        await asyncio.sleep(5)
    


if __name__ == '__main__':

    asyncio.get_event_loop().run_until_complete(demo())










