<div align="center">
  <h1>TgPrism</h1>
  <p>Telegram HTTP backend with encryption</p>
  <img src="https://img.shields.io/badge/language-python-blue"/>
</div>

### Features:
- **Security**: JSON responses are encrypted with AES-128, and media files have URLs signed with specific token which only server and client know. Man-In-The-Middle attacks are useless in this scenario.

  ___Please note:___ While I implemented some basic security to this project, it doesn't mean it's invulnerable. Instance owners can still use your .session files however they want, maybe there are other vulnerabilities that I didn't notice, and it is very likely. **I am not responsible for any damage caused by using this code**.
- **Versatility**: Server communicate in HTTP with basic responses such as JSON, request headers and plain images. It means that clients can be done with almost any device that can handle AES-128 encoding and decoding.

### Deployment methods:
#### Docker (compose, Hypercorn server, fast):
1. Clone the repo:

   `git clone https://github.com/spytaspund/TgPrism`
2. Navigate to the cloned folder and create .env file:
   `cd TgPrism`
   ```ini
   API_ID=your_api_id_get_it_from_my_telegram_org
   API_HASH=your_api_hash_get_it_from_my_telegram_org
   SESSIONS_DIR=sessions
   SERVER_PORT=4848
   PROXY_TYPE=off/local/http/socks/mtproto
   PROXY_PORT=2828
   PROXY_ADDR="your_proxy_addr_ONLY_FOR_MTPROTO/HTTP/SOCKS_TYPE"
   SINGBOX_SUB="your_glorious_sub_ONLY_FOR_LOCAL_TYPE"
   PROXY_SECRET="your_mtproto_secret_ONLY_FOR_MTPROTO_TYPE"
   LOG_LEVEL=info
   ```

3. Create `docker-compose.yml` file:
   ```yml
   services:
      tgprism:
         build: .
         container_name: tgprism
         restart: always
         ports:
            - "${SERVER_PORT:-8000}:${SERVER_PORT:-8000}"
         volumes:
            - ./sessions:/app/sessions
         environment:
            - LOG_LEVEL
            - PROXY_TYPE
            - SERVER_PORT
            - SINGBOX_SUB
            - API_ID
            - API_HASH
   ```

4. Build Docker image:

   `docker compose build`
5. Run docker compose:
   
   `docker compose up -d`

#### Python (venv, Quart server, slow):
1. Clone the repo:
   
   `git clone https://github.com/spytaspund/TgPrism`
2. _(Highly recommended)_ Navigate to the cloned folder and create virtual environment:
   
   `cd TgPrism`

   `python3 -m venv .venv`
3. Activate your newly created environment:
   
   `source .venv/bin/activate`
4. Install dependencies:
   
   `pip install -r requirements.txt`
5. Configure the server:
   1. Create .env file with following contents:
      ```ini
      API_ID=your_api_id_get_it_from_my_telegram_org
      API_HASH=your_api_hash_get_it_from_my_telegram_org
      SESSIONS_DIR=sessions
      SERVER_PORT=4848
      PROXY_TYPE=off_or_local_or_remote
      PROXY_PORT=2828
      PROXY_ADDR="your_proxy_addr_ONLY_FOR_REMOTE_TYPE"
      SINGBOX_SUB="your_glorious_sub_ONLY_FOR_LOCAL_TYPE"
      LOG_LEVEL=info
      ```
   2. Edit the file to suit your needs
6. Run TgPrism.py:
    
   `python3 TgPrism.py`

### Adding TG-WS proxy
Telegram WebSockets proxy is a stable local proxy that does not rely on sing-box and uses another docker container instead. Here's how to add it to your compose file:
1. Clone tg-ws-proxy repo:

   `git clone https://github.com/Flowseal/tg-ws-proxy.git`

2. Add this to your existing `docker-compose.yml`:
   ```yml
   tg-ws-proxy:
    build:
      context: ../tg-ws-proxy
      dockerfile: Dockerfile
    container_name: tg-ws-proxy
    restart: always
    ports:
      - "YOUR_PROXY_PORT:YOUR_PROXY_PORT"
    environment:
      - TG_WS_PROXY_HOST=0.0.0.0
      - TG_WS_PROXY_PORT=YOUR_PROXY_PORT
      - TG_WS_PROXY_SECRET=YOUR_PROXY_SECRET
   ```
   Secret can be generated like this: `openssl rand -hex 16`

3. Adjust your `.env` file to suit your new proxy:
   ```ini
   PROXY_TYPE=mtproto
   PROXY_ADDR=tg-ws-proxy
   PROXY_PORT=YOUR_PROXY_PORT
   PROXY_SECRET="YOUR_PROXY_SECRET"
   ```
   Note that PROXY_ADDR needs to resemble your tg-ws-proxy container name in docker-compose.yml.

* Special thanks to [Flowseal](https://github.com/Flowseal), developer of this proxy. Check [this](https://github.com/Flowseal/tg-ws-proxy) for additional information.

###### _Psst!_ Check out [ReflectoGram](https://github.com/spytaspund/ReflectoGram)!
