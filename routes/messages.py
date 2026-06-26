from quart import Blueprint, Response, request, jsonify, send_file, current_app, make_response
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    MessageMediaPoll, DocumentAttributeSticker, 
    DocumentAttributeAudio, DocumentAttributeVideo, Document
)
from PIL import Image
from telethon.helpers import TotalList
from telethon import functions
from client import validate_input
from encryption import encrypt_binary, get_media_token, decrypt_binary
import io

bp_messages = Blueprint("messages", __name__)

def get_message_types(message, session_id=None):
    if not message: return None

    sender = getattr(message, "sender", None)
    sender_id = getattr(sender, "id", 0) or 0
    sender_name = str(getattr(sender, "first_name", "")) or "User" if sender else "Unknown"
    raw_text = getattr(message, "message", "") or ""

    message_data = {
        "id": getattr(message, "id", 0) or 0,
        "sender": sender_name,
        "senderId": sender_id,
        "text": str(raw_text), 
        "date": message.date.isoformat() if getattr(message, "date", None) else "",
        "isOutgoing": bool(getattr(message, "out", False)),
        "type": "text",
        "mediaToken": "",
        "hasMedia": False,
        "mediaInfo": {
            "hasThumb": False,
            "fileName": "",
            "mimeType": "",
            "size": 0,
            "emoji": "",
            "isAnimated": False,
            "isVideo": False,
            "isVoice": False,
            "duration": 0,
            "title": "",
            "performer": ""
        }
    }

    if getattr(message, "action", None):
        message_data["type"] = "system"

    if getattr(message, "media", None):
        message_data["hasMedia"] = True
        
        match message.media:
            case MessageMediaPhoto():
                message_data["type"] = "photo"
                message_data["mediaInfo"]["hasThumb"] = True
                
            case MessageMediaPoll(poll=poll):
                message_data["type"] = "poll"
                message_data["text"] = f"📊 {poll.question}" if poll.question else "📊 Poll"
                
            case MessageMediaDocument(document=doc) if doc:
                message_data["type"] = "document"
                message_data["mediaInfo"]["mimeType"] = getattr(doc, "mime_type", "application/octet-stream")
                message_data["mediaInfo"]["size"] = getattr(doc, "size", 0)
                
                is_sticker = False
                is_audio = False
                
                for attr in doc.attributes:
                    if isinstance(attr, DocumentAttributeSticker):
                        is_sticker = True
                        message_data["type"] = "sticker"
                        message_data["mediaInfo"]["emoji"] = str(getattr(attr, "alt", ""))
                        message_data["mediaInfo"]["isAnimated"] = message_data["mediaInfo"]["mimeType"] == "application/x-tgsticker"
                        message_data["mediaInfo"]["isVideo"] = message_data["mediaInfo"]["mimeType"] == "video/webm"
                        message_data["mediaInfo"]["hasThumb"] = True
                        break
                        
                    elif isinstance(attr, DocumentAttributeAudio):
                        is_audio = True
                        message_data["type"] = "audio"
                        message_data["mediaInfo"]["duration"] = int(getattr(attr, "duration", 0))
                        message_data["mediaInfo"]["title"] = str(getattr(attr, "title", "Untitled"))
                        message_data["mediaInfo"]["performer"] = str(getattr(attr, "performer", "Unknown"))
                        if getattr(attr, "voice", False):
                            message_data["type"] = "voice"
                            message_data["mediaInfo"]["isVoice"] = True
                        break
                        
                    elif isinstance(attr, DocumentAttributeVideo):
                        message_data["mediaInfo"]["isVideo"] = True
                        message_data["mediaInfo"]["duration"] = int(getattr(attr, "duration", 0))
                        message_data["mediaInfo"]["hasThumb"] = True
                        if getattr(attr, "round_message", False):
                            message_data["type"] = "videoNote"
                        else:
                            message_data["type"] = "video"
                        break
                        
                    elif hasattr(attr, "file_name"):
                        message_data["mediaInfo"]["fileName"] = attr.file_name
                        
                if not is_sticker and not is_audio and not message_data["mediaInfo"]["isVideo"] and not message_data["mediaInfo"]["fileName"]:
                    message_data["mediaInfo"]["fileName"] = "document"
            case _: pass

    if session_id and message_data["hasMedia"] and message_data["type"] not in ["text", "system"]:
        message_data["mediaToken"] = get_media_token(session_id, message_data["id"])

    return message_data


