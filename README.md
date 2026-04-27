<div align="center">
  <h1>TgPrism</h1>
  <p>Telegram HTTP backend with encryption</p>
  <img src="https://img.shields.io/badge/language-python-blue"/>
</div>

### Features:
- **Security**: JSON responses are encrypted with AES-128, and media files have URLs signed with specific token which only server and client know. Man-In-The-Middle attacks are useless in this scenario.

  ___Please note:___ While I implemented some basic security to this project, it doesn't mean it's invulnerable. Instance owners can still use your .session files however they want, maybe there are other vulnerabilities that I didn't notice, and it is very likely. **I am not responsible for any damage caused by using this code.
- **Versatility**: Server communicate in HTTP with basic responses such as JSON, request headers and plain images. It means that clients can be done with almost any device that can handle AES-128 encoding and decoding.

### Deployment:
1. Clone the repo:
   
   `git clone https://github.com/spytaspund/TgPrism`
2. _(Highly recommended)_ Navigate to the cloned folder and create virtual environment:
   
   `cd TgPrism`

   `python3 -m venv .venv`
3. Activate your newly created environment:
   
   `source .venv/bin/activate`
4. Install dependencies:
   
   `pip install -r requierments.txt`
5. Configure the server:
   1. Create .env file with following contents:
      ```ini
      API_ID=your_api_id_get_it_from_my_telegram_org
      API_HASH=your_api_hash_get_it_from_my_telegram_org
      SESSIONS_DIR=sessions
      SERVER_PORT=4848
      PROXY_ADDR="127.0.0.1"
      PROXY_PORT=1234
      LOG_LEVEL=info
      ```
   2. Edit the file to suit your needs
6. Run TgPrism.py:
    
   `python3 TgPrism.py`


###### _Psst!_ Check out [ReflectoGram](https://github.com/spytaspund/ReflectoGram)!
