import os
import uuid
import qrcode
import asyncio
from io import BytesIO
from collections import defaultdict
from quart import Blueprint, send_file, current_app, request, jsonify, make_response
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate
from sqlite3 import OperationalError
from config import Config
from connection import ProxyManager
import db

bp_client = Blueprint("client", __name__)
active_clients = {}

session_locks = defaultdict(asyncio.Lock)
login_lock = asyncio.Lock()
cfg = Config()
proxy_manager = ProxyManager()

@bp_client.before_app_serving
async def start_garbage_collector():
    async def session_garbage_collector():
        while True:
            try:
                await db.cleanup_old_sessions(days_inactive=30)
                current_app.logger.info("Database cleaned: old sessions removed.")
            except Exception as e:
                current_app.logger.error(f"Garbage collector error: {e}")
            await asyncio.sleep(86400)
            
    current_app.add_background_task(session_garbage_collector)

async def get_client(session_id, session_data=None):
    async with session_locks[session_id]:
        if session_id in active_clients:
            client = active_clients[session_id]
            if client.is_connected():           return client
            if await ensure_connection(client): return client
            else:                               del active_clients[session_id]

    async with login_lock:
        if not session_data:
            session_data = await db.get_session_data(session_id)
        if not session_data:
            return None

        session_str = session_data[1]
        client_args = {
            "session": StringSession(session_str),
            "api_id": cfg.API_ID,
            "api_hash": cfg.API_HASH,
            "connection_retries": 3, 
            "retry_delay": 1,
            "auto_reconnect": True
        }

        proxy = proxy_manager.get_telethon_proxy()
        if proxy:
            client_args['proxy'] = proxy
            if cfg.PROXY_TYPE == "mtproto":
                client_args['connection'] = ConnectionTcpMTProxyRandomizedIntermediate
        
        client = TelegramClient(**client_args)
        
        if await ensure_connection(client):
            active_clients[session_id] = client
            return client
    return None

