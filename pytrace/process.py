import textwrap
import pty
import os
import uuid
import asyncio
import json
from interface import Interface

class Process:

    def __init__(self, code, callback):
        self.code = code
        self.callback = callback
        self.pty = None
        self.server_name = None
        self.server = None
        self.process = None
        self.pty = None
        self.server_writer = None

    #########################################################################################
    # Functions related to starting the process that runs the code                          #
    #########################################################################################

    async def start(self):
        '''
        Start a new process running the python code.
        '''
        if self.process is not None:
            print(f"[{self}] => ERROR: Process already exists when starting process")
            return
        if self.server is not None:
            print(f"[{self}] => ERROR: Server already exists when starting process")
            return
        if self.server_name is not None:
            print(f"[{self}] => ERROR: Server name already exists when starting process")
            return
        if self.pty is not None:
            print(f"[{self}] => ERROR: PTY already exists when starting process")
            return
        
        x = """
        "How are you?", he said.
        """
        
        # Wrap code with TRACE_CODE to enable communication back to the client
        full_code = Process.START_CODE + f"\n        exec(\"\"\"\n{self.code}\n\"\"\",ns, ns)\n" + Process.END_CODE
        
        # Create a PTY for both sides for stdout/stdin forwarding
        # PTY is a pseudo terminal interface
        self.pty, pty_subprocess = pty.openpty()

        # Create a server for process to communicate status of the program
        self.server_name = f"sockets/pytrace_{str(uuid.uuid4())}.sock"
        container_server_name = f"/sockets/{os.path.basename(self.server_name)}" 
        os.makedirs("sockets", exist_ok=True)
        os.chmod("sockets", 0o777)       
        self.server = await asyncio.start_unix_server(self.handle_server, path=self.server_name)
        os.chmod(self.server_name, 0o666)

        # Start the process.  
        self.process = await asyncio.create_subprocess_exec(
            "docker", "run", "-u", f"{os.getuid()}:{os.getgid()}", "--rm", "-it", 
            "-v", f"{os.getcwd()}/sockets:/sockets", "-e", f"SERVER_NAME={container_server_name}", 
            "python:3.11-slim", "python", "-u", "-c", full_code,
            stdout = pty_subprocess,
            stderr = pty_subprocess,
            stdin = pty_subprocess,
            close_fds = True)
        
        # We don't need the process side of the PTY anymore
        os.close(pty_subprocess)

        # Read STDOUT until the process completes
        await self.handle_process_reader()

        # Verify the process has completely closed
        # and then cleanup and send message back to Client
        # that the program is completed
        await self.process.wait()
        self.process = None
        await self.completed()

    async def handle_process_reader(self):
        '''
        Read STDOUT from the process via the PTY.  Forward
        any text to the Client
        '''

        # Create a queue to manage all the STDOUT received
        queue = asyncio.Queue()
        pty_loop = asyncio.get_running_loop()

        def on_read():
            '''
            Read process STDOUT from the PTY and put it in the queue
            for processing by handle_process_reader
            '''
            try:
                data = os.read(self.pty, 1024)
                queue.put_nowait(data)
            except:
                # This will cause the handle_process_reader
                # to exit and return back to the start function.
                queue.put_nowait(None)

        # Connect the PTY as a reader on the current execution loop
        pty_loop.add_reader(self.pty, on_read)
        while True:
            text = await queue.get()
            if text is None:
                # When None, then the STDOUT has been closed
                break
            # Forward the STDOUT to the client
            text = text.decode("utf-8")
            message = {"CMD" : Interface.PROC_CMD_STDOUT, "CONTENT" : { "TEXT" : text}}
            await self.callback(message)

        # When STDOUT is closed, remove the PTY as a reader
        pty_loop.remove_reader(self.pty)

    async def handle_server(self, reader, writer):
        '''
        Handles all data messages sent to the server from the code process.  These messages
        are forwarded to the client.
        '''
        if self.server_writer is not None:
            print(f"[{self}] => ERROR: Server Writer already exists when starting process")
            return
        
        # Save the current writer so it can be used in other functions to forward STDIN
        self.server_writer = writer
        try:
            while True:
                # Read messages sent by the client until None is returned by handle_process_reader
                json_message = await reader.read(4096)
                if json_message is None:
                    break

                # Convert the data received into a dictionary and send to the client
                decoded_json_message = json_message.decode("UTF-8").rstrip("\n")
                content = json.loads(decoded_json_message)
                message = {"CMD" : Interface.PROC_CMD_DATA, "CONTENT" : content}
                await self.callback(message)
        except:
            pass
        finally:
            try:
                # Runs when the server is closed
                writer.close()
                await writer.wait_closed()
            except:
                pass
            finally:
                self.server_writer = None

    #########################################################################################
    # Functions related to stopping (or cleaning up) the process that runs the code         #
    #########################################################################################
            
    async def stop(self):
        '''
        Shutdown the server, process, and pty if they have not already be closed.
        '''
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.process is not None:
            try:
                self.process.kill()
            except:
                pass
            finally:
                await self.process.wait()
                self.process = None  
        if self.pty is not None:
            os.close(self.pty)
            self.pty = None
        if self.server_name is not None:
            os.remove(self.server_name)
            self.server_name = None

    async def completed(self):
        '''
        If a process has completed naturally, then perform the stop function
        and then provide a completed indication to the client.  This is not sent
        if the process did not complete naturally.
        '''
        await self.stop()
        message = {"CMD" : Interface.PROC_CMD_COMPLETED, "CONTENT" : {}}
        await self.callback(message)

    #########################################################################################
    # Functions related to commands from the client and code process.                       #
    #########################################################################################

    async def proceed(self):
        '''
        Direct the code process to proceed to the next line of code
        '''
        if self.server_writer is None:
            print(f"[{self}] => ERROR: Server Writer does not exist to proceed")
            return
        # The word PROCEED is not checked by the code running in the process
        self.server_writer.write(b"PROCEED\n")
        await self.server_writer.drain()

    async def forward(self, text):
        '''
        Direct STDIN text to be used by the code process
        '''
        if self.pty is None:
            print(f"[{self}] => ERROR: PTY does not exist to forward STDIN")
            return
        os.write(self.pty, text.encode("utf-8"))

    START_CODE = \
