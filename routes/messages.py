from quart import Blueprint, Response, request, jsonify, send_file, current_app, make_response
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    MessageMediaPoll, MessageMediaWebPage,
    DocumentAttributeSticker, DocumentAttributeAudio, Document
)
from PIL import Image
from telethon.helpers import TotalList
from telethon import functions
from client import validate_input
from encryption import encrypt_binary, get_media_token, decrypt_binary
import io

bp_messages = Blueprint("messages", __name__)

def parse_message_types(message):
    raw_text = getattr(message, "message", "") or ""
    message_data = {
        "id": message.id,
        "text": str(raw_text), 
        "date": message.date.isoformat() if message.date else None,
        "is_outgoing": message.out,
        "type": "text",
        "media_info": None
    }

    if not message.media:
        if getattr(message, "action", None):
            message_data["type"] = "system"
        return message_data

    match message.media:
        case MessageMediaPhoto():
            message_data.update({"type": "photo", "media_info": {"has_thumb": True}})
        case MessageMediaPoll(poll=poll):
            message_data.update({
                "type": "poll",
                "media_info": {
                    "question": str(poll.question),
                    "answers": [{"text": str(a.text), "votes": 0} for a in poll.answers]
                }
            })
        case MessageMediaWebPage(webpage=webpage) if hasattr(webpage, "title"):
            message_data.update({
                "type": "webpage",
                "media_info": {
                    "title": str(getattr(webpage, "title", "")),
                    "description": str(getattr(webpage, "description", "")),
                    "url": str(getattr(webpage, "url", ""))
                }
            })
        case MessageMediaDocument(document=doc) if doc:
            message_data["type"] = "document"
            for attr in doc.attributes:
                match attr:
                    case DocumentAttributeSticker(alt=alt):
                        message_data.update({
                            "type": "sticker",
                            "media_info": {
                                "emoji": str(alt),
                                "is_animated": getattr(doc, "mime_type", "") == "application/x-tgsticker",
                                "is_video": getattr(doc, "mime_type", "") == "video/webm"
                            }
                        })
                        break
                    case DocumentAttributeAudio(duration=dur, title=t, performer=p):
                        message_data.update({
                            "type": "audio",
                            "media_info": {
                                "duration": dur,
                                "title": str(t or "Untitled"),
                                "performer": str(p or "Unknown")
                            }
                        })
                        break
        case _: pass
    return message_data

@bp_messages.route("/messages")
async def get_messages():
    res = await validate_input("session_id", "chat_id")
    if res[1]: return res[1]
    
    data = res[0]
    assert data is not None
    client, session_data, args = data

    session_id = args["session_id"]
    chat_id = int(args["chat_id"] if args["chat_id"] else 0) # pyright strikes again
    aes_key = session_data[0]
    
    try:
        messages = []
        async for message in client.iter_messages(chat_id, limit=50):
            message_data = parse_message_types(message)
            sender = message.sender

            message_data["sender"] = str(getattr(sender, "first_name", "User")) if sender else "Unknown"
            message_data["senderID"] = getattr(sender, "id", 0) if sender else 0
            
            if message_data["type"] not in ["text", "service", "poll", "webpage"]:
                message_data["mediaToken"] = get_media_token(session_id, message.id)
            messages.append(message_data)

        binary_payload = encrypt_binary({"messages": messages}, aes_key)
        return Response(binary_payload, mimetype="application/octet-stream")
    except Exception as e:
        current_app.logger.error(f"Error getting messages: {str(e)}")
        return jsonify({"error": str(e)}), 500

