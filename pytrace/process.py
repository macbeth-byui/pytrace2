import textwrap
import pty
import os
import uuid
import asyncio
import sys
import json
from interface import Interface

class Process:

    def __init__(self, code, callback):
        self.code = code
        self.callback = callback
        self.pty = None
        self.server_name = None
        self.process = None
        self.pty = None
        self.server_writer = None

    async def start(self):
        if self.process is not None:
            print(f"[{self}] => ERROR: Process already exists when starting process")
            return
        full_code = (Process.TRACE_CODE 
            + "\ndef __run__():\n"
            + textwrap.indent(self.code, "    ")
            + "\ntry:\n"
            + "\n    __run__()"
            + "\nexcept KeyboardInterrupt:"
            + "\n    pass")
        
        self.pty, pty_subprocess = pty.openpty()
        server_name = f"pytrace_{str(uuid.uuid4())}.sock"
        server = await asyncio.start_unix_server(self.handle_server, path=server_name)
        os.chmod(server_name, 0o660)
        env = os.environ.copy()
        env['SOCK_PATH'] = server_name
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c", full_code,
            stdout = pty_subprocess,
            stderr = pty_subprocess,
            stdin = pty_subprocess,
            close_fds = True,
            env = env)
        os.close(pty_subprocess)
        print("DEBUG: Started Process and Server")
        await self.handle_process_reader()
        print("DEBUG: Cleaning Up Process and Server")
        await self.process.wait()
        os.close(self.pty)
        server.close()
        await server.wait_closed()
        os.remove(server_name)
        self.process = None
        message = {"CMD" : Interface.PROC_CMD_COMPLETED, "CONTENT" : {}}
        await self.callback(message)

    async def handle_process_reader(self):
        queue = asyncio.Queue()
        pty_loop = asyncio.get_running_loop()
        pty_loop.add_reader(self.pty, on_read)

        def on_read():
            try:
                data = os.read(self.pty, 1024)
            except:
                data = b""
            finally:
                if data:
                    queue.put_nowait(data)
                else:
                    queue.put_nowait(None)
        
        while True:
            text = await queue.get()
            print("DEBUG: TEXT = {text}")
            if text is None:
                break
            text = text.decode("utf-8")
            message = {"CMD" : Interface.PROC_CMD_STDOUT, "CONTENT" : { "TEXT" : text}}
            await self.callback(message)

        pty_loop.remove_reader(self.pty)

    async def handle_server(self, reader, writer):
        self.server_writer = writer
        try:
            while True:
                json_message = await reader.read(4096)
                if not json_message:
                    break
                decoded_json_message = json_message.decode("UTF-8").rstrip("\n")
                print(f"DEBUG: {decoded_json_message}")
                content = json.loads(decoded_json_message)
                message = {"CMD" : Interface.PROC_CMD_DATA, "CONTENT" : content}
                await self.callback(message)
        finally:
            try:
                print("DEBUG: Attempting to close writer")
                writer.close()
                await writer.wait_closed()
                self.server_writer = None
            except:
                pass
            

    async def stop(self):
        if self.process is not None:
            try:
                self.process.kill()
            finally:
                await self.process.wait()
                self.process = None  

    async def proceed(self):
        print("DEBUG: Proceed")
        if self.server_writer is None:
            print(f"[{self}] => ERROR: Server Writer does not exist to proceed")
            return
        self.server_writer.write(b"PROCEED\n")
        await self.server_writer.drain()

    async def forward(self, text):
        if self.pty is None:
            print(f"[{self}] => ERROR: PTY does not exist to forward STDIN")
            return
        os.write(self.pty, text.encode("utf-8"))

    TRACE_CODE = \
"""import sys
import socket
import json
import os
def trace(frame, event, arg):
    if event == "line" and frame.f_code.co_filename == "<string>": 
        sock_path = os.environ.get("SOCK_PATH")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            data = json.dumps({
                "line": frame.f_lineno - 19,
                "file": frame.f_code.co_filename,
                "variables": frame.f_locals
            })
            s.connect(sock_path)
            s.sendall(data.encode("utf-8"))
            print(s.recv(4096).decode("utf-8"))
    return trace
sys.settrace(trace)"""