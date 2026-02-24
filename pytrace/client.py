import json
import asyncio
from process import Process
from interface import Interface

class Client:

    STATE_DEAD = -1
    STATE_IDLE = 0
    STATE_RUNNING = 1
    STATE_WAIT = 2

    WS_CMD_STDIN = "WS_CMD_STDIN"
    WS_CMD_STDOUT = "WS_CMD_STDOUT"
    WS_CMD_START = "WS_CMD_START"
    WS_CMD_WAIT = "WS_CMD_WAIT"
    WS_CMD_STEP = "WS_CMD_STEP"
    WS_CMD_STOP = "WS_CMD_STOP"
    WS_CMD_STATE = "WS_CMD_STATE"
    WS_CMD_DATA = "WS_CMD_DATA"
    
    def __init__(self, ws):
        self.ws = ws
        self.state = Client.STATE_IDLE
        self.process = None
        self.process_task = None

    #########################################################################################
    # Functions related to managing the WebSocket object                                    #
    #########################################################################################

    async def disconnect(self):
        '''
        Disconnect the websocket.  This will cause this client object
        to become unusable.  Intended for use when the client is 
        either closed or forced closed.
        '''
        if self.ws is not None:
            try:
                await self.reset_client()
                await self.ws.close(code=1001)
            except:
                pass
            finally:
                self.ws = None
        self.state = Client.STATE_DEAD
        print(f"[{self}] => Disconnected")

    async def send_ws(self, cmd, content):
        '''
        Send a message via the websocket.
        '''
        message = {"CMD" : cmd, "CONTENT" : content}
        if self.ws is None:
            print(f"[{self}] => ERROR: Websocket is unexpectedly closed when sending [{message}]")
            return
        await self.ws.send(json.dumps(message))

    async def send_ws_terminal(self, text):
        '''
        Send text via STDOUT directly to the client terminal.
        '''
        content = {"TEXT" : text}
        await self.send_ws(Client.WS_CMD_STDOUT, content)

    #########################################################################################
    # Functions related to managing the state of the Client                                 #
    #########################################################################################

    async def set_state(self, state):
        '''
        Set the state and send the STATE command to the client.
        '''
        self.state = state
        content = {"STATE" : state}
        await self.send_ws(Client.WS_CMD_STATE, content)

    async def reset_client(self):
        ''' 
        Terminate the client process but keep the websocket active
        '''
        if self.process is not None:
            try:
                await self.process.stop()
            except:
                pass
            finally:
                self.process = None
        
        if self.process_task is not None:
            try:
                self.process_task.cancel()
                await self.process_task
            except:
                pass
            finally:
                self.process_task = None      

    #########################################################################################
    # Functions related to handling messages from the WebScoket object                      #
    #########################################################################################

    async def handle_ws(self):
        '''
        Read messages on the websocket for the client.  The loop
        will end if an exception occurs for a closed client or
        if self.ws is None (which should not happen).
        '''
        print(f"[{self}] => Connected")
        try:
            while True:
                message = await self.ws.receive()
                await self.handle_ws_msg(message)
        except:
            pass
        finally:
            await self.disconnect()

    async def handle_ws_msg(self, json_message):
        '''
        Process the websocket messages: STDIN, START, STEP, STOP
        '''
        try:
            message = json.loads(json_message)
            cmd = message["CMD"]
            content = message["CONTENT"]
        except:
            print(f"[{self}] => ERROR: Message not proper JSON format [{message}]")
            return
        
        match cmd:
            case Client.WS_CMD_STDIN:
                await self.handle_ws_stdin(content)
            case Client.WS_CMD_START:
                await self.handle_ws_start(content)
            case Client.WS_CMD_STEP:
                await self.handle_ws_step(content)
            case Client.WS_CMD_STOP:
                await self.handle_ws_stop(content)
            case _:
                print(f"[{self}] => ERROR: Invalid message type from websocket [{cmd}]")


    async def handle_ws_stdin(self, content):
        '''
        Instruct process to receive STDIN text from the client.  No change
        to the state.
        '''
        try:
            text = content["TEXT"]
        except:
            print(f"[{self}] => ERROR: Invalid STDIN CONTENT [{content}]")
            return
        if self.process is None or self.process_task is None:
            print(f"[{self}] => ERROR: Process does not exist to forward STDIN")
            return
        await self.process.forward(text)

    async def handle_ws_start(self, content):
        '''
        Create a new Process object with the code and create a asyncio task to run
        the process.  Change to RUNNING state.
        '''
        try:
            code = content["CODE"]
        except:
            print(f"[{self}] => ERROR: Invalid START CONTENT [{content}]")
            return

        if self.process is not None or self.process_task is not None:
            print(f"[{self}] => ERROR: Unexpected process exists when attempting to START")
            return
        await self.send_ws_terminal("\n--- PROGRAM STARTED ---\n")
        self.process = Process(code, self.handle_process_msg)
        self.process_task = asyncio.create_task(self.process.start())  
        await self.set_state(Client.STATE_RUNNING)      

    async def handle_ws_step(self, content):
        '''
        Instruct process to step to the next line of code. Change state to 
        RUNNING state.
        '''
        if self.process is None or self.process_task is None:
            print("[{self}] => ERROR: Process does not exist to forward STEP")
            return
        await self.set_state(Client.STATE_RUNNING)
        await self.process.proceed()
        
    async def handle_ws_stop(self, content):
        '''
        Stop process early and reset the client.  Change state to IDLE.
        '''
        await self.reset_client()
        await self.set_state(Client.STATE_IDLE)
        await self.send_ws_terminal("\n--- PROGRAM STOPPED ---\n")


    #########################################################################################
    # Functions related to handling messages from the Process object                        #
    #########################################################################################

    async def handle_process_msg(self, message):
        try:
            cmd = message["CMD"]
            content = message["CONTENT"]
        except:
            print(f"[{self}] => ERROR: Message not proper dictionary format [{message}]")
            return
        
        match cmd:
            case Interface.PROC_CMD_DATA:
                await self.handle_process_data(content)
            case Interface.PROC_CMD_STDOUT:
                await self.handle_process_stdout(content)
            case Interface.PROC_CMD_COMPLETED:
                await self.handle_process_completed(content)
            case _:
                print(f"[{self}] => ERROR: Invalid message type from process [{cmd}]")

    async def handle_process_data(self, content):
        '''
        Handle request from process to move to transmit DATA to the Client
        and move to the WAIT state.
        '''
        await self.send_ws(Client.WS_CMD_DATA, content)
        await self.set_state(Client.STATE_WAIT)
        
    async def handle_process_stdout(self, content):
        '''
        Handle request from the process to forward stdout to the client.
        '''
        try:
            text = content["TEXT"]
        except:
            print(f"[{self}] => ERROR: Invalid STDOUT CONTENT [{content}]")
            return
        content = {"TEXT" : text}
        await self.send_ws(Client.WS_CMD_STDOUT, content)
  
    async def handle_process_completed(self, content):
        '''
        Handle request from the process indicating that the process is completed
        '''
        if self.state == Client.STATE_RUNNING:
            await self.send_ws_terminal("\n--- PROGRAM COMPLETED ---\n")
        await self.reset_client()
        await self.set_state(Client.STATE_IDLE)
        


   
            