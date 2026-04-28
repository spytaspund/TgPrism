from quart import Quart, render_template, request, g
from rich.logging import RichHandler
from rich.console import Console
from routes.messages import bp_messages
from routes.chats import bp_chats
from client import bp_client
from config import Config
import logging, time, db, httpx

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
    repo_url = "https://api.github.com/repos/spytaspund/ReflectoGram/releases"
    latest_version = "No Release"
    ipa_url = "#"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(repo_url)
            if response.status_code == 200:
                releases = response.json()
                if releases:
                    latest_data = releases[0] 
                    latest_version = latest_data.get('tag_name', 'Unknown')
                    if latest_data.get('prerelease'): latest_version += " (Pre-release)"
                    for asset in latest_data.get('assets', []):
                        if asset['name'].endswith('.ipa'):
                            ipa_url = asset['browser_download_url']
                            break
            else: app.logger.warning(f"GitHub API error {response.status_code}")
    except Exception as e: app.logger.error(f"GitHub API Error: {e}")
    return await render_template("index.html", version=latest_version, ipa_url=ipa_url)

@app.route("/install/manifest.plist")
async def manifest():
    return await render_template("manifest.xml", ipa_url=request.args.get("url", "")), 200, {'Content-Type': 'application/xml'}

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