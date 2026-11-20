#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
net_analyzer.py - Modulo de Analise de Rede Local, Roteador & Link Fibra (Tela 13).

Monitoramento defensivo e administrativo da propria rede domestica / homelab:
  - Deteccao automatica do roteador / gateway padrao (IP, interface, MAC, URL admin).
  - Latencia, jitter e perda de pacotes (ICMP) para o Roteador (LAN) e WAN (1.1.1.1).
  - Tempo de resolucao DNS e verificacao da interface administrativa HTTP do roteador.
  - Throughput em tempo real (RX/TX em Mbps) relativo ao plano contratado (ex: 700 Mbps Vivo Fibra).
  - Inventario passivo de vizinhos na LAN via tabela ARP do kernel (`ip neigh` / `arp -a`).
  - Teste de velocidade (Speedtest) sob demanda via Cloudflare HTTP multi-stream.
"""

import concurrent.futures
import json
import os
import platform
import re
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime

import psutil

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


def _run_cmd(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
            creationflags=cflags,
        )
        return (res.stdout or "").strip()
    except Exception:
        return ""


def detect_default_route() -> tuple[str, str, str]:
    """Retorna (gateway_ip, interface_name, local_ip)."""
    gw_ip = ""
    iface = ""
    local_ip = ""

    if IS_LINUX:
        out = _run_cmd(["ip", "route", "show", "default"], timeout=2.0)
        for ln in out.splitlines():
            m_gw = re.search(r"default\s+via\s+(\d+\.\d+\.\d+\.\d+)", ln)
            m_dev = re.search(r"\bdev\s+(\S+)", ln)
            m_src = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", ln)
            if m_gw:
                gw_ip = m_gw.group(1)
            if m_dev:
                iface = m_dev.group(1)
            if m_src:
                local_ip = m_src.group(1)
            if gw_ip:
                break

    if not local_ip:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"

    if not gw_ip and local_ip and local_ip.count(".") == 3 and not local_ip.startswith("127."):
        parts = local_ip.split(".")
        gw_ip = f"{parts[0]}.{parts[1]}.{parts[2]}.1"

    return gw_ip, iface or "eth0", local_ip


def ping_stats(host: str, count: int = 3) -> dict:
    """Executa ping ICMP leve e retorna {up, avg_ms, jitter_ms, loss_pct}."""
    if not host:
        return {"up": False, "avg_ms": 0.0, "jitter_ms": 0.0, "loss_pct": 100}

    if IS_WINDOWS:
        cmd = ["ping", "-n", str(count), "-w", "1000", host]
    else:
        cmd = ["ping", "-c", str(count), "-i", "0.2", "-W", "1", host]

    out = _run_cmd(cmd, timeout=max(3.5, count * 1.2))
    if not out:
        return {"up": False, "avg_ms": 0.0, "jitter_ms": 0.0, "loss_pct": 100}

    loss_pct = 100
    m_loss = re.search(r"(\d+(?:\.\d+)?)%\s*(?:packet\s+loss|perda)", out, re.IGNORECASE)
    if m_loss:
        loss_pct = int(round(float(m_loss.group(1))))

    avg_ms = 0.0
    jit_ms = 0.0
    # Linux: rtt min/avg/max/mdev = 0.412/0.511/0.601/0.077 ms
    m_rtt = re.search(
        r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms",
        out,
        re.IGNORECASE,
    )
    if m_rtt:
        avg_ms = round(float(m_rtt.group(2)), 1)
        jit_ms = round(float(m_rtt.group(4)), 1)
    else:
        times = [float(x) for x in re.findall(r"(?:time|tempo)[=<]\s*([\d.]+)\s*ms", out, re.IGNORECASE)]
        if times:
            avg_ms = round(sum(times) / len(times), 1)
            if len(times) > 1:
                diffs = [abs(times[i] - times[i - 1]) for i in range(1, len(times))]
                jit_ms = round(sum(diffs) / len(diffs), 1)
            if loss_pct == 100:
                loss_pct = max(0, int(round((count - len(times)) * 100.0 / count)))

    return {
        "up": loss_pct < 100 and avg_ms >= 0.0,
        "avg_ms": avg_ms,
        "jitter_ms": jit_ms,
        "loss_pct": loss_pct,
    }


def check_router_http(gw_ip: str) -> tuple[int, str]:
    """Verifica se a interface administrativa web do roteador responde em HTTP (porta 80)."""
    if not gw_ip:
        return 0, ""
    url = f"http://{gw_ip}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CYD-NetAnalyzer/1.0"})
        with urllib.request.urlopen(req, timeout=1.6) as resp:
            code = int(getattr(resp, "status", 200))
            srv = str(resp.headers.get("Server", "") or "").strip()
            body = resp.read(2048).decode("utf-8", errors="ignore")
            m_tit = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", m_tit.group(1)).strip()[:28] if m_tit else ""
            hint = title or srv[:28] or "Admin Web"
            return code, hint
    except urllib.error.HTTPError as he:
        # 401/403/302 ainda significa que o painel admin do roteador esta ativo!
        srv = str(getattr(he, "headers", {}).get("Server", "") or "").strip()
        return int(he.code), (srv[:28] or f"HTTP {he.code}")
    except Exception:
        return 0, ""


def measure_dns_ms(domain: str = "cloudflare.com") -> int:
    t0 = time.perf_counter()
    try:
        socket.getaddrinfo(domain, 443, socket.AF_INET)
        return int(round((time.perf_counter() - t0) * 1000.0))
    except Exception:
        return -1


def read_lan_neighbors(gw_ip: str = "", scanner_ip: str = "") -> list[dict]:
    """Le passivamente a tabela ARP/vizinhos do kernel (sem varredura ativa)."""
    hosts: list[dict] = []
    seen_ip: set[str] = set()

    if IS_LINUX:
        out = _run_cmd(["ip", "-4", "neigh", "show"], timeout=2.0)
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) < 4:
                continue
            ip_s = parts[0]
            if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip_s) or ip_s in seen_ip:
                continue
            state_s = parts[-1].upper()
            if state_s in ("FAILED", "INCOMPLETE"):
                continue
            mac_s = ""
            if "lladdr" in parts:
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    mac_s = parts[idx + 1].upper()
            seen_ip.add(ip_s)
            tag = "LAN"
            if ip_s == gw_ip:
                tag = "ROTEADOR"
            elif scanner_ip and ip_s == scanner_ip:
                tag = "ESP32-RADAR"
            elif mac_s.startswith("20:50:0D"):
                tag = "ESP32-RADAR"
            hosts.append({"ip": ip_s, "mac": mac_s, "state": state_s, "tag": tag})
    else:
        out = _run_cmd(["arp", "-a"], timeout=2.0)
        for ln in out.splitlines():
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:-]{17})", ln)
            if m:
                ip_s = m.group(1)
                mac_s = m.group(2).replace("-", ":").upper()
                if ip_s not in seen_ip and not ip_s.endswith(".255") and not ip_s.startswith("224."):
                    seen_ip.add(ip_s)
                    tag = "ROTEADOR" if ip_s == gw_ip else "LAN"
                    hosts.append({"ip": ip_s, "mac": mac_s, "state": "ARP", "tag": tag})

    hosts.sort(key=lambda h: (0 if h["tag"] == "ROTEADOR" else (1 if "ESP32" in h["tag"] else 2), h["ip"]))
    return hosts


def fetch_public_isp_info() -> tuple[str, str]:
    """Consulta opcional e em cache longo (15m) do IP publico e nome do provedor (ISP)."""
    try:
        req = urllib.request.Request(
            "https://ipinfo.io/json",
            headers={"User-Agent": "CYD-NetAnalyzer/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            pub_ip = str(data.get("ip", "") or "").strip()
            org = str(data.get("org", "") or "").strip()
            # Remove prefixo ASxxxx para caber limpo na CYD (ex: "AS26599 Telefonica Brasil" -> "Telefonica Brasil")
            org_clean = re.sub(r"^AS\d+\s+", "", org).strip()
            if "telefonica" in org_clean.lower() or "vivo" in org_clean.lower():
                org_clean = "Vivo Fibra"
            return pub_ip, org_clean[:22]
    except Exception:
        return "", ""


def run_cloudflare_speedtest() -> dict:
    """
    Executa teste de velocidade (Download + Upload em Mbps) usando Cloudflare Speedtest.
    Usa 4 fluxos paralelos de download (4 x 8 MB = 32 MB) para aferir links de alta
    velocidade como Vivo Fibra 700 Mbps com precisao em poucos segundos.
    """
    ping_res = ping_stats("1.1.1.1", count=4)

    def _dl_chunk(size_bytes: int) -> int:
        url = f"https://speed.cloudflare.com/__down?bytes={size_bytes}"
        req = urllib.request.Request(url, headers={"User-Agent": "CYD-Speedtest/1.0"})
        total = 0
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            while True:
                buf = resp.read(65536)
                if not buf:
                    break
                total += len(buf)
        return total

    # Download paralelo (4 streams x 8 MB = 32 MB)
    dl_mbps = 0.0
    t0 = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(_dl_chunk, 8_000_000) for _ in range(4)]
            total_bytes = sum(f.result() for f in futs)
        dt = max(0.05, time.perf_counter() - t0)
        dl_mbps = round((total_bytes * 8.0) / (dt * 1_000_000.0), 1)
    except Exception:
        dl_mbps = 0.0

    # Upload (2 streams x 3 MB = 6 MB)
    ul_mbps = 0.0
    payload_bytes = b"0" * 3_000_000

    def _ul_chunk() -> int:
        req = urllib.request.Request(
            "https://speed.cloudflare.com/__up",
            data=payload_bytes,
            method="POST",
            headers={
                "User-Agent": "CYD-Speedtest/1.0",
                "Content-Type": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            resp.read(256)
        return len(payload_bytes)

    t1 = time.perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_ul_chunk) for _ in range(2)]
            total_up = sum(f.result() for f in futs)
        dt_up = max(0.05, time.perf_counter() - t1)
        ul_mbps = round((total_up * 8.0) / (dt_up * 1_000_000.0), 1)
    except Exception:
        ul_mbps = 0.0

    return {
        "dl_mbps": dl_mbps,
        "ul_mbps": ul_mbps,
        "ping_ms": ping_res.get("avg_ms", 0.0),
        "jitter_ms": ping_res.get("jitter_ms", 0.0),
        "time_str": datetime.now().strftime("%H:%M"),
        "ok": dl_mbps > 0.0,
    }


class NetworkAnalyzerCollector:
    """
    Coletor de Analise de Rede, Roteador e Link Fibra (Tela 13 / SCR_NET_ANALYZER).
    """

    def __init__(self, plan_mbps: int = 700, on_log=None, scanner_ip_fn=None, auto_start: bool = True):
        self._lock = threading.Lock()
        self._on_log = on_log
        self._scanner_ip_fn = scanner_ip_fn
        self._plan_mbps = max(10, min(10000, int(plan_mbps or 700)))
        self._running = False
        self._thread: threading.Thread | None = None

        self._gw_ip = ""
        self._gw_mac = ""
        self._iface = ""
        self._local_ip = ""
        self._gw_up = False
        self._gw_ms = 0.0
        self._gw_jit = 0.0
        self._gw_loss = 0
        self._gw_http = 0
        self._gw_hint = ""

        self._wan_up = False
        self._wan_ms = 0.0
        self._wan_jit = 0.0
        self._wan_loss = 0
        self._dns_ms = 0
        self._pub_ip = ""
        self._isp = ""

        self._rx_mbps = 0.0
        self._tx_mbps = 0.0
        self._peak_rx_mbps = 0.0
        self._peak_tx_mbps = 0.0
        self._lan_hosts: list[dict] = []

        self._spd_running = False
        self._spd_dl = 0.0
        self._spd_ul = 0.0
        self._spd_ping = 0.0
        self._spd_time = "--:--"
        self._spd_err = ""
        self._last_update_str = "--:--:--"

        self._prev_net = psutil.net_io_counters()
        self._prev_net_t = time.monotonic()

        if auto_start:
            self.start()

    def set_log_callback(self, fn):
        self._on_log = fn

    def _emit_log(self, msg: str):
        if self._on_log:
            try:
                self._on_log(msg)
            except Exception:
                pass

    def set_plan_mbps(self, plan_mbps: int):
        try:
            v = max(10, min(10000, int(plan_mbps)))
            with self._lock:
                self._plan_mbps = v
        except Exception:
            pass

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="NetAnalyzerThread")
        self._thread.start()

    def stop(self):
        self._running = False

    def trigger_speedtest(self) -> bool:
        """Inicia um teste de velocidade em thread separada (nao-bloqueante)."""
        with self._lock:
            if self._spd_running:
                return False
            self._spd_running = True
            self._spd_err = ""

        def _runner():
            self._emit_log(f"⚡ Iniciando Speedtest Fibra (meta plano {self._plan_mbps} Mbps)...")
            try:
                res = run_cloudflare_speedtest()
                with self._lock:
                    self._spd_running = False
                    if res.get("ok"):
                        self._spd_dl = res["dl_mbps"]
                        self._spd_ul = res["ul_mbps"]
                        self._spd_ping = res["ping_ms"]
                        self._spd_time = res["time_str"]
                        self._spd_err = ""
                    else:
                        self._spd_err = "Falha no teste de velocidade"
                if res.get("ok"):
                    pct = int(round(res["dl_mbps"] * 100.0 / max(1, self._plan_mbps)))
                    self._emit_log(
                        f"✅ Speedtest concluido: DL {res['dl_mbps']:.1f} Mbps ({pct}% do plano) | "
                        f"UL {res['ul_mbps']:.1f} Mbps | Ping {res['ping_ms']:.1f} ms"
                    )
                else:
                    self._emit_log("⚠️ Speedtest falhou (verifique conexao com a internet).")
            except Exception as ex:
                with self._lock:
                    self._spd_running = False
                    self._spd_err = str(ex)[:50]
                self._emit_log(f"⚠️ Erro no Speedtest: {ex}")

        threading.Thread(target=_runner, daemon=True, name="SpeedtestThread").start()
        return True

    def force_refresh(self):
        """Atualiza imediatamente roteador, WAN, DNS e tabela ARP."""
        threading.Thread(target=self._probe_cycle, kwargs={"force_http": True, "force_isp": True}, daemon=True).start()

    def get_router_diagnostics(self) -> dict:
        """Executa diagnostico completo sob demanda no roteador/gateway atual."""
        gw_ip, iface, local_ip = detect_default_route()
        gw_p = ping_stats(gw_ip, count=4)
        http_code, hint = check_router_http(gw_ip)
        # Testa se o roteador responde como servidor DNS local
        dns_gw_out = _run_cmd(["dig", f"@{gw_ip}", "cloudflare.com", "+short", "+time=1", "+tries=1"], timeout=2.5) if IS_LINUX else ""
        dns_gw_ok = bool(dns_gw_out and re.search(r"\d+\.\d+\.\d+\.\d+", dns_gw_out))
        scanner_ip = self._scanner_ip_fn() if self._scanner_ip_fn else ""
        hosts = read_lan_neighbors(gw_ip=gw_ip, scanner_ip=scanner_ip)
        gw_mac = next((h["mac"] for h in hosts if h["ip"] == gw_ip), "")
        with self._lock:
            self._gw_ip = gw_ip
            self._gw_mac = gw_mac
            self._iface = iface
            self._local_ip = local_ip
            self._gw_up = gw_p["up"]
            self._gw_ms = gw_p["avg_ms"]
            self._gw_jit = gw_p["jitter_ms"]
            self._gw_loss = gw_p["loss_pct"]
            self._gw_http = http_code
            self._gw_hint = hint
            self._lan_hosts = hosts
        return {
            "gateway_ip": gw_ip,
            "gateway_mac": gw_mac,
            "interface": iface,
            "local_ip": local_ip,
            "admin_url": f"http://{gw_ip}" if gw_ip else "",
            "ping_ms": gw_p["avg_ms"],
            "jitter_ms": gw_p["jitter_ms"],
            "loss_pct": gw_p["loss_pct"],
            "http_status": http_code,
            "http_hint": hint,
            "dns_forwarder_ok": dns_gw_ok,
            "lan_count": len(hosts),
            "lan_hosts": hosts,
        }

    def get_cyd_payload(self) -> dict:
        """Payload compacto (< 360 bytes) para o bloco 'neta' da Tela 13 na CYD."""
        with self._lock:
            return {
                "gw": self._gw_ip or "---",
                "if": self._iface[:10] or "eth0",
                "ip": self._local_ip or "---",
                "gwup": bool(self._gw_up),
                "gwms": round(self._gw_ms, 1),
                "gwjit": round(self._gw_jit, 1),
                "loss": int(self._gw_loss),
                "gwh": int(self._gw_http),
                "wanup": bool(self._wan_up),
                "wanms": round(self._wan_ms, 1),
                "dnsms": int(self._dns_ms),
                "rx": round(self._rx_mbps, 1),
                "tx": round(self._tx_mbps, 1),
                "plan": int(self._plan_mbps),
                "lan": len(self._lan_hosts),
                "isp": (self._isp or "ISP")[:16],
                "srun": bool(self._spd_running),
                "sdl": round(self._spd_dl, 1),
                "sul": round(self._spd_ul, 1),
                "stm": self._spd_time,
            }

    def get_ui_snapshot(self) -> dict:
        """Snapshot completo para Desktop Flet, Web/Mobile e CLI Linux `cyd`."""
        with self._lock:
            return {
                "gateway_ip": self._gw_ip,
                "gateway_mac": self._gw_mac,
                "admin_url": f"http://{self._gw_ip}" if self._gw_ip else "",
                "interface": self._iface,
                "local_ip": self._local_ip,
                "gw_up": self._gw_up,
                "gw_ms": self._gw_ms,
                "gw_jit": self._gw_jit,
                "gw_loss": self._gw_loss,
                "gw_http": self._gw_http,
                "gw_hint": self._gw_hint,
                "wan_up": self._wan_up,
                "wan_ms": self._wan_ms,
                "wan_jit": self._wan_jit,
                "wan_loss": self._wan_loss,
                "dns_ms": self._dns_ms,
                "pub_ip": self._pub_ip,
                "isp": self._isp or "Detectando...",
                "rx_mbps": round(self._rx_mbps, 2),
                "tx_mbps": round(self._tx_mbps, 2),
                "peak_rx_mbps": round(self._peak_rx_mbps, 1),
                "peak_tx_mbps": round(self._peak_tx_mbps, 1),
                "plan_mbps": self._plan_mbps,
                "lan_count": len(self._lan_hosts),
                "lan_hosts": [dict(h) for h in self._lan_hosts],
                "speedtest": {
                    "running": self._spd_running,
                    "dl_mbps": self._spd_dl,
                    "ul_mbps": self._spd_ul,
                    "ping_ms": self._spd_ping,
                    "time_str": self._spd_time,
                    "error": self._spd_err,
                    "plan_pct": int(round(self._spd_dl * 100.0 / max(1, self._plan_mbps))) if self._spd_dl > 0 else 0,
                },
                "updated": self._last_update_str,
            }

    def _sample_throughput(self):
        now_m = time.monotonic()
        dt = max(0.2, now_m - self._prev_net_t)
        cur = psutil.net_io_counters()
        if cur and self._prev_net:
            rx_mbps = max(0.0, (cur.bytes_recv - self._prev_net.bytes_recv) * 8.0 / (dt * 1_000_000.0))
            tx_mbps = max(0.0, (cur.bytes_sent - self._prev_net.bytes_sent) * 8.0 / (dt * 1_000_000.0))
            with self._lock:
                self._rx_mbps = rx_mbps
                self._tx_mbps = tx_mbps
                if rx_mbps > self._peak_rx_mbps:
                    self._peak_rx_mbps = rx_mbps
                if tx_mbps > self._peak_tx_mbps:
                    self._peak_tx_mbps = tx_mbps
        self._prev_net = cur
        self._prev_net_t = now_m

    def _probe_cycle(self, force_http: bool = False, force_isp: bool = False):
        gw_ip, iface, local_ip = detect_default_route()
        gw_p = ping_stats(gw_ip, count=3)
        wan_p = ping_stats("1.1.1.1", count=3)
        dns_ms = measure_dns_ms("cloudflare.com")
        scanner_ip = self._scanner_ip_fn() if self._scanner_ip_fn else ""
        hosts = read_lan_neighbors(gw_ip=gw_ip, scanner_ip=scanner_ip)
        gw_mac = next((h["mac"] for h in hosts if h["ip"] == gw_ip), "")

        http_code = None
        http_hint = None
        if force_http:
            http_code, http_hint = check_router_http(gw_ip)

        pub_ip = None
        isp = None
        if force_isp:
            pub_ip, isp = fetch_public_isp_info()

        now_str = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._gw_ip = gw_ip
            if gw_mac:
                self._gw_mac = gw_mac
            self._iface = iface
            self._local_ip = local_ip
            self._gw_up = gw_p["up"]
            self._gw_ms = gw_p["avg_ms"]
            self._gw_jit = gw_p["jitter_ms"]
            self._gw_loss = gw_p["loss_pct"]
            if http_code is not None:
                self._gw_http = http_code
                self._gw_hint = http_hint or ""
            self._wan_up = wan_p["up"]
            self._wan_ms = wan_p["avg_ms"]
            self._wan_jit = wan_p["jitter_ms"]
            self._wan_loss = wan_p["loss_pct"]
            self._dns_ms = dns_ms
            if pub_ip:
                self._pub_ip = pub_ip
            if isp:
                self._isp = isp
            self._lan_hosts = hosts
            self._last_update_str = now_str

    def _worker(self):
        last_probe = 0.0
        last_http = 0.0
        last_isp = 0.0
        while self._running:
            try:
                self._sample_throughput()
                now_m = time.monotonic()
                if (now_m - last_probe) >= 8.0:
                    do_http = (now_m - last_http) >= 45.0 or last_http == 0.0
                    do_isp = (now_m - last_isp) >= 900.0 or last_isp == 0.0
                    self._probe_cycle(force_http=do_http, force_isp=do_isp)
                    last_probe = now_m
                    if do_http:
                        last_http = now_m
                    if do_isp:
                        last_isp = now_m
            except Exception:
                pass
            time.sleep(1.0)
