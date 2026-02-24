import sys
import socket
import json
import os
import traceback

def trace(frame, event, arg):
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
                "line": frame.f_lineno - 29,  # length of this code + 2
                "file": frame.f_code.co_filename,
                "variables": variables
            })
            # try:
            #     s.connect(sock_path)
            #     s.sendall(data.encode("utf-8"))
            #     _ = s.recv(4096)
            # except:
            #     sys.exit()
    return trace

    sys.settrace(trace)
try:
    exec({code})
except SyntaxError as e:
    print()
    print("EXCEPTION OCCURRED")
    print("==================")
    print(f"{type(e).__name__}: {e.msg}")
    print(f"(Row {e.lineno}, Col {e.offset})")

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
                stack.append((None, tb[i].lineno, tb[i].colno))
            else:
                stack.append((tb[i].name, tb[i].lineno, tb[i].colno))
    space = ""
    if len(stack) > 0:
        for (name,line,position) in reversed(stack):
            if name is None:
                print(f"(Row {line}, Col {position})")
            else:
                print(f"{space}\u2514\u2500\u25b6 Inside [{name}] (Row {line}, Col {position})")
            space += "       "



