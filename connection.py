from quart import current_app
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from singbox2proxy import SingBoxBatch, SingBoxProxy
from typing import Any
from config import Config
import asyncio, httpx, base64, time
cfg = Config()

class ProxyManager:
    def __init__(self):
        self.active_proxy: SingBoxProxy | None = None 
        self.best_latency: float = 9999.0
        self.is_running = False
        self.supported_protocols = ["vless://", "ss://", "trojan://", "hysteria2://", "tuic://", "hy2://"]
        self._rebalance_event = asyncio.Event()
        self._last_balance_time = 0.0
        self.is_balancing = False

    def get_telethon_proxy(self) -> dict[str, Any] | None:
        if cfg.PROXY_TYPE == "off": return None
        addr = "127.0.0.1" if cfg.PROXY_TYPE == "local" else cfg.PROXY_ADDR
        return {
            'proxy_type': 'socks5',
            'addr': addr,
            'port': cfg.PROXY_PORT,
            'rdns': True
        }

    async def get_proxies_from_sub(self) -> list:
        if not cfg.SINGBOX_SUB: return []
        
        sub_urls = [s.strip() for s in str(cfg.SINGBOX_SUB).replace("\n", ",").replace("\r", "").split(",") if s.strip()]
        all_urls = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            for sub_url in sub_urls:
                try:
                    current_app.logger.info(f"Downloading subscription: '{sub_url}'")
                    resp = await client.get(sub_url)
                    text = resp.text
                    
                    if not any(proto in text for proto in self.supported_protocols):
                        try: text = base64.b64decode(text).decode('utf-8')
                        except Exception: pass

                    for line in text.splitlines():
                        line = line.strip()
                        if any(line.startswith(proto) for proto in self.supported_protocols):
                            line = line.replace("xtls-rprx-vision-udp443", "xtls-rprx-vision")
                            if "vision" in line: continue
                            if "plugin=" in line: continue
                            all_urls.append(line)
                except Exception as e:
                    current_app.logger.error(f"Failed to fetch {sub_url}: {e}")
        
        unique_urls = list(set(all_urls))
        current_app.logger.info(f"Found {len(unique_urls)} total unique servers from {len(sub_urls)} subscriptions")
        return unique_urls

    async def check_telegram(self, proxy_url: str) -> float:
        start = time.perf_counter()
        try:
            timeout = httpx.Timeout(connect=5.0, read=4.0, write=2.0, pool=1.5)
            async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout, verify=False) as client:
                resp = await client.get("https://api.telegram.org/bot/getMe")
                if resp.status_code in (401, 404) and "ok" in resp.text:
                    return (time.perf_counter() - start) * 1000
        except Exception:
            pass
        return 9999.0

    async def run_balancer_cycle(self):
        if cfg.PROXY_TYPE != "local": return
        urls = await self.get_proxies_from_sub()
        if not urls: 
            current_app.logger.warning("No proxy URLs found in subscription.")
            return

        results = []
        test_batch_size = 50 
        batch = SingBoxBatch(urls, batch_size=test_batch_size)
        concurrency_limit = asyncio.Semaphore(25)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=current_app.config.get('CONSOLE')
        ) as progress:
            task = progress.add_task(f"[cyan]Parallel testing ({len(urls)} proxies)...", total=len(urls))
            
            async def worker(proxy_instance):
                async with concurrency_limit:
                    try:
                        latency = await self.check_telegram(proxy_instance.socks_url)
                        if latency < 2000:
                            return proxy_instance.url, latency
                    except Exception as e:
                        current_app.logger.error(f"Worker crashed for {proxy_instance.socks_url}: {e}")
                    
                    return None, 9999.0
            check_tasks = [asyncio.create_task(worker(p)) for p in batch]
            
            for f in asyncio.as_completed(check_tasks):
                url, latency = await f
                progress.advance(task)
                if latency < 2000 and url:
                    results.append((url, latency))
                    
            batch.stop()

        if not results:
            current_app.logger.error("No working proxies found for Telegram!")
            return

        results.sort(key=lambda x: x[1])
        best_url, best_ping = results[0]
        
        if self.active_proxy:
            current_ping = await self.check_telegram(str(self.active_proxy.socks5_proxy_url))
            self.best_latency = current_ping
            
            if current_ping < 450:
                if best_ping > (current_ping - 100):
                    current_app.logger.info(f"Current proxy is stable ({current_ping:.0f}ms). No switch needed.")
                    return
            else:
                current_app.logger.warning(f"Active proxy degraded/died ({current_ping:.0f}ms). Switching...")

        current_app.logger.info(f"[bold green]Switching to {best_url[:20]}... ({best_ping:.1f}ms)")
        try:
            new_proxy = SingBoxProxy(best_url, socks_port=cfg.PROXY_PORT)
            await asyncio.sleep(1.2)
            
            old_proxy = self.active_proxy
            self.active_proxy = new_proxy
            self.best_latency = best_ping
            
            if old_proxy:
                await asyncio.sleep(2)
                old_proxy.stop()
                
            current_app.logger.info(f"Proxy switched successfully on port {cfg.PROXY_PORT}")
        except Exception as e:
            current_app.logger.error(f"Failed to switch proxy: {e}")
    
    def trigger_rebalance(self, force: bool = False) -> bool:
        if cfg.PROXY_TYPE != "local": return False
        if self.is_balancing: return False
        if not force and (time.time() - self._last_balance_time < 45):
            return False
            
        self._rebalance_event.set()
        return True
    
    async def start_loop(self):
        if cfg.PROXY_TYPE != "local":
            current_app.logger.info(f"Proxy mode: {cfg.PROXY_TYPE}. Balancer loop skipped.")
            return

        self.is_running = True
        current_app.logger.info("Starting Proxy Balancer loop...")
        
        while self.is_running:
            try:
                self.is_balancing = True
                await self.run_balancer_cycle()
                self._last_balance_time = time.time()
            except Exception as e: current_app.logger.error(f"Balancer loop error: {e}")
            finally: self.is_balancing = False

            try:
                await asyncio.wait_for(self._rebalance_event.wait(), timeout=3600)
                self._rebalance_event.clear()
                current_app.logger.warning("Connection failure! Starting forced rebalance...")
            except asyncio.TimeoutError: pass