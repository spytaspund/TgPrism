from quart import Quart, render_template, request, g
from rich.logging import RichHandler
from rich.console import Console
from routes.messages import bp_messages
from routes.chats import bp_chats
from client import bp_client
from config import Config
import logging, time, db

app = Quart(__name__)
cfg = Config()
console = Console()
logging.basicConfig(
    level=cfg.LOG_LEVEL,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, console=console, show_path=False, markup=True)]
)

@app.before_serving
async def startup():
    await db.init_db()

@app.route("/")
async def helloPage():
    return await render_template("index.html")

# logging things
@app.before_request
async def start_timer():
    g.start_time = time.time()

@app.after_request
async def log_request(response):
    if request.path != "/favicon.ico":
        process_time = (time.time() - g.start_time) * 1000
        method = f"{request.method:<7}"
        path = f"{request.path:<25}"
        addr = f"({request.remote_addr})"
        log_msg = f"{method} {path} -> {response.status_code} {addr} {process_time:.1f}ms"
        logging.info(log_msg)
    return response

if __name__ == "__main__":
    logging.getLogger("quart.serving").disabled = True
    logging.getLogger("hypercorn.access").disabled = True
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.INFO)
    app.register_blueprint(bp_chats)
    app.register_blueprint(bp_messages)
    app.register_blueprint(bp_client)
    app.run(host="0.0.0.0", port=cfg.SERVER_PORT, debug=False)