@bp_messages.route("/messages", methods=["GET"])
async def get_messages():
    res = await validate_input("session_id", "chat_id")
    if res[1]: return res[1]
    
    data = res[0]
    client, session_data, args = data

    session_id = args["session_id"]
    chat_id = int(args["chat_id"] if args["chat_id"] else 0)
    aes_key = session_data[0]
    
    limit = int(request.args.get("limit", 50))
    offset_id = int(request.args.get("offsetId", 0))
    
    try:
        messages = []
        async for message in client.iter_messages(chat_id, limit=limit, offset_id=offset_id):
            msg_parsed = get_message_types(message, session_id)
            if msg_parsed:
                messages.append(msg_parsed)

        binary_payload = encrypt_binary({"messages": messages}, aes_key)
        return Response(binary_payload, mimetype="application/octet-stream")
    except Exception as e:
        current_app.logger.error(f"Error getting messages: {str(e)}")
        return jsonify({"error": str(e)}), 500


@bp_messages.route("/avatar", methods=["GET"])
async def get_avatar():
    res = await validate_input("session_id", "user_id")
    if res[1]: return res[1]
    
    data = res[0]
    assert data is not None
    client, _, args = data
    
    if args["user_id"] == "me": 
        me = await client.get_me()
        user_id = getattr(me, "id")
    else:  
        user_id = int(args["user_id"] if args["user_id"] else 0)

    size = request.args.get("size")

    try:
        output = io.BytesIO()
        result = await client.download_profile_photo(user_id, file=output, download_big=False)
        if not result: return jsonify({"error": "no_avatar"}), 404
            
        output.seek(0)
        if size:
            try:
                target_size = int(size)
                img = Image.open(output)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                
                img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
                
                new_output = io.BytesIO()
                img.save(new_output, format="JPEG", quality=85)
                new_output.seek(0)
                return await send_file(new_output, mimetype="image/jpeg")
            except Exception as e:
                current_app.logger.warning(f"Avatar resize failed: {e}")
                output.seek(0)

        return await send_file(output, mimetype="image/jpeg")
    except Exception as e:
        current_app.logger.error(f"Avatar download error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@bp_messages.route("/get_media", methods=["GET"])
async def get_media():
    res = await validate_input("session_id") 
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

    user_id = None
    media = None
    is_sticker = False
    doc = None
    
    if raw_uid:
        if raw_uid == "me":
            me = await client.get_me()
            user_id = getattr(me, "id")
        else: user_id = int(raw_uid)

    try:
        if music_id and user_id:
            try:
                saved_music = await client(functions.users.GetSavedMusicRequest(
                    id=user_id, offset=0, limit=20, hash=0
                ))
                media = next((d for d in getattr(saved_music, "documents", []) if str(d.id) == str(music_id)), None)
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
            image_buf = io.BytesIO()
            thumbs = getattr(media, "thumbs", None) or getattr(media, "sizes", None)
            if not thumbs and doc: thumbs = getattr(doc, "thumbs", None)

            if thumbs:
                target_thumb = thumbs[1] if len(thumbs) > 1 else thumbs[0]
                await client.download_media(media, file=image_buf, thumb=target_thumb)
            else:
                if isinstance(media, MessageMediaPhoto): await client.download_media(media, file=image_buf, thumb=1) 
                else: return jsonify({"error": "No thumb available"}), 404
            
            image_buf.seek(0)
            try:
                img = Image.open(image_buf)
                png_buf = io.BytesIO()
                if img.mode != "RGBA": img = img.convert("RGBA")
                img.save(png_buf, format="PNG")
                png_buf.seek(0)
                return await send_file(png_buf, mimetype="image/png")
            except Exception as e:
                current_app.logger.error(f"PNG Conversion failed: {e}")
                image_buf.seek(0)
                return await send_file(image_buf, mimetype="image/jpeg")

        file_size = getattr(doc, "size", 0) if doc else 0
        if not file_size and isinstance(media, MessageMediaPhoto):
            image_buf = io.BytesIO()
            await client.download_media(media, file=image_buf)
            image_buf.seek(0)
            return await send_file(image_buf, mimetype="image/jpeg")

        mime = getattr(doc, "mime_type", "application/octet-stream") if doc else "application/octet-stream"
        range_header = request.headers.get("Range")

        if range_header and file_size:
            byte_range = range_header.replace("bytes=", "").split("-")
            start = int(byte_range[0]) if byte_range[0] else 0
            end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1

            if start >= file_size:
                return Response(status=416, headers={"Content-Range": f"bytes */{file_size}"})

            length = end - start + 1

            CHUNK_SIZE = 524288
            aligned_start = (start // CHUNK_SIZE) * CHUNK_SIZE
            skip_bytes = start - aligned_start

            async def generate_chunked():
                downloaded = 0
                skipped = 0
                
                async for chunk in client.iter_download(media, offset=aligned_start, request_size=CHUNK_SIZE):
                    if skipped < skip_bytes:
                        if skipped + len(chunk) <= skip_bytes:
                            skipped += len(chunk)
                            continue
                        else:
                            chunk = chunk[skip_bytes - skipped:]
                            skipped = skip_bytes
                    
                    chunk_len = len(chunk)
                    if downloaded + chunk_len > length:
                        yield chunk[:length - downloaded]
                        break
                    yield chunk
                    downloaded += chunk_len

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Type": mime
            }
            return Response(generate_chunked(), status=206, headers=headers)
        else:
            async def generate_full():
                async for chunk in client.iter_download(media):
                    yield chunk

            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size) if file_size else None,
                "Content-Type": mime
            }
            return Response(generate_full(), status=200, headers=headers)

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

    chat_id = args["chat_id"]
    aes_key = session_data[0]

    encrypted_body = await request.get_data()
    if not encrypted_body: return jsonify({"error": "Empty request body"}), 400

    decrypted_data = decrypt_binary(encrypted_body, aes_key)
    if decrypted_data is None: return jsonify({"error": "Decryption failed"}), 400
    
    text = decrypted_data.get("text")
    if not chat_id or not text: return jsonify({"error": "Missing text"}), 400
    
    try:
        message = await client.send_message(int(chat_id), str(text))
        response_data = {
            "status": "ok",
            "id": message.id,
            "date": message.date.isoformat() if message.date else None
        }
    except Exception as e:
        current_app.logger.error(f"Error sending message: {str(e)}")
        response_data = {"error": str(e)}

    binary_payload = encrypt_binary(response_data, aes_key)
    return Response(binary_payload, mimetype="application/octet-stream")

