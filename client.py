import os
import uuid
import qrcode
import asyncio
from io import BytesIO
from quart import Blueprint, send_file, current_app, request, jsonify, make_response
from telethon import TelegramClient
from config import Config
from connection import ProxyManager
import db

bp_client = Blueprint("client", __name__)
active_clients = {}
login_lock = asyncio.Lock()
cfg = Config()
proxy_manager = ProxyManager()

async def ensure_connection(client):
    for attempt in range(3):
        try:
            if cfg.PROXY_TYPE == "local": await asyncio.sleep(1)
            await asyncio.wait_for(client.connect(), timeout=12)
            return True
        except (ConnectionError, asyncio.TimeoutError) as e:
            current_app.logger.warning(f"Connection attempt {attempt+1} failed: {e}")
            await asyncio.sleep(2)
    return False

async def get_client(session_id, session_data=None):
    if session_id in active_clients:
        client = active_clients[session_id]
        if client.is_connected():
            return client
        if await ensure_connection(client):
            return client

    async with login_lock:
        if not session_data:
            session_data = await db.get_session_data(session_id)
        if not session_data:
            return None

        session_path = os.path.join(cfg.SESSIONS_DIR, session_data[1])
        client_proxy = proxy_manager.get_telethon_proxy()
        client_args = {
            "session": session_path,
            "api_id": cfg.API_ID,
            "api_hash": cfg.API_HASH,
            "connection_retries": 2,
            "retry_delay": 2
        }
        if client_proxy: client_args["proxy"] = client_proxy
        client = TelegramClient(**client_args) # all of that to silence linter
        
        if await ensure_connection(client):
            active_clients[session_id] = client
            return client
    return None

@bp_client.route("/qr", methods=["GET"])
async def qr_init():
    session_id = str(uuid.uuid4())
    aes_key = os.urandom(16)
    session_file = f"refraction_{session_id}"
    
    current_app.logger.info(f"Generating QR for new session: {session_id}")
    
    client_args = {
        'session': os.path.join(cfg.SESSIONS_DIR, session_file),
        'api_id': cfg.API_ID,
        'api_hash': cfg.API_HASH
    }
    proxy = proxy_manager.get_telethon_proxy()
    if proxy: client_args['proxy'] = proxy

    client = TelegramClient(**client_args)

    try:
        if not await ensure_connection(client):
            return jsonify({"error": "Failed to connect to Telegram servers (Proxy issue?)"}), 503

        qr_obj = await asyncio.wait_for(client.qr_login(), timeout=15)
        if not qr_obj:
            return jsonify({"error": "QR generation failed"}), 500

        active_clients[session_id] = client
        await db.create_pending_session(session_id, aes_key, session_file)
        
        current_app.add_background_task(wait_for_login, qr_obj, session_id)

        img = qrcode.make(qr_obj.url)
        buf = BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        
        resp = await send_file(buf, mimetype="image/png")
        resp.headers["X-Session-ID"] = session_id
        resp.headers["X-AES-Key"] = aes_key.hex()
        return resp

    except Exception as e:
        current_app.logger.error(f"QR Init Critical Error: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

async def wait_for_login(qr_obj, session_id):
    try:
        await qr_obj.wait()
        await db.activate_session(session_id)
        current_app.logger.info(f"Session {session_id} successfully authorized!")
    except Exception as e:
        current_app.logger.error(f"Wait for login failed for {session_id}: {e}")
        if session_id in active_clients:
            await active_clients[session_id].disconnect()
            del active_clients[session_id]

async def validate_input(*required_args):
    session_id = request.args.get("session_id")
    if not session_id:
        return None, await make_response(jsonify({"error": "No session ID"}), 401)

    args = {arg: request.args.get(arg) for arg in required_args}
    for arg, val in args.items():
        if not val:
            return None, await make_response(jsonify({"error": f"Missing {arg}"}), 400)

    session_data = await db.get_session_data(session_id)
    if not session_data:
        return None, await make_response(jsonify({"error": "Invalid session"}), 403)

    client = await get_client(session_id, session_data)
    if not client or not await client.is_user_authorized():
        return None, await make_response(jsonify({"error": "Not authorized"}), 401)
    
    return (client, session_data, args), None