#!/usr/bin/env python3
"""
agent.py - Agente PC & Painel de Controle Total em FLET (Flutter) para o
CYD Hardware Monitor (No-Touch Edition - 100% controlado pelo PC via USB Serial).

Coleta telemetria (LibreHardwareMonitor na porta 8085 / WMI / psutil / nvidia-smi / RTSS)
e gerencia 100% da interface da placa CYD (Telas, Estúdio de Cores RGB565 em tempo real,
Imagens de Fundo do Cartão SD com redimensionamento automático 320x240 e upload Serial,
e Controle de Brilho PWM).

Formato do Payload Serial:
{"sys":{"cpu": 45, "gpu": 60, "ram": 80, "temp": 55, ...},
 "ui":{"screen": 1, "color": "0x07E0", "bg": "cyberpunk.jpg", "brt": 200}}
"""

import argparse
import base64
import inspect
import io
import json
import mmap
import os
import platform
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

IS_WINDOWS = platform.system() == "Windows"
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

try:
    import psutil
except ImportError:
    sys.exit("Faltando psutil. Instale as dependencias com: pip install -r agent/requirements.txt")

BAUD = 115200
INTERVAL = 1.0
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "ui_config.json")

# Fuso horario de Brasilia (UTC-3)
try:
    from zoneinfo import ZoneInfo
    TZ_BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:
    TZ_BRASILIA = timezone(timedelta(hours=-3))


def brasilia_now():
    return datetime.now(TZ_BRASILIA)