@bp_messages.route("/send_media", methods=["POST"])
async def send_media():
    res = await validate_input("session_id", "chat_id")
    if res[1]: return res[1]
    data = res[0]
    assert data is not None
    client, session_data, args = data
    
    chat_id = args["chat_id"]
    aes_key = session_data[0]
    
    form = await request.form
    files = await request.files
    
    file_obj = files.get("file")
    if not file_obj:
        return jsonify({"error": "No file uploaded"}), 400
        
    file_bytes = io.BytesIO(file_obj.read())
    file_bytes.name = file_obj.filename or "file.ext"
    
    caption = form.get("caption", "")
    # expecting: photo, document, voice, videoNote, video
    media_type = form.get("type", "document")
    
    force_document = media_type == "document"
    voice_note = media_type == "voice"
    video_note = media_type == "videoNote"
    is_video = media_type == "video"
    
    try:
        message = await client.send_file(
            int(chat_id),
            file=file_bytes,
            caption=caption,
            force_document=force_document,
            voice_note=voice_note,
            video_note=video_note,
            is_video=is_video
        )
        response_data = {
            "status": "ok",
            "id": message.id,
            "date": message.date.isoformat() if message.date else None
        }
    except Exception as e:
        current_app.logger.error(f"Error sending media: {e}")
        response_data = {"error": str(e)}
        
    binary_payload = encrypt_binary(response_data, aes_key)
    return Response(binary_payload, mimetype="application/octet-stream")