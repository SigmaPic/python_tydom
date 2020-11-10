# Python Tydom
Another simple python implementation to access Tydom gateway.

Based on:
 - https://github.com/mrwiwi/tydom2mqtt
 - https://github.com/cth35/tydom_python (I contributed)


# Why using this implementation?
 - Very easy to use!!!
 - Fully asynchronous (asyncio async/await)
 - Manage tydom push request through callback
 - Optional keep alive through ping command
 - Automatic reconnection on keep alive failure
 - Easy to integrate into an home automation system (Home Assistant, Jeedom...)
 - No MQTT

# Tydom Push request
Tydom gateway automatically sends a push request when an event occurs (alarm mode change).
This means that an incoming PUT request is received on the websocket.

# Requirements
  - Python >= 3.5
 - websockets

# Limitations
- Tested in local mode only (local ip connection)
- Low level command implementation (no feature abstraction)

# Sample Code

```python
def  callback(uri, data):
    print(uri, data)

async def demo():
    # create tydom instance
    tydom = Tydom("00ABCDEF1234", "123456", host='192.168.0.20', request_handler=callback)

    # connect to tydom
    await tydom.connect(keep_alive_delay=None)
    
    # get data
    while True:
        data = await tydom.get_device_data(0)
        print(data)
        await asyncio.sleep(5)
        
asyncio.get_event_loop().run_until_complete(demo())
```
