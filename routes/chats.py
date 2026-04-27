from telethon.tl.types import User
from telethon.tl.functions.users import GetFullUserRequest, GetSavedMusicRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth, DocumentAttributeAudio
from quart import Blueprint, Response, jsonify, current_app
from client import validate_input
from encryption import encrypt_binary
from asyncio import gather

bp_chats = Blueprint("chats", __name__)

def get_chat_type(dialog):
    if dialog.is_user: return "user"
    if dialog.is_channel: return "megagroup" if getattr(dialog.entity, "megagroup", False) else "channel"
    if dialog.is_group: return "group"
    return "other"

def seen_online(status):
    match status:
        case UserStatusOnline():               return {"type": 0, "seen_online": 0}
        case UserStatusOffline(was_online=dt): return {"type": 4, "seen_online": int(dt.timestamp())}
        case UserStatusRecently():             return {"type": 1, "seen_online": 0}
        case UserStatusLastWeek():             return {"type": 2, "seen_online": 0}
        case UserStatusLastMonth():            return {"type": 3, "seen_online": 0}
        case _:                                return {"type": 1, "seen_online": 0}

async def fetch_private_channel(client, pc_id: int):
    try:
        ch_entity = await client.get_entity(pc_id)
        full_ch, history = await gather(client(GetFullChannelRequest(ch_entity)), client.get_messages(ch_entity, limit=1))
        return {
            "id": ch_entity.id,
            "title": getattr(ch_entity, "title", "Channel"),
            "username": getattr(ch_entity, "username", None),
            "subs_count": getattr(full_ch.full_chat, "participants_count", 0),
            "last_post": history[0].message if history else None
        }
    except Exception as e:
        current_app.logger.error(f"Error parsing private channel: {e}")
        return {"id": pc_id, "title": "Private Channel", "subs_count": 0, "last_post": None}

async def get_about(entity, client):
    is_user = isinstance(entity, User)
    name = getattr(entity, "first_name", "") or getattr(entity, "title", "Unknown")

    if is_user: chat_type = "user"
    else: chat_type = "channel" if getattr(entity, "broadcast", False) else "group"

    results = {
        "bio": "",
        "personal_channel": None,
        "about_music": [],
        "members": []
    }

    try:
        if is_user:
            tasks = [
                client(GetFullUserRequest(entity)),
                client(GetSavedMusicRequest(id=entity, offset=0, limit=10, hash=0))
            ]
            responses = await gather(*tasks, return_exceptions=True)
            
            if not isinstance(responses[0], Exception):
                full_u = responses[0].full_user
                results["bio"] = full_u.about or ""
                
                pc_id = getattr(full_u, "personal_channel_id", None)
                if pc_id: results["personal_channel"] = await fetch_private_channel(client, pc_id)

            if not isinstance(responses[1], Exception):
                for doc in getattr(responses[1], "documents", []):
                    audio = next((a for a in doc.attributes if isinstance(a, DocumentAttributeAudio)), None)
                    if audio:
                        results["about_music"].append({
                            "id": str(doc.id),
                            "performer": str(getattr(audio, "performer", "Unknown")),
                            "title": str(getattr(audio, "title", "Untitled")),
                            "duration": getattr(audio, "duration", 0)
                        })

        else:
            full_chat_info = await client(GetFullChannelRequest(entity))
            results["bio"] = full_chat_info.full_chat.about or ""
            
            if chat_type == "group":
                async for user in client.iter_participants(entity, limit=50):
                    results["members"].append({
                        "id": user.id,
                        "name": getattr(user, "first_name", "") or "User",
                        "last_seen": seen_online(user.status) if getattr(user, "status", None) else {"type": 1, "seen_online": 0}
                    })

    except Exception as e:
        current_app.logger.error(f"Get_about error: {e}")

    return {
        "id": entity.id,
        "type": chat_type,
        "name": name,
        "phone": getattr(entity, "phone", None),
        "username": f"@{entity.username}" if getattr(entity, "username", None) else None,
        "bio": results["bio"],
        "seen_online": seen_online(entity.status) if is_user and getattr(entity, "status", None) else {"type": 1, "seen_online": 0},
        "is_premium": getattr(entity, "premium", False),
        "profile_channel": results["personal_channel"],
        "profile_music": results["about_music"],
        "members": results["members"]
    }

@bp_chats.route("/about")
async def about_chat():
    res = await validate_input("session_id", "user_id")
    if res[1]: return res[1]
    data = res[0]
    assert data is not None

    client, session_data, args = data
    aes_key = session_data[0]
    user_id = int(args["user_id"] if args["user_id"] else 0)

    try:
        if user_id == "me": entity = await client.get_me() 
        else:               entity = await client.get_entity(user_id)

        data = await get_about(entity, client)
        current_app.logger.debug(f"Sending: {data}")
        binary_payload = encrypt_binary(data, aes_key)
        return Response(binary_payload, mimetype="application/octet-stream")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp_chats.route("/chats")
async def get_chats():
    res = await validate_input("session_id")
    if res[1]: return res[1]
    data = res[0]
    assert data is not None

    client, session_data, _ = data
    aes_key = session_data[0]

    try:
        chats_list = []
        async for dialog in client.iter_dialogs(limit=15):
            last_msg = dialog.message 
            chats_list.append({
                "id": dialog.id,
                "name": dialog.name,
                "date": str(dialog.date),
                "lastMessage": last_msg.text if last_msg else "",
                "lastMessageSenderID": getattr(last_msg, "sender_id", 0) if last_msg else 0,
                "type": get_chat_type(dialog)
            })
            
        binary_payload = encrypt_binary({"chats": chats_list}, aes_key)
        return Response(binary_payload, mimetype="application/octet-stream")
    except Exception as e:
        current_app.logger.error(str(e))
        return jsonify({"error": str(e)}), 500