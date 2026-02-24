import quart as qt
from client import Client

# Create the Quart App and also the AppManager to track clients
app = qt.Quart(__name__)

# Configure the Quart App
app.config.update({
    "SECRET_KEY" : "dev"
});

# Handle request for browser root request
@app.route("/")
async def index():
    return await qt.render_template("browser.html")

# Create the websocket which will formally create a Client 
# object.  If the websocket closes, then this function will 
# return.
@app.websocket("/ws")
async def ws():
    client = Client(qt.websocket)
    try:
        await client.handle_ws()
    except:
        pass
    finally:
        pass



