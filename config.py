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
        self.PROXY_TYPE = getenv("PROXY_TYPE", "off") # either off/local/socks5/http
        self.PROXY_ADDR = getenv("PROXY_ADDR", "127.0.0.1") # for remote proxy
        self.PROXY_PORT = int(getenv("PROXY_PORT", 1515))
        self.SINGBOX_SUB = getenv("SINGBOX_SUB", "") # for local proxy
        self.LOG_LEVEL = getenv("LOG_LEVEL", "INFO").upper()
        if not path.exists(self.SESSIONS_DIR):
            makedirs(self.SESSIONS_DIR)