@bp_client.route("/qr", methods=["GET"])
async def qr_init():
    session_id = str(uuid.uuid4())
    aes_key = os.urandom(16)
    
    current_app.logger.info(f"Generating QR for new session: {session_id}")
    
    client_args = {
        "session": StringSession(),
        "api_id": cfg.API_ID,
        "api_hash": cfg.API_HASH,
        "connection_retries": 3,
        "retry_delay": 1,
        "auto_reconnect": True
    }
    proxy = proxy_manager.get_telethon_proxy()
    if proxy:
        client_args['proxy'] = proxy
        if cfg.PROXY_TYPE == "mtproto":
            client_args['connection'] = ConnectionTcpMTProxyRandomizedIntermediate

    client = TelegramClient(**client_args)

    try:
        if not await ensure_connection(client):
            return jsonify({"error": "Failed to connect to Telegram servers"}), 503

        qr_obj = await asyncio.wait_for(client.qr_login(), timeout=15)
        if not qr_obj:
            return jsonify({"error": "QR generation failed"}), 500

        active_clients[session_id] = client
        
        await db.create_pending_session(session_id, aes_key)
        current_app.add_background_task(wait_for_login, qr_obj, session_id, client)

        img = qrcode.make(qr_obj.url)
        buf = BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        
        resp = await send_file(buf, mimetype="image/png")
        resp.headers["X-Session-ID"] = session_id
        resp.headers["X-AES-Key"] = aes_key.hex()
        return resp

    except (ConnectionError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e: raise e
    except Exception as e:
        current_app.logger.error(f"QR Init Error: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

async def wait_for_login(qr_obj, session_id, client):
    try:
        await qr_obj.wait()
        session_str = client.session.save()
        await db.save_session_string(session_id, session_str)
        current_app.logger.info(f"Session {session_id} successfully authorized to DB!")
    except Exception as e:
        current_app.logger.error(f"Wait for login failed for {session_id}: {e}")
        if session_id in active_clients:
            await active_clients[session_id].disconnect()
            del active_clients[session_id]

@bp_client.route("/auth/phone", methods=["POST"])
async def auth_phone():
    data = await request.get_json()
    phone = data.get("phone")
    if not phone: return jsonify({"error": "Missing phone"}), 400

    session_id = str(uuid.uuid4())
    aes_key = os.urandom(16)
    
    client_args = {
        "session": StringSession(),
        "api_id": cfg.API_ID,
        "api_hash": cfg.API_HASH,
        "connection_retries": 3,
        "retry_delay": 1,
        "auto_reconnect": True
    }
    proxy = proxy_manager.get_telethon_proxy()
    if proxy:
        client_args['proxy'] = proxy
        if cfg.PROXY_TYPE == "mtproto":
            client_args['connection'] = ConnectionTcpMTProxyRandomizedIntermediate

    client = TelegramClient(**client_args)
    if not await ensure_connection(client):
        return jsonify({"error": "Connection to Telegram failed"}), 503

    try:
        sent = await client.send_code_request(phone)
        active_clients[session_id] = client
        await db.create_pending_session(session_id, aes_key)
        
        return jsonify({
            "session_id": session_id,
            "aes_key": aes_key.hex(),
            "phone_code_hash": sent.phone_code_hash
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp_client.route("/auth/code", methods=["POST"])
async def auth_code():
    data = await request.get_json()
    session_id = data.get("session_id")
    phone = data.get("phone")
    code = data.get("code")
    phone_code_hash = data.get("phone_code_hash")

    if not all([session_id, phone, code, phone_code_hash]):
        return jsonify({"error": "Missing parameters"}), 400

    client = active_clients.get(session_id)
    if not client: return jsonify({"error": "Session expired or invalid"}), 404

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        session_str = client.session.save()
        await db.save_session_string(session_id, session_str)
        return jsonify({"status": "ok"})
    except SessionPasswordNeededError:
        return jsonify({"status": "requires_2fa"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@bp_client.route("/auth/password", methods=["POST"])
async def auth_password():
    data = await request.get_json()
    session_id = data.get("session_id")
    password = data.get("password")

    if not session_id or not password:
        return jsonify({"error": "Missing parameters"}), 400

    client = active_clients.get(session_id)
    if not client: return jsonify({"error": "Session expired or invalid"}), 404

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        await db.save_session_string(session_id, session_str)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@bp_client.route("/logout", methods=["POST"])
async def logout():
    session_id = request.args.get("session_id")
    aes_key_hex = request.headers.get("X-AES-Key")
    
    if not session_id or not aes_key_hex:
        return jsonify({"error": "Missing session_id or aes_key"}), 400

    session_data = await db.get_session_data(session_id)
    if not session_data:
        return jsonify({"error": "Session not found or already deleted"}), 404

    db_aes_key = session_data[0]
    if aes_key_hex != db_aes_key.hex():
        current_app.logger.warning(f"Unauthorized logout attempt for {session_id}")
        return jsonify({"error": "Unauthorized: Invalid AES key"}), 403

    client = await get_client(session_id, session_data)
    if client:
        try:
            async with session_locks[session_id]:
                await client.log_out()
        except Exception as e:
            current_app.logger.warning(f"Telegram server logout failed, wiping locally anyway: {e}")

    await db.delete_session(session_id)
    if session_id in active_clients:
        del active_clients[session_id]
    if session_id in session_locks:
        del session_locks[session_id]

    current_app.logger.info(f"Session {session_id} successfully terminated and wiped.")
    return jsonify({"status": "success", "message": "Session securely terminated"})

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
    if not client:
        return None, await make_response(jsonify({"error": "Not authorized"}), 401)
    
    try:
        async with session_locks[session_id]:
            is_auth = await client.is_user_authorized()
            
    except (ConnectionError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
        current_app.logger.error(f"MTProto connection error: {e}")
        proxy_manager.trigger_rebalance()
        if session_id in active_clients:
            del active_clients[session_id]
        return None, await make_response(jsonify({"error": "Proxy connection lost. Retrying..."}), 503)

    if not is_auth:
        return None, await make_response(jsonify({"error": "Not authorized"}), 401)
    
    current_app.add_background_task(db.update_last_used, session_id)
    return (client, session_data, args), None

async def ensure_connection(client):
    if client.is_connected(): return True
    
    for attempt in range(2):
        try:
            await asyncio.wait_for(client.connect(), timeout=5)
            return True
        except (OSError, asyncio.TimeoutError, OperationalError) as e:
            current_app.logger.warning(f"Connection attempt {attempt+1} failed: {e}")
            
            new_proxy = proxy_manager.get_telethon_proxy()
            if new_proxy:
                client.set_proxy(new_proxy)
            
            await asyncio.sleep(0.5)

    current_app.logger.error("All connection attempts failed. Forcing rebalance...")
    proxy_manager.trigger_rebalance(force=True)
    return False