def rgb_hex_to_rgb565_str(hex_color: str) -> str:
    """Converte '#RRGGBB' para string hexadecimal RGB565 ex: '0x07E0'."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return "0x07E0"
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return "0x07E0"
    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    if rgb565 == 0:
        rgb565 = 0x0841  # evita preto total invisivel
    return f"0x{rgb565:04X}"


def hex_to_rgb_tuple(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return (0, 255, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 255, 0)


# VID:PID dos conversores USB-serial usados nas placas CYD
KNOWN_USB_IDS = {
    (0x1A86, 0x7523),  # CH340
    (0x1A86, 0x55D4),  # CH9102
    (0x10C4, 0xEA60),  # CP2102
    (0x0403, 0x6001),  # FT232
}

DEFAULT_GAME_PROCESSES = (
    "pcsx2", "rpcs3", "dolphin-emu", "yuzu", "ryujinx", "cemu", "citra",
    "ppsspp", "duckstation", "mupen64plus", "retroarch", "xemu",
)


def _is_steam_game(exe_path):
    if not exe_path:
        return False
    return "steamapps/common" in exe_path.replace("\\", "/").lower()


# --------------------------------------------------------------- helpers ----
def run(cmd, timeout=2):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


SYSTEM_ROOT = os.path.abspath(os.sep)


def load_average():
    try:
        return round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        return None


def get_rtss_fps():
    """Le o FPS do RTSS (RivaTuner Statistics Server) compartilhado na memoria."""
    if not IS_WINDOWS:
        return None
    try:
        shmem = mmap.mmap(-1, 32768, "RTSSSharedMemoryV2", access=mmap.ACCESS_READ)
        sig = struct.unpack("<I", shmem[0:4])[0]
        if sig != 0x52545353:
            shmem.close()
            return None

        app_arr_offset = struct.unpack("<I", shmem[12:16])[0]
        app_arr_size = struct.unpack("<I", shmem[16:20])[0]
        app_entry_size = struct.unpack("<I", shmem[8:12])[0]
        total_size = app_arr_offset + app_arr_size * app_entry_size
        shmem.close()

        shmem = mmap.mmap(-1, total_size, "RTSSSharedMemoryV2", access=mmap.ACCESS_READ)
        for i in range(app_arr_size):
            offset = app_arr_offset + i * app_entry_size
            proc_id = struct.unpack("<I", shmem[offset:offset + 4])[0]
            if proc_id == 0:
                continue
            frame_time = struct.unpack("<I", shmem[offset + 280:offset + 284])[0]
            if frame_time > 0:
                fps = 1000000.0 / frame_time
                if 0 < fps < 2000:
                    shmem.close()
                    return int(fps + 0.5)
        shmem.close()
        return None
    except Exception:
        return None


# ----------------------------- Sensores no Windows (LibreHardwareMonitor) ---
_lhm = None
_lhm_tried = False


def _lhm_connect():
    global _lhm, _lhm_tried
    if _lhm_tried:
        return _lhm
    _lhm_tried = True
    if not IS_WINDOWS:
        return None
    try:
        import wmi
    except ImportError:
        return None
    for ns in ("LibreHardwareMonitor", "OpenHardwareMonitor"):
        try:
            w = wmi.WMI(namespace=f"root/{ns}")
            w.Sensor()
            _lhm = w
            break
        except Exception:
            continue
    return _lhm


def _lhm_sensors(kind):
    w = _lhm_connect()
    if not w:
        return []
    try:
        return [s for s in w.Sensor() if s.SensorType == kind]
    except Exception:
        return []


CPU_TEMP_KEYS = ("k10temp", "zenpower", "coretemp", "cpu_thermal",
                 "acpitz", "soc_thermal", "thinkpad")
CPU_LABEL_HINTS = ("tctl", "tdie", "package", "cpu", "core 0", "composite")


def _get_lhm_web_data():
    """Consulta o servidor web do LibreHardwareMonitor na porta 8085."""
    try:
        with urllib.request.urlopen("http://localhost:8085/data.json", timeout=0.8) as url:
            return json.loads(url.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _find_web_sensors(node, kind, name_hints=None):
    results = []
    if not node:
        return results

    def recurse(n, path):
        t = (n.get("Text") or "").lower()
        curr_path = path + [t]
        val = n.get("Value")
        if val:
            path_str = " ".join(curr_path)
            if kind.lower() in path_str:
                if name_hints:
                    if any(h.lower() in path_str for h in name_hints):
                        results.append(val)
                else:
                    results.append(val)
        for c in n.get("Children", []):
            recurse(c, curr_path)

    recurse(node, [])
    parsed = []
    for r in results:
        try:
            num = float(r.split()[0].replace(",", "."))
            parsed.append(num)
        except Exception:
            pass
    return parsed


def cpu_temperature(web_data=None):
    """Retorna a temperatura da CPU em graus Celsius."""
    temps = None
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        pass

    if temps:
        for chip in CPU_TEMP_KEYS:
            for name, entries in temps.items():
                if chip not in name.lower():
                    continue
                for e in entries:
                    if e.label and any(h in e.label.lower() for h in CPU_LABEL_HINTS):
                        return round(e.current, 1)
                if entries:
                    return round(entries[0].current, 1)

        best = None
        for entries in temps.values():
            for e in entries:
                if e.current and 0 < e.current < 130:
                    best = e.current if best is None else max(best, e.current)
        if best:
            return round(best, 1)

    if web_data is None:
        web_data = _get_lhm_web_data()
    if web_data:
        web_temps = _find_web_sensors(web_data, "temperature", ["cpu", "package", "tctl", "tdie", "core"])
        if web_temps:
            return round(max(web_temps), 1)

    cpu_sensors = [s for s in _lhm_sensors("Temperature")
                   if "cpu" in (s.Name or "").lower()
                   or "cpu" in (s.Parent or "").lower()]
    for s in cpu_sensors:
        n = (s.Name or "").lower()
        if any(h in n for h in ("package", "tctl", "tdie", "core max", "average")):
            return round(s.Value, 1)
    if cpu_sensors:
        return round(cpu_sensors[0].Value, 1)

    return None


def fan_rpm():
    try:
        fans = psutil.sensors_fans()
    except Exception:
        fans = None
    for entries in (fans or {}).values():
        for e in entries:
            if e.current and e.current > 0:
                return int(e.current)
    for s in _lhm_sensors("Fan"):
        if s.Value:
            return int(s.Value)
    return None


# -------------------------------------------------------------------- GPU ---
_gpu_kind = None
_amd_paths = {}
_nvidia_smi = None


def _find_nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if exe:
        return exe
    if IS_WINDOWS:
        for c in (
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
        ):
            if os.path.isfile(c):
                return c
    return None


def _detect_gpu():
    global _gpu_kind, _amd_paths, _nvidia_smi
    _nvidia_smi = _find_nvidia_smi()
    if _nvidia_smi and run([_nvidia_smi, "-L"]):
        _gpu_kind = "nvidia"
        return
    import glob
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]/device")):
        if os.path.exists(os.path.join(card, "gpu_busy_percent")):
            hw = glob.glob(os.path.join(card, "hwmon", "hwmon*"))
            _amd_paths = {
                "busy": os.path.join(card, "gpu_busy_percent"),
                "vram_used": os.path.join(card, "mem_info_vram_used"),
                "vram_total": os.path.join(card, "mem_info_vram_total"),
                "temp": os.path.join(hw[0], "temp1_input") if hw else None,
                "fan": os.path.join(hw[0], "fan1_input") if hw else None,
                "power": os.path.join(hw[0], "power1_average") if hw else None,
            }
            _gpu_kind = "amd"
            return
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hw, "name")) as f:
                if f.read().strip() in ("i915", "xe"):
                    _amd_paths = {"temp": os.path.join(hw, "temp1_input")}
                    _gpu_kind = "intel"
                    return
        except Exception:
            pass
    _gpu_kind = "none"


def _lhm_gpu_stats():
    temps = _lhm_sensors("Temperature")
    gpu_temp = next((s.Value for s in temps if "gpu" in (s.Name or "").lower()), None)
    if gpu_temp is None:
        return None
    loads = _lhm_sensors("Load")
    powers = _lhm_sensors("Power")
    gpu_load = next((s.Value for s in loads
                     if (s.Name or "").lower() in ("gpu core", "gpu")), None)
    gpu_power = next((s.Value for s in powers if "gpu" in (s.Name or "").lower()), None)
    parent = next((s.Parent or "" for s in temps if "gpu" in (s.Name or "").lower()), "")
    name = "AMD" if "amdgpu" in parent.lower() else ("INTEL" if "intelgpu" in parent.lower() else "GPU")
    return {
        "gpu": round(gpu_load, 1) if gpu_load is not None else 0.0,
        "gput": round(gpu_temp, 1),
        "gpuw": round(gpu_power, 1) if gpu_power is not None else None,
        "gpuname": name,
    }


def _lhm_gpu_stats_web(web_data=None):
    if web_data is None:
        web_data = _get_lhm_web_data()
    if not web_data:
        return None
    gpu_temps = _find_web_sensors(web_data, "temperature", ["gpu", "hot spot"])
    if not gpu_temps:
        gpu_temps = _find_web_sensors(web_data, "temperature", ["tctl", "tdie", "package"])
    gpu_loads = _find_web_sensors(web_data, "load", ["gpu core", "d3d 3d"])
    gpu_powers = _find_web_sensors(web_data, "power", ["gpu", "package"])
    vram_used = _find_web_sensors(web_data, "data", ["gpu memory used", "d3d dedicated memory used"])
    vram_total = _find_web_sensors(web_data, "data", ["gpu memory total", "d3d dedicated memory total"])

    if not gpu_temps and not gpu_loads:
        return None

    vu_mb = vram_used[0] if vram_used else None
    vt_mb = vram_total[0] if vram_total else None
    vram_pct = round(100.0 * vu_mb / vt_mb, 1) if (vu_mb is not None and vt_mb) else None

    return {
        "gpu": round(max(gpu_loads), 1) if gpu_loads else 0.0,
        "gput": round(max(gpu_temps), 1) if gpu_temps else None,
        "gpuw": round(gpu_powers[0], 1) if gpu_powers else None,
        "vram": vram_pct,
        "vramu": round(vu_mb / 1024.0, 1) if vu_mb is not None else None,
        "vramt": round(vt_mb / 1024.0, 1) if vt_mb is not None else None,
        "gpuname": "RADEON",
    }


def gpu_stats(web_data=None):
    if _gpu_kind is None:
        _detect_gpu()

    web = _lhm_gpu_stats_web(web_data)

    if _gpu_kind == "nvidia":
        q = run([_nvidia_smi,
                 "--query-gpu=utilization.gpu,temperature.gpu,memory.used,"
                 "memory.total,power.draw,fan.speed",
                 "--format=csv,noheader,nounits"])
        if q:
            parts = [p.strip() for p in q.splitlines()[0].split(",")]

            def num(i):
                try:
                    return float(parts[i])
                except Exception:
                    return None
            used, total = num(2), num(3)
            return {
                "gpu": num(0) if num(0) is not None else 0.0,
                "gput": num(1),
                "vram": round(100.0 * used / total, 1) if used and total else None,
                "vramu": round(used / 1024.0, 1) if used else None,
                "vramt": round(total / 1024.0, 1) if total else None,
                "gpuw": num(4),
                "gpufan": num(5),
                "gpuname": "NVIDIA",
            }

    if _gpu_kind == "amd":
        busy = read_int(_amd_paths.get("busy") or "")
        temp = read_int(_amd_paths.get("temp") or "")
        vu = read_int(_amd_paths.get("vram_used") or "")
        vt = read_int(_amd_paths.get("vram_total") or "")
        pw = read_int(_amd_paths.get("power") or "")
        return {
            "gpu": busy if busy is not None else 0.0,
            "gput": round(temp / 1000.0, 1) if temp else None,
            "vram": round(100.0 * vu / vt, 1) if vu and vt else None,
            "vramu": round(vu / 1073741824.0, 1) if vu else None,
            "vramt": round(vt / 1073741824.0, 1) if vt else None,
            "gpuw": round(pw / 1000000.0, 1) if pw else None,
            "gpufan": read_int(_amd_paths.get("fan") or ""),
            "gpuname": "AMD",
        }

    if web:
        return web

    lhm = _lhm_gpu_stats()
    if lhm:
        return lhm

    if _gpu_kind == "intel":
        temp = read_int(_amd_paths.get("temp") or "")
        return {"gpu": 0.0, "gput": round(temp / 1000.0, 1) if temp else None, "gpuname": "INTEL"}

    return {"gpu": 0.0, "gpuname": None}


# --------------------------------------------------------------- coletor ----
class Collector:
    def __init__(self, game_processes=()):
        psutil.cpu_percent(interval=None)
        self.host = socket.gethostname()[:14]
        self.prev_net = psutil.net_io_counters()
        self.prev_disk = psutil.disk_io_counters()
        self.prev_t = time.time()
        self.cores = psutil.cpu_count(logical=True)
        self.game_processes = tuple(g.lower() for g in DEFAULT_GAME_PROCESSES + tuple(game_processes))
        self._last_proc_scan = 0.0
        self._cached_top = ""
        self._cached_gaming = False

    def sample_sys(self):
        """Coleta todas as metricas do sistema para o objeto 'sys' do JSON."""
        now = time.time()
        dt = max(now - self.prev_t, 0.1)

        web_data = _get_lhm_web_data()
        cpu = psutil.cpu_percent(interval=None)
        cput = cpu_temperature(web_data)
        freq = psutil.cpu_freq()
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        du = psutil.disk_usage(SYSTEM_ROOT)

        net = psutil.net_io_counters()
        rx = (net.bytes_recv - self.prev_net.bytes_recv) / dt / 1048576.0
        tx = (net.bytes_sent - self.prev_net.bytes_sent) / dt / 1048576.0
        self.prev_net = net

        dio = psutil.disk_io_counters()
        if dio and self.prev_disk:
            dr = (dio.read_bytes - self.prev_disk.read_bytes) / dt / 1048576.0
            dw = (dio.write_bytes - self.prev_disk.write_bytes) / dt / 1048576.0
        else:
            dr = dw = 0.0
        self.prev_disk = dio
        self.prev_t = now

        # Varredura de processos com cache de 5s para manter uso de CPU quase zero
        if now - self._last_proc_scan >= 5.0:
            self._last_proc_scan = now
            top = ""
            gaming = False
            try:
                procs = []
                for p in psutil.process_iter(["name", "cpu_percent", "exe"]):
                    name = p.info["name"] or ""
                    if p.info["cpu_percent"]:
                        procs.append((p.info["cpu_percent"], name))
                    if not gaming:
                        low = name.lower()
                        gaming = (any(g in low for g in self.game_processes)
                                  or _is_steam_game(p.info.get("exe")))
                if procs:
                    top = max(procs)[1][:12]
            except Exception:
                pass
            self._cached_top = top
            self._cached_gaming = gaming

        br = brasilia_now()
        sys_data = {
            "cpu": round(cpu, 1),
            "temp": cput,
            "cput": cput,
            "cpuf": int(freq.current) if freq and freq.current else None,
            "cores": self.cores,
            "load": load_average(),
            "hh": br.hour,
            "mm": br.minute,
            "ram": round(vm.percent, 1),
            "ramu": round(vm.used / 1073741824.0, 1),
            "ramt": round(vm.total / 1073741824.0, 1),
            "swap": round(sw.percent, 1),
            "dsk": round(du.percent, 1),
            "dskf": round(du.free / 1073741824.0, 1),
            "dr": round(dr, 2),
            "dw": round(dw, 2),
            "rx": round(rx, 2),
            "tx": round(tx, 2),
            "up": int(now - psutil.boot_time()),
            "fan": fan_rpm() if not web_data else None,
            "host": self.host,
            "top": self._cached_top,
            "game": self._cached_gaming,
            "fps": get_rtss_fps() if self._cached_gaming else None,
        }
        sys_data.update(gpu_stats(web_data))
        return {k: v for k, v in sys_data.items() if v is not None}


# ---------------------------------------------------------------- serial ----
def find_port():
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("Faltando pyserial. Rode: pip install pyserial")
    cands = list(list_ports.comports())
    for p in cands:
        if p.vid is not None and (p.vid, p.pid) in KNOWN_USB_IDS:
            return p.device
    for p in cands:
        if re.search(r"ttyUSB|ttyACM|^COM\d+$", p.device):
            return p.device
    return None


def prepare_image_for_cyd(filepath: str) -> tuple[str, bytes]:
    """
    Prepara uma imagem do PC para o Cartao SD da CYD (320x240):
    - Se for .gif: envia os bytes originais.
    - Se for .jpg, .jpeg, .png, .bmp: redimensiona/recorta em 320x240 usando Pillow
      e converte para JPEG Baseline otimizado (~15 KB) para transferencia rapida
      via Serial e compatibilidade 100% com o TJpg_Decoder do ESP32.
    """
    ext = os.path.splitext(filepath)[1].lower()
    raw_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", os.path.splitext(os.path.basename(filepath))[0])[:18]

    if ext == ".gif":
        with open(filepath, "rb") as f:
            return f"{raw_base}.gif", f.read()

    try:
        from PIL import Image, ImageOps
        img = Image.open(filepath).convert("RGB")
        img = ImageOps.fit(img, (320, 240), method=Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True, progressive=False)
        return f"{raw_base}.jpg", buf.getvalue()
    except ImportError:
        with open(filepath, "rb") as f:
            return f"{raw_base}{ext}", f.read()


def load_ui_config():
    defaults = {
        "screen": 1,
        "hex_color": "#00FF00",
        "color": "0x07E0",
        "bg": "none",
        "brt": 200,
        "ticker": True,
        "sd_files": [
            "none",
            "terminal",
            "z1p0",
            "cyberpunk.jpg",
            "megadeth.jpg",
            "megadeth2.jpg",
            "megadeth-rust-in-peace.jpg",
            "pantera-vulgar-display-of-power.jpg",
            "heavymetal.gif",
            "background.gif",
        ],
    }
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_ui_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ========================================== COLETOR DE MERCADO FINANCEIRO ====
class MarketCollector:
    """
    Coletor Financeiro & Cripto em Tempo Real de Alta Performance (Multi-Threaded).
      - Criptomoedas (Coinbase Spot USD + Binance 24h chg): atualizadas a cada 3.0s.
        Garante alinhamento centavo por centavo com a busca do Google ("preço do bitcoin em dolar").
      - Indices (IBOVESPA, S&P 500) e Câmbio Oficial (USD/BRL, EUR/BRL): atualizados a cada 12.0s.
      - Sparkline de 24h do Bitcoin (48 candles) da Binance.
    """

    def __init__(self, crypto_interval: float = 3.0, stock_interval: float = 12.0):
        self.crypto_interval = crypto_interval
        self.stock_interval = stock_interval
        self._lock = threading.Lock()
        self._data = {
            "usd": 0.0, "usdc": 0.0,
            "eur": 0.0, "eurc": 0.0,
            "ibov": 0.0, "ibovc": 0.0,
            "sp500": 0.0, "sp500c": 0.0,
            "btc": 0.0, "btcc": 0.0, "btc_brl": 0.0,
            "eth": 0.0, "ethc": 0.0,
            "sol": 0.0, "solc": 0.0,
            "bnb": 0.0, "bnbc": 0.0,
            "xrp": 0.0, "xrpc": 0.0,
            "btch": [],
            "last_str": "--:--:--",
        }
        self._updated_at = 0.0
        self._running = True
        self._trigger_crypto = threading.Event()
        self._trigger_stock = threading.Event()
        threading.Thread(target=self._crypto_worker, daemon=True).start()
        threading.Thread(target=self._stock_worker, daemon=True).start()

    def _http_json(self, url: str, timeout: float = 3.5):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CYDMonitor/3.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def _fetch_yahoo_quote(self, ticker_encoded: str) -> tuple[float, float] | None:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_encoded}?interval=1d&range=2d"
            raw = self._http_json(url, timeout=3.5)
            meta = raw["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
            chg = ((price - prev) / prev * 100.0) if prev > 0 else 0.0
            return round(price, 4), round(chg, 2)
        except Exception:
            return None

    def fetch_crypto_now(self) -> bool:
        new_d = {}
        updated = False

        # 1) Spot Prices em USD direto da Coinbase (mesma fonte primária exibida pelo Google)
        rates = None
        try:
            raw_cb = self._http_json("https://api.coinbase.com/v2/exchange-rates?currency=USD", timeout=3.0)
            rates = raw_cb.get("data", {}).get("rates", {})
            if rates:
                if "BTC" in rates and float(rates["BTC"]) > 0:
                    new_d["btc"] = round(1.0 / float(rates["BTC"]), 0)
                    updated = True
                if "ETH" in rates and float(rates["ETH"]) > 0:
                    new_d["eth"] = round(1.0 / float(rates["ETH"]), 0)
                    updated = True
                if "SOL" in rates and float(rates["SOL"]) > 0:
                    new_d["sol"] = round(1.0 / float(rates["SOL"]), 2)
                    updated = True
                if "BNB" in rates and float(rates["BNB"]) > 0:
                    new_d["bnb"] = round(1.0 / float(rates["BNB"]), 2)
                    updated = True
                if "XRP" in rates and float(rates["XRP"]) > 0:
                    new_d["xrp"] = round(1.0 / float(rates["XRP"]), 4)
                    updated = True
                if "BRL" in rates and float(rates["BRL"]) > 0:
                    new_d["usd"] = round(float(rates["BRL"]), 3)
                    if "EUR" in rates and float(rates["EUR"]) > 0:
                        new_d["eur"] = round(float(rates["BRL"]) / float(rates["EUR"]), 3)
                    updated = True
        except Exception:
            pass

        # 2) Variação Percentual 24h e Fallback de Cotações via Binance Ticker API
        try:
            syms = "%5B%22BTCUSDT%22,%22ETHUSDT%22,%22SOLUSDT%22,%22BNBUSDT%22,%22XRPUSDT%22%5D"
            tickers = self._http_json(f"https://api.binance.com/api/v3/ticker/24hr?symbols={syms}", timeout=3.0)
            mapping = {
                "BTCUSDT": ("btc", "btcc", 0),
                "ETHUSDT": ("eth", "ethc", 0),
                "SOLUSDT": ("sol", "solc", 2),
                "BNBUSDT": ("bnb", "bnbc", 2),
                "XRPUSDT": ("xrp", "xrpc", 4),
            }
            for item in tickers:
                sym = item.get("symbol")
                if sym in mapping:
                    k_p, k_c, dec = mapping[sym]
                    if k_p not in new_d:
                        p_val = float(item.get("lastPrice", 0.0))
                        new_d[k_p] = round(p_val, dec) if dec > 0 else round(p_val, 0)
                    new_d[k_c] = round(float(item.get("priceChangePercent", 0.0)), 2)
                    updated = True
        except Exception:
            pass

        if updated:
            with self._lock:
                self._data.update(new_d)
                usd_now = self._data.get("usd", 0.0)
                btc_now = self._data.get("btc", 0.0)
                if usd_now > 0 and btc_now > 0:
                    self._data["btc_brl"] = round(btc_now * usd_now, 0)
                self._data["last_str"] = brasilia_now().strftime("%H:%M:%S")
                self._updated_at = time.time()
        return updated

    def fetch_stock_now(self) -> bool:
        new_d = {}
        updated = False

        # 1) Câmbio USD/BRL e EUR/BRL oficial (AwesomeAPI)
        try:
            fx = self._http_json("https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL", timeout=3.5)
            if "USDBRL" in fx:
                new_d["usd"] = round(float(fx["USDBRL"]["bid"]), 3)
                new_d["usdc"] = round(float(fx["USDBRL"].get("pctChange", 0.0)), 2)
                updated = True
            if "EURBRL" in fx:
                new_d["eur"] = round(float(fx["EURBRL"]["bid"]), 3)
                new_d["eurc"] = round(float(fx["EURBRL"].get("pctChange", 0.0)), 2)
                updated = True
        except Exception:
            pass

        # 2) Índices da Bolsa: IBOVESPA (^BVSP) e S&P 500 (^GSPC) via Yahoo Finance
        ibov = self._fetch_yahoo_quote("%5EBVSP")
        if ibov:
            new_d["ibov"] = round(ibov[0], 0)
            new_d["ibovc"] = ibov[1]
            updated = True

        sp500 = self._fetch_yahoo_quote("%5EGSPC")
        if sp500:
            new_d["sp500"] = round(sp500[0], 0)
            new_d["sp500c"] = sp500[1]
            updated = True

        # 3) Curva Sparkline de 24h do Bitcoin (48 candles de 30m da Binance)
        try:
            klines = self._http_json(
                "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=30m&limit=48",
                timeout=3.5,
            )
            closes = [float(k[4]) for k in klines if len(k) > 4]
            if len(closes) >= 4:
                lo, hi = min(closes), max(closes)
                span = (hi - lo) if (hi > lo) else 1.0
                new_d["btch"] = [int(round((c - lo) / span * 100.0)) for c in closes]
                updated = True
        except Exception:
            pass

        if updated:
            with self._lock:
                self._data.update(new_d)
                usd_now = self._data.get("usd", 0.0)
                btc_now = self._data.get("btc", 0.0)
                if usd_now > 0 and btc_now > 0:
                    self._data["btc_brl"] = round(btc_now * usd_now, 0)
                self._data["last_str"] = brasilia_now().strftime("%H:%M:%S")
                self._updated_at = time.time()
        return updated

    def _crypto_worker(self):
        while self._running:
            try:
                self.fetch_crypto_now()
            except Exception:
                pass
            self._trigger_crypto.wait(timeout=self.crypto_interval)
            self._trigger_crypto.clear()

    def _stock_worker(self):
        while self._running:
            try:
                self.fetch_stock_now()
            except Exception:
                pass
            self._trigger_stock.wait(timeout=self.stock_interval)
            self._trigger_stock.clear()

    def fetch_once(self) -> bool:
        r1 = self.fetch_crypto_now()
        r2 = self.fetch_stock_now()
        return r1 or r2

    def force_refresh(self):
        self._trigger_crypto.set()
        self._trigger_stock.set()

    def get_market_dict(self) -> dict:
        with self._lock:
            return dict(self._data)

    @property
    def updated_at(self) -> float:
        with self._lock:
            return self._updated_at


# ========================================== INTERFACE MODERNA EM FLET (FLUTTER) ==
def launch_flet_gui(col: Collector, mkt_col: MarketCollector, cli_args):
    import flet as ft

    # Helpers compativeis entre Flet 0.2x e Flet 1.0+
    _ICONS = getattr(ft, "Icons", getattr(ft, "icons", None))
    _Border = getattr(ft, "Border", getattr(ft, "border", None))
    _Padding = getattr(ft, "Padding", getattr(ft, "padding", None))
    _Button = getattr(ft, "Button", getattr(ft, "ElevatedButton", None))

    def icon_val(name: str):
        return getattr(_ICONS, name, None) if _ICONS else None

    def border_all(width: float, color: str):
        return _Border.all(width, color)

    def pad_sym(horizontal: float = 0, vertical: float = 0):
        return _Padding.symmetric(horizontal=horizontal, vertical=vertical)

    def build_app(page: ft.Page):
        page.title = "CYD Hardware & Financial Market Monitor — Painel de Controle Total (Flet / Flutter)"
        page.bgcolor = "#07090E"
        page.padding = 16
        page.scroll = ft.ScrollMode.AUTO
        page.theme_mode = ft.ThemeMode.DARK

        cfg = load_ui_config()
        state = {
            "screen": int(cfg.get("screen", 1)),
            "hex_color": cfg.get("hex_color", "#00FF00").upper(),
            "color": cfg.get("color", "0x07E0"),
            "bg": cfg.get("bg", "none"),
            "brt": int(cfg.get("brt", 200)),
            "ticker": bool(cfg.get("ticker", True)),
            "sd_files": list(cfg.get("sd_files", [])),
            "running": True,
            "ui_dirty": True,
            "last_ui_sync": 0.0,
            "last_mkt_sync": 0.0,
            "last_brt_ev": 0.0,
        }

        def restore_window(icon=None, item=None):
            try:
                if hasattr(page, "window") and page.window is not None:
                    page.window.minimized = False
                    page.window.visible = True
                    page.update()
                    if hasattr(page, "run_task") and hasattr(page.window, "to_front"):
                        try:
                            page.run_task(page.window.to_front)
                        except Exception:
                            pass
            except Exception:
                pass

        def minimize_window(icon=None, item=None):
            try:
                if hasattr(page, "window") and page.window is not None:
                    page.window.minimized = True
                    page.update()
            except Exception:
                pass

        def quit_app(icon=None, item=None):
            state["running"] = False
            try:
                if tray_icon:
                    tray_icon.stop()
            except Exception:
                pass
            try:
                if hasattr(page, "window") and hasattr(page.window, "destroy"):
                    page.run_task(page.window.destroy)
            except Exception:
                pass
            time.sleep(0.1)
            os._exit(0)

        def on_window_event(e):
            ev_data = str(getattr(e, "data", "")).lower()
            ev_type = str(getattr(e, "type", "")).lower()
            if "close" in ev_data or "close" in ev_type:
                minimize_window()

        try:
            if hasattr(page, "window") and page.window is not None:
                page.window.width = 900
                page.window.height = 940
                page.window.min_width = 740
                page.window.min_height = 740
                page.window.prevent_close = True
                page.window.on_event = on_window_event
            else:
                page.window_width = 900
                page.window_height = 940
        except Exception:
            pass

        # ---------------------- BANDEJA DO SISTEMA (SYSTEM TRAY) -------------
        tray_icon = None
        try:
            import pystray
            from PIL import Image, ImageDraw

            def create_tray_image():
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rounded_rectangle([2, 2, 62, 62], radius=12, fill=(15, 23, 42, 255), outline=(0, 255, 128, 255), width=3)
                draw.line([(10, 44), (22, 28), (34, 38), (46, 18), (54, 26)], fill=(0, 255, 128, 255), width=4)
                return img

            tray_menu = pystray.Menu(
                pystray.MenuItem("Abrir Painel", restore_window, default=True),
                pystray.MenuItem("Minimizar para Segundo Plano", minimize_window),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Encerrar Agente", quit_app),
            )
            tray_icon = pystray.Icon(
                "cyd_monitor",
                create_tray_image(),
                "CYD Hardware & Market Monitor (Ativo em Segundo Plano)",
                menu=tray_menu,
            )
            threading.Thread(target=tray_icon.run, daemon=True).start()
        except Exception:
            tray_icon = None

        ui_event_queue = queue.Queue()
        transfer_queue = queue.Queue()
        ack_event = threading.Event()
        last_ack = {"val": None}
        log_lines = []

        def get_ui_dict():
            bg = (state["bg"] or "none").strip()
            if bg.startswith("/"):
                bg = bg[1:]
            return {
                "screen": int(state["screen"]),
                "color": state["color"],
                "bg": bg,
                "brt": int(state["brt"]),
                "ticker": bool(state["ticker"]),
            }

        def persist_and_queue_ui():
            cfg.update({
                "screen": state["screen"],
                "hex_color": state["hex_color"],
                "color": state["color"],
                "bg": state["bg"],
                "brt": state["brt"],
                "ticker": state["ticker"],
                "sd_files": state["sd_files"],
            })
            save_ui_config(cfg)
            state["ui_dirty"] = True
            while not ui_event_queue.empty():
                try:
                    ui_event_queue.get_nowait()
                except Exception:
                    break
            ui_event_queue.put({"ui": get_ui_dict(), "mkt": mkt_col.get_market_dict()})

        def append_log(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            log_lines.append(f"[{ts}] {msg}")
            if len(log_lines) > 35:
                del log_lines[0]
            txt_console.value = "\n".join(log_lines)
            try:
                page.update()
            except Exception:
                pass

        # ------------------------ CABECALHO & STATUS USB ---------------------
        lbl_title = ft.Text(
            "⚡ CYD HARDWARE & MARKET MONITOR",
            size=22,
            weight=ft.FontWeight.BOLD,
            color=state["hex_color"],
            font_family="Consolas",
        )
        lbl_subtitle = ft.Text(
            "Painel de Controle Total • Hardware + Bolsa de Valores & Cripto em Tempo Real (USB Serial)",
            size=12,
            color="#8B95A8",
        )
        status_dot = ft.Container(
            width=10,
            height=10,
            border_radius=5,
            bgcolor="#F59E0B",
        )
        lbl_usb_status = ft.Text(
            "Procurando porta USB...",
            size=12,
            weight=ft.FontWeight.W_600,
            color="#E2E8F0",
            font_family="Consolas",
        )
        status_badge = ft.Container(
            content=ft.Row([status_dot, lbl_usb_status], spacing=8, tight=True),
            bgcolor="#111622",
            border=border_all(1, "#222B3D"),
            border_radius=20,
            padding=pad_sym(horizontal=14, vertical=6),
        )

        btn_minimize = ft.IconButton(
            icon=ft.Icons.MINIMIZE,
            icon_color="#94A3B8",
            tooltip="Minimizar (continua em segundo plano)",
            on_click=lambda e: minimize_window(),
        )
        btn_quit = ft.IconButton(
            icon=ft.Icons.POWER_SETTINGS_NEW,
            icon_color="#EF4444",
            tooltip="Encerrar Agente",
            on_click=lambda e: quit_app(),
        )

        header_row = ft.Row(
            [
                ft.Column([lbl_title, lbl_subtitle], spacing=2, expand=True),
                ft.Row([status_badge, btn_minimize, btn_quit], spacing=6, tight=True),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # ---------------- FAIXA DE TELEMETRIA AO VIVO NO PC ------------------
        def make_metric_card(title: str, init_val: str, init_sub: str):
            val_txt = ft.Text(init_val, size=20, weight=ft.FontWeight.BOLD, color="#FFFFFF", font_family="Consolas")
            sub_txt = ft.Text(init_sub, size=11, color="#8B95A8", font_family="Consolas")
            bar = ft.ProgressBar(value=0.0, color=state["hex_color"], bgcolor="#1A2130", height=6, border_radius=3)
            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(title, size=11, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                                sub_txt,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        val_txt,
                        bar,
                    ],
                    spacing=6,
                ),
                bgcolor="#0E131D",
                border=border_all(1, "#1E2738"),
                border_radius=12,
                padding=12,
                expand=True,
            )
            return card, val_txt, sub_txt, bar

        card_cpu, lbl_cpu_val, lbl_cpu_sub, bar_cpu = make_metric_card("PROCESSADOR (CPU)", "0.0%", "-- °C")
        card_ram, lbl_ram_val, lbl_ram_sub, bar_ram = make_metric_card("MEMÓRIA (RAM)", "0.0%", "0.0/0G")
        card_gpu, lbl_gpu_val, lbl_gpu_sub, bar_gpu = make_metric_card("GRÁFICOS (GPU)", "0.0%", "-- °C")
        card_dsk, lbl_dsk_val, lbl_dsk_sub, bar_dsk = make_metric_card("DISCO & REDE", "0.0%", "0.0 MB/s")

        telemetry_row = ft.Row([card_cpu, card_ram, card_gpu, card_dsk], spacing=10)

        # ---------------- FAIXA DE MERCADO FINANCEIRO & CRIPTO AO VIVO -------
        def make_fin_pill(symbol: str, init_price: str):
            p_txt = ft.Text(init_price, size=14, weight=ft.FontWeight.BOLD, color="#FFFFFF", font_family="Consolas")
            c_txt = ft.Text("0.00%", size=11, weight=ft.FontWeight.BOLD, color="#22C55E", font_family="Consolas")
            pill = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(symbol, size=11, weight=ft.FontWeight.BOLD, color=state["hex_color"]),
                                c_txt,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        p_txt,
                    ],
                    spacing=2,
                ),
                bgcolor="#0E1420",
                border=border_all(1, "#1E293B"),
                border_radius=10,
                padding=pad_sym(horizontal=10, vertical=8),
                expand=True,
            )
            return pill, p_txt, c_txt

        pill_usd, lbl_usd_p, lbl_usd_c = make_fin_pill("💵 USD/BRL", "R$ --")
        pill_eur, lbl_eur_p, lbl_eur_c = make_fin_pill("💶 EUR/BRL", "R$ --")
        pill_btc, lbl_btc_p, lbl_btc_c = make_fin_pill("₿ BITCOIN", "$ --")
        pill_eth, lbl_eth_p, lbl_eth_c = make_fin_pill("Ξ ETHEREUM", "$ --")
        pill_sol, lbl_sol_p, lbl_sol_c = make_fin_pill("◎ SOLANA", "$ --")
        pill_ibov, lbl_ibov_p, lbl_ibov_c = make_fin_pill("📈 IBOV (B3)", "---k pts")

        def on_toggle_ticker(_e):
            state["ticker"] = not state["ticker"]
            new_lbl = (
                "📟 Letreiro da Bolsa no Rodapé: ATIVO"
                if state["ticker"]
                else "📟 Letreiro da Bolsa no Rodapé: OCULTO"
            )
            if hasattr(btn_ticker_toggle, "content"):
                btn_ticker_toggle.content = new_lbl
            if hasattr(btn_ticker_toggle, "text"):
                btn_ticker_toggle.text = new_lbl
            persist_and_queue_ui()
            append_log(f"Letreiro infinito (Ticker Tape) {'ativado' if state['ticker'] else 'ocultado'} nas telas.")

        btn_ticker_toggle = ft.OutlinedButton(
            "📟 Letreiro da Bolsa no Rodapé: ATIVO" if state["ticker"] else "📟 Letreiro da Bolsa no Rodapé: OCULTO",
            on_click=on_toggle_ticker,
        )

        lbl_market_status = ft.Text(
            "🟢 Cripto: Ao Vivo (Coinbase / Binance • 3s) • 🟡 B3 & Câmbio: Fechado (Fim de semana)",
            size=11,
            color="#F59E0B",
            weight=ft.FontWeight.W_500,
        )
        lbl_market_time = ft.Text("Última cotação: --:--:--", size=11, color="#64748B", font_family="Consolas")

        def on_manual_mkt_refresh(_e):
            def run_refresh():
                btn_refresh_mkt.text = "⏳ Atualizando..."
                btn_refresh_mkt.disabled = True
                try:
                    page.update()
                except Exception:
                    pass
                mkt_col.force_refresh()
                time.sleep(0.5)
                m = mkt_col.get_market_dict()
                append_log(f"Cotações atualizadas: BTC ${m.get('btc', 0):,.0f} | USD R$ {m.get('usd', 0):.2f}")
                btn_refresh_mkt.text = "✅ Atualizado!"
                try:
                    page.update()
                except Exception:
                    pass
                time.sleep(1.2)
                btn_refresh_mkt.text = "🔄 Atualizar Cotações"
                btn_refresh_mkt.disabled = False
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=run_refresh, daemon=True).start()

        btn_refresh_mkt = ft.OutlinedButton("🔄 Atualizar Cotações", on_click=on_manual_mkt_refresh)

        sec_market_live = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        "📊 MERCADO FINANCEIRO & CRIPTO AO VIVO (EXIBIDO NA TELA 6 E NO LETREIRO INFINITO DA TELA PRINCIPAL)",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color="#94A3B8",
                                    ),
                                    ft.Row([lbl_market_status, lbl_market_time], spacing=12),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    btn_ticker_toggle,
                                    btn_refresh_mkt,
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row([pill_usd, pill_eur, pill_btc, pill_eth, pill_sol, pill_ibov], spacing=8),
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=12,
        )

        # ---------------- 1. GERENCIADOR DE TELAS (GRID INTERATIVO) ----------
        screen_defs = [
            (0, "Tela 0: Resumo Gauges", "Gauges circulares de CPU & RAM + Disco/Rede + Letreiro Bolsa", "SPEED"),
            (1, "Tela 1: Painel CPU + RAM (Principal)", "Barras + Gráficos de CPU % e RAM % lado a lado + Letreiro Bolsa", "TERMINAL"),
            (2, "Tela 2: Gráfico Duplo CPU vs RAM", "Curvas de Uso de CPU % + Uso de RAM % juntas + Letreiro Bolsa", "SHOW_CHART"),
            (3, "Tela 3: GPU Focus", "Gauge Grande de GPU + VRAM + Watts/FPS + Letreiro Bolsa", "VIDEOGAME_ASSET"),
            (4, "Tela 4: 4x Gráficos", "Grid em tempo real: CPU %, RAM %, GPU % e TEMP °C + Letreiro Bolsa", "GRID_VIEW"),
            (5, "Tela 5: Wallpaper HUD", "Destaque para a imagem do Cartão SD + Dock CPU/RAM + Letreiro", "WALLPAPER"),
            (6, "📈 Tela 6: Mercado Financeiro & Bolsa (Cripto + Dólar + Euro + B3)", "Terminal completo: Dólar (USD/BRL), Euro (EUR/BRL), IBOVESPA, Top 5 Cripto (BTC/ETH/SOL/BNB/XRP) + Gráfico Bitcoin 24h", "CURRENCY_BITCOIN"),
        ]
        screen_cards = []

        def on_select_screen(scr_idx: int):
            state["screen"] = scr_idx
            refresh_screen_cards()
            persist_and_queue_ui()
            append_log(f"Tela alterada para {scr_idx}")

        def refresh_screen_cards():
            for idx, cont, title_t, badge_t in screen_cards:
                active = (idx == state["screen"])
                cont.bgcolor = "#162032" if active else "#0F141F"
                cont.border = border_all(2 if active else 1, state["hex_color"] if active else "#1E2738")
                title_t.color = state["hex_color"] if active else "#E2E8F0"
                badge_t.bgcolor = state["hex_color"] if active else "#1A2234"
                badge_t.content.color = "#05070A" if active else "#94A3B8"
            try:
                page.update()
            except Exception:
                pass

        for idx, title, desc, _ic in screen_defs:
            active = (idx == state["screen"])
            title_t = ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=state["hex_color"] if active else "#E2E8F0")
            desc_t = ft.Text(desc, size=11, color="#8B95A8")
            badge_t = ft.Container(
                content=ft.Text(f"TELA {idx}", size=10, weight=ft.FontWeight.BOLD, color="#05070A" if active else "#94A3B8"),
                bgcolor=state["hex_color"] if active else "#1A2234",
                border_radius=6,
                padding=pad_sym(horizontal=8, vertical=2),
            )
            card_cont = ft.Container(
                content=ft.Column(
                    [
                        ft.Row([title_t, badge_t], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        desc_t,
                    ],
                    spacing=4,
                ),
                bgcolor="#162032" if active else "#0F141F",
                border=border_all(2 if active else 1, state["hex_color"] if active else "#1E2738"),
                border_radius=10,
                padding=10,
                ink=True,
                on_click=lambda e, i=idx: on_select_screen(i),
                expand=True,
            )
            screen_cards.append((idx, card_cont, title_t, badge_t))

        screens_grid = ft.Column(
            [
                ft.Row([screen_cards[0][1], screen_cards[1][1]], spacing=10),
                ft.Row([screen_cards[2][1], screen_cards[3][1]], spacing=10),
                ft.Row([screen_cards[4][1], screen_cards[5][1]], spacing=10),
                ft.Row([screen_cards[6][1]], spacing=10),
            ],
            spacing=8,
        )

        sec_screens = ft.Container(
            content=ft.Column(
                [
                    ft.Text("🖥️ 1. GERENCIADOR DE TELAS DA CYD (TROCA INSTANTÂNEA)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                    screens_grid,
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 2. ESTÚDIO DE CORES RGB565 (COLOR PICKER) ----------
        r_init, g_init, b_init = hex_to_rgb_tuple(state["hex_color"])

        color_preview_box = ft.Container(
            width=44,
            height=44,
            bgcolor=state["hex_color"],
            border_radius=10,
            border=border_all(2, "#FFFFFF"),
        )
        txt_hex_input = ft.TextField(
            label="Código HEX",
            value=state["hex_color"],
            width=135,
            height=44,
            text_size=13,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        lbl_rgb565_badge = ft.Text(
            f"RGB565: {state['color']}",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=state["hex_color"],
            font_family="Consolas",
        )

        slider_r = ft.Slider(min=0, max=255, divisions=255, value=r_init, active_color="#EF4444", expand=True)
        slider_g = ft.Slider(min=0, max=255, divisions=255, value=g_init, active_color="#22C55E", expand=True)
        slider_b = ft.Slider(min=0, max=255, divisions=255, value=b_init, active_color="#3B82F6", expand=True)

        def apply_new_hex(hex_str: str, update_sliders=True):
            h = hex_str.strip().upper()
            if not h.startswith("#"):
                h = "#" + h
            if len(h) != 7:
                return
            state["hex_color"] = h
            state["color"] = rgb_hex_to_rgb565_str(h)

            if update_sliders:
                rv, gv, bv = hex_to_rgb_tuple(h)
                slider_r.value = rv
                slider_g.value = gv
                slider_b.value = bv

            txt_hex_input.value = h
            color_preview_box.bgcolor = h
            lbl_rgb565_badge.value = f"RGB565: {state['color']}"
            lbl_rgb565_badge.color = h
            lbl_title.color = h
            bar_cpu.color = h
            bar_ram.color = h
            bar_gpu.color = h
            bar_dsk.color = h
            slider_brt.active_color = h
            refresh_screen_cards()
            persist_and_queue_ui()

        def on_rgb_slider_change(_e):
            rv = int(slider_r.value or 0)
            gv = int(slider_g.value or 0)
            bv = int(slider_b.value or 0)
            new_hex = f"#{rv:02X}{gv:02X}{bv:02X}"
            apply_new_hex(new_hex, update_sliders=False)

        slider_r.on_change = on_rgb_slider_change
        slider_g.on_change = on_rgb_slider_change
        slider_b.on_change = on_rgb_slider_change
        txt_hex_input.on_submit = lambda e: apply_new_hex(txt_hex_input.value, update_sliders=True)

        presets = [
            ("Matrix", "#00FF00"),
            ("Cyber Cyan", "#00FFFF"),
            ("Amber", "#FFA500"),
            ("Magenta", "#FF00FF"),
            ("Crimson", "#FF2020"),
            ("Neon Blue", "#1E90FF"),
            ("Ouro", "#FFD700"),
            ("Roxo", "#A855F7"),
            ("Lime", "#84CC16"),
            ("Branco", "#FFFFFF"),
        ]
        swatch_controls = []
        for pname, phex in presets:
            swatch_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(width=12, height=12, border_radius=6, bgcolor=phex),
                            ft.Text(pname, size=11, weight=ft.FontWeight.W_600, color="#E2E8F0"),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                    bgcolor="#141B29",
                    border=border_all(1, phex),
                    border_radius=16,
                    padding=pad_sym(horizontal=10, vertical=5),
                    ink=True,
                    on_click=lambda e, h=phex: apply_new_hex(h, update_sliders=True),
                )
            )

        sec_colors = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🎨 2. SELETOR DE CORES EM TEMPO REAL (COLOR PICKER RGB565)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            lbl_rgb565_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(swatch_controls, wrap=True, spacing=8, run_spacing=8),
                    ft.Row(
                        [
                            color_preview_box,
                            txt_hex_input,
                            ft.Column(
                                [
                                    ft.Row([ft.Text("R", size=11, color="#EF4444", width=14), slider_r], spacing=4),
                                    ft.Row([ft.Text("G", size=11, color="#22C55E", width=14), slider_g], spacing=4),
                                    ft.Row([ft.Text("B", size=11, color="#3B82F6", width=14), slider_b], spacing=4),
                                ],
                                spacing=0,
                                expand=True,
                            ),
                        ],
                        spacing=14,
                    ),
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 3. FUNDO DO CARTAO SD & BRILHO PWM -----------------
        def make_dropdown_options(items):
            opts = list(items)
            current_bg = state.get("bg", "none")
            if current_bg and current_bg not in opts:
                opts.append(current_bg)
            return [ft.dropdown.Option(x) for x in opts]

        dd_kwargs = {
            "label": "Imagem de Fundo / Tema no Cartão SD",
            "value": state["bg"],
            "options": make_dropdown_options(state["sd_files"]),
            "expand": True,
        }
        dd_sig = inspect.signature(ft.Dropdown.__init__).parameters

        def on_bg_selected(_e):
            if dd_bg.value:
                state["bg"] = dd_bg.value
                persist_and_queue_ui()
                append_log(f"Fundo alterado para '{state['bg']}'")

        if "on_change" in dd_sig:
            dd_kwargs["on_change"] = on_bg_selected
        elif "on_select" in dd_sig:
            dd_kwargs["on_select"] = on_bg_selected

        dd_bg = ft.Dropdown(**dd_kwargs)

        prog_upload = ft.ProgressBar(value=0.0, visible=False, color=state["hex_color"], bgcolor="#1A2130", height=8)
        lbl_upload_status = ft.Text("", size=11, color="#94A3B8", visible=False)

        def request_sd_files(_e=None):
            ui_event_queue.put({"cmd": "list_sd"})
            append_log("Solicitando lista de imagens do Cartão SD da CYD...")

        def start_file_transfer(filepath: str):
            if not filepath:
                return
            try:
                target_name, data = prepare_image_for_cyd(filepath)
            except Exception as ex:
                append_log(f"Erro ao preparar imagem: {ex}")
                return

            append_log(f"Iniciando envio de '{target_name}' ({len(data)/1024:.1f} KB) para o SD da CYD...")

            def worker():
                prog_upload.visible = True
                lbl_upload_status.visible = True
                prog_upload.value = 0.0
                lbl_upload_status.value = f"Conectando com SD para gravar '{target_name}'..."
                try:
                    page.update()
                except Exception:
                    pass

                def wait_for_ack(expected_prefix, timeout=4.0):
                    t0 = time.time()
                    while time.time() - t0 < timeout:
                        if ack_event.wait(timeout=0.08):
                            ack_event.clear()
                            val = last_ack.get("val") or ""
                            if val.startswith("ERR_NO_SD"):
                                return False, "ERR_NO_SD"
                            if val.startswith("ERR_OPEN"):
                                return False, "ERR_OPEN"
                            if val.startswith(expected_prefix):
                                return True, val
                    return False, "TIMEOUT"

                # 1) Inicia gravacao no SD
                ack_event.clear()
                transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "w"})
                ok, resp = wait_for_ack("ACK_START", timeout=4.5)
                if not ok:
                    prog_upload.visible = False
                    if resp == "ERR_NO_SD":
                        lbl_upload_status.value = "❌ Cartão MicroSD não detectado na CYD! Formate em FAT32."
                        append_log("Upload cancelado: Cartão MicroSD ausente ou não montado. Formate em FAT32.")
                    else:
                        lbl_upload_status.value = f"❌ Falha ao iniciar gravação no SD ({resp})."
                        append_log(f"Upload cancelado: Placa não respondeu ACK_START ({resp}).")
                    try:
                        page.update()
                    except Exception:
                        pass
                    return

                # 2) Envia chunks de 512 bytes com sincronizacao por pacote
                chunk_size = 512
                total = len(data)
                seq = 0
                for i in range(0, total, chunk_size):
                    chunk = data[i:i + chunk_size]
                    b64 = base64.b64encode(chunk).decode("ascii")
                    ack_event.clear()
                    transfer_queue.put({
                        "file_name": f"/{target_name}",
                        "file_mode": "a",
                        "seq": seq,
                        "file_data": b64,
                    })
                    ok, resp = wait_for_ack("ACK_CHUNK", timeout=3.5)
                    if not ok:
                        prog_upload.visible = False
                        lbl_upload_status.value = f"❌ Erro ao gravar bloco {seq} no SD ({resp})."
                        append_log(f"Upload falhou no bloco {seq} ({resp}).")
                        try:
                            page.update()
                        except Exception:
                            pass
                        return

                    seq += 1
                    pct = min((i + len(chunk)) / float(total), 1.0)
                    prog_upload.value = pct
                    lbl_upload_status.value = f"Gravando '{target_name}' no SD ({int(pct * 100)}%)..."
                    try:
                        page.update()
                    except Exception:
                        pass

                # 3) Finaliza gravacao
                ack_event.clear()
                transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "eof"})
                ok, resp = wait_for_ack("ACK_EOF", timeout=5.0)
                if not ok:
                    prog_upload.visible = False
                    lbl_upload_status.value = f"❌ Falha ao finalizar arquivo ({resp})."
                    append_log(f"Upload: Falha ao fechar arquivo no SD ({resp}).")
                    try:
                        page.update()
                    except Exception:
                        pass
                    return

                # 4) Sucesso total!
                prog_upload.value = 1.0
                prog_upload.visible = False
                lbl_upload_status.value = f"✅ '{target_name}' gravado no SD e aplicado na tela!"
                append_log(f"Upload concluído com sucesso: '{target_name}' gravado no SD e definido como fundo.")

                if target_name not in state["sd_files"]:
                    state["sd_files"].append(target_name)
                state["bg"] = target_name
                dd_bg.options = make_dropdown_options(state["sd_files"])
                dd_bg.value = target_name
                persist_and_queue_ui()
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=worker, daemon=True).start()

        def on_click_upload(_e):
            def pick_native_file():
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    r = tk.Tk()
                    r.withdraw()
                    r.attributes("-topmost", True)
                    init_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "imagens-referencia")
                    p = filedialog.askopenfilename(
                        initialdir=init_dir if os.path.isdir(init_dir) else None,
                        title="Selecione uma imagem para o Cartão SD da CYD (JPG, PNG, BMP, GIF)",
                        filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.gif")],
                    )
                    r.destroy()
                    if p:
                        start_file_transfer(p)
                except Exception as ex:
                    append_log(f"Erro ao abrir seletor de arquivos: {ex}")

            threading.Thread(target=pick_native_file, daemon=True).start()

        # Controle de Brilho PWM
        lbl_brt_value = ft.Text(
            f"{int(state['brt'] * 100 / 255)}% ({state['brt']})",
            size=13,
            weight=ft.FontWeight.BOLD,
            color="#E2E8F0",
            font_family="Consolas",
        )

        def on_brt_change(_e):
            b = int(slider_brt.value or 200)
            state["brt"] = b
            lbl_brt_value.value = f"{int(b * 100 / 255)}% ({b})"
            now = time.time()
            if now - state["last_brt_ev"] > 0.08:
                state["last_brt_ev"] = now
                persist_and_queue_ui()
            try:
                page.update()
            except Exception:
                pass

        slider_brt = ft.Slider(
            min=10,
            max=255,
            divisions=245,
            value=state["brt"],
            active_color=state["hex_color"],
            on_change=on_brt_change,
            expand=True,
        )

        sec_bg_and_brt = ft.Row(
            [
                # Coluna Esquerda: Cartao SD
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("🖼️ 3. FUNDO DE TELA (CARTÃO SD)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            ft.Row(
                                [
                                    dd_bg,
                                    _Button("Aplicar", on_click=on_bg_selected),
                                    ft.OutlinedButton("🔄 Ler SD", on_click=request_sd_files),
                                ],
                                spacing=8,
                            ),
                            _Button(
                                "📤 Enviar Imagem do PC p/ SD (Auto 320x240 JPG/GIF)",
                                icon=icon_val("UPLOAD_FILE"),
                                on_click=on_click_upload,
                            ),
                            prog_upload,
                            lbl_upload_status,
                        ],
                        spacing=10,
                    ),
                    bgcolor="#0B0F17",
                    border=border_all(1, "#1A2232"),
                    border_radius=14,
                    padding=14,
                    expand=3,
                ),
                # Coluna Direita: Brilho PWM
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("☀️ 4. BRILHO (PWM)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                                    lbl_brt_value,
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text("Ajuste instantâneo do backlight da CYD (Pino 21):", size=11, color="#8B95A8"),
                            slider_brt,
                            ft.Row(
                                [
                                    ft.OutlinedButton("25%", on_click=lambda e: (setattr(slider_brt, "value", 64), on_brt_change(e))),
                                    ft.OutlinedButton("50%", on_click=lambda e: (setattr(slider_brt, "value", 128), on_brt_change(e))),
                                    ft.OutlinedButton("80%", on_click=lambda e: (setattr(slider_brt, "value", 204), on_brt_change(e))),
                                    ft.OutlinedButton("100%", on_click=lambda e: (setattr(slider_brt, "value", 255), on_brt_change(e))),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                        ],
                        spacing=10,
                    ),
                    bgcolor="#0B0F17",
                    border=border_all(1, "#1A2232"),
                    border_radius=14,
                    padding=14,
                    expand=2,
                ),
            ],
            spacing=12,
        )

        # ---------------- 4. CONSOLE SERIAL & LOG ----------------------------
        txt_console = ft.Text(
            value="Inicializando agente de telemetria, mercado financeiro e comunicação USB Serial...",
            size=11,
            color="#94A3B8",
            font_family="Consolas",
            selectable=True,
        )
        sec_console = ft.Container(
            content=ft.Column(
                [
                    ft.Text("📡 CONSOLE SERIAL & TELEMETRIA EM TEMPO REAL", size=12, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                    ft.Container(
                        content=txt_console,
                        bgcolor="#05070B",
                        border=border_all(1, "#151C28"),
                        border_radius=8,
                        padding=10,
                        width=float("inf"),
                    ),
                ],
                spacing=6,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=12,
        )

        page.add(
            header_row,
            ft.Divider(height=8, color="#151C28"),
            telemetry_row,
            sec_market_live,
            sec_screens,
            sec_colors,
            sec_bg_and_brt,
            sec_console,
        )

        # ---------------- THREAD DE COMUNICACAO SERIAL -----------------------
        def read_serial_responses(ser):
            while ser.in_waiting > 0:
                try:
                    raw = ser.readline().decode("utf-8", errors="ignore").strip()
                except Exception:
                    break
                if not raw:
                    continue
                if raw.startswith("ACK_") or raw.startswith("ERR_"):
                    last_ack["val"] = raw
                    ack_event.set()
                elif raw == "MONITOR_READY":
                    state["ui_dirty"] = True
                    request_sd_files()
                elif raw.startswith("SD_FILES:"):
                    try:
                        files = json.loads(raw.split("SD_FILES:", 1)[1])
                        if isinstance(files, list):
                            base_opts = ["none", "terminal", "z1p0"]
                            merged = base_opts + [f for f in files if f not in base_opts]
                            state["sd_files"] = merged
                            cfg["sd_files"] = merged
                            save_ui_config(cfg)
                            dd_bg.options = make_dropdown_options(merged)
                            if files:
                                append_log(f"SD Card sincronizado: {len(files)} imagem(ns) encontrada(s): {', '.join(files)}")
                            else:
                                append_log("SD Card sincronizado: Nenhuma imagem encontrada ou cartão não detectado.")
                    except Exception:
                        pass
                elif raw.startswith("SD_INIT:OK"):
                    append_log(f"Cartão MicroSD detectado e montado com sucesso ({raw}).")
                elif raw.startswith("SD_INIT:FAIL"):
                    append_log("⚠️ Cartão MicroSD não detectado pela placa CYD. Verifique se está inserido e formatado em FAT32.")
                elif raw.startswith("JPG_ERR:"):
                    append_log(f"⚠️ Erro no hardware CYD ao decodificar imagem JPEG ({raw}).")

        def _fmt_chg(lbl_c, chg_val: float):
            lbl_c.value = f"{'+' if chg_val >= 0 else ''}{chg_val:.2f}%"
            lbl_c.color = "#22C55E" if chg_val >= 0 else "#EF4444"

        def update_pc_telemetry_cards(sys_m: dict, mkt_m: dict):
            cpu_v = sys_m.get("cpu", 0.0)
            cput_v = sys_m.get("cput")
            lbl_cpu_val.value = f"{cpu_v:.1f}%"
            lbl_cpu_sub.value = f"{cput_v:.0f} °C" if cput_v is not None else f"{sys_m.get('cpuf', 0)} MHz"
            bar_cpu.value = min(max(cpu_v / 100.0, 0.0), 1.0)

            ram_v = sys_m.get("ram", 0.0)
            lbl_ram_val.value = f"{ram_v:.1f}%"
            lbl_ram_sub.value = f"{sys_m.get('ramu', 0):.1f}/{sys_m.get('ramt', 0):.0f} GB"
            bar_ram.value = min(max(ram_v / 100.0, 0.0), 1.0)

            gpu_v = sys_m.get("gpu", 0.0)
            gput_v = sys_m.get("gput")
            lbl_gpu_val.value = f"{gpu_v:.1f}%"
            lbl_gpu_sub.value = f"{gput_v:.0f} °C" if gput_v is not None else (sys_m.get("gpuname") or "GPU")
            bar_gpu.value = min(max(gpu_v / 100.0, 0.0), 1.0)

            dsk_v = sys_m.get("dsk", 0.0)
            lbl_dsk_val.value = f"DSK {dsk_v:.0f}%"
            lbl_dsk_sub.value = f"↓{sys_m.get('rx', 0):.1f} ↑{sys_m.get('tx', 0):.1f} MB/s"
            bar_dsk.value = min(max(dsk_v / 100.0, 0.0), 1.0)

            # Atualiza faixa de mercado financeiro no PC
            if mkt_m.get("usd", 0) > 0:
                lbl_usd_p.value = f"R$ {mkt_m['usd']:.2f}"
                _fmt_chg(lbl_usd_c, mkt_m.get("usdc", 0.0))
            if mkt_m.get("eur", 0) > 0:
                lbl_eur_p.value = f"R$ {mkt_m['eur']:.2f}"
                _fmt_chg(lbl_eur_c, mkt_m.get("eurc", 0.0))
            if mkt_m.get("btc", 0) > 0:
                lbl_btc_p.value = f"$ {mkt_m['btc']:,.0f}"
                _fmt_chg(lbl_btc_c, mkt_m.get("btcc", 0.0))
            if mkt_m.get("eth", 0) > 0:
                lbl_eth_p.value = f"$ {mkt_m['eth']:,.0f}"
                _fmt_chg(lbl_eth_c, mkt_m.get("ethc", 0.0))
            if mkt_m.get("sol", 0) > 0:
                lbl_sol_p.value = f"$ {mkt_m['sol']:.2f}"
                _fmt_chg(lbl_sol_c, mkt_m.get("solc", 0.0))
            if mkt_m.get("ibov", 0) > 0:
                lbl_ibov_p.value = f"{mkt_m['ibov']/1000.0:.1f}k pts"
                _fmt_chg(lbl_ibov_c, mkt_m.get("ibovc", 0.0))

            if mkt_m.get("last_str") and mkt_m["last_str"] != "--:--:--":
                lbl_market_time.value = f"Última cotação: {mkt_m['last_str']}"

            now_br = brasilia_now()
            if now_br.weekday() in (5, 6):
                lbl_market_status.value = "🟢 Cripto: Ao Vivo (Coinbase / Binance • 3s) • 🟡 B3 & Câmbio: Fechado (Fim de semana)"
                lbl_market_status.color = "#F59E0B"
            else:
                lbl_market_status.value = "🟢 Cripto: Ao Vivo (Coinbase / 3s) • 🟢 B3 & Câmbio: Mercado Aberto"
                lbl_market_status.color = "#10B981"

            try:
                page.update()
            except Exception:
                pass

        def serial_worker():
            import serial
            ser = None
            last_telemetry_t = 0.0

            while state["running"]:
                try:
                    now = time.time()
                    sys_metrics = None
                    mkt_metrics = mkt_col.get_market_dict()
                    if now - last_telemetry_t >= cli_args.interval:
                        last_telemetry_t = now
                        sys_metrics = col.sample_sys()
                        update_pc_telemetry_cards(sys_metrics, mkt_metrics)

                    if ser is None:
                        port = cli_args.port or find_port()
                        if not port:
                            status_dot.bgcolor = "#F59E0B"
                            lbl_usb_status.value = "Aguardando CYD na USB..."
                            try:
                                page.update()
                            except Exception:
                                pass
                            time.sleep(1.5)
                            continue

                        ser = serial.Serial(port, BAUD, timeout=0.5)
                        time.sleep(1.8)
                        ser.reset_input_buffer()
                        state["ui_dirty"] = True
                        status_dot.bgcolor = "#22C55E"
                        lbl_usb_status.value = f"Conectado em {port} ({BAUD} bps)"
                        append_log(f"Conectado com sucesso na porta {port}")
                        request_sd_files()

                    read_serial_responses(ser)

                    # 1) Prioridade maxima: Transferencia de imagem em andamento
                    if not transfer_queue.empty():
                        pkt = transfer_queue.get_nowait()
                        line = json.dumps(pkt, separators=(",", ":")) + "\n"
                        ser.write(line.encode("utf-8"))
                        ser.flush()
                        continue

                    # 2) Prioridade alta: Mudanca de UI instantanea (Event-Driven <50ms)
                    if not ui_event_queue.empty():
                        ev_pkt = ui_event_queue.get_nowait()
                        line = json.dumps(ev_pkt, separators=(",", ":")) + "\n"
                        ser.write(line.encode("utf-8"))
                        ser.flush()
                        state["ui_dirty"] = False
                        state["last_ui_sync"] = time.time()

                    # 3) Envio de telemetria periodica + dados do Mercado Financeiro
                    if sys_metrics is not None:
                        payload = {"sys": sys_metrics}
                        if state["ui_dirty"] or (now - state["last_ui_sync"] >= 10.0):
                            payload["ui"] = get_ui_dict()
                            state["ui_dirty"] = False
                            state["last_ui_sync"] = now

                        if (now - state["last_mkt_sync"] >= 2.0) or ("ui" in payload):
                            if mkt_metrics.get("usd", 0) > 0 or mkt_metrics.get("btc", 0) > 0:
                                payload["mkt"] = mkt_metrics
                                state["last_mkt_sync"] = now

                        line = json.dumps(payload, separators=(",", ":")) + "\n"
                        ser.write(line.encode("utf-8"))
                        ser.flush()

                except Exception as ex:
                    status_dot.bgcolor = "#EF4444"
                    lbl_usb_status.value = "Reconectando USB..."
                    append_log(f"Conexão USB interrompida ({ex})")
                    if ser:
                        try:
                            ser.close()
                        except Exception:
                            pass
                    ser = None
                    time.sleep(2.0)
                    continue

                time.sleep(0.04)

            if ser:
                ser.close()

        threading.Thread(target=serial_worker, daemon=True).start()

    # Inicializa Flet compativel com versoes 1.0+ (ft.run) e 0.2x (ft.app)
    if hasattr(ft, "run"):
        ft.run(build_app)
    else:
        ft.app(target=build_app)


def main():
    ap = argparse.ArgumentParser(description="Agente CYD Hardware & Financial Market Monitor (Flet / Flutter Edition)")
    ap.add_argument("-p", "--port", help="Porta serial, ex: COM5 ou /dev/ttyUSB0")
    ap.add_argument("-i", "--interval", type=float, default=INTERVAL)
    ap.add_argument("--stdout", action="store_true", help="Imprime o JSON no terminal e nao abre GUI")
    ap.add_argument("--once", action="store_true", help="Coleta uma amostra JSON e sai")
    ap.add_argument("--game-proc", action="append", default=[], help="Processo extra de jogo")
    args = ap.parse_args()

    col = Collector(game_processes=args.game_proc)
    mkt_col = MarketCollector(crypto_interval=3.0, stock_interval=12.0)
    time.sleep(0.35)

    if args.stdout or args.once:
        cfg = load_ui_config()
        mkt_col.fetch_once()
        while True:
            payload = {
                "sys": col.sample_sys(),
                "mkt": mkt_col.get_market_dict(),
                "ui": {
                    "screen": cfg["screen"],
                    "color": cfg["color"],
                    "bg": cfg["bg"],
                    "brt": cfg["brt"],
                    "ticker": cfg.get("ticker", True),
                },
            }
            print(json.dumps(payload, ensure_ascii=False))
            sys.stdout.flush()
            if args.once:
                return
            time.sleep(args.interval)

    launch_flet_gui(col, mkt_col, args)


if __name__ == "__main__":
    main()
