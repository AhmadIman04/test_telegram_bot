from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from threading import Thread
import uvicorn


# 1. Create the FastAPI app
app = FastAPI()

# 2. Create the route that returns "Alive"
@app.get("/", response_class=PlainTextResponse)
def index():
    return "Alive"

# 3. Define how to run the server
def run():
    # FastAPI requires Uvicorn to run the server
    uvicorn.run(app, host="0.0.0.0", port=8080)

# 4. Start the server in a background thread
def keep_alive():
    t = Thread(target=run)
    t.start()