"""import sys
import socket
import json
import os
import traceback

def trace(frame, event, arg):
    # print(event,frame.f_code.co_name,frame.f_lineno,frame.f_code.co_filename)
    if event == "line" and frame.f_code.co_filename == "<string>": 
        sock_path = os.environ.get("SERVER_NAME")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            variables = {}
            for (name, value) in frame.f_locals.items():
                try:
                    json.dumps(value)
                    variables[name] = value
                except:
                    pass
            data = json.dumps({
                "line": frame.f_lineno - 1, # Lines of Code in this string
                "file": frame.f_code.co_filename,
                "variables": variables
            })
            try:
                s.connect(sock_path)
                s.sendall(data.encode("utf-8"))
                _ = s.recv(4096)
            except:
                sys.exit()
    return trace

def __pytrace():
    sys.settrace(trace)
    ns = dict()
    try:
"""

    END_CODE = \
"""

    except SyntaxError as e:
        print()
        print("EXCEPTION OCCURRED")
        print("==================")
        print(f"{type(e).__name__}: {e.msg}")
        print(f"Row {e.lineno-1}")

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        stack = []
        print()
        print("EXCEPTION OCCURRED")
        print("==================")
        print(f"{type(e).__name__}: {str(e)}")
        for i in range(len(tb)-1, -1, -1):
            if tb[i].filename == "<string>":
                if tb[i].name == "<module>":
                    stack.append((None, tb[i].lineno-1))
                elif tb[i].name != "__pytrace":
                    stack.append((tb[i].name, tb[i].lineno-1))
        space = ""
        if len(stack) > 0:
            for (name,line) in reversed(stack):
                if name is None:
                    print(f"Row {line}")
                else:
                    print(f"{space}\u2514\u2500\u25b6 Inside [{name}] (Row {line})")
                space += "   "

__pytrace()
"""