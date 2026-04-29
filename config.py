from dotenv import load_dotenv
from os import getenv, urandom, path, makedirs
class Config():
    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        self.API_ID = int(getenv("API_ID", 0))
        self.API_HASH = getenv("API_HASH", "")
        self.SERVER_SALT = getenv("SERVER_SALT", str(urandom(16))).encode()
        self.SESSIONS_DIR = getenv("SESSIONS_DIR", "sessions")
        self.SERVER_PORT = int(getenv("SERVER_PORT", 4848))
        self.PROXY_PORT = int(getenv("PROXY_PORT", 1515))
        self.VLESS_SUB = getenv("VLESS_SUB", "")
        self.LOG_LEVEL = getenv("LOG_LEVEL", "INFO").upper()
        if not path.exists(self.SESSIONS_DIR):
            makedirs(self.SESSIONS_DIR)