import asyncio
import httpx
import base64
import time
from urllib.parse import urlparse
from quart import current_app
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from singbox2proxy import SingBoxBatch, SingBoxProxy
from config import Config

cfg = Config()

class VlessBalancer:
    def __init__(self, sub_url: str, check_interval: int = 3600):
        self.sub_url = sub_url
        self.check_interval = check_interval
        self.active_proxy: SingBoxProxy = None
        self.current_socks_url: str = None
        self.best_latency: float = 9999.0
        self.is_running = False

    async def get_proxies_from_sub(self) -> list:
        current_app.logger.info(f"Downloading subscription: {self.sub_url}")
        async with httpx.AsyncClient() as client:
            resp = await client.get(self.sub_url)
            text = resp.text
        if "vless://" not in text:
            try: text = base64.b64decode(text).decode('utf-8')
            except Exception: return []

        urls = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("vless://"):
                line = line.replace("xtls-rprx-vision-udp443", "xtls-rprx-vision") # lib doesn't support it
                if "flow=xtls-rprx-vision" not in line and "reality" in line:
                    if "flow=" in line:
                        import re
                        line = re.sub(r'flow=[^&]+', 'flow=xtls-rprx-vision', line)
                urls.append(line)
        return urls

    async def fast_tcp_check(self, urls: list, progress, task_id) -> list:
        alive = []
        async def check(url):
            try:
                parsed = urlparse(url)
                host = parsed.hostname
                port = parsed.port or 443
                fut = asyncio.open_connection(host, port)
                await asyncio.wait_for(fut, timeout=1.5)
                alive.append(url)
            except Exception: pass
            finally: progress.advance(task_id)
        chunk_size = 50
        for i in range(0, len(urls), chunk_size):
            chunk = urls[i:i+chunk_size]
            await asyncio.gather(*(check(u) for u in chunk)) 
        return alive

    async def check_telegram(self, proxy_url: str) -> float:
        try:
            return await asyncio.wait_for(self._internal_check(proxy_url), timeout=1.1)
        except (asyncio.TimeoutError, Exception):
            return 9999.0
    
    async def _internal_check(self, proxy_url: str) -> float:
        start = time.perf_counter()
        try:
            limits = httpx.Timeout(1.0, connect=0.8) 
            async with httpx.AsyncClient(
                proxy=proxy_url, 
                timeout=limits, 
                follow_redirects=False,
                verify=False
            ) as client:
                resp = await client.get("https://api.telegram.org/bot/getMe")
                if resp.status_code < 500: 
                    return (time.perf_counter() - start) * 1000
        except Exception:
            pass
        return 9999.0

    async def run_balancer_cycle(self):
        urls = await self.get_proxies_from_sub()
        if not urls: return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=current_app.config['CONSOLE']
        ) as progress:
            task1 = progress.add_task("(1) [cyan]TCP Scan...", total=len(urls))
            alive_urls = await self.fast_tcp_check(urls, progress, task1)
            
            if not alive_urls:
                current_app.logger.warning("All servers are offline!")
                return
            
            task2 = progress.add_task("(2) [green]Telegram connection test...", total=len(alive_urls))
            batch = SingBoxBatch(alive_urls, batch_size=20)
            
            results = []
            for proxy in batch:
                latency = await self.check_telegram(proxy.socks_url)
                if latency < 1000:
                    results.append((proxy.url, latency))
                progress.advance(task2)
                
            batch.stop()

        if not results:
            current_app.logger.error("No server is able to connect to Telegram!")
            return
        results.sort(key=lambda x: x[1])
        best_url, best_ping = results[0]

        current_app.logger.info(f"[bold green]Best server found![/] Ping: {best_ping:.1f}ms")
        if self.active_proxy and self.best_latency < 300 and best_ping > self.best_latency - 50:
            current_app.logger.info("Current server is fine, keeping it.")
            return

        current_app.logger.info("Switching to another server...")
        try:
            new_proxy = SingBoxProxy(best_url, socks_port=cfg.PROXY_PORT)
            await asyncio.sleep(0.5) 
        except Exception as e:
            current_app.logger.error(f"Cannot start sing-box on port {cfg.PROXY_PORT}: {e}")
            return

        self.current_socks_url = new_proxy.socks5_proxy_url
        self.best_latency = best_ping
        
        old_proxy = self.active_proxy
        self.active_proxy = new_proxy
        
        if old_proxy:
            await asyncio.sleep(2)
            old_proxy.stop()
            
        current_app.logger.info(f"[bold green]Switched server on 127.0.0.1:{cfg.PROXY_PORT}")

    async def start_loop(self):
        self.is_running = True
        while self.is_running:
            try: await self.run_balancer_cycle()
            except Exception as e: current_app.logger.error(f"Balancer error: {e}")
            await asyncio.sleep(self.check_interval)