@bp_messages.route("/avatar")
async def get_avatar():
    res = await validate_input("session_id", "user_id")
    if res[1]: return res[1]
    
    data = res[0]
    assert data is not None
    client, _, args = data
    
    if args["user_id"] == "me": 
        me = await client.get_me()
        user_id = getattr(me, "id")
    else:  user_id = int(args["user_id"] if args["user_id"] else 0)

    try:
        output = io.BytesIO()
        result = await client.download_profile_photo(user_id, file=output, download_big=False)
        if not result: return jsonify({"error": "no_avatar"}), 404
            
        output.seek(0)
        return await send_file(output, mimetype="image/jpeg")
    except Exception as e:
        current_app.logger.error(f"Avatar download error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@bp_messages.route("/get_media")
async def get_media():
    res = await validate_input("session_id") # other args is optional!
    if res[1]: return res[1]
    
    data = res[0]
    assert data is not None
    client, _, args = data

    session_id = str(args["session_id"])
    message_id = request.args.get("message_id")
    chat_id = request.args.get("chat_id")
    music_id = request.args.get("music_id")
    raw_uid = request.args.get("user_id")
    
    thumb = request.args.get("thumb") is not None
    token = request.args.get("token")

    # will use these later
    image_buf = io.BytesIO()
    user_id = None
    media = None
    is_sticker = False
    doc = None
    
    if raw_uid:
        if raw_uid == "me":
            me = await client.get_me()
            user_id = getattr(me, "id")
        else:
            user_id = int(raw_uid)

    try:
        if music_id and user_id:
            try:
                saved_music = await client(functions.users.GetSavedMusicRequest(
                    id=user_id, offset=0, limit=20, hash=0
                ))
                media = next((doc for doc in getattr(saved_music, "documents", []) if str(doc.id) == str(music_id)), None)
            except Exception as e:
                return jsonify({"error": f"Failed to fetch profile music: {e}"}), 400
        elif message_id and chat_id:
            if token != get_media_token(session_id, int(message_id)): 
                return await make_response("Forbidden", 403)
            
            result = await client.get_messages(int(chat_id), ids=int(message_id))
            message = result[0] if isinstance(result, TotalList) else result
            if message and hasattr(message, "media"): media = message.media

        if not media: return jsonify({"error": "Media not found"}), 404

        if isinstance(media, MessageMediaDocument): doc = media.document
        elif isinstance(media, Document): doc = media
        if doc and hasattr(doc, "attributes"): is_sticker = any(isinstance(attr, DocumentAttributeSticker) for attr in doc.attributes)
        if is_sticker: thumb = True
        
        if thumb:
            thumbs = getattr(media, "thumbs", None) or getattr(media, "sizes", None)
            if not thumbs and doc:
                thumbs = getattr(doc, "thumbs", None)

            if thumbs:
                if len(thumbs) > 1: target_thumb = thumbs[1]
                else:               target_thumb = thumbs[0]
                
                await client.download_media(media, file=image_buf, thumb=target_thumb)
            else:
                if isinstance(media, MessageMediaPhoto):
                    await client.download_media(media, file=image_buf, thumb=1) 
                else:
                    return jsonify({"error": "No thumb available"}), 404
        else:
            await client.download_media(media, file=image_buf)
            
        image_buf.seek(0)

        # image conversion, primarily for stickers
        if thumb:
            try:
                img = Image.open(image_buf)
                png_buf = io.BytesIO()
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                img.save(png_buf, format="PNG")
                png_buf.seek(0)
                return await send_file(png_buf, mimetype="image/png")
            except Exception as e:
                current_app.logger.error(f"PNG Conversion failed: {e}")
                image_buf.seek(0)

        mime = "application/octet-stream"
        if doc and hasattr(doc, "mime_type"): mime = getattr(doc, "mime_type")
        return await send_file(image_buf, mimetype=mime)

    except Exception as e:
        current_app.logger.error(f"Media download failed: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
@bp_messages.route("/send_message", methods=["POST"])
async def send_message():
    res = await validate_input("session_id", "chat_id")
    if res[1]: return res[1]
    data = res[0]
    assert data is not None
    client, session_data, args = data

    session_id = str(args["session_id"])
    chat_id = args["chat_id"]
    aes_key = session_data[0]

    encrypted_body = await request.get_data()
    if not encrypted_body:
        current_app.logger.warning(f"Empty request body from session {session_id}")
        return jsonify({"error": "Empty request body"}), 400

    decrypted_data = decrypt_binary(encrypted_body, aes_key)
    if decrypted_data is None:
        current_app.logger.error(f"Failed to decrypt message body for session {session_id}")
        return jsonify({"error": "Decryption failed"}), 400
    
    text = decrypted_data.get("text")
    if not chat_id or not text:
        current_app.logger.warning(f"Missing text in payload from session {session_id}")
        return jsonify({"error": "Missing text"}), 400
    
    try:
        current_app.logger.info(f"Sending message to {chat_id} via session {session_id}")
        message = await client.send_message(int(chat_id), str(text))
        response_data = {
            "status": "ok",
            "id": message.id,
            "date": message.date.isoformat() if message.date else None
        }
    except Exception as e:
        current_app.logger.error(f"Error sending message in session {session_id}: {e}")
        response_data = {"error": str(e)}

    binary_payload = encrypt_binary(response_data, aes_key)
    return Response(binary_payload, mimetype="application/octet-stream")