from quart import Blueprint, send_file, current_app, request, jsonify, make_response
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from io import BytesIO
from config import Config
import os, uuid, qrcode, db, asyncio

active_clients = {}
bp_client = Blueprint("client", __name__)
login_lock = asyncio.Lock()
cfg = Config()
proxy = {"proxy_type": "socks5", "addr": cfg.PROXY_ADDR, "port": cfg.PROXY_PORT}

async def wait_for_scan_task(qr_login, session_id):
    try:
        await qr_login.wait()
        current_app.logger.debug(f"New session: {session_id}")
        await db.activate_session(session_id)
    except Exception as e:
        current_app.logger.error(f"Login error for {session_id}: {e}")
        if session_id in active_clients: del active_clients[session_id]

async def get_client(session_id, session_data):
    client = active_clients.get(session_id)
    async def try_connect(cli):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await asyncio.wait_for(cli.connect(), timeout=10)
                if await cli.is_user_authorized(): return True
                return False
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                current_app.logger.error(f"Attempt {attempt+1}: Server is dead: {e}")
                return False
        return False

    if client:
        if client.is_connected():
            return client
        if await try_connect(client):
            return client
        return None

    async with login_lock:
        if session_id in active_clients: return active_clients[session_id]
        if not session_data: session_data = await db.get_session_data(session_id)
        assert session_data is not None

        session_file_path = os.path.join(cfg.SESSIONS_DIR, session_data[1])
        client = TelegramClient(
            session_file_path, 
            cfg.API_ID, 
            cfg.API_HASH, 
            proxy=proxy,
            connection_retries=1,
            retry_delay=1
        )
        
        if await try_connect(client):
            active_clients[session_id] = client
            return client
        
        return None

async def get_minimal_thumb(media):
    # parsing thumb sizes for different documents
    sizes = []
    if isinstance(media, MessageMediaPhoto): sizes = getattr(media.photo, "sizes", [])
    elif isinstance(media, MessageMediaDocument): sizes = getattr(media.document, "thumbs", [])
    
    # parsing minimal size
    if not sizes: return None
    for target_type in ["s", "m"]:
        for size in sizes:
            if getattr(size, "type", "") == target_type:
                return size
    for s in sizes:
        if hasattr(size, "size"):
            return size
            
    return sizes[0] if sizes else None

async def validate_input(*required_args):
    args = {arg: request.args.get(arg) for arg in required_args}
    for arg, val in args.items():
        if not val: return None, await make_response(jsonify({"error": f"Missing {arg}"}), 400)

    session_id = request.args.get("session_id")
    if not session_id: return None, await make_response(jsonify({"error": "No session ID"}), 401)

    session_data = await db.get_session_data(session_id)
    if not session_data: return None, await make_response(jsonify({"error": "Invalid session"}), 403)

    client = await get_client(session_id, session_data=session_data)
    if not client: return None, await make_response(jsonify({"error": "Telegram client not authorized"}), 401)
    return (client, session_data, args), None

@bp_client.route("/qr")
async def qr_init():
    session_id = str(uuid.uuid4())
    aes_key = os.urandom(16)
    session_file = "refraction_" + session_id

    image_buf = BytesIO()
    qr_obj = None
    client = TelegramClient(
        os.path.join(cfg.SESSIONS_DIR, session_file), 
        cfg.API_ID, 
        cfg.API_HASH, 
        proxy=proxy,
        connection_retries=1,
        retry_delay=1
    )

    try:
        await asyncio.wait_for(client.connect(), timeout=10)
        qr_obj = await asyncio.wait_for(client.qr_login(), timeout=10)
        
        if not qr_obj: return jsonify({"error": "Could not generate QR code"}), 500

        active_clients[session_id] = client
        await db.create_pending_session(session_id, aes_key, session_file)
        current_app.add_background_task(wait_for_scan_task, qr_obj, session_id)

        img = qrcode.make(qr_obj.url)
        img.save(image_buf, "PNG")
        image_buf.seek(0)
        
        response = await send_file(image_buf, mimetype="image/png")
        response.headers["X-Session-ID"] = session_id
        response.headers["X-AES-Key"] = aes_key.hex()
        return response

    except Exception as e:
        current_app.logger.critical(f"QR Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500