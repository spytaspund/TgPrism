from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import json, os, hmac, hashlib
from config import Config

cfg = Config()

def encrypt_binary(data_dict, key):
    payload = json.dumps(data_dict, ensure_ascii=False).encode("utf-8")
    iv = os.urandom(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return iv + cipher.encrypt(pad(payload, 16))

def decrypt_binary(encrypted_data, key):
    iv = encrypted_data[:16]
    payload = encrypted_data[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(payload), 16)
    return json.loads(decrypted.decode("utf-8"))

def get_media_token(session_id, msg_id):
    data = f"{session_id}:{msg_id}".encode()
    return hmac.new(cfg.SERVER_SALT, data, hashlib.sha256).hexdigest()