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
import asyncio
import base64
import ctypes
import getpass
import hashlib
import http.server
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
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone

try:
    import qrcode
except ImportError:
    qrcode = None

try:
    import paramiko
except ImportError:
    paramiko = None

try:
    import mobile_web
except ImportError:
    try:
        from . import mobile_web
    except Exception:
        import agent.mobile_web as mobile_web

try:
    import wifi_scanner
except ImportError:
    try:
        from . import wifi_scanner
    except Exception:
        import agent.wifi_scanner as wifi_scanner

try:
    import net_analyzer
except ImportError:
    try:
        from . import net_analyzer
    except Exception:
        import agent.net_analyzer as net_analyzer

try:
    import ai_analyst
except ImportError:
    try:
        from . import ai_analyst
    except Exception:
        import agent.ai_analyst as ai_analyst

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
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


def _resolve_config_file() -> str:
    """Resolve onde salvar ui_config.json (diretório do app ou ~/.config/cyd-cyber-deck no Linux/AppImage)."""
    local_cfg = os.path.join(APP_DIR, "ui_config.json")
    if os.path.exists(local_cfg) and os.access(local_cfg, os.W_OK):
        return local_cfg
    if os.access(APP_DIR, os.W_OK) and not os.environ.get("APPIMAGE"):
        return local_cfg
    xdg_cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    cfg_dir = os.path.join(xdg_cfg, "cyd-cyber-deck")
    try:
        os.makedirs(cfg_dir, exist_ok=True)
        return os.path.join(cfg_dir, "ui_config.json")
    except Exception:
        return local_cfg


CONFIG_FILE = _resolve_config_file()


def copy_text_to_clipboard(text: str, page=None) -> bool:
    """Copia texto para a área de transferência no Windows e Linux (Wayland wl-copy / X11 xclip / xsel)."""
    if not text:
        return False
    if page is not None and hasattr(page, "set_clipboard"):
        try:
            page.set_clipboard(text)
            return True
        except Exception:
            pass
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["clip"],
                input=text.encode("utf-16le"),
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        if IS_LINUX:
            for cmd in (
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ):
                if shutil.which(cmd[0]):
                    subprocess.run(cmd, input=text.encode("utf-8"), timeout=1.5, check=False)
                    return True
    except Exception:
        pass
    return False


def get_resource_path(relative_path: str) -> str:
    """Retorna o caminho absoluto do recurso, compativel com PyInstaller (--onefile) e modo script."""
    base_path = getattr(sys, "_MEIPASS", APP_DIR)
    p = os.path.join(base_path, relative_path)
    if os.path.exists(p):
        return p
    p1 = os.path.join(APP_DIR, relative_path)
    if os.path.exists(p1):
        return p1
    root_dir = os.path.dirname(APP_DIR) if os.path.basename(APP_DIR) == "agent" else APP_DIR
    p2 = os.path.join(root_dir, relative_path)
    if os.path.exists(p2):
        return p2
    return p


def get_app_icon_paths() -> tuple[str, str]:
    """
    Resolve os caminhos absolutos da nova identidade visual do projeto:
      - `icone-cyd-resource-monitor.ico` (Ícone nativo da janela Windows / PyInstaller / System Tray)
      - `icone-cyd-resource-monitor.png` (Logotipo PNG de alta resolução para AppBar e NavigationRail)
    """
    ico_candidates = [
        os.path.join("imgs", "icone-cyd-resource-monitor.ico"),
        os.path.join("preview", "5.0", "icone-cyd-resource-monitor.ico"),
        os.path.join("imgs", "imgsCYD.ico"),
    ]
    png_candidates = [
        os.path.join("imgs", "icone-cyd-resource-monitor.png"),
        os.path.join("preview", "5.0", "icone-cyd-resource-monitor.png"),
    ]
    ico_resolved = ""
    for rel in ico_candidates:
        cand = get_resource_path(rel)
        if os.path.exists(cand):
            ico_resolved = os.path.abspath(cand)
            break
    png_resolved = ""
    for rel in png_candidates:
        cand = get_resource_path(rel)
        if os.path.exists(cand):
            png_resolved = os.path.abspath(cand)
            break
    return ico_resolved, png_resolved

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
    (0x303A, 0x1001),  # ESP32 Native USB JTAG/Serial
}

DEFAULT_GAME_PROCESSES = (
    "pcsx2", "rpcs3", "dolphin-emu", "yuzu", "ryujinx", "cemu", "citra",
    "ppsspp", "duckstation", "mupen64plus", "retroarch", "xemu",
    "gamescope", "wine64-preloader", "wine-preloader", "mangohud",
)


def _is_steam_game(exe_path):
    if not exe_path:
        return False
    low = exe_path.replace("\\", "/").lower()
    return "steamapps/common" in low or "/proton" in low


# --------------------------------------------------------------- helpers ----
def run(cmd, timeout=2):
    try:
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=cflags,
        )
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


def get_linux_distro_name() -> str:
    """Retorna o nome amigável da distribuição Linux (ex: 'Zorin OS 17.2 Core')."""
    if not IS_LINUX:
        return f"{platform.system()} {platform.release()}"
    for p in ("/etc/os-release", "/usr/lib/os-release"):
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for ln in f:
                        if ln.startswith("PRETTY_NAME="):
                            val = ln.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass
    return f"Linux {platform.release()}"


def get_linux_cpu_name() -> str:
    """Lê o modelo real do processador via /proc/cpuinfo no Linux."""
    if IS_LINUX and os.path.isfile("/proc/cpuinfo"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    if ln.lower().startswith("model name") and ":" in ln:
                        return ln.split(":", 1)[1].strip()
        except Exception:
            pass
    return platform.processor() or "x86_64 CPU"


def get_cpu_freq_mhz() -> int | None:
    """Retorna o clock atual da CPU em MHz com fallback para sysfs / /proc/cpuinfo no Linux."""
    try:
        freq = psutil.cpu_freq()
        if freq and freq.current and freq.current > 100:
            return int(freq.current)
    except Exception:
        pass
    if IS_LINUX:
        khz = read_int("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
        if khz and khz > 100000:
            return int(khz // 1000)
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                mhz_vals = []
                for ln in f:
                    if ln.lower().startswith("cpu mhz") and ":" in ln:
                        mhz_vals.append(float(ln.split(":", 1)[1].strip()))
                if mhz_vals:
                    return int(max(mhz_vals))
        except Exception:
            pass
    return None


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
                 "acpitz", "soc_thermal", "thinkpad", "nct67", "it86", "it87", "asusec")
CPU_LABEL_HINTS = ("tctl", "tdie", "package", "cpu", "core 0", "composite")


_lhm_web_cache_data = None
_lhm_web_cache_ts = 0.0
_lhm_web_backoff_until = 0.0
_lhm_web_lock = threading.Lock()


def _get_lhm_web_data():
    """
    Consulta o servidor web do LibreHardwareMonitor na porta 8085 com cache de 1.5s
    e backoff inteligente de 30s caso a porta esteja fechada (evita delay de 800ms de SYN no Windows!).
    """
    if not IS_WINDOWS:
        return None
    global _lhm_web_cache_data, _lhm_web_cache_ts, _lhm_web_backoff_until
    now = time.monotonic()
    with _lhm_web_lock:
        if now < _lhm_web_backoff_until:
            return None
        if _lhm_web_cache_data is not None and (now - _lhm_web_cache_ts) < 1.5:
            return _lhm_web_cache_data

    try:
        with urllib.request.urlopen("http://127.0.0.1:8085/data.json", timeout=0.25) as url:
            data = json.loads(url.read().decode("utf-8", errors="ignore"))
            with _lhm_web_lock:
                _lhm_web_cache_data = data
                _lhm_web_cache_ts = time.monotonic()
                _lhm_web_backoff_until = 0.0
            return data
    except Exception:
        with _lhm_web_lock:
            _lhm_web_cache_data = None
            _lhm_web_backoff_until = time.monotonic() + 30.0
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
    """Retorna a temperatura da CPU em graus Celsius (Linux sysfs/hwmon/psutil & Windows LHM/WMI)."""
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

    if IS_LINUX:
        import glob
        for tz in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
            val = read_int(tz)
            if val and 10000 < val < 125000:
                return round(val / 1000.0, 1)

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
    if IS_LINUX:
        import glob
        for fn in glob.glob("/sys/class/hwmon/hwmon*/fan*_input"):
            v = read_int(fn)
            if v and v > 0:
                return int(v)
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
    if IS_LINUX and os.path.isfile("/usr/bin/nvidia-smi"):
        return "/usr/bin/nvidia-smi"
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
            pwr_path = None
            if hw:
                for p_cand in ("power1_average", "power1_input"):
                    cand_full = os.path.join(hw[0], p_cand)
                    if os.path.exists(cand_full):
                        pwr_path = cand_full
                        break
            _amd_paths = {
                "busy": os.path.join(card, "gpu_busy_percent"),
                "vram_used": os.path.join(card, "mem_info_vram_used"),
                "vram_total": os.path.join(card, "mem_info_vram_total"),
                "temp": os.path.join(hw[0], "temp1_input") if hw else None,
                "fan": os.path.join(hw[0], "fan1_input") if hw else None,
                "power": pwr_path,
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


def get_linux_gpu_model_name() -> str:
    """Detecta o nome comercial da GPU no Linux (via nvidia-smi ou lspci)."""
    if _nvidia_smi:
        n_out = run([_nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], timeout=1.5)
        if n_out:
            return n_out.splitlines()[0].strip()[:24]
    if IS_LINUX and shutil.which("lspci"):
        lsp = run(["lspci"], timeout=1.5)
        if lsp:
            for ln in lsp.splitlines():
                low = ln.lower()
                if "vga compatible controller:" in low or "3d controller:" in low or "display controller:" in low:
                    desc = ln.split(":", 2)[-1].strip()
                    m_br = re.findall(r"\[([^\]]+)\]", desc)
                    if m_br:
                        for b in reversed(m_br):
                            if not re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$", b):
                                return b[:24]
                    return desc[:24]
    return "GPU Linux"


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
            "gpu": float(busy) if busy is not None else 0.0,
            "gput": round(temp / 1000.0, 1) if temp else None,
            "vram": round(100.0 * vu / vt, 1) if vu and vt else None,
            "vramu": round(vu / 1073741824.0, 1) if vu else None,
            "vramt": round(vt / 1073741824.0, 1) if vt else None,
            "gpuw": round(pw / 1000000.0, 1) if pw else None,
            "gpufan": read_int(_amd_paths.get("fan") or ""),
            "gpuname": "RADEON",
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
    """
    Coletor de Telemetria de Hardware Otimizado com Cache & Background Worker:
      - Isola leituras pesadas (WMI, LibreHardwareMonitor, nvidia-smi e varredura de processos)
        em uma thread daemon dedicada com cache multinível:
          * Contadores leves (CPU%, RAM%, Disco%, Rede RX/TX): 1.0s
          * Sensores térmicos / GPU (WMI / LHM / nvidia-smi / sysfs): 2.0s
          * Top processos & detecção de jogos/RTSS: 6.0s
      - `sample_sys()` retorna o snapshot em cache instantaneamente (< 0.02 ms, O(1)),
        eliminando picos de CPU/RAM no agente e impedindo qualquer travamento na UI ou Serial.
    """

    def __init__(self, game_processes=(), poll_interval: float = 1.0):
        psutil.cpu_percent(interval=None)
        self._lock = threading.Lock()
        self.poll_interval = max(0.5, float(poll_interval))
        self.host = socket.gethostname()[:14]
        self.prev_net = psutil.net_io_counters()
        self.prev_disk = psutil.disk_io_counters()
        self.prev_t = time.time()
        self.boot_t = psutil.boot_time()
        self.cores = psutil.cpu_count(logical=True)
        self.game_processes = tuple(g.lower() for g in DEFAULT_GAME_PROCESSES + tuple(game_processes))
        self.last_gpu_name = get_linux_gpu_model_name() if IS_LINUX else None

        self._last_heavy_scan = 0.0
        self._last_proc_scan = 0.0
        self._cached_cput = None
        self._cached_fan = None
        self._cached_gpu = {"gpu": 0.0, "gpuname": None}
        self._cached_top = ""
        self._cached_gaming = False
        self._cached_sys: dict = {}
        self._running = True

        # Popula o primeiro snapshot imediatamente (modo rápido) e inicia o worker em background
        self._collect_once_internal(include_heavy=True)
        threading.Thread(target=self._bg_worker, daemon=True, name="HardwareCollectorWorker").start()

    def stop(self):
        self._running = False

    def _collect_once_internal(self, include_heavy: bool = False):
        now = time.time()
        dt = max(now - self.prev_t, 0.1)

        cpu = psutil.cpu_percent(interval=None)
        cpuf_mhz = get_cpu_freq_mhz()
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        du = psutil.disk_usage(SYSTEM_ROOT)

        net = psutil.net_io_counters()
        rx = (net.bytes_recv - self.prev_net.bytes_recv) / dt / 1048576.0 if net and self.prev_net else 0.0
        tx = (net.bytes_sent - self.prev_net.bytes_sent) / dt / 1048576.0 if net and self.prev_net else 0.0
        self.prev_net = net

        dio = psutil.disk_io_counters()
        if dio and self.prev_disk:
            dr = (dio.read_bytes - self.prev_disk.read_bytes) / dt / 1048576.0
            dw = (dio.write_bytes - self.prev_disk.write_bytes) / dt / 1048576.0
        else:
            dr = dw = 0.0
        self.prev_disk = dio
        self.prev_t = now

        # Camada 2: Sensores pesados (WMI / LHM / GPU / Temperatura) em cache de 2.0s
        if include_heavy or (now - self._last_heavy_scan >= 2.0):
            self._last_heavy_scan = now
            try:
                web_data = _get_lhm_web_data()
                self._cached_cput = cpu_temperature(web_data)
                self._cached_gpu = gpu_stats(web_data) or {"gpu": 0.0, "gpuname": None}
                if self._cached_gpu.get("gpuname"):
                    self.last_gpu_name = self._cached_gpu["gpuname"]
                self._cached_fan = fan_rpm() if not web_data else None
            except Exception:
                pass

        # Camada 3: Varredura de processos e jogos em cache de 6.0s
        if now - self._last_proc_scan >= 6.0:
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
                        gaming = (
                            any(g in low for g in self.game_processes)
                            or _is_steam_game(p.info.get("exe"))
                        )
                if procs:
                    top = max(procs)[1][:12]
            except Exception:
                pass
            self._cached_top = top
            self._cached_gaming = gaming

        br = brasilia_now()
        sys_data = {
            "cpu": round(cpu, 1),
            "temp": self._cached_cput,
            "cput": self._cached_cput,
            "cpuf": cpuf_mhz,
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
            "dr": round(max(0.0, dr), 2),
            "dw": round(max(0.0, dw), 2),
            "rx": round(max(0.0, rx), 2),
            "tx": round(max(0.0, tx), 2),
            "up": int(now - self.boot_t),
            "fan": self._cached_fan,
            "host": self.host,
            "top": self._cached_top,
            "game": self._cached_gaming,
            "fps": get_rtss_fps() if self._cached_gaming else None,
        }
        sys_data.update(self._cached_gpu)
        cleaned = {k: v for k, v in sys_data.items() if v is not None}
        with self._lock:
            self._cached_sys = cleaned

    def _bg_worker(self):
        # Inicializa COM para esta thread caso o WMI seja consultado no Windows
        if IS_WINDOWS:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
        while self._running:
            t0 = time.monotonic()
            try:
                self._collect_once_internal(include_heavy=False)
            except Exception:
                pass
            elapsed = time.monotonic() - t0
            time.sleep(max(0.25, self.poll_interval - elapsed))

    def sample_sys(self) -> dict:
        """Retorna instantaneamente (< 0.02ms) o snapshot de telemetria em cache sem bloquear I/O."""
        with self._lock:
            if not self._cached_sys:
                pass
            else:
                snap = dict(self._cached_sys)
                br = brasilia_now()
                snap["hh"] = br.hour
                snap["mm"] = br.minute
                return snap
        self._collect_once_internal(include_heavy=True)
        with self._lock:
            return dict(self._cached_sys)


# ---------------------------------------------------------------- serial ----
def find_port(excluded_ports=None):
    excluded_canon = {wifi_scanner._canonical_port(p) for p in (excluded_ports or set()) if p}
    if IS_LINUX and os.path.exists("/dev/mike"):
        if wifi_scanner._canonical_port("/dev/mike") not in excluded_canon:
            return "/dev/mike"
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("Faltando pyserial. Rode: pip install pyserial")
    cands = list(list_ports.comports())
    for p in cands:
        if wifi_scanner._canonical_port(p.device) in excluded_canon:
            continue
        if p.vid is not None and (p.vid, p.pid) in KNOWN_USB_IDS:
            return p.device
    for p in cands:
        if wifi_scanner._canonical_port(p.device) in excluded_canon:
            continue
        if re.search(r"ttyUSB|ttyACM|^COM\d+$", p.device):
            return p.device
    return None


UDP_DEFAULT_PORT = 8888
# lwIP do Arduino-ESP32 vem com CONFIG_LWIP_IP4_REASSEMBLY desativado: datagramas
# maiores que o MTU (~1472 B) sao DESCARTADOS pela placa. Mantemos margem de seguranca.
UDP_MAX_DATAGRAM = 1400
UDP_ALIVE_TIMEOUT_S = 6.0
UDP_PING_INTERVAL_S = 2.0


def _json_compact(pkt) -> str:
    return json.dumps(pkt, separators=(",", ":"), ensure_ascii=True)


def split_payload_for_udp(pkt: dict, max_bytes: int = UDP_MAX_DATAGRAM) -> list[str]:
    """
    Fragmenta um payload JSON em datagramas independentes <= max_bytes.
      - Agrupa chaves de topo ("sys", "mkt", "ui", "news"...) de forma gulosa: o firmware
        processa cada bloco de forma independente em applyJson(), entao a divisao e segura.
      - Se um bloco isolado ainda exceder o limite (ex: "news" com fila de manchetes),
        reduz a fila de manchetes progressivamente ate caber.
    """
    raw = _json_compact(pkt)
    if len(raw) <= max_bytes or not isinstance(pkt, dict):
        return [raw]

    def _shrink_block(key, val):
        blk = {key: val}
        if len(_json_compact(blk)) <= max_bytes:
            return blk
        if key == "news" and isinstance(val, dict) and isinstance(val.get("queue"), list):
            v2 = dict(val)
            q = list(v2["queue"])
            while q and len(_json_compact({key: v2})) > max_bytes:
                q = q[:-1]
                v2["queue"] = q
            if len(_json_compact({key: v2})) <= max_bytes:
                return {key: v2}
        return blk  # Ultimo recurso: envia mesmo assim (pode ser descartado pela placa)

    datagrams: list[str] = []
    cur: dict = {}
    for k, v in pkt.items():
        blk = _shrink_block(k, v)
        trial = dict(cur)
        trial.update(blk)
        if cur and len(_json_compact(trial)) > max_bytes:
            datagrams.append(_json_compact(cur))
            cur = dict(blk)
        else:
            cur = trial
    if cur:
        datagrams.append(_json_compact(cur))
    return datagrams


class SerialManager:
    """
    Gerenciador Híbrido de Transporte (USB Serial 115200 bps + Wi-Fi UDP :8888):
      - Isola 100% do I/O (pyserial + socket UDP) em threads dedicadas. O loop do Flet
        NUNCA espera resposta da CYD nem bloqueia em `ser.write()` / `sendto()`.
      - Rota única por pacote (nunca duplicada): se o mesmo pacote fosse por USB e UDP,
        chunks de upload seriam gravados 2x no SD, o Buzzer tocaria 2x e os gráficos
        avançariam em dobro. Política de roteamento:
          1. UDP ativo + placa respondendo PONG (< 6s)  -> Wi-Fi UDP (rota principal)
          2. USB conectado                               -> USB Serial (fallback/debug)
          3. UDP ativo sem resposta e sem USB            -> Wi-Fi UDP "às cegas"
      - Heartbeat `{"cmd":"udp_ping"}` a cada 2s; a CYD responde `UDP_PONG:<uptime>:<ip>`.
        Uptime regressivo = placa reiniciou -> dispara `MONITOR_READY` para reenviar o estado.
      - 3 canais de prioridade:
          1. `transfer_queue`: blocos de imagem/capa para o Cartão SD (controle por ACK).
          2. `event_queue`: tela, cor, brilho, alertas, Terminal (< 20ms). Aceita `dict`
             ou tupla `("serial", dict)` para forçar a rota USB (ex: provisionamento Wi-Fi).
          3. `_latest_telemetry`: slot atômico (descarta frames velhos, zero lag acumulado).
      - Abertura da porta COM sem `sleep` bloqueante: a janela de boot do ESP32 (1.5s) é
        controlada por timestamp, então o UDP continua transmitindo durante a reconexão USB.
    """

    def __init__(
        self,
        preferred_port: str = None,
        baud: int = BAUD,
        on_rx_line=None,
        on_status_change=None,
        on_log=None,
        auto_start: bool = True,
        udp_enabled: bool = False,
        udp_ip: str = "",
        udp_port: int = UDP_DEFAULT_PORT,
        excluded_ports_fn=None,
    ):
        self.preferred_port = preferred_port
        self.baud = int(baud)
        self.on_rx_line = on_rx_line
        self.on_status_change = on_status_change
        self.on_log = on_log
        self.excluded_ports_fn = excluded_ports_fn
        self._scanner_ignored_ports: dict[str, float] = {}
        self._wrong_board_port: str = ""
        self._active_serial_port: str = ""

        self.event_queue: queue.Queue = queue.Queue()
        self.transfer_queue: queue.Queue = queue.Queue()
        self.ack_event = threading.Event()
        self.last_ack = {"val": None}

        self._telemetry_lock = threading.Lock()
        self._latest_telemetry: dict | None = None

        # ---- Wi-Fi UDP ----
        self._udp_lock = threading.Lock()
        self._udp_enabled = bool(udp_enabled)
        self._udp_ip = (udp_ip or "").strip()
        self._udp_port = int(udp_port or UDP_DEFAULT_PORT)
        self._udp_sock: socket.socket | None = None
        self._udp_rx_thread: threading.Thread | None = None
        self._udp_alive_t = 0.0
        self._udp_last_uptime = -1
        self._udp_last_ping_t = 0.0
        self._udp_ping_sent_t = 0.0
        self.detected_ip = ""

        self._status_lock = threading.Lock()
        self._status = {
            "connected": False,
            "state": "SEARCHING",
            "port": "",
            "baud": self.baud,
            "tx_packets": 0,
            "rx_packets": 0,
            "tx_bytes_sec": 0,
            "last_error": "",
            "transport": "NONE",  # NONE | USB | UDP
            "udp_enabled": self._udp_enabled,
            "udp_target": self._udp_target_str(),
            "udp_alive": False,
            "udp_rtt_ms": 0,
            "udp_tx": 0,
            "udp_drop": 0,
        }
        self._running = False
        self._reconnect_flag = threading.Event()
        self._thread: threading.Thread | None = None

        if auto_start:
            self.start()

    # ------------------------------------------------------------ API pública
    def set_callbacks(self, on_rx_line=None, on_status_change=None, on_log=None):
        """Define ou atualiza callbacks assíncronos de linha recebida e status."""
        if on_rx_line is not None:
            self.on_rx_line = on_rx_line
        if on_status_change is not None:
            self.on_status_change = on_status_change
        if on_log is not None:
            self.on_log = on_log
        if not self._running:
            self.start()

    def get_status_snapshot(self) -> dict:
        """Alias para get_status(). Retorna uma cópia thread-safe do estado da conexão."""
        return self.get_status()

    def get_active_ports(self) -> set[str]:
        """Retorna a porta serial atualmente aberta pela CYD (para evitar conflito com o Scanner ESP32)."""
        p = self._active_serial_port
        return {p} if p else set()

    def set_excluded_ports_fn(self, fn):
        self.excluded_ports_fn = fn

    def _get_excluded_ports(self) -> set[str]:
        excluded: set[str] = set()
        if self.excluded_ports_fn:
            try:
                res = self.excluded_ports_fn()
                if isinstance(res, str) and res:
                    excluded.add(res)
                elif res:
                    for item in res:
                        if item:
                            excluded.add(str(item))
            except Exception:
                pass
        now_m = time.monotonic()
        expired = [k for k, exp in self._scanner_ignored_ports.items() if now_m >= exp]
        for k in expired:
            self._scanner_ignored_ports.pop(k, None)
        excluded.update(self._scanner_ignored_ports.keys())
        return excluded

    def start(self):
        if self._running:
            return
        self._running = True
        self._ensure_udp_socket()
        self._thread = threading.Thread(target=self._io_worker, daemon=True, name="SerialManagerThread")
        self._thread.start()

    def stop(self):
        self._running = False
        self._reconnect_flag.set()
        with self._udp_lock:
            if self._udp_sock is not None:
                try:
                    self._udp_sock.close()
                except Exception:
                    pass
                self._udp_sock = None

    def request_reconnect(self, new_port: str = None):
        if new_port is not None:
            self.preferred_port = new_port.strip() or None
        self._reconnect_flag.set()

    def configure_udp(self, enabled: bool, ip: str = None, port: int = None):
        """Ativa/desativa a transmissão Wi-Fi UDP e define o IP:porta da placa CYD (thread-safe)."""
        with self._udp_lock:
            self._udp_enabled = bool(enabled)
            if ip is not None:
                self._udp_ip = (ip or "").strip()
            if port is not None:
                try:
                    self._udp_port = max(1, min(65535, int(port)))
                except Exception:
                    self._udp_port = UDP_DEFAULT_PORT
            self._udp_alive_t = 0.0
            self._udp_last_ping_t = 0.0
        self._ensure_udp_socket()
        self._update_status(
            udp_enabled=self._udp_enabled,
            udp_target=self._udp_target_str(),
            udp_alive=False,
        )
        if self.on_log:
            if self._udp_enabled and self._udp_ip:
                self.on_log(f"📶 Wi-Fi UDP ativado → {self._udp_target_str()} (USB Serial como fallback)")
            elif self._udp_enabled:
                self.on_log("📶 Wi-Fi UDP ativado, mas sem IP da CYD configurado.")
            else:
                self.on_log("🔌 Wi-Fi UDP desativado. Transmissão 100% via USB Serial.")

    def is_udp_alive(self) -> bool:
        return self._udp_ready() and (time.monotonic() - self._udp_alive_t) < UDP_ALIVE_TIMEOUT_S

    def clear_pending_events(self):
        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
            except Exception:
                break

    def send_event(self, pkt: dict, coalesce: bool = False, route: str = "auto"):
        """Enfileira um comando/evento de alta prioridade (< 20ms) sem bloquear a UI.
        route="serial" força o envio exclusivamente pela USB (ex: credenciais Wi-Fi)."""
        if not pkt:
            return
        if coalesce:
            self.clear_pending_events()
        self.event_queue.put((route, pkt) if route != "auto" else pkt)

    def send_transfer(self, pkt: dict):
        """Enfileira um bloco de transferência para o Cartão SD."""
        if pkt:
            self.transfer_queue.put(pkt)

    def send_telemetry(self, payload: dict):
        """Atualiza o slot atômico de telemetria (sempre envia o pacote mais fresco)."""
        with self._telemetry_lock:
            self._latest_telemetry = payload

    def wait_for_ack(self, expected_prefix: str, timeout: float = 4.0) -> tuple[bool, str]:
        """Aguarda resposta ACK_/ERR_ da placa CYD (chega por USB ou UDP, conforme a rota ativa)."""
        t0 = time.monotonic()
        while (time.monotonic() - t0) < timeout:
            if self.ack_event.wait(timeout=0.06):
                self.ack_event.clear()
                val = self.last_ack.get("val") or ""
                if val.startswith("ERR_NO_SD"):
                    return False, "ERR_NO_SD"
                if val.startswith("ERR_OPEN"):
                    return False, "ERR_OPEN"
                if val.startswith(expected_prefix):
                    return True, val
        return False, "TIMEOUT"

    def get_status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    # ------------------------------------------------------------ internos
    def _udp_target_str(self) -> str:
        return f"{self._udp_ip}:{self._udp_port}" if self._udp_ip else ""

    def _udp_ready(self) -> bool:
        return self._udp_enabled and bool(self._udp_ip) and self._udp_sock is not None

    def _update_status(self, **kwargs):
        changed = False
        with self._status_lock:
            for k, v in kwargs.items():
                if self._status.get(k) != v:
                    self._status[k] = v
                    changed = True
            snap = dict(self._status)
        if changed and self.on_status_change:
            try:
                self.on_status_change(snap)
            except Exception:
                pass

    def _ensure_udp_socket(self):
        """Cria (uma única vez) o socket UDP não-bloqueante + thread receptora de respostas."""
        with self._udp_lock:
            if self._udp_sock is not None:
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
                s.bind(("0.0.0.0", 0))  # Porta efêmera: a CYD responde para (ip, porta) de origem
                s.settimeout(0.5)
                # Windows: evita WSAECONNRESET (10054) no recvfrom quando a CYD está offline
                if IS_WINDOWS and hasattr(socket, "SIO_UDP_CONNRESET"):
                    try:
                        s.ioctl(socket.SIO_UDP_CONNRESET, False)
                    except Exception:
                        pass
                self._udp_sock = s
            except Exception as ex:
                self._udp_sock = None
                if self.on_log:
                    self.on_log(f"⚠️ Falha ao criar socket UDP: {str(ex)[:60]}")
                return
        self._udp_rx_thread = threading.Thread(target=self._udp_rx_worker, daemon=True, name="UdpRxThread")
        self._udp_rx_thread.start()

    def _udp_sendto(self, pkt: dict) -> int:
        """Envia um pacote via UDP (fragmentado em datagramas <= 1400 B). Nunca lança exceção."""
        sock = self._udp_sock
        if sock is None or not self._udp_ip:
            return 0
        sent = 0
        target = (self._udp_ip, self._udp_port)
        for dg in split_payload_for_udp(pkt):
            try:
                sock.sendto(dg.encode("utf-8"), target)
                sent += len(dg)
            except OSError:
                with self._status_lock:
                    self._status["udp_drop"] += 1
        if sent:
            with self._status_lock:
                self._status["tx_packets"] += 1
                self._status["udp_tx"] += 1
        return sent

    def _write_json_line(self, ser, pkt: dict) -> int:
        raw_bytes = (_json_compact(pkt) + "\n").encode("utf-8")
        # Se o buffer de saída do driver estiver congestionado, faz flush preventivo
        try:
            out_w = getattr(ser, "out_waiting", 0)
            if out_w and out_w > 4096:
                ser.reset_output_buffer()
        except Exception:
            pass
        ser.write(raw_bytes)
        ser.flush()
        with self._status_lock:
            self._status["tx_packets"] += 1
        return len(raw_bytes)

    def _resolve_route(self, ser_ready: bool) -> str | None:
        if self._udp_ready() and self.is_udp_alive():
            return "udp"
        if ser_ready:
            return "serial"
        if self._udp_ready():
            return "udp"
        return None

    def _send_pkt(self, ser, route: str, pkt: dict) -> int:
        if route == "udp":
            return self._udp_sendto(pkt)
        if route == "serial" and ser is not None:
            return self._write_json_line(ser, pkt)
        return 0

    def _handle_rx_line(self, raw: str, via: str):
        """Processa uma linha recebida da CYD (mesmo tratamento para USB e UDP)."""
        if not raw:
            return
        # Protecao dual-ESP32: se esta porta serial responder como ESP32 Scanner, libera imediatamente
        if via == "serial" and not self.preferred_port and wifi_scanner.is_scanner_banner_line(raw):
            cur_p = self._active_serial_port
            if cur_p:
                self._scanner_ignored_ports[wifi_scanner._canonical_port(cur_p)] = time.monotonic() + 30.0
                self._wrong_board_port = cur_p
            return
        with self._status_lock:
            self._status["rx_packets"] += 1

        if raw.startswith("UDP_PONG"):
            # Formato: UDP_PONG:<uptime_s>:<ip>
            parts = raw.split(":")
            now_m = time.monotonic()
            rtt = int((now_m - self._udp_ping_sent_t) * 1000) if self._udp_ping_sent_t else 0
            self._udp_alive_t = now_m
            try:
                up = int(parts[1]) if len(parts) > 1 else -1
            except Exception:
                up = -1
            rebooted = self._udp_last_uptime >= 0 and 0 <= up < self._udp_last_uptime
            self._udp_last_uptime = up
            if len(parts) > 2 and parts[2]:
                self.detected_ip = parts[2]
            self._update_status(udp_alive=True, udp_rtt_ms=max(0, min(rtt, 9999)))
            if rebooted and self.on_rx_line:
                try:
                    self.on_rx_line("MONITOR_READY")
                except Exception:
                    pass
            return

        if raw.startswith("WIFI_IP:"):
            self.detected_ip = raw.split("WIFI_IP:", 1)[1].strip()

        if raw.startswith("ACK_") or raw.startswith("ERR_"):
            self.last_ack["val"] = raw
            self.ack_event.set()
        elif self.on_rx_line:
            try:
                self.on_rx_line(raw)
            except Exception:
                pass

    def _udp_rx_worker(self):
        """Thread receptora: respostas da CYD (TERM_LOG, ACK_, SD_FILES, UDP_PONG) via Wi-Fi."""
        while self._running or self._udp_sock is not None:
            sock = self._udp_sock
            if sock is None:
                break
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                # Windows: WSAECONNRESET (10054) quando um ICMP "port unreachable" retorna; ignora
                if not self._running:
                    break
                time.sleep(0.05)
                continue
            if self._udp_ip and addr[0] != self._udp_ip:
                continue  # Ignora pacotes de outros hosts da rede
            for ln in data.decode("utf-8", errors="ignore").splitlines():
                self._handle_rx_line(ln.strip(), via="udp")

    def _read_available_lines(self, ser):
        lines_read = 0
        while lines_read < 32:
            try:
                waiting = ser.in_waiting
            except Exception:
                break
            if waiting <= 0:
                break
            if waiting > 8192:
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass
                break
            try:
                raw = ser.readline().decode("utf-8", errors="ignore").strip()
            except Exception:
                break
            lines_read += 1
            self._handle_rx_line(raw, via="serial")

    def _io_worker(self):
        import serial

        ser = None
        ser_settle_until = 0.0  # Janela de boot do ESP32 após abrir a COM (DTR/RTS reset)
        ser_ready = False
        next_port_scan = 0.0
        bytes_window = 0
        window_t0 = time.monotonic()

        def _close_serial():
            nonlocal ser, ser_ready
            if ser is not None:
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    ser.close()
                except Exception:
                    pass
            ser = None
            ser_ready = False
            self._active_serial_port = ""

        while self._running:
            now_m = time.monotonic()

            # ---------- 1) Ciclo de vida da porta USB (100% não-bloqueante) ----------
            try:
                if self._wrong_board_port:
                    wrong_p = self._wrong_board_port
                    self._wrong_board_port = ""
                    _close_serial()
                    next_port_scan = now_m + 0.5
                    self._update_status(connected=False, state="SEARCHING", port="")
                    if self.on_log:
                        self.on_log(f"📡 Porta {wrong_p} identificada como ESP32 Scanner Wi-Fi (liberada para o Radar RF).")

                if self._reconnect_flag.is_set():
                    self._reconnect_flag.clear()
                    _close_serial()
                    next_port_scan = 0.0
                    self._update_status(connected=False, state="RECONNECTING", port="", tx_bytes_sec=0)

                if ser is None and now_m >= next_port_scan:
                    port = self.preferred_port or find_port(excluded_ports=self._get_excluded_ports())
                    if not port:
                        self._update_status(connected=False, state="SEARCHING", port="")
                        next_port_scan = now_m + 1.5
                    else:
                        self._update_status(connected=False, state="CONNECTING", port=port)
                        ser = serial.Serial(port=port, baudrate=self.baud, timeout=0.04, write_timeout=0.35)
                        self._active_serial_port = port
                        ser_settle_until = now_m + 1.5
                        ser_ready = False

                if ser is not None and not ser_ready and now_m >= ser_settle_until:
                    # Antes de limpar o buffer, verifica se o banner de boot e da ESP32 Scanner
                    self._read_available_lines(ser)
                    if self._wrong_board_port:
                        continue
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    ser_ready = True
                    port_name = getattr(ser, "port", "") or ""
                    self._active_serial_port = port_name
                    self._update_status(connected=True, state="CONNECTED", port=port_name, last_error="")
                    if self.on_log:
                        self.on_log(f"⚡ USB Serial conectada em {port_name} ({self.baud} bps • Non-Blocking I/O)")
                    if self.on_rx_line:
                        try:
                            self.on_rx_line("SERIAL_CONNECTED")
                        except Exception:
                            pass
            except Exception as ex:
                err_s = str(ex)[:60]
                if IS_LINUX and ("Permission denied" in str(ex) or "Errno 13" in str(ex)):
                    now_warn = time.monotonic()
                    if now_warn - getattr(self, "_last_perm_warn_t", 0.0) >= 15.0:
                        self._last_perm_warn_t = now_warn
                        if self.on_log:
                            self.on_log(
                                f"⚠️ Sem permissão na porta {port} (Errno 13)! "
                                "No Ubuntu/Linux rode: ./linux/install_ubuntu.sh ou 'sudo usermod -aG dialout $USER' e relogue."
                            )
                _close_serial()
                next_port_scan = now_m + 1.5
                self._update_status(connected=False, state="DISCONNECTED", port="", last_error=err_s)

            # ---------- 2) Heartbeat UDP + estado da rota Wi-Fi ----------
            if self._udp_ready() and (now_m - self._udp_last_ping_t) >= UDP_PING_INTERVAL_S:
                self._udp_last_ping_t = now_m
                self._udp_ping_sent_t = now_m
                self._udp_sendto({"cmd": "udp_ping"})
            udp_alive = self.is_udp_alive()
            if self._status.get("udp_alive") != udp_alive:
                self._update_status(udp_alive=udp_alive)

            route = self._resolve_route(ser_ready)
            self._update_status(transport={"udp": "UDP", "serial": "USB"}.get(route, "NONE"))

            # ---------- 3) Leitura + envio por prioridade ----------
            try:
                if ser_ready:
                    self._read_available_lines(ser)

                if route is None:
                    time.sleep(0.05)
                    continue

                # Prioridade 1: Transferência de blocos para o Cartão SD (sincronizada por ACK)
                if not self.transfer_queue.empty():
                    pkt = self.transfer_queue.get_nowait()
                    bytes_window += self._send_pkt(ser, route, pkt)
                    continue

                # Prioridade 2: Eventos imediatos de UI / Terminal / Alertas (< 20ms)
                ev_sent = 0
                while not self.event_queue.empty() and ev_sent < 3:
                    item = self.event_queue.get_nowait()
                    ev_route = route
                    if isinstance(item, tuple):
                        forced, item = item
                        if forced == "serial":
                            if not ser_ready:
                                if self.on_log:
                                    self.on_log("⚠️ Comando exige USB Serial conectada (descartado).")
                                ev_sent += 1
                                continue
                            ev_route = "serial"
                    bytes_window += self._send_pkt(ser, ev_route, item)
                    ev_sent += 1

                # Prioridade 3: Telemetria periódica (apenas o snapshot mais recente)
                tele_pkt = None
                with self._telemetry_lock:
                    if self._latest_telemetry is not None:
                        tele_pkt = self._latest_telemetry
                        self._latest_telemetry = None
                if tele_pkt is not None:
                    bytes_window += self._send_pkt(ser, route, tele_pkt)

                # Atualiza taxa de transmissão (B/s) a cada 1.0s
                if now_m - window_t0 >= 1.0:
                    bps = int(round(bytes_window / (now_m - window_t0)))
                    bytes_window = 0
                    window_t0 = now_m
                    with self._status_lock:
                        self._status["tx_bytes_sec"] = bps

            except Exception as ex:
                # Somente erros de I/O USB chegam aqui (envios UDP nunca lançam exceção)
                err_s = str(ex)[:60]
                self._update_status(connected=False, state="DISCONNECTED", port="", last_error=err_s)
                if self.on_log:
                    self.on_log(f"⚠️ Porta USB desconectada ou ocupada ({err_s}). Reconectando em background...")
                _close_serial()
                next_port_scan = time.monotonic() + 1.5
                continue

            time.sleep(0.015)

        _close_serial()


def get_local_lan_ip() -> str:
    """Detecta o IP do PC na rede local Wi-Fi/Ethernet (ex: 192.168.0.109)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_qr_base64(url: str) -> str:
    """Gera imagem PNG Base64 do QR Code apontando para o URL mobile."""
    if not qrcode:
        return ""
    try:
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#FFFFFF")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def prepare_image_bytes_for_cyd(filename: str, raw_bytes: bytes) -> tuple[str, bytes]:
    """
    Prepara bytes de imagem (enviados do celular ou carregados do disco) para o Cartao SD da CYD (320x240):
    - Se for .gif: mantem bytes originais.
    - Se for .jpg, .jpeg, .png, .bmp: redimensiona/recorta em 320x240 usando Pillow
      e converte para JPEG Baseline otimizado (~15 KB) para streaming serial rapido
      e compatibilidade total com o TJpg_Decoder do ESP32.
    """
    ext = os.path.splitext(filename)[1].lower()
    raw_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", os.path.splitext(os.path.basename(filename))[0])[:18]
    if not raw_base:
        raw_base = "mob_wall"

    if ext == ".gif":
        return f"{raw_base}.gif", raw_bytes

    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        img = ImageOps.fit(img, (320, 240), method=Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True, progressive=False)
        return f"{raw_base}.jpg", buf.getvalue()
    except Exception:
        return f"{raw_base}{ext if ext else '.jpg'}", raw_bytes


def prepare_image_for_cyd(filepath: str) -> tuple[str, bytes]:
    """Prepara uma imagem do disco local para a CYD delegando para prepare_image_bytes_for_cyd."""
    with open(filepath, "rb") as f:
        return prepare_image_bytes_for_cyd(os.path.basename(filepath), f.read())


def ascii_for_tft(text: str, max_len: int = 44) -> str:
    """Normaliza acentos e caracteres especiais UTF-8 para ASCII limpo suportado pelas fontes nativas do TFT_eSPI."""
    if not text:
        return ""
    s = str(text)
    for src_ch, dst_ch in (("—", "-"), ("–", "-"), ("•", "-"), ("“", '"'), ("”", '"'), ("’", "'"), ("‘", "'")):
        s = s.replace(src_ch, dst_ch)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


def prepare_media_cover_for_cyd(raw_bytes: bytes) -> tuple[bytes, str, str]:
    """
    Prepara a capa do álbum (Spotify 1:1 ou YouTube Music 16:9 / 1:1) em 320x240 JPEG Baseline (~12 KB)
    para gravação rápida no Cartão SD da CYD + retorna (jpeg_cyd_bytes, preview_b64_png, cover_id_8hex).
    Remove barras pretas laterais de thumbnails 16:9 do YouTube Music automaticamente!
    """
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    w, h = img.size

    # Se vier thumbnail 16:9 do YouTube Music com barras laterais escuras, recorta o quadrado central da capa
    if w > h * 1.28 and h > 40:
        margin_w = int((w - h) / 2)
        if margin_w > 8:
            left_strip = img.crop((0, int(h * 0.15), min(margin_w, 24), int(h * 0.85)))
            raw_strip = left_strip.tobytes()
            if raw_strip:
                avg_luma = sum(raw_strip) / float(len(raw_strip))
                if avg_luma < 28.0:
                    sq = int(h)
                    x0 = max(0, (w - sq) // 2)
                    img = img.crop((x0, 0, x0 + sq, h))

    # Preview nítido 160x160 para a interface Flet Desktop e Smartphone WebApp
    prev_img = ImageOps.fit(img, (160, 160), method=Image.Resampling.LANCZOS)
    prev_buf = io.BytesIO()
    prev_img.save(prev_buf, format="JPEG", quality=84)
    prev_b64 = base64.b64encode(prev_buf.getvalue()).decode("ascii")

    # Imagem 320x240 Baseline JPEG otimizada para o TJpg_Decoder do ESP32 (foco levemente superior p/ overlay)
    cyd_img = ImageOps.fit(img, (320, 240), method=Image.Resampling.LANCZOS, centering=(0.5, 0.32))
    cyd_buf = io.BytesIO()
    cyd_img.save(cyd_buf, format="JPEG", quality=78, optimize=True, progressive=False)
    cyd_bytes = cyd_buf.getvalue()
    cid = hashlib.md5(cyd_bytes).hexdigest()[:8]
    return cyd_bytes, prev_b64, cid


DEFAULT_ALERT_RULES = [
    {
        "id": "cpu_temp",
        "name": "CPU Temp Crítica",
        "source": "cput",
        "op": ">",
        "val": 85.0,
        "bz": True,
        "led": "0xF800",
        "p": 3,
        "enabled": True,
        "cooldown_s": 45.0,
    },
    {
        "id": "gpu_temp",
        "name": "GPU Temp Crítica",
        "source": "gput",
        "op": ">",
        "val": 82.0,
        "bz": True,
        "led": "0xF800",
        "p": 3,
        "enabled": True,
        "cooldown_s": 45.0,
    },
    {
        "id": "cpu_load",
        "name": "CPU Sobrecarga",
        "source": "cpu",
        "op": ">",
        "val": 95.0,
        "bz": False,
        "led": "0xFD20",
        "p": 2,
        "enabled": True,
        "cooldown_s": 30.0,
    },
    {
        "id": "ram_load",
        "name": "RAM Sobrecarga",
        "source": "ram",
        "op": ">",
        "val": 92.0,
        "bz": False,
        "led": "0xFD20",
        "p": 2,
        "enabled": True,
        "cooldown_s": 30.0,
    },
    {
        "id": "btc_target",
        "name": "Bitcoin > 100k USD",
        "source": "btc",
        "op": ">",
        "val": 100000.0,
        "bz": True,
        "led": "0x07E0",
        "p": 1,
        "enabled": False,
        "cooldown_s": 60.0,
    },
    {
        "id": "usd_target",
        "name": "Dólar > 6.00 BRL",
        "source": "usd",
        "op": ">",
        "val": 6.00,
        "bz": True,
        "led": "0xF81F",
        "p": 2,
        "enabled": False,
        "cooldown_s": 60.0,
    },
]


_LINUX_IDLE_CACHE = {"ts": 0.0, "val": 0.0}


def get_system_idle_seconds() -> float:
    """Retorna o tempo de inatividade do usuário (sem uso de mouse/teclado) em segundos no Windows e Linux (Zorin OS Wayland/X11)."""
    try:
        if sys.platform == "win32":
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                return max(0.0, millis / 1000.0)
        elif IS_LINUX:
            now_m = time.monotonic()
            if now_m - _LINUX_IDLE_CACHE["ts"] < 2.0:
                return _LINUX_IDLE_CACHE["val"]
            _LINUX_IDLE_CACHE["ts"] = now_m

            # 1) Zorin OS / Ubuntu (GNOME Shell Mutter IdleMonitor via D-Bus - suporta Wayland e X11)
            if shutil.which("gdbus"):
                try:
                    res = subprocess.run(
                        [
                            "gdbus", "call", "--session",
                            "--dest", "org.gnome.Mutter.IdleMonitor",
                            "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                            "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime",
                        ],
                        capture_output=True, text=True, timeout=0.45,
                    )
                    if res.returncode == 0 and res.stdout:
                        m = re.search(r"uint64\s+(\d+)|\((\d+),?\)", res.stdout)
                        if m:
                            ms = int(m.group(1) or m.group(2))
                            val = max(0.0, ms / 1000.0)
                            _LINUX_IDLE_CACHE["val"] = val
                            return val
                except Exception:
                    pass

            # 2) Utilitário leve xprintidle (X11 / Zorin OS Lite XFCE)
            if shutil.which("xprintidle"):
                try:
                    res = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=0.35)
                    if res.returncode == 0 and res.stdout.strip().isdigit():
                        val = max(0.0, int(res.stdout.strip()) / 1000.0)
                        _LINUX_IDLE_CACHE["val"] = val
                        return val
                except Exception:
                    pass

            # 3) X11 libXss.so.1 direta via ctypes
            if os.environ.get("DISPLAY"):
                try:
                    class XScreenSaverInfo(ctypes.Structure):
                        _fields_ = [
                            ("window", ctypes.c_ulong),
                            ("state", ctypes.c_int),
                            ("kind", ctypes.c_int),
                            ("til_or_since", ctypes.c_ulong),
                            ("idle", ctypes.c_ulong),
                            ("eventMask", ctypes.c_ulong),
                        ]

                    libX11 = ctypes.cdll.LoadLibrary("libX11.so.6")
                    libXss = ctypes.cdll.LoadLibrary("libXss.so.1")
                    libX11.XOpenDisplay.restype = ctypes.c_void_p
                    libX11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
                    libX11.XDefaultRootWindow.restype = ctypes.c_ulong
                    libXss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
                    libXss.XScreenSaverQueryInfo.argtypes = [
                        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XScreenSaverInfo)
                    ]

                    dpy = libX11.XOpenDisplay(None)
                    if dpy:
                        try:
                            root = libX11.XDefaultRootWindow(dpy)
                            xss_info = libXss.XScreenSaverAllocInfo()
                            if xss_info:
                                try:
                                    if libXss.XScreenSaverQueryInfo(dpy, root, xss_info):
                                        val = max(0.0, float(xss_info.contents.idle) / 1000.0)
                                        _LINUX_IDLE_CACHE["val"] = val
                                        return val
                                finally:
                                    libX11.XFree(xss_info)
                        finally:
                            libX11.XCloseDisplay(dpy)
                except Exception:
                    pass
    except Exception:
        pass
    return 0.0


def calculate_dynamic_brightness(base_brt: int, cfg_state: dict) -> tuple[int, str]:
    """Calcula o brilho dinâmico (0-255) baseado em inatividade (Sleep) e horário (Modo Noturno)."""
    # 1) Detecção de Sleep por inatividade de mouse/teclado
    if cfg_state.get("sleep_enabled", True):
        timeout_sec = cfg_state.get("sleep_timeout_min", 15) * 60
        idle_sec = get_system_idle_seconds()
        if idle_sec >= timeout_sec:
            return 0, f"Sleep Mode (ocioso há {int(idle_sec // 60)} min)"

    # 2) Modo Noturno automático (ex: 22h às 06h)
    if cfg_state.get("night_mode_enabled", True):
        cur_h = datetime.now().hour
        start_h = cfg_state.get("night_start_hour", 22)
        end_h = cfg_state.get("night_end_hour", 6)
        is_night = False
        if start_h > end_h:
            is_night = (cur_h >= start_h or cur_h < end_h)
        else:
            is_night = (start_h <= cur_h < end_h)

        if is_night:
            night_brt = cfg_state.get("night_brightness", 40)
            return min(base_brt, night_brt), f"Modo Noturno ({start_h}h-{end_h}h, máx {night_brt})"

    return base_brt, "Normal"


def evaluate_alert_rules(rules: list, sys_m: dict, mkt_m: dict, last_fired_dict: dict, now_t: float) -> dict | None:
    """Avalia regras de gatilhos físicos. Retorna dicionário do alerta se disparado."""
    for r in rules:
        if not r.get("enabled", True):
            continue
        src = r.get("source")
        op = r.get("op", ">")
        target_val = float(r.get("val", 0.0))
        rule_id = r.get("id", f"{src}_{op}_{target_val}")

        curr_val = None
        if sys_m and src in sys_m:
            curr_val = sys_m[src]
        elif mkt_m and src in mkt_m:
            curr_val = mkt_m[src]

        if curr_val is None:
            continue

        try:
            curr_val = float(curr_val)
        except (ValueError, TypeError):
            continue

        is_triggered = (curr_val > target_val) if op == ">" else (curr_val < target_val)
        if is_triggered:
            last_t = last_fired_dict.get(rule_id, 0.0)
            cooldown = r.get("cooldown_s", 45.0)
            if now_t - last_t >= cooldown:
                last_fired_dict[rule_id] = now_t
                return {
                    "rule_name": r.get("name", rule_id),
                    "curr_val": curr_val,
                    "target_val": target_val,
                    "op": op,
                    "alrt": {
                        "bz": bool(r.get("bz", False)),
                        "led": str(r.get("led", "0xF800")),
                        "p": int(r.get("p", 1)),
                    },
                }
    return None


DEFAULT_PORTFOLIO = [
    {"ticker": "BTC", "qty": 0.025, "avg_price": 370000.0, "currency": "BRL"},
    {"ticker": "ETH", "qty": 0.40, "avg_price": 11200.0, "currency": "BRL"},
    {"ticker": "PETR4", "qty": 100.0, "avg_price": 35.80, "currency": "BRL"},
]

DEFAULT_NEWS_TOPICS = [
    "Política",
    "Tecnologia",
    "Relações Internacionais",
    "Mercado Financeiro",
]

ALL_PRESET_NEWS_TOPICS = [
    "Política",
    "Tecnologia",
    "Relações Internacionais",
    "Mercado Financeiro",
    "Sistemas Embarcados",
    "Cibersegurança & Linux",
    "Ciência & Espaço",
]

DEFAULT_GEMS = [
    {
        "id": "gem_embedded",
        "name": "🔧 Radar Embarcados & IoT",
        "topic": "Sistemas Embarcados ESP32 IoT Microcontroladores",
        "prompt": (
            "Traga as 3 notícias ou novidades técnicas mais recentes sobre Sistemas Embarcados, "
            "ESP32, Microcontroladores, RTOS e IoT em 3 tópicos curtos (máx 340 caracteres no total), "
            "diretos e sem formatação markdown complexa."
        ),
        "interval_min": 60,
        "enabled": True,
    },
    {
        "id": "gem_weather_vot",
        "name": "🌦️ Clima & Alertas Regionais",
        "topic": "Previsao do Tempo Votuporanga Interior SP Chuva",
        "prompt": (
            "Analise o clima atual de {city} ({temp}°C, sensação {feels}°C, condição {cond}, "
            "chuva {rain}%, vento {wind} km/h, mín {tmin}°C / máx {tmax}°C) e gere um boletim "
            "prático de 3 linhas curtas avisando sobre calor, chuva ou tempestade."
        ),
        "interval_min": 60,
        "enabled": True,
    },
    {
        "id": "gem_market_flash",
        "name": "📈 Flash de Mercado & Cripto",
        "topic": "Bitcoin Dolar Ibovespa Mercado Financeiro",
        "prompt": (
            "Com base nas cotações atuais (Dólar R$ {usd}, Bitcoin US$ {btc}, Ethereum US$ {eth}, "
            "IBOV {ibov} pts) e no cenário econômico do dia, resuma em 3 frases curtas os destaques financeiros."
        ),
        "interval_min": 120,
        "enabled": True,
    },
    {
        "id": "gem_cpp_python",
        "name": "💡 Dica Dev: ESP32 C++ & Python",
        "topic": "Programacao ESP32 C++ FreeRTOS Python Automacao",
        "prompt": (
            "Gere 3 dicas práticas rápidas de arquitetura e performance para projetos com ESP32 "
            "(C++/TFT_eSPI/FreeRTOS) e Python (Flet/Serial) em frases curtas."
        ),
        "interval_min": 180,
        "enabled": True,
    },
]


def load_ui_config():
    defaults = {
        "screen": 1,
        "hex_color": "#00FF00",
        "color": "0x07E0",
        "bg": "none",
        "brt": 200,
        "ticker": True,
        "sleep_enabled": True,
        "sleep_timeout_min": 15,
        "night_mode_enabled": True,
        "night_start_hour": 22,
        "night_end_hour": 6,
        "night_brightness": 40,
        "alert_rules": [dict(r) for r in DEFAULT_ALERT_RULES],
        "portfolio": [dict(p) for p in DEFAULT_PORTFOLIO],
        "portfolio_pnl_mode": "hist",
        "pomo_work_min": 25,
        "pomo_break_min": 5,
        "pomo_long_min": 15,
        "pomo_buzzer": True,
        "media_source_pref": "auto",
        "media_auto_cover": True,
        "weather_city": "Votuporanga",
        "udp_enabled": False,
        "udp_ip": "",
        "udp_port": UDP_DEFAULT_PORT,
        "esp_wifi_ssid": "",
        "esp_wifi_pass": "",
        "scanner_enabled": True,
        "scanner_port": "",
        "scanner_interval_s": 8.0,
        "net_plan_mbps": 700,
        "news_topics": list(DEFAULT_NEWS_TOPICS),
        "news_api_key": os.environ.get("NEWS_API_KEY", ""),
        "news_rotate_sec": 15,
        "ai_provider": "auto",
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "gemini_model": "gemini-2.5-flash",
        "local_ai_url": "http://127.0.0.1:11434",
        "local_ai_model": "",
        "gems": [dict(g) for g in DEFAULT_GEMS],
        "active_gem_id": "gem_embedded",
        "gem_auto_rotate": True,
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
                # Garante que regras novas ou atualizadas permaneçam íntegras
                if "alert_rules" not in saved or not saved["alert_rules"]:
                    defaults["alert_rules"] = [dict(r) for r in DEFAULT_ALERT_RULES]
                if "portfolio" not in saved or not isinstance(saved["portfolio"], list):
                    defaults["portfolio"] = [dict(p) for p in DEFAULT_PORTFOLIO]
                if "gems" not in saved or not isinstance(saved["gems"], list) or not saved["gems"]:
                    defaults["gems"] = [dict(g) for g in DEFAULT_GEMS]
                if "news_topics" not in saved or not isinstance(saved["news_topics"], list) or not saved["news_topics"]:
                    defaults["news_topics"] = list(DEFAULT_NEWS_TOPICS)
                if not defaults.get("gemini_api_key") and os.environ.get("GEMINI_API_KEY"):
                    defaults["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "")
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
      - Indices (IBOVESPA, S&P 500), Câmbio Oficial (USD/BRL, EUR/BRL) e Ações extras do Portfólio
        (ex: PETR4, VALE3, ITUB4, NVDA): atualizados a cada 12.0s.
      - Sparkline de 24h do Bitcoin (48 candles) da Binance.
    """

    BUILTIN_SYMBOLS = {"BTC", "ETH", "SOL", "BNB", "XRP", "USD", "USDT", "USDC", "EUR", "IBOV", "SP500"}

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
        self._custom_tickers: set[str] = set()
        self._custom_quotes: dict[str, dict] = {}
        self._updated_at = 0.0
        self._running = True
        self._trigger_crypto = threading.Event()
        self._trigger_stock = threading.Event()
        threading.Thread(target=self._crypto_worker, daemon=True).start()
        threading.Thread(target=self._stock_worker, daemon=True).start()

    def set_custom_tickers(self, tickers: list[str]):
        cleaned = {t.strip().upper() for t in tickers if t and t.strip()}
        extras = cleaned - self.BUILTIN_SYMBOLS
        trigger = False
        with self._lock:
            if extras - self._custom_tickers:
                trigger = True
            self._custom_tickers = extras
        if trigger:
            self._trigger_stock.set()

    def _http_json(self, url: str, timeout: float = 3.5):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CYDMonitor/4.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def _fetch_yahoo_quote(self, ticker_encoded: str) -> tuple[float, float] | None:
        res = self._fetch_yahoo_quote_full(ticker_encoded)
        if res is None:
            return None
        return res[0], res[1]

    def _fetch_yahoo_quote_full(self, ticker_encoded: str) -> tuple[float, float, str] | None:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_encoded}?interval=1d&range=2d"
            raw = self._http_json(url, timeout=3.5)
            meta = raw["chart"]["result"][0]["meta"]
            price = float(meta["regularMarketPrice"])
            prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
            chg = ((price - prev) / prev * 100.0) if prev > 0 else 0.0
            cur = str(meta.get("currency") or "USD").upper()
            return round(price, 4), round(chg, 2), cur
        except Exception:
            return None

    def _fetch_single_custom_ticker(self, sym: str) -> dict | None:
        s = sym.strip().upper()
        if not s:
            return None
        # Ações / FIIs / ETFs da B3 (ex: PETR4, VALE3, ITUB4, HGLG11, BOVA11)
        if re.match(r"^[A-Z]{4}\d{1,2}F?$", s):
            q = self._fetch_yahoo_quote_full(urllib.parse.quote(f"{s}.SA"))
            if q:
                return {"price": q[0], "chg": q[1], "currency": "BRL"}
        if s.endswith(".SA"):
            q = self._fetch_yahoo_quote_full(urllib.parse.quote(s))
            if q:
                return {"price": q[0], "chg": q[1], "currency": "BRL"}
        # Tenta ticker direto (ações EUA como NVDA, AAPL, MSFT)
        q = self._fetch_yahoo_quote_full(urllib.parse.quote(s))
        if q:
            return {"price": q[0], "chg": q[1], "currency": q[2]}
        # Fallback cripto par USD no Yahoo (ex: ADA-USD, DOGE-USD, AVAX-USD)
        q = self._fetch_yahoo_quote_full(urllib.parse.quote(f"{s}-USD"))
        if q:
            return {"price": q[0], "chg": q[1], "currency": "USD"}
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

        # 4) Cotações extras dos ativos personalizados do Portfólio (ex: PETR4, VALE3, NVDA)
        with self._lock:
            extras = list(self._custom_tickers)
        custom_res = {}
        for sym in extras:
            q_info = self._fetch_single_custom_ticker(sym)
            if q_info:
                custom_res[sym] = q_info
                updated = True

        if updated:
            with self._lock:
                self._data.update(new_d)
                if custom_res:
                    self._custom_quotes.update(custom_res)
                usd_now = self._data.get("usd", 0.0)
                btc_now = self._data.get("btc", 0.0)
                if usd_now > 0 and btc_now > 0:
                    self._data["btc_brl"] = round(btc_now * usd_now, 0)
                self._data["last_str"] = brasilia_now().strftime("%H:%M:%S")
                self._updated_at = time.time()
        return updated

    def resolve_asset_quote(self, ticker: str) -> dict | None:
        """Retorna cotação atual do ativo convertida para BRL e USD + variação 24h."""
        sym = (ticker or "").strip().upper()
        if not sym:
            return None
        with self._lock:
            d = dict(self._data)
            cq = self._custom_quotes.get(sym)

        usd_rate = float(d.get("usd") or 0.0)
        if usd_rate <= 0:
            usd_rate = 5.00

        crypto_map = {
            "BTC": ("btc", "btcc"),
            "ETH": ("eth", "ethc"),
            "SOL": ("sol", "solc"),
            "BNB": ("bnb", "bnbc"),
            "XRP": ("xrp", "xrpc"),
        }
        if sym in crypto_map:
            kp, kc = crypto_map[sym]
            p_usd = float(d.get(kp) or 0.0)
            if p_usd <= 0:
                return None
            return {
                "price_brl": p_usd * usd_rate,
                "price_usd": p_usd,
                "native_price": p_usd,
                "native_currency": "USD",
                "chg_24h": float(d.get(kc) or 0.0),
            }
        if sym in ("USD", "USDT", "USDC"):
            if d.get("usd", 0.0) <= 0:
                return None
            return {
                "price_brl": usd_rate,
                "price_usd": 1.0,
                "native_price": usd_rate,
                "native_currency": "BRL",
                "chg_24h": float(d.get("usdc") or 0.0),
            }
        if sym == "EUR":
            p_eur = float(d.get("eur") or 0.0)
            if p_eur <= 0:
                return None
            return {
                "price_brl": p_eur,
                "price_usd": p_eur / usd_rate,
                "native_price": p_eur,
                "native_currency": "BRL",
                "chg_24h": float(d.get("eurc") or 0.0),
            }
        if cq and cq.get("price", 0.0) > 0:
            p_nat = float(cq["price"])
            cur = cq.get("currency", "BRL").upper()
            p_brl = p_nat if cur == "BRL" else (p_nat * usd_rate)
            p_usd = (p_nat / usd_rate) if cur == "BRL" else p_nat
            return {
                "price_brl": p_brl,
                "price_usd": p_usd,
                "native_price": p_nat,
                "native_currency": cur,
                "chg_24h": float(cq.get("chg") or 0.0),
            }
        return None

    def compute_portfolio(self, items: list[dict], pnl_mode: str = "hist") -> tuple[dict, list[dict]]:
        """
        Calcula o Patrimônio Consolidado (R$), PnL Histórico (vs Preço Médio) e Diário (24h).
        Retorna (portf_json_payload, lista_detalhada_para_ui).
        """
        with self._lock:
            usd_rate = float(self._data.get("usd") or 0.0)
        if usd_rate <= 0:
            usd_rate = 5.00

        enriched = []
        tot_brl = 0.0
        tot_cost_brl = 0.0
        tot_prev_day_brl = 0.0

        for it in items:
            sym = str(it.get("ticker", "")).strip().upper()
            if not sym:
                continue
            try:
                qty = float(it.get("qty", 0.0))
                avg_p = float(it.get("avg_price", 0.0))
            except (ValueError, TypeError):
                continue
            if qty <= 0:
                continue

            cur_pm = str(it.get("currency", "BRL")).upper()
            cost_unit_brl = avg_p * usd_rate if cur_pm == "USD" else avg_p
            pos_cost_brl = qty * cost_unit_brl

            q = self.resolve_asset_quote(sym)
            if q:
                unit_brl = q["price_brl"]
                chg_24h = q["chg_24h"]
                quote_ok = True
            else:
                unit_brl = cost_unit_brl
                chg_24h = 0.0
                quote_ok = False

            pos_val_brl = qty * unit_brl
            pos_pnl_val = pos_val_brl - pos_cost_brl
            pos_pnl_pct = (pos_pnl_val / pos_cost_brl * 100.0) if pos_cost_brl > 0 else 0.0

            denom = 1.0 + (chg_24h / 100.0)
            prev_day_val = (pos_val_brl / denom) if denom > 0.01 else pos_val_brl

            tot_brl += pos_val_brl
            tot_cost_brl += pos_cost_brl
            tot_prev_day_brl += prev_day_val

            enriched.append({
                "ticker": sym,
                "qty": qty,
                "avg_price": avg_p,
                "currency": cur_pm,
                "unit_brl": unit_brl,
                "pos_val_brl": pos_val_brl,
                "pos_cost_brl": pos_cost_brl,
                "pnl_val": pos_pnl_val,
                "pnl_pct": pos_pnl_pct,
                "chg_24h": chg_24h,
                "quote_ok": quote_ok,
                "weight_pct": 0.0,
            })

        for row in enriched:
            row["weight_pct"] = (row["pos_val_brl"] / tot_brl * 100.0) if tot_brl > 0 else 0.0

        hist_pnl_val = tot_brl - tot_cost_brl
        hist_pnl_pct = (hist_pnl_val / tot_cost_brl * 100.0) if tot_cost_brl > 0 else 0.0
        day_pnl_val = tot_brl - tot_prev_day_brl
        day_pnl_pct = (day_pnl_val / tot_prev_day_brl * 100.0) if tot_prev_day_brl > 0 else 0.0

        sorted_top = sorted(enriched, key=lambda x: x["pos_val_brl"], reverse=True)
        top3_syms = [x["ticker"][:8] for x in sorted_top[:3]]
        use_day = (pnl_mode == "day")
        top3_chgs = [round(x["chg_24h"] if use_day else x["pnl_pct"], 2) for x in sorted_top[:3]]
        top3_weights = [round(x["weight_pct"], 1) for x in sorted_top[:3]]

        portf_payload = {
            "tot": round(tot_brl, 2),
            "pnl_pct": round(day_pnl_pct if use_day else hist_pnl_pct, 2),
            "pnl_val": round(day_pnl_val if use_day else hist_pnl_val, 2),
            "day_pct": round(day_pnl_pct, 2),
            "cnt": len(enriched),
            "top3": top3_syms,
            "top3c": top3_chgs,
            "top3w": top3_weights,
        }
        return portf_payload, enriched

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


# ========================================== MODULO 3: POMODORO & MULTIMIDIA ==
class PomodoroEngine:
    """
    Máquina de estados thread-safe para o Hub de Produtividade Pomodoro (Tela 8):
      - WORK:  Foco profundo (padrão 25 min)
      - BREAK: Pausa curta (padrão 5 min)
      - LONG:  Pausa longa a cada 4 ciclos de foco (padrão 15 min)
    Dispara evento de conclusão para acionar o Buzzer e LED RGB da CYD!
    """

    def __init__(self, work_min: int = 25, break_min: int = 5, long_min: int = 15, buzzer_enabled: bool = True):
        self._lock = threading.Lock()
        self.work_min = max(1, min(120, int(work_min)))
        self.break_min = max(1, min(60, int(break_min)))
        self.long_min = max(1, min(90, int(long_min)))
        self.buzzer_enabled = bool(buzzer_enabled)

        self.state = "WORK"  # "WORK" | "BREAK" | "LONG"
        self.running = False
        self.cycles = 0
        self.total_focus_sec_today = 0
        self.tot_sec = self.work_min * 60
        self.rem_sec = float(self.tot_sec)
        self._last_tick_t = time.monotonic()

    def _phase_duration(self, phase: str) -> int:
        if phase == "LONG":
            return self.long_min * 60
        if phase == "BREAK":
            return self.break_min * 60
        return self.work_min * 60

    def set_durations(self, work_min: int, break_min: int, long_min: int):
        with self._lock:
            self.work_min = max(1, min(120, int(work_min)))
            self.break_min = max(1, min(60, int(break_min)))
            self.long_min = max(1, min(90, int(long_min)))
            new_tot = self._phase_duration(self.state)
            if not self.running:
                self.tot_sec = new_tot
                self.rem_sec = float(new_tot)
            else:
                self.tot_sec = new_tot
                self.rem_sec = min(self.rem_sec, float(new_tot))

    def set_phase(self, phase: str):
        p = str(phase or "WORK").upper()
        if p not in ("WORK", "BREAK", "LONG"):
            p = "WORK"
        with self._lock:
            self.state = p
            self.running = False
            self.tot_sec = self._phase_duration(p)
            self.rem_sec = float(self.tot_sec)
            self._last_tick_t = time.monotonic()

    def toggle(self) -> bool:
        with self._lock:
            self.running = not self.running
            self._last_tick_t = time.monotonic()
            return self.running

    def reset(self):
        with self._lock:
            self.running = False
            self.tot_sec = self._phase_duration(self.state)
            self.rem_sec = float(self.tot_sec)
            self._last_tick_t = time.monotonic()

    def skip(self) -> str:
        with self._lock:
            self._advance_phase_unlocked(count_cycle=(self.state == "WORK"))
            return self.state

    def _advance_phase_unlocked(self, count_cycle: bool):
        if self.state == "WORK":
            if count_cycle:
                self.cycles += 1
            self.state = "LONG" if (self.cycles > 0 and self.cycles % 4 == 0) else "BREAK"
        else:
            self.state = "WORK"
        self.tot_sec = self._phase_duration(self.state)
        self.rem_sec = float(self.tot_sec)
        self._last_tick_t = time.monotonic()

    def tick(self) -> dict | None:
        """Avança o relógio. Se um ciclo terminou agora, avança de fase e retorna evento de conclusão."""
        now_m = time.monotonic()
        with self._lock:
            dt = max(0.0, now_m - self._last_tick_t)
            self._last_tick_t = now_m
            if not self.running:
                return None

            self.rem_sec -= dt
            if self.state == "WORK":
                self.total_focus_sec_today += dt

            if self.rem_sec <= 0.0:
                finished_phase = self.state
                self._advance_phase_unlocked(count_cycle=(finished_phase == "WORK"))
                # Mantém rodando na transição automática para fluxo contínuo Pomodoro
                self.running = True
                return {
                    "finished_phase": finished_phase,
                    "next_phase": self.state,
                    "cycles": self.cycles,
                    "buzzer": self.buzzer_enabled,
                }
            return None

    def get_payload(self, done_flag: bool = False) -> dict:
        with self._lock:
            d = {
                "st": self.state,
                "run": self.running,
                "rem": max(0, int(round(self.rem_sec))),
                "tot": int(self.tot_sec),
                "cyc": int(self.cycles),
            }
            if done_flag:
                d["done"] = True
            return d

    def get_ui_snapshot(self) -> dict:
        with self._lock:
            rem_i = max(0, int(round(self.rem_sec)))
            tot_i = max(1, int(self.tot_sec))
            return {
                "state": self.state,
                "running": self.running,
                "rem": rem_i,
                "tot": tot_i,
                "pct": min(1.0, max(0.0, (tot_i - rem_i) / float(tot_i))),
                "cycles": int(self.cycles),
                "focus_min_today": int(self.total_focus_sec_today // 60),
                "work_min": self.work_min,
                "break_min": self.break_min,
                "long_min": self.long_min,
                "buzzer": self.buzzer_enabled,
            }


def _scan_windows_media_titles() -> dict:
    """
    Inspeciona rapidamente (<0.5ms via Win32 EnumWindows) os títulos das janelas abertas
    para distinguir com 100% de precisão YouTube Music (no Chrome/Edge/Brave/Firefox/PWA)
    e Spotify Web de abas comuns do navegador.
    """
    info = {"ytmusic_open": False, "spotify_web_open": False, "ytmusic_titles": []}
    if not IS_WINDOWS:
        return info
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if 0 < length < 512:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    t = buf.value
                    tl = t.lower()
                    if "youtube music" in tl:
                        info["ytmusic_open"] = True
                        info["ytmusic_titles"].append(t)
                    elif "spotify" in tl and (" - " in t or "web player" in tl):
                        info["spotify_web_open"] = True
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    return info


class MediaCollector:
    """
    Coletor Multimídia Assíncrono (Windows GSMTC via winrt / winsdk) com suporte nativo a:
      - Spotify (App Desktop, Microsoft Store e Web Player)
      - YouTube Music (Chrome, Edge, Brave, Firefox, PWA instalado e App Desktop)
      - Qualquer reprodutor compatível com Windows Media Session
    Extrai metadados em tempo real, baixa/lê a capa do álbum (com fallback Deezer HD),
    prepara o arquivo 320x240 JPEG para o Cartão SD e executa comandos Play/Pause/Next/Prev!
    """

    BROWSER_HINTS = ("chrome", "msedge", "edge", "brave", "firefox", "opera", "vivaldi", "arc", "waterfox", "zen")

    def __init__(self, source_pref: str = "auto"):
        self._lock = threading.Lock()
        self._running = True
        self._source_pref = str(source_pref or "auto").lower()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._online_cover_cache: dict[str, bytes] = {}
        self._processed_cover_cache: dict[str, tuple[bytes, str, str]] = {}

        self._state = {
            "source": "NONE",       # "SPOTIFY" | "YT MUSIC" | "MEDIA" | "NONE"
            "app_id": "",
            "playing": False,
            "title": "",
            "artist": "",
            "album": "",
            "pos": 0,
            "dur": 0,
            "track_key": "",
            "cover_id": "",
            "cover_b64": "",        # Preview 160x160 para Flet e Mobile WebApp
            "cover_cyd_bytes": b"", # JPEG 320x240 pronto para envio ao SD da CYD
            "updated_at": 0.0,
        }

        if IS_WINDOWS:
            threading.Thread(target=self._worker_loop, daemon=True).start()
        elif IS_LINUX:
            threading.Thread(target=self._worker_loop_linux, daemon=True).start()

    def set_source_pref(self, pref: str):
        with self._lock:
            self._source_pref = str(pref or "auto").lower()

    def control(self, action: str):
        """Enfileira comando de transporte ('play_pause', 'next', 'prev') para a sessão ativa."""
        if action in ("play_pause", "next", "prev"):
            self._cmd_queue.put(action)

    def get_ui_snapshot(self) -> dict:
        with self._lock:
            return {
                "source": self._state["source"],
                "playing": self._state["playing"],
                "title": self._state["title"],
                "artist": self._state["artist"],
                "album": self._state["album"],
                "pos": self._state["pos"],
                "dur": self._state["dur"],
                "track_key": self._state["track_key"],
                "cover_id": self._state["cover_id"],
                "cover_b64": self._state["cover_b64"],
            }

    def get_cover_for_sd(self) -> tuple[str, str, bytes]:
        """Retorna (track_key, cover_id, cyd_jpeg_bytes) da música atual."""
        with self._lock:
            return (
                self._state["track_key"],
                self._state["cover_id"],
                self._state["cover_cyd_bytes"],
            )

    def get_cyd_payload(self, synced_cover_id: str = "") -> dict:
        with self._lock:
            src = self._state["source"]
            tit = ascii_for_tft(self._state["title"] or "Nenhuma midia ativa", 42)
            art = ascii_for_tft(self._state["artist"] or "Abra Spotify ou YouTube Music", 36)
            alb = ascii_for_tft(self._state["album"] or "", 30)
            return {
                "src": src,
                "play": bool(self._state["playing"]),
                "tit": tit,
                "art": art,
                "alb": alb,
                "pos": int(self._state["pos"]),
                "dur": int(self._state["dur"]),
                "cov": "_media_cov.jpg",
                "cid": synced_cover_id or self._state["cover_id"] or "",
            }

    def _classify_session(self, app_id: str, title: str, artist: str, album: str, win_info: dict) -> str:
        aid = (app_id or "").lower()
        if "spotify" in aid:
            return "SPOTIFY"
        if any(k in aid for k in ("youtubemusic", "youtube-music", "ytmdesktop", "ytmusic", "th-ch", "pear")):
            return "YT MUSIC"

        is_browser = any(b in aid for b in self.BROWSER_HINTS)
        if is_browser:
            # Verifica se o título da faixa bate com uma janela aberta do YouTube Music
            if win_info.get("ytmusic_open"):
                t_low = (title or "").lower()
                for wt in win_info.get("ytmusic_titles", []):
                    if not t_low or t_low[:16] in wt.lower() or "youtube music" in wt.lower():
                        return "YT MUSIC"
            # YouTube Music no navegador preenche album_title via MediaSession API (YouTube comum deixa vazio)
            if album and album.strip():
                if win_info.get("spotify_web_open") and not win_info.get("ytmusic_open"):
                    return "SPOTIFY"
                return "YT MUSIC"
            if win_info.get("spotify_web_open"):
                return "SPOTIFY"
        return "MEDIA"

    def _fetch_online_cover_fallback(self, title: str, artist: str) -> bytes:
        key = f"{artist}|{title}".strip().lower()
        if not title:
            return b""
        if key in self._online_cover_cache:
            return self._online_cover_cache[key]
        try:
            q = urllib.parse.quote(f"{artist} {title}".strip())
            req = urllib.request.Request(
                f"https://api.deezer.com/search?q={q}&limit=1",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=2.8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            items = data.get("data") or []
            if items:
                cov_url = items[0].get("album", {}).get("cover_big") or items[0].get("album", {}).get("cover_medium")
                if cov_url:
                    req_img = urllib.request.Request(cov_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req_img, timeout=3.0) as r_img:
                        raw = r_img.read()
                        if len(raw) > 512:
                            self._online_cover_cache[key] = raw
                            return raw
        except Exception:
            pass
        return b""

    def _worker_loop(self):
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
            from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
        except ImportError:
            try:
                from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
                from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions
            except ImportError:
                return

        async def _poll_once():
            mgr = await SessionManager.request_async()
            if not mgr:
                return

            sessions = list(mgr.get_sessions())
            win_info = _scan_windows_media_titles()
            with self._lock:
                pref = self._source_pref

            candidates = []
            for s in sessions:
                try:
                    app_id = s.source_app_user_model_id or ""
                    pb = s.get_playback_info()
                    pb_status = int(pb.playback_status) if pb and pb.playback_status is not None else 0
                    is_playing = (pb_status == 4)  # 4 = Playing no enum GSMTC

                    props = await s.try_get_media_properties_async()
                    title = (props.title or "").strip() if props else ""
                    artist = (props.artist or "").strip() if props else ""
                    album = (props.album_title or "").strip() if props else ""
                    if not title and not artist:
                        continue

                    # Limpa sufixo " - Topic" comum em artistas do YouTube Music
                    if artist.endswith(" - Topic"):
                        artist = artist[:-8].strip()

                    src_kind = self._classify_session(app_id, title, artist, album, win_info)

                    # Filtra conforme preferência do usuário
                    if pref == "spotify" and src_kind != "SPOTIFY":
                        continue
                    if pref == "ytmusic" and src_kind != "YT MUSIC":
                        continue

                    # Pontuação de prioridade: Tocando agora > Spotify / YT Music > Outras mídias
                    score = 0
                    if is_playing:
                        score += 100
                    if src_kind in ("SPOTIFY", "YT MUSIC"):
                        score += 40
                    if pref == "auto" and src_kind == "YT MUSIC" and win_info.get("ytmusic_open"):
                        score += 10
                    candidates.append((score, s, src_kind, app_id, is_playing, props, title, artist, album))
                except Exception:
                    continue

            if not candidates:
                while not self._cmd_queue.empty():
                    try:
                        self._cmd_queue.get_nowait()
                    except Exception:
                        break
                with self._lock:
                    self._state.update({
                        "source": "NONE",
                        "playing": False,
                        "pos": 0,
                        "dur": 0,
                    })
                return

            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_s, src_kind, app_id, is_playing, props, title, artist, album = candidates[0]

            # Executa eventuais comandos remotos (Play/Pause, Next, Prev) na sessão selecionada
            while not self._cmd_queue.empty():
                cmd = self._cmd_queue.get_nowait()
                try:
                    if cmd == "play_pause":
                        await best_s.try_toggle_play_pause_async()
                    elif cmd == "next":
                        await best_s.try_skip_next_async()
                    elif cmd == "prev":
                        await best_s.try_skip_previous_async()
                except Exception:
                    pass

            # Posição na linha do tempo da música
            pos_sec, dur_sec = 0, 0
            try:
                tl = best_s.get_timeline_properties()
                if tl:
                    if tl.position:
                        pos_sec = max(0, int(tl.position.total_seconds()))
                    if tl.end_time:
                        dur_sec = max(0, int(tl.end_time.total_seconds()))
            except Exception:
                pass

            track_key = f"{src_kind}|{title}|{artist}|{album}"

            # Extrai e processa a capa apenas quando muda a faixa ou se ainda não temos capa para esta faixa
            cyd_bytes, prev_b64, cid = b"", "", ""
            if track_key in self._processed_cover_cache:
                cyd_bytes, prev_b64, cid = self._processed_cover_cache[track_key]
            else:
                raw_thumb = b""
                try:
                    if props and props.thumbnail:
                        stream = await props.thumbnail.open_read_async()
                        if stream:
                            sz = int(stream.size)
                            if 64 < sz < 8_000_000:
                                buf = Buffer(sz)
                                await stream.read_async(buf, sz, InputStreamOptions.NONE)
                                dr = DataReader.from_buffer(buf)
                                arr = bytearray(sz)
                                dr.read_bytes(arr)
                                raw_thumb = bytes(arr)
                                dr.close()
                            stream.close()
                except Exception:
                    raw_thumb = b""

                if not raw_thumb:
                    raw_thumb = self._fetch_online_cover_fallback(title, artist)

                if raw_thumb:
                    try:
                        cyd_bytes, prev_b64, cid = prepare_media_cover_for_cyd(raw_thumb)
                        if len(self._processed_cover_cache) > 24:
                            self._processed_cover_cache.clear()
                        self._processed_cover_cache[track_key] = (cyd_bytes, prev_b64, cid)
                    except Exception:
                        pass

            with self._lock:
                self._state.update({
                    "source": src_kind,
                    "app_id": app_id,
                    "playing": is_playing,
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "pos": pos_sec,
                    "dur": dur_sec,
                    "track_key": track_key,
                    "cover_id": cid,
                    "cover_b64": prev_b64,
                    "cover_cyd_bytes": cyd_bytes,
                    "updated_at": time.time(),
                })

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self._running:
            try:
                loop.run_until_complete(_poll_once())
            except Exception:
                pass
            time.sleep(0.85)

    def _load_linux_art_url(self, art_url: str, title: str, artist: str) -> bytes:
        """Carrega bytes da capa de álbum via file://, http(s):// ou fallback Deezer no Linux."""
        if art_url:
            try:
                if art_url.startswith("file://"):
                    local_path = urllib.parse.unquote(art_url[7:])
                    if os.path.isfile(local_path):
                        with open(local_path, "rb") as f:
                            raw = f.read()
                        if len(raw) > 256:
                            return raw
                elif art_url.startswith(("http://", "https://")):
                    if art_url in self._online_cover_cache:
                        return self._online_cover_cache[art_url]
                    req = urllib.request.Request(art_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=2.8) as resp:
                        raw = resp.read()
                    if len(raw) > 256:
                        if len(self._online_cover_cache) > 32:
                            self._online_cover_cache.clear()
                        self._online_cover_cache[art_url] = raw
                        return raw
            except Exception:
                pass
        return self._fetch_online_cover_fallback(title, artist)

    def _poll_mpris_playerctl(self) -> list[dict]:
        """Coleta sessões MPRIS2 ativas no Linux usando playerctl (se instalado)."""
        if not shutil.which("playerctl"):
            return []
        fmt = "{{playerName}}\t{{status}}\t{{title}}\t{{artist}}\t{{album}}\t{{mpris:artUrl}}\t{{xesam:url}}\t{{position}}\t{{mpris:length}}"
        try:
            res = subprocess.run(
                ["playerctl", "-a", "metadata", "--format", fmt],
                capture_output=True, text=True, timeout=0.9,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return []
            players = []
            for ln in res.stdout.splitlines():
                parts = ln.split("\t")
                if len(parts) < 9:
                    continue
                p_name, status, title, artist, album, art_url, x_url, pos_us, len_us = parts[:9]
                title = title.strip()
                artist = artist.strip()
                album = album.strip()
                if not title and not artist:
                    continue
                try:
                    pos_s = max(0, int(float(pos_us) / 1_000_000)) if pos_us.strip() else 0
                except Exception:
                    pos_s = 0
                try:
                    dur_s = max(0, int(float(len_us) / 1_000_000)) if len_us.strip() else 0
                except Exception:
                    dur_s = 0
                players.append({
                    "backend": "playerctl",
                    "bus_name": p_name.strip(),
                    "app_id": p_name.strip(),
                    "playing": status.strip().lower() == "playing",
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "art_url": art_url.strip(),
                    "url": x_url.strip(),
                    "pos": pos_s,
                    "dur": dur_s,
                })
            return players
        except Exception:
            return []

    def _poll_mpris_gdbus(self) -> list[dict]:
        """Fallback MPRIS2 nativo via gdbus (pré-instalado no Zorin OS / Ubuntu / GNOME sem precisar de pacotes extras)."""
        if not shutil.which("gdbus"):
            return []
        try:
            res = subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.freedesktop.DBus",
                    "--object-path", "/org/freedesktop/DBus",
                    "--method", "org.freedesktop.DBus.ListNames",
                ],
                capture_output=True, text=True, timeout=0.8,
            )
            if res.returncode != 0 or not res.stdout:
                return []
            buses = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", res.stdout)
            players = []
            for bus in buses:
                try:
                    p_res = subprocess.run(
                        [
                            "gdbus", "call", "--session",
                            "--dest", bus,
                            "--object-path", "/org/mpris/MediaPlayer2",
                            "--method", "org.freedesktop.DBus.Properties.GetAll",
                            "org.mpris.MediaPlayer2.Player",
                        ],
                        capture_output=True, text=True, timeout=0.8,
                    )
                    if p_res.returncode != 0 or not p_res.stdout:
                        continue
                    out = p_res.stdout
                    is_playing = "'PlaybackStatus': <'Playing'>" in out

                    def _extract_str(key: str) -> str:
                        m = re.search(rf"'{re.escape(key)}':\s*<(?:\[\s*)?'([^']*)'", out)
                        return m.group(1).strip() if m else ""

                    title = _extract_str("xesam:title")
                    artist = _extract_str("xesam:artist")
                    album = _extract_str("xesam:album")
                    art_url = _extract_str("mpris:artUrl")
                    x_url = _extract_str("xesam:url")
                    if not title and not artist:
                        continue

                    m_pos = re.search(r"'Position':\s*<(?:int64|uint64)\s+(\d+)>", out)
                    pos_s = int(m_pos.group(1)) // 1_000_000 if m_pos else 0
                    m_len = re.search(r"'mpris:length':\s*<(?:int64|uint64)\s+(\d+)>", out)
                    dur_s = int(m_len.group(1)) // 1_000_000 if m_len else 0

                    short_id = bus.replace("org.mpris.MediaPlayer2.", "")
                    players.append({
                        "backend": "gdbus",
                        "bus_name": bus,
                        "app_id": short_id,
                        "playing": is_playing,
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "art_url": art_url,
                        "url": x_url,
                        "pos": max(0, pos_s),
                        "dur": max(0, dur_s),
                    })
                except Exception:
                    continue
            return players
        except Exception:
            return []

    def _worker_loop_linux(self):
        """Worker de mídia MPRIS2 / D-Bus para Linux (Zorin OS / Ubuntu / Debian)."""
        while self._running:
            try:
                raw_players = self._poll_mpris_playerctl()
                if not raw_players:
                    raw_players = self._poll_mpris_gdbus()

                with self._lock:
                    pref = self._source_pref

                candidates = []
                for p in raw_players:
                    app_id = p["app_id"]
                    title = p["title"]
                    artist = p["artist"]
                    album = p["album"]
                    x_url = (p.get("url") or "").lower()
                    if artist.endswith(" - Topic"):
                        artist = artist[:-8].strip()

                    win_info = {
                        "ytmusic_open": ("music.youtube.com" in x_url or "youtube.com" in x_url),
                        "spotify_web_open": ("open.spotify.com" in x_url or "spotify.com" in x_url),
                        "ytmusic_titles": [title] if "music.youtube.com" in x_url else [],
                    }
                    src_kind = self._classify_session(app_id, title, artist, album, win_info)
                    if src_kind == "MEDIA":
                        if "music.youtube.com" in x_url:
                            src_kind = "YT MUSIC"
                        elif "spotify.com" in x_url:
                            src_kind = "SPOTIFY"

                    if pref == "spotify" and src_kind != "SPOTIFY":
                        continue
                    if pref == "ytmusic" and src_kind != "YT MUSIC":
                        continue

                    score = (100 if p["playing"] else 0) + (40 if src_kind in ("SPOTIFY", "YT MUSIC") else 0)
                    candidates.append((score, p, src_kind, title, artist, album))

                if not candidates:
                    while not self._cmd_queue.empty():
                        try:
                            self._cmd_queue.get_nowait()
                        except Exception:
                            break
                    with self._lock:
                        self._state.update({
                            "source": "NONE",
                            "playing": False,
                            "pos": 0,
                            "dur": 0,
                        })
                    time.sleep(0.95)
                    continue

                candidates.sort(key=lambda x: x[0], reverse=True)
                _, best_p, src_kind, title, artist, album = candidates[0]

                # Executa comandos de transporte (Play/Pause, Next, Prev) via MPRIS2
                while not self._cmd_queue.empty():
                    cmd = self._cmd_queue.get_nowait()
                    try:
                        if best_p["backend"] == "playerctl":
                            pctl_cmd = {"play_pause": "play-pause", "next": "next", "prev": "previous"}.get(cmd)
                            if pctl_cmd:
                                subprocess.run(
                                    ["playerctl", "-p", best_p["bus_name"], pctl_cmd],
                                    capture_output=True, timeout=0.8,
                                )
                        else:
                            mpris_m = {"play_pause": "PlayPause", "next": "Next", "prev": "Previous"}.get(cmd)
                            if mpris_m:
                                subprocess.run(
                                    [
                                        "gdbus", "call", "--session",
                                        "--dest", best_p["bus_name"],
                                        "--object-path", "/org/mpris/MediaPlayer2",
                                        "--method", f"org.mpris.MediaPlayer2.Player.{mpris_m}",
                                    ],
                                    capture_output=True, timeout=0.8,
                                )
                    except Exception:
                        pass

                track_key = f"{src_kind}|{title}|{artist}|{album}"
                cyd_bytes, prev_b64, cid = b"", "", ""
                if track_key in self._processed_cover_cache:
                    cyd_bytes, prev_b64, cid = self._processed_cover_cache[track_key]
                else:
                    raw_thumb = self._load_linux_art_url(best_p.get("art_url", ""), title, artist)
                    if raw_thumb:
                        try:
                            cyd_bytes, prev_b64, cid = prepare_media_cover_for_cyd(raw_thumb)
                            if len(self._processed_cover_cache) > 24:
                                self._processed_cover_cache.clear()
                            self._processed_cover_cache[track_key] = (cyd_bytes, prev_b64, cid)
                        except Exception:
                            pass

                with self._lock:
                    self._state.update({
                        "source": src_kind,
                        "app_id": best_p["app_id"],
                        "playing": best_p["playing"],
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "pos": best_p["pos"],
                        "dur": best_p["dur"],
                        "track_key": track_key,
                        "cover_id": cid,
                        "cover_b64": prev_b64,
                        "cover_cyd_bytes": cyd_bytes,
                        "updated_at": time.time(),
                    })
            except Exception:
                pass
            time.sleep(0.95)


# ========================================== CLIMA REGIONAL & TEMPESTADES =====
def to_ascii_safe(text: str) -> str:
    """Converte acentos e emojis do português para ASCII puro compatível com a fonte bitmap TFT_eSPI da CYD."""
    import unicodedata

    if not text:
        return ""
    s = str(text)
    replacements = {
        "🔧": "[EMB] ",
        "🌦️": "[CLIMA] ",
        "⛈️": "[ALERTA] ",
        "📈": "[MKT] ",
        "💻": "[DEV] ",
        "🤖": "[IA] ",
        "☀️": "",
        "🌤️": "",
        "☁️": "",
        "🌧️": "",
        "•": "|",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "’": "'",
        "°": "o",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch) and (ord(ch) < 128 or ch == "\n"))
    return ascii_str.strip()


class WeatherCollector:
    """
    Coletor Meteorológico Regional + Detector de Tempestade/Clima Severo (Open-Meteo API).
    - Configurado por padrão para 'Votuporanga' (SP, Brasil), editável para qualquer cidade.
    - Fornece Data Atual (DD/MM e DD/MM/AAAA), Dia da Semana, Temperatura (°C), Sensação,
      Umidade, Vento, Probabilidade de Chuva e Alerta de Tempestade/Clima Severo para a CYD.
    """

    PRESET_COORDS = {
        "votuporanga": ("Votuporanga", "SP", -20.4228, -49.9728),
        "sao jose do rio preto": ("S. J. Rio Preto", "SP", -20.8197, -49.3794),
        "rio preto": ("S. J. Rio Preto", "SP", -20.8197, -49.3794),
        "fernandopolis": ("Fernandopolis", "SP", -20.2839, -50.2464),
        "jales": ("Jales", "SP", -20.2689, -50.5458),
        "aracatuba": ("Aracatuba", "SP", -21.2089, -50.4328),
        "sao paulo": ("Sao Paulo", "SP", -23.5505, -46.6333),
        "campinas": ("Campinas", "SP", -22.9056, -47.0608),
        "ribeirao preto": ("Ribeirao Preto", "SP", -21.1775, -47.8103),
        "curitiba": ("Curitiba", "PR", -25.4284, -49.2733),
        "rio de janeiro": ("Rio de Janeiro", "RJ", -22.9068, -43.1729),
        "belo horizonte": ("Belo Horizonte", "MG", -19.9167, -43.9345),
        "brasilia": ("Brasilia", "DF", -15.7939, -47.8828),
    }

    DOW_PT = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]

    def __init__(self, initial_city: str = "Votuporanga", poll_interval: float = 240.0, city: str = None, interval: float = None):
        self._lock = threading.Lock()
        self.poll_interval = float(interval if interval is not None else poll_interval)
        self._city_query = (city or initial_city or "Votuporanga").strip()
        self._resolved_city = "Votuporanga"
        self._resolved_state = "SP"
        self._lat = -20.4228
        self._lon = -49.9728
        self._simulated_storm = False
        self._simulated_msg = "TEMPESTADE / RAIOS NA REGIAO!"
        self._data = {
            "valid": False,
            "temp": 28.0,
            "feels": 29.5,
            "tmin": 20.0,
            "tmax": 32.0,
            "hum": 55,
            "wind": 12.0,
            "rain": 10,
            "wmo_code": 0,
            "icon": 0,
            "cond": "Ceu Limpo",
            "emoji": "☀️",
            "real_storm": False,
            "alert_msg": "TEMPESTADE / CHUVA FORTE EM VOTUPORANGA!",
            "last_str": "--:--:--",
        }
        self._trigger = threading.Event()
        self._running = True
        self._resolve_city_coords(self._city_query)
        threading.Thread(target=self._worker, daemon=True).start()

    def _http_json(self, url: str, timeout: float = 4.5):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CYDMonitor/4.1",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def _resolve_city_coords(self, city_name: str) -> bool:
        clean = (city_name or "Votuporanga").strip()
        norm = clean.lower()
        for k, v in [("á", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c")]:
            norm = norm.replace(k, v)

        if norm in self.PRESET_COORDS:
            c_name, st_code, lat, lon = self.PRESET_COORDS[norm]
            with self._lock:
                self._resolved_city = c_name
                self._resolved_state = st_code
                self._lat = lat
                self._lon = lon
            return True

        try:
            q = urllib.parse.quote(clean)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=pt&format=json"
            res = self._http_json(url, timeout=4.0)
            results = res.get("results") or []
            if results:
                r0 = results[0]
                c_name = str(r0.get("name") or clean)[:22]
                admin1 = str(r0.get("admin1") or "")[:16]
                lat = float(r0.get("latitude", -20.4228))
                lon = float(r0.get("longitude", -49.9728))
                with self._lock:
                    self._resolved_city = c_name
                    self._resolved_state = admin1
                    self._lat = lat
                    self._lon = lon
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _decode_wmo(wmo_code: int, wind_kmh: float, precip_mm: float) -> tuple[str, int, str, bool]:
        if wmo_code in (95, 96, 99):
            return "Tempestade Raios", 3, "⛈️", True
        if wmo_code in (65, 67, 82) or precip_mm >= 15.0:
            return "Chuva Severa", 3, "⛈️", True
        if wind_kmh >= 52.0:
            return "Vendaval Forte", 3, "🌬️", True
        if wmo_code in (51, 53, 55, 61, 63, 80, 81):
            return "Chuva", 2, "🌧️", False
        if wmo_code in (71, 73, 75, 77, 85, 86):
            return "Granizo/Frio", 2, "🌨️", (wmo_code == 75)
        if wmo_code in (45, 48):
            return "Neblina", 1, "🌫️", False
        if wmo_code in (2, 3):
            return "Nublado", 1, "☁️", False
        if wmo_code == 1:
            return "Poucas Nuvens", 1, "🌤️", False
        return "Ceu Limpo", 0, "☀️", False

    def set_city(self, new_city: str) -> bool:
        c = (new_city or "Votuporanga").strip()
        if not c:
            c = "Votuporanga"
        with self._lock:
            self._city_query = c
        ok = self._resolve_city_coords(c)
        self.fetch_now()
        return ok

    def set_simulated_storm(self, active: bool, custom_msg: str = ""):
        with self._lock:
            self._simulated_storm = bool(active)
            if custom_msg:
                self._simulated_msg = custom_msg.strip()
            else:
                self._simulated_msg = f"TEMPESTADE / RAIOS EM {self._resolved_city.upper()}!"

    def trigger_storm_simulation(self, active: bool, custom_msg: str = ""):
        self.set_simulated_storm(active, custom_msg)

    def force_refresh(self):
        self._trigger.set()

    def toggle_simulated_storm(self) -> bool:
        with self._lock:
            self._simulated_storm = not self._simulated_storm
            self._simulated_msg = f"TEMPESTADE / RAIOS EM {self._resolved_city.upper()}!"
            return self._simulated_storm

    def fetch_now(self) -> bool:
        with self._lock:
            lat = self._lat
            lon = self._lon
            city_lbl = self._resolved_city

        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation"
                "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                "&timezone=America%2FSao_Paulo"
            )
            raw = self._http_json(url, timeout=4.5)
            cur = raw.get("current") or {}
            daily = raw.get("daily") or {}

            temp = float(cur.get("temperature_2m", 28.0))
            feels = float(cur.get("apparent_temperature", temp))
            hum = int(round(float(cur.get("relative_humidity_2m", 55))))
            wind = float(cur.get("wind_speed_10m", 10.0))
            precip = float(cur.get("precipitation", 0.0))
            wmo = int(cur.get("weather_code", 0))

            tmax_arr = daily.get("temperature_2m_max") or [temp + 3.0]
            tmin_arr = daily.get("temperature_2m_min") or [temp - 4.0]
            rain_arr = daily.get("precipitation_probability_max") or [0]

            tmax = float(tmax_arr[0]) if tmax_arr else temp
            tmin = float(tmin_arr[0]) if tmin_arr else temp
            rain_prob = int(round(float(rain_arr[0] or 0))) if rain_arr else 0

            cond_str, icon_code, emoji, is_storm = self._decode_wmo(wmo, wind, precip)
            alert_txt = f"TEMPESTADE / {cond_str.upper()} EM {city_lbl.upper()}!" if is_storm else f"CLIMA ESTAVEL EM {city_lbl.upper()}"

            with self._lock:
                self._data.update({
                    "valid": True,
                    "temp": round(temp, 1),
                    "feels": round(feels, 1),
                    "tmin": round(tmin, 1),
                    "tmax": round(tmax, 1),
                    "hum": max(0, min(100, hum)),
                    "wind": round(wind, 1),
                    "rain": max(0, min(100, rain_prob)),
                    "wmo_code": wmo,
                    "icon": icon_code,
                    "cond": cond_str,
                    "emoji": emoji,
                    "real_storm": is_storm,
                    "alert_msg": alert_txt,
                    "last_str": brasilia_now().strftime("%H:%M:%S"),
                })
            return True
        except Exception:
            return False

    def _worker(self):
        self.fetch_now()
        while self._running:
            self._trigger.wait(timeout=self.poll_interval)
            self._trigger.clear()
            if not self._running:
                break
            self.fetch_now()

    def get_cyd_payload(self) -> dict:
        now_br = brasilia_now()
        dt_short = now_br.strftime("%d/%m")
        dt_full = now_br.strftime("%d/%m/%Y")
        dow_str = self.DOW_PT[now_br.weekday()]
        with self._lock:
            d = dict(self._data)
            city = self._resolved_city
            sim_storm = self._simulated_storm
            sim_msg = self._simulated_msg

        is_alert = bool(sim_storm or d.get("real_storm", False))
        icon_val = 3 if is_alert else int(d.get("icon", 0))
        cond_val = "Tempestade!" if sim_storm else str(d.get("cond", "Ceu Limpo"))
        rain_val = max(85, int(d.get("rain", 0))) if sim_storm else int(d.get("rain", 0))
        amsg = sim_msg if sim_storm else str(d.get("alert_msg", "TEMPESTADE NA REGIAO!"))

        return {
            "city": to_ascii_safe(city)[:22],
            "dt": dt_short,
            "dtf": dt_full,
            "dow": dow_str,
            "temp": round(float(d.get("temp", 28.0)), 1),
            "feels": round(float(d.get("feels", 29.0)), 1),
            "tmin": round(float(d.get("tmin", 20.0)), 1),
            "tmax": round(float(d.get("tmax", 32.0)), 1),
            "hum": int(d.get("hum", 55)),
            "wind": round(float(d.get("wind", 10.0)), 1),
            "rain": rain_val,
            "icon": icon_val,
            "cond": to_ascii_safe(cond_val)[:20],
            "alert": is_alert,
            "alrt": is_alert,
            "amsg": to_ascii_safe(amsg)[:52],
        }

    def get_ui_snapshot(self) -> dict:
        now_br = brasilia_now()
        with self._lock:
            d = dict(self._data)
            city = self._resolved_city
            state_uf = self._resolved_state
            lat = self._lat
            lon = self._lon
            sim_storm = self._simulated_storm
            sim_msg = self._simulated_msg

        is_alert = bool(sim_storm or d.get("real_storm", False))
        rain_v = max(85, d.get("rain", 0)) if sim_storm else d.get("rain", 0)
        return {
            "valid": d.get("valid", False),
            "city": city,
            "state": state_uf,
            "region": state_uf,
            "lat": lat,
            "lon": lon,
            "date_short": now_br.strftime("%d/%m"),
            "date_full": f"{self.DOW_PT[now_br.weekday()]} {now_br.strftime('%d/%m/%Y')}",
            "dow": self.DOW_PT[now_br.weekday()],
            "temp": d.get("temp", 28.0),
            "feels": d.get("feels", 29.0),
            "tmin": d.get("tmin", 20.0),
            "tmax": d.get("tmax", 32.0),
            "hum": d.get("hum", 55),
            "wind": d.get("wind", 10.0),
            "rain": rain_v,
            "rain_prob": rain_v,
            "cond": "Tempestade Severa (Simulada)" if sim_storm else d.get("cond", "Céu Limpo"),
            "emoji": "⛈️" if is_alert else d.get("emoji", "☀️"),
            "alert": is_alert,
            "simulated_storm": sim_storm,
            "sim_storm": sim_storm,
            "alert_msg": sim_msg if sim_storm else d.get("alert_msg", ""),
            "last_str": d.get("last_str", "--:--:--"),
            "updated": d.get("last_str", "--:--:--"),
        }


# ========================================== MÓDULO 1: FEED DE NOTÍCIAS (NEWS API / RSS) =
class NewsFeedCollector:
    """
    Leitor Passivo de Notícias Customizável (Substitui a antiga lógica de IA Gems):
      - Permite escolher múltiplos tópicos (ex: 'Política', 'Tecnologia', 'Relações Internacionais',
        'Mercado Financeiro', 'Sistemas Embarcados', além de tópicos customizados).
      - Possui função assíncrona (`fetch_topics_async`) que coleta manchetes reais em português
        via fontes gratuitas (Google News RSS PT-BR, Bing/DuckDuckGo News RSS e suporte opcional a NewsAPI.org).
      - Mantém uma fila circular de manchetes e rotaciona automaticamente a cada 15 segundos,
        enviando no JSON via Serial: `"news": {"topic": "Política", "headline": "Título da notícia aqui..."}`.
    """

    TOPIC_QUERIES = {
        "política": "Política Brasil Congresso Governo Brasília STF",
        "tecnologia": "Tecnologia Inteligência Artificial Computação Chips Software",
        "relações internacionais": "Relações Internacionais Geopolítica Diplomacia Mundo",
        "mercado financeiro": "Mercado Financeiro Ibovespa Dólar Economia Juros",
        "sistemas embarcados": "Sistemas Embarcados ESP32 Microcontroladores IoT Arduino",
        "cibersegurança & linux": "Cibersegurança Linux Redes Servidores Open Source",
        "ciência & espaço": "Ciência Espaço NASA Astronomia Descobertas",
    }

    FALLBACK_HEADLINES = {
        "Política": [
            ("Congresso debate agenda econômica e pacote de responsabilidade fiscal em Brasília", "Agência Brasil"),
            ("Comissões analisam marco regulatório de tecnologia e infraestrutura nacional", "Senado Notícias"),
        ],
        "Tecnologia": [
            ("Novas arquiteturas de chips e IA na borda aceleram automação e dispositivos conectados", "Canaltech"),
            ("Comunidade open-source lança ferramentas otimizadas para sistemas Linux e containers", "Tecnoblog"),
        ],
        "Relações Internacionais": [
            ("Cúpula internacional discute acordos comerciais, energia limpa e cadeias de semicondutores", "Reuters"),
            ("Diplomacia global acompanha negociações estratégicas entre blocos econômicos", "DW Brasil"),
        ],
        "Mercado Financeiro": [
            ("Investidores monitoram fluxo cambial, curva de juros e desempenho do Ibovespa e Bitcoin", "InfoMoney"),
            ("Mercados globais operam atentos a indicadores de inflação e liquidez internacional", "Valor"),
        ],
        "Sistemas Embarcados": [
            ("ESP32 e RTOS: Displays SPI TFT com sprites em RAM garantem interfaces fluidas sem flicker", "Embedded Lab"),
            ("Cyber Decks baseados em microcontroladores ganham espaço em monitoramento de redes e DevOps", "Hackaday"),
        ],
    }

    def __init__(
        self,
        topics: list[str] = None,
        news_api_key: str = "",
        rotate_sec: float = 15.0,
        poll_interval: float = 180.0,
        **kwargs,
    ):
        self._lock = threading.Lock()
        self.topics = list(topics or DEFAULT_NEWS_TOPICS)
        if not self.topics:
            self.topics = list(DEFAULT_NEWS_TOPICS)
        self.news_api_key = (news_api_key or os.environ.get("NEWS_API_KEY", "")).strip()
        self.rotate_sec = max(5.0, float(rotate_sec or 15.0))
        self.poll_interval = max(60.0, float(poll_interval or 180.0))
        self._queue: list[dict] = []
        self._active_idx = 0
        self._last_rotate_ts = time.time()
        self._last_fetch_ts = 0.0
        self._busy = False
        self._status_msg = "Inicializando Feed de Notícias..."
        self._running = True
        self._trigger = threading.Event()
        self._seed_initial_queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def _seed_initial_queue(self):
        now_hm = brasilia_now().strftime("%H:%M")
        seeded = []
        for t in self.topics:
            items = self.FALLBACK_HEADLINES.get(t) or [
                (f"Acompanhando últimas atualizações em tempo real sobre {t}", "News Feed")
            ]
            hl, src = items[0]
            seeded.append({
                "topic": t,
                "headline": hl,
                "src": src,
                "tm": now_hm,
            })
        with self._lock:
            if not self._queue:
                self._queue = seeded

    def set_topics(self, topics: list[str], news_api_key: str = None):
        cleaned = []
        for t in (topics or []):
            s = str(t).strip()
            if s and s not in cleaned:
                cleaned.append(s)
        if not cleaned:
            cleaned = list(DEFAULT_NEWS_TOPICS)
        with self._lock:
            self.topics = cleaned
            if news_api_key is not None:
                self.news_api_key = news_api_key.strip()
        self.force_refresh()

    def configure(self, **kwargs):
        if "topics" in kwargs and kwargs["topics"]:
            self.set_topics(kwargs["topics"], kwargs.get("news_api_key"))

    def update_config(self, **kwargs):
        self.configure(**kwargs)

    def force_refresh(self):
        self._trigger.set()

    def next_headline(self) -> dict:
        with self._lock:
            if self._queue:
                self._active_idx = (self._active_idx + 1) % len(self._queue)
                self._last_rotate_ts = time.time()
                return dict(self._queue[self._active_idx])
        return self.get_active_item()

    def select_index(self, idx: int) -> dict:
        with self._lock:
            if self._queue:
                self._active_idx = max(0, min(int(idx), len(self._queue) - 1))
                self._last_rotate_ts = time.time()
                return dict(self._queue[self._active_idx])
        return self.get_active_item()

    def _fetch_single_topic_sync(self, topic: str, max_items: int = 3) -> list[dict]:
        import html
        import xml.etree.ElementTree as ET

        q_raw = self.TOPIC_QUERIES.get(topic.strip().lower(), topic.strip())
        q_enc = urllib.parse.quote(q_raw)
        now_hm = brasilia_now().strftime("%H:%M")
        results = []

        # 1) Se o usuário configurou chave opcional da NewsAPI.org, tenta primeiro
        with self._lock:
            api_key = self.news_api_key
        if api_key:
            try:
                url_napi = (
                    f"https://newsapi.org/v2/everything?q={q_enc}&language=pt&sortBy=publishedAt&pageSize={max_items}"
                )
                req = urllib.request.Request(
                    url_napi,
                    headers={"X-Api-Key": api_key, "User-Agent": "CYDCyberDeck/4.0"},
                )
                with urllib.request.urlopen(req, timeout=4.5) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    for art in (data.get("articles") or [])[:max_items]:
                        tit = str(art.get("title") or "").strip()
                        src = str((art.get("source") or {}).get("name") or "NewsAPI").strip()
                        if tit and tit != "[Removed]":
                            results.append({"topic": topic, "headline": tit, "src": src[:20], "tm": now_hm})
                if results:
                    return results
            except Exception:
                pass

        # 2) Fonte Gratuita Principal: Google News RSS PT-BR (Zero API Key)
        rss_urls = [
            f"https://news.google.com/rss/search?q={q_enc}&hl=pt-BR&gl=BR&ceid=BR:pt-419",
            f"https://www.bing.com/news/search?q={q_enc}&format=rss&setlang=pt-br",
        ]
        for rss_url in rss_urls:
            try:
                req = urllib.request.Request(
                    rss_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CYDCyberDeck/4.0"},
                )
                with urllib.request.urlopen(req, timeout=4.5) as resp:
                    xml_bytes = resp.read()
                root = ET.fromstring(xml_bytes)
                for item in root.findall(".//item"):
                    title_el = item.find("title")
                    source_el = item.find("source")
                    if title_el is not None and title_el.text:
                        raw_t = html.unescape(title_el.text).strip()
                        src_name = (
                            html.unescape(source_el.text).strip()
                            if (source_el is not None and source_el.text)
                            else "News RSS"
                        )
                        if " - " in raw_t:
                            parts = raw_t.rsplit(" - ", 1)
                            raw_t = parts[0].strip()
                            if src_name == "News RSS" and parts[1].strip():
                                src_name = parts[1].strip()
                        if raw_t and len(raw_t) > 12:
                            results.append({
                                "topic": topic,
                                "headline": raw_t[:190],
                                "src": src_name[:20],
                                "tm": now_hm,
                            })
                            if len(results) >= max_items:
                                break
                if results:
                    return results
            except Exception:
                continue

        # 3) Fallback local resiliente se estiver sem internet
        fb_list = self.FALLBACK_HEADLINES.get(topic) or [
            (f"{topic}: Monitoramento de manchetes ativo no Cyber Deck", "Local RSS")
        ]
        for hl, src in fb_list[:max_items]:
            results.append({"topic": topic, "headline": hl, "src": src, "tm": now_hm})
        return results

    async def fetch_topics_async(self, topics_list: list[str]) -> list[dict]:
        """Função assíncrona que busca em paralelo as últimas manchetes de todos os tópicos ativos."""
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, self._fetch_single_topic_sync, topic_name, 3)
            for topic_name in topics_list
        ]
        per_topic_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Intercala as manchetes por tópico (Política -> Tecnologia -> Rel. Internacionais...)
        interleaved: list[dict] = []
        valid_lists = [r for r in per_topic_results if isinstance(r, list) and r]
        max_len = max((len(lst) for lst in valid_lists), default=0)
        for i in range(max_len):
            for lst in valid_lists:
                if i < len(lst):
                    interleaved.append(lst[i])
        return interleaved

    def fetch_now(self) -> bool:
        with self._lock:
            topics_copy = list(self.topics)
            self._busy = True
            self._status_msg = f"Buscando manchetes ({', '.join(topics_copy[:3])}...)"

        try:
            new_queue = asyncio.run(self.fetch_topics_async(topics_copy))
            if new_queue:
                now_str = brasilia_now().strftime("%H:%M:%S")
                with self._lock:
                    self._queue = new_queue[:16]
                    if self._active_idx >= len(self._queue):
                        self._active_idx = 0
                    self._last_fetch_ts = time.time()
                    self._busy = False
                    self._status_msg = f"{len(self._queue)} manchetes sincronizadas às {now_str} (RSS/API)"
                return True
        except Exception as ex:
            with self._lock:
                self._busy = False
                self._status_msg = f"Usando fila em cache ({ex})"
        with self._lock:
            self._busy = False
        return False

    def _worker(self):
        self.fetch_now()
        while self._running:
            self._trigger.wait(timeout=self.poll_interval)
            self._trigger.clear()
            if not self._running:
                break
            self.fetch_now()

    def tick_scheduler(self, **kwargs) -> dict | None:
        """Avança a fila de manchetes a cada 15 segundos e retorna a nova manchete quando rotacionar."""
        now = time.time()
        with self._lock:
            if not self._queue:
                return None
            if now - self._last_rotate_ts >= self.rotate_sec:
                self._active_idx = (self._active_idx + 1) % len(self._queue)
                self._last_rotate_ts = now
                return dict(self._queue[self._active_idx])
        return None

    def get_active_item(self) -> dict:
        with self._lock:
            if self._queue:
                idx = self._active_idx % len(self._queue)
                return dict(self._queue[idx])
        return {
            "topic": "Tecnologia",
            "headline": "Sincronizando manchetes do Cyber Deck News Feed...",
            "src": "RSS Live",
            "tm": brasilia_now().strftime("%H:%M"),
        }

    def get_cyd_news_payload(self, include_queue: bool = False, force: bool = True) -> dict:
        """Retorna o nó `"news": {"topic": "...", "headline": "..."}` otimizado para Serial 115200 bps."""
        item = self.get_active_item()
        pkt = {
            "topic": to_ascii_safe(item.get("topic", "Noticias"))[:24],
            "headline": to_ascii_safe(item.get("headline", ""))[:190],
            "src": to_ascii_safe(item.get("src", "RSS"))[:18],
            "tm": str(item.get("tm", "--:--"))[:8],
            "force": bool(force),
        }
        if include_queue:
            with self._lock:
                q_slice = list(self._queue[:6])
            pkt["queue"] = [
                {
                    "topic": to_ascii_safe(x.get("topic", "Noticias"))[:22],
                    "headline": to_ascii_safe(x.get("headline", ""))[:160],
                    "src": to_ascii_safe(x.get("src", "RSS"))[:16],
                    "tm": str(x.get("tm", "--:--"))[:8],
                }
                for x in q_slice
            ]
        return pkt

    def get_cyd_payload(self) -> dict:
        """Mantém compatibilidade com o campo legado `gem` caso necessário."""
        item = self.get_active_item()
        return {
            "tit": to_ascii_safe(f"[{item.get('topic', 'NEWS')}] {item.get('src', '')}")[:32],
            "txt": to_ascii_safe(item.get("headline", ""))[:220],
            "tm": str(item.get("tm", "--:--"))[:8],
            "mdl": "NEWS-RSS",
        }

    def get_ui_snapshot(self) -> dict:
        with self._lock:
            q_copy = [dict(x) for x in self._queue]
            act_idx = self._active_idx % len(q_copy) if q_copy else 0
            act = q_copy[act_idx] if q_copy else {
                "topic": "Tecnologia",
                "headline": "Carregando manchetes...",
                "src": "RSS",
                "tm": "--:--",
            }
            rem_s = max(0, int(round(self.rotate_sec - (time.time() - self._last_rotate_ts))))
            return {
                "topics": list(self.topics),
                "queue": q_copy,
                "active_index": act_idx,
                "total": len(q_copy),
                "active_topic": act.get("topic", "Notícias"),
                "active_headline": act.get("headline", ""),
                "active_source": act.get("src", "RSS"),
                "active_time": act.get("tm", "--:--"),
                "remain_sec": rem_s,
                "status_msg": self._status_msg,
                "busy": self._busy,
                "news_api_key": self.news_api_key,
                # Chaves de retrocompatibilidade UI
                "last_title": f"[{act.get('topic', 'News')}] {act.get('src', 'RSS')}",
                "last_text": act.get("headline", ""),
                "last_time": act.get("tm", "--:--"),
                "last_model": "News Feed RSS/API",
            }


# Alias de retrocompatibilidade
GeminiGemsEngine = NewsFeedCollector


# ========================================== MÓDULO 2: O TERMINAL CYD (CYBER DECK) =
class CyberDeckTerminalEngine:
    """
    Motor do Terminal Administrativo Cyber Deck v4.6 (`SCR_TERMINAL` - Tela 11):
      - Display da CYD: 14 linhas x 48 colunas monospace ASCII (`TERM_COLS = 48`).
      - 100% defensivo/passivo: telemetria RF passiva da ESP32-WROOM-32U, espectro 2.4 GHz,
        auditoria passiva, OUI offline e diagnosticos de rede/gateway/DNS/TLS/MTU/jitter.
    """

    TERM_COLS = 48
    TERM_ROWS = 14

    def __init__(self, max_history: int = 150, collector=None, wifi_scan_col=None, net_col=None, ai_eng=None):
        self._lock = threading.Lock()
        self.max_history = max_history
        self.collector = collector
        self.wifi_scan_col = wifi_scan_col
        self.net_col = net_col
        self.ai_eng = ai_eng
        self._lines: list[str] = [
            "================================================",
            " CYD CYBER DECK TERMINAL v4.7 [RF + IA HIBRIDA]",
            " Digite 'help' (rf | net | ai | sys | esp)",
            "================================================",
        ]
        self._cmd_history: list[str] = []
        self._busy = False
        self._last_cmd = "ready"
        self._total_seq = len(self._lines)

    @staticmethod
    def _rssi_ascii_bar(rssi: int) -> str:
        if rssi >= -55:
            return "####"
        if rssi >= -67:
            return "###."
        if rssi >= -78:
            return "##.."
        if rssi >= -88:
            return "#..."
        return "...."

    def append_line(self, text: str):
        if not text:
            return
        with self._lock:
            for raw_ln in str(text).splitlines():
                ln = to_ascii_safe(raw_ln.rstrip())[: self.TERM_COLS]
                if ln:
                    self._lines.append(ln)
                    self._total_seq += 1
            if len(self._lines) > self.max_history:
                self._lines = self._lines[-self.max_history :]

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "lines": list(self._lines),
                "text": "\n".join(self._lines),
                "busy": self._busy,
                "last_cmd": self._last_cmd,
                "history": list(self._cmd_history),
                "seq": self._total_seq,
            }

    def clear(self, dispatch_fn=None):
        with self._lock:
            self._lines = [
                "CYD CYBER DECK OS v4.7 - Terminal limpo.",
                "Digite 'help' (rf | net | ai | sys | esp).",
            ]
            self._last_cmd = "clear"
            self._total_seq += 2
        if dispatch_fn:
            dispatch_fn({"cmd": "term_clear"})

    def execute_command(
        self,
        raw_cmd: str,
        dispatch_fn,
        log_fn=None,
        auto_switch_screen: bool = True,
        wait: bool = False,
        timeout_s: float = 10.0,
    ) -> list[str]:
        """Interpreta e executa um comando em background (ou aguarda ate timeout_s se wait=True)."""
        cmd_str = (raw_cmd or "").strip()
        if not cmd_str:
            return []

        with self._lock:
            if not self._cmd_history or self._cmd_history[-1] != cmd_str:
                self._cmd_history.append(cmd_str)
                if len(self._cmd_history) > 60:
                    self._cmd_history = self._cmd_history[-60:]
            self._last_cmd = cmd_str

        captured_lines: list[str] = []
        done_ev = threading.Event()

        def _record_and_append(line_s: str) -> str:
            c_ln = to_ascii_safe(line_s)[: self.TERM_COLS]
            if c_ln:
                captured_lines.append(c_ln)
                self.append_line(c_ln)
            return c_ln

        def _send_cyd_lines(lines_list: list[str], switch_scr: bool = False):
            clean_batch = []
            for x in lines_list:
                if x is not None and str(x).strip():
                    c_ln = _record_and_append(str(x))
                    if c_ln:
                        clean_batch.append(c_ln)
            if not clean_batch:
                return
            # Divide em pacotes enxutos de ate 4 linhas para nao saturar a Serial a 115200 bps
            for i in range(0, len(clean_batch), 4):
                chunk = clean_batch[i : i + 4]
                pkt = {
                    "term": {
                        "lines": chunk,
                        "cmd": to_ascii_safe(cmd_str)[:30],
                        "auto_scr": bool(switch_scr and i == 0),
                    }
                }
                if dispatch_fn:
                    dispatch_fn(pkt)
                if i + 4 < len(clean_batch):
                    time.sleep(0.04)

        parts = cmd_str.split()
        verb = parts[0].lower()
        arg_rest = cmd_str[len(parts[0]) :].strip()
        low_full = cmd_str.lower().strip()

        # 1) Comando Limpar Terminal
        if verb in ("clear", "cls", "reset"):
            self.clear(dispatch_fn)
            return list(self._lines)

        # 2) Comandos Nativos Delegados ao ESP32 (placa CYD)
        # a) Wi-Fi Scan local na CYD
        if verb == "wifi" or low_full.startswith("wifi scan") or low_full == "wifiscan":
            _record_and_append(f"$ {cmd_str}")
            _record_and_append("[WIFI] Scan 2.4GHz delegado ao radio da CYD...")
            if dispatch_fn:
                dispatch_fn({"cmd": "wifi_scan"})
            if log_fn:
                log_fn("💻 Terminal CYD: Trigger {'cmd': 'wifi_scan'} enviado ao ESP32!")
            return captured_lines

        # b) Easter egg: Matrix Rain (cmatrix)
        if verb in ("cmatrix", "matrix"):
            _record_and_append(f"$ {cmd_str}")
            _record_and_append("[OK] Ativando Matrix Rain na SCR_TERMINAL...")
            if dispatch_fn:
                dispatch_fn({"cmd": "cmatrix"})
            if log_fn:
                log_fn("🟢 Terminal CYD: Easter egg Matrix Rain iniciado no ESP32!")
            return captured_lines

        # c) ESP32 Memoria Heap (esp mem)
        if low_full in ("esp mem", "espmem"):
            _record_and_append(f"$ {cmd_str}")
            _record_and_append("[OK] Requisitando Heap RAM da placa CYD...")
            if dispatch_fn:
                dispatch_fn({"cmd": "esp_mem"})
            return captured_lines

        # d) ESP32 Reboot (esp reboot)
        if low_full in ("esp reboot", "espreboot") or (verb == "reboot" and ("esp" in low_full or len(parts) == 1)):
            _record_and_append(f"$ {cmd_str}")
            _record_and_append("[WARN] Enviando REBOOT remoto para a CYD...")
            if dispatch_fn:
                dispatch_fn({"cmd": "esp_reboot"})
            if log_fn:
                log_fn("⚠️ Terminal CYD: Reboot remoto enviado a placa CYD!")
            return captured_lines

        # e) ESP32 Info (esp info / esp_info)
        if low_full in ("esp info", "esp_info", "espinfo", "esp"):
            _record_and_append(f"$ {cmd_str}")
            _record_and_append("[OK] Consultando telemetria interna da CYD...")
            if dispatch_fn:
                dispatch_fn({"cmd": "esp_info"})
            return captured_lines

        # 3) Comandos Processados no Agente Python em Thread Assincrona
        def _runner():
            with self._lock:
                self._busy = True
            try:
                _send_cyd_lines([f"$ {cmd_str}"], switch_scr=auto_switch_screen)

                # ================================== HELP (CATEGORIZADO <= 14x48) ==========
                if verb in ("help", "?", "man"):
                    cat = (parts[1].lower() if len(parts) > 1 else "").strip()
                    if cat in ("rf", "wifi", "radar", "32u"):
                        _send_cyd_lines([
                            "=== [HELP RF] ESP32-WROOM-32U & ESPECTRO ===",
                            "rf status       : Status 32U, IP, APs e canais",
                            "rf scan         : Varredura 2.4GHz + OUI vendor",
                            "rf spectrum     : Ocupacao CH 1..13 + melhor CH",
                            "rf track <alvo> : Sinal min/med/max, dB e dist",
                            "rf audit        : Auditoria passiva (OPEN/Mesh)",
                            "rf diff         : Redes novas (+), ausentes (-)",
                            "rf export [fmt] : Salva JSON/CSV em reports/",
                            "oui <mac>       : Fabricante OUI do MAC/BSSID",
                            "wifi scan       : Scan local no radio da CYD",
                        ])
                    elif cat in ("net", "rede", "router", "wan"):
                        _send_cyd_lines([
                            "=== [HELP NET] DIAGNOSTICO DE REDE & FIBRA ===",
                            "netcheck / diag : Bateria GW+WAN+DNS+LAN+32U",
                            "router / gw     : Gateway, ping, HTTP e MAC",
                            "jitter [alvo]   : Estabilidade ICMP (10 pkts)",
                            "mtu [alvo]      : Descoberta Path MTU (DF)",
                            "tls <dominio>   : Inspecao cert TLS/SSL :443",
                            "route           : Tabela de rotas IPv4 kernel",
                            "lan / arp       : Vizinhos ativos na rede local",
                            "dns <dom>       : Tempo de resolucao DNS",
                            "ping / trace    : Latencia ICMP e rota (8 hops)",
                            "fetch / speed   : HTTP GET e Speedtest Fibra",
                        ])
                    elif cat in ("sys", "pc", "system", "docker"):
                        _send_cyd_lines([
                            "=== [HELP SYS] SISTEMA PC, HOMELAB & DOCKER ===",
                            "whoami          : Usuario, host, OS e IP LAN",
                            "neofetch        : Resumo ASCII CPU/RAM/GPU/OS",
                            "df -h           : Uso de particoes de disco",
                            "free -m         : Memoria RAM e Swap (MB)",
                            "uptime          : Tempo ligado e carga atual",
                            "top             : Top 5 processos por uso RAM",
                            "ip addr         : Interfaces de rede e IPv4",
                            "netstat -tuln   : Portas locais em LISTEN",
                            "docker ps|stats : Containers ativos e recursos",
                            "ssh u@host <c>  : Executa comando SSH remoto",
                            "history         : Ultimos 10 comandos rodados",
                        ])
                    elif cat in ("esp", "cyd", "hw"):
                        _send_cyd_lines([
                            "=== [HELP ESP] HARDWARE NATIVO PLACA CYD ===",
                            "esp info        : IP, RSSI, MAC e clock da CYD",
                            "esp mem         : Heap livre, min e PSRAM",
                            "esp reboot      : Reinicia a placa CYD",
                            "wifi scan       : Scan 2.4GHz no radio da CYD",
                            "cmatrix         : Chuva Matrix Rain na Tela 11",
                            "clear           : Limpa buffer do terminal",
                        ])
                    elif cat in ("ai", "ia", "gemini", "ollama"):
                        _send_cyd_lines([
                            "=== [HELP AI] AGENTE IA (GEMINI + LOCAL) ===",
                            "ai status       : Status Gemini + IA Local",
                            "ai models       : Lista modelos Ollama/Local",
                            "ai provider <p> : Alterna auto | gemini | local",
                            "ai report [p]   : Relatorio completo rede + RF",
                            "ai rf [p]       : Analise espectro 2.4GHz 32U",
                            "ai ask <perg.>  : Pergunta sobre a rede atual",
                            "Obs: Relatorios .md salvos em reports/",
                        ])
                    else:
                        _send_cyd_lines([
                            "=== CYD TERMINAL v4.7 (RF + REDE + IA) ===",
                            "Categorias (digite para detalhar):",
                            "  help rf  : Radar 2.4GHz, Espectro, OUI, Audit",
                            "  help net : Diag, Jitter, MTU, TLS, Rota, LAN",
                            "  help ai  : Agente Gemini + IA Local (Ollama)",
                            "  help sys : Hardware PC, Disco, RAM, Docker",
                            "  help esp : Comandos nativos da placa CYD",
                            "Atalhos rapidos:",
                            "  ai report | ai rf    | ai status  | ai models",
                            "  rf scan   | rf audit | netcheck   | jitter",
                            "  mtu       | tls <d>  | router     | clear",
                        ])

                # ================================== HISTORY ===============================
                elif verb in ("history", "hist"):
                    with self._lock:
                        h_slice = list(self._cmd_history[-10:])
                    lines_hist = [f"[OK] Historico ({len(h_slice)} ultimos comandos):"]
                    for idx_h, c_item in enumerate(h_slice, 1):
                        lines_hist.append(f" {idx_h:02d}) {c_item[:42]}")
                    _send_cyd_lines(lines_hist)

                # ================================== OUI / VENDOR ==========================
                elif verb in ("oui", "vendor"):
                    mac_q = arg_rest.strip()
                    if not mac_q:
                        _send_cyd_lines([
                            "[WARN] Uso: oui <mac_ou_bssid>",
                            "Ex: oui 30:DE:4B:11:22:33 ou oui 20:50:0D",
                        ])
                    else:
                        vend = wifi_scanner.lookup_oui(mac_q)
                        hex_c = re.sub(r"[^0-9A-Fa-f]", "", mac_q).upper()
                        pref = f"{hex_c[0:2]}:{hex_c[2:4]}:{hex_c[4:6]}" if len(hex_c) >= 6 else mac_q[:8].upper()
                        tag = "[OK]" if vend != "Desconhecido" else "[WARN]"
                        out_o = [
                            f"[WIFI] Consulta OUI: {mac_q[:24]}",
                            f"{tag} Prefixo {pref} -> {vend}",
                        ]
                        if self.wifi_scan_col is not None:
                            matches = self.wifi_scan_col.track_ap(pref)
                            if matches:
                                m0 = matches[0]
                                out_o.append(
                                    f"AP ativo: {m0['ssid'][:14]} C{m0['ch']:02d} {m0['cur']}dBm"
                                )
                        _send_cyd_lines(out_o)

                # ================================== RF / SPECTRUM / AUDIT / TRACK =========
                elif verb in ("rf", "spectrum", "channels", "track", "audit"):
                    if verb in ("spectrum", "channels"):
                        rf_sub = "spectrum"
                        rf_arg = arg_rest
                    elif verb == "track":
                        rf_sub = "track"
                        rf_arg = arg_rest
                    elif verb == "audit":
                        rf_sub = "audit"
                        rf_arg = arg_rest
                    else:
                        rf_sub = parts[1].lower() if len(parts) > 1 else "status"
                        rf_arg = " ".join(parts[2:]).strip() if len(parts) > 2 else ""

                    wcol = self.wifi_scan_col
                    if wcol is None:
                        _send_cyd_lines(["[ERR] Coletor WiFiScanner nao inicializado."])
                    elif rf_sub in ("status", "info", "st"):
                        ws = wcol.get_ui_snapshot()
                        spec = wcol.get_spectrum_analysis()
                        st_tag = "[OK] ONLINE" if ws["online"] else "[WARN] OFFLINE"
                        src_s = ws["scanner_ip"] or ws["port"] or "UDP:8889"
                        best_s = f"{ws['best_rssi']}dBm" if ws["total"] > 0 else "--"
                        avg_s = f"{ws['avg_rssi']}dBm" if ws["total"] > 0 else "--"
                        bch_s = f"CH{spec['busiest_channel']:02d}" if spec["busiest_channel"] > 0 else "--"
                        _send_cyd_lines([
                            "[WIFI] ESP32-WROOM-32U RADAR RF (2.4 GHz)",
                            f"Estado : {st_tag} ({src_s[:18]})",
                            f"Scans  : #{ws['scan_count']} ({ws['last_scan_str']}) | APs: {ws['total']}",
                            f"Segur. : Open: {ws['open_count']} | Novas: {ws['new_count']}",
                            f"Sinal  : Melhor {best_s} | Media {avg_s}",
                            f"Canais : Livre CH{spec['best_channel']:02d} | Cheio {bch_s}",
                            f"Recom. : {spec['recommendation'][:38]}",
                        ])

                    elif rf_sub == "scan":
                        _send_cyd_lines(["[WIFI] Solicitando scan a ESP32-WROOM-32U..."])
                        ws = wcol.wait_for_fresh_scan(timeout_s=6.0)
                        nets = ws.get("networks", [])
                        if not nets:
                            _send_cyd_lines([
                                "[WARN] 0 APs no buffer da ESP32-WROOM-32U.",
                                "Verifique energia/UDP :8889 da antena 32U.",
                            ])
                        else:
                            out_s = [
                                f"[WIFI] {len(nets)} APs (Livre:CH{ws['free_ch']:02d} Cheio:CH{ws['busiest_ch']:02d})",
                                "SSID          CH  dBm BAR  ENC  VENDOR",
                            ]
                            for n in nets[:10]:
                                ssid_s = str(n.get("ssid_ascii") or n.get("ssid") or "<OCULTA>")[:13]
                                ch_i = int(n.get("ch", 0))
                                rssi_i = int(n.get("rssi", -100))
                                bar_s = self._rssi_ascii_bar(rssi_i)
                                enc_s = str(n.get("enc", "WPA"))[:4]
                                vend_s = str(n.get("vendor") or wifi_scanner.lookup_oui(n.get("bssid", "")))[:8]
                                out_s.append(
                                    f"{ssid_s:<13} C{ch_i:02d} {rssi_i:>4d} {bar_s} {enc_s:<4} {vend_s}"
                                )
                            _send_cyd_lines(out_s)

                    elif rf_sub in ("spectrum", "channels", "spec", "ch"):
                        spec = wcol.get_spectrum_analysis()
                        chs = spec["channels"]
                        max_c = max(max((chs[c]["count"] for c in range(1, 14)), default=1), 1)

                        def _fmt_ch_cell(c_num: int) -> str:
                            ci = chs[c_num]
                            cnt = ci["count"]
                            filled = min(5, int(round((cnt / float(max_c)) * 5.0))) if cnt > 0 else 0
                            if cnt > 0 and filled == 0:
                                filled = 1
                            bar = "#" * filled + "." * (5 - filled)
                            return f"C{c_num:02d}[{bar}]{cnt:>2d} I:{ci['score']:>3.1f}"

                        out_sp = ["[WIFI] ESPECTRO 2.4GHz (APs & INTERFERENCIA)"]
                        for row_i in range(1, 8):
                            left_s = _fmt_ch_cell(row_i)
                            right_ch = row_i + 7
                            if right_ch <= 13:
                                right_s = _fmt_ch_cell(right_ch)
                                out_sp.append(f"{left_s} | {right_s}")
                            else:
                                out_sp.append(left_s)

                        rk = spec["ranking"]
                        rk_str = " ".join(f"{i+1}o:CH{r['ch']:02d}({r['score']:.1f})" for i, r in enumerate(rk))
                        out_sp.append(f"Rank 1/6/11: {rk_str}")
                        out_sp.append(f"[OK] {spec['recommendation'][:42]}")
                        _send_cyd_lines(out_sp)

                    elif rf_sub == "track":
                        matches = wcol.track_ap(rf_arg)
                        if not matches:
                            _send_cyd_lines([
                                f"[WARN] Nenhum AP encontrado p/ '{rf_arg or '*'}'",
                                "Rode 'rf scan' primeiro ou tente outro termo.",
                            ])
                        else:
                            m0 = matches[0]
                            st_lbl = "Estavel" if m0["spread"] <= 6 else ("Moderado" if m0["spread"] <= 12 else "Oscilante")
                            st_tag = "[OK]" if m0["spread"] <= 8 else "[WARN]"
                            out_tr = [
                                f"[WIFI] TRACK: {m0['ssid'][:18]} ({m0['vendor'][:10]})",
                                f"BSSID: {m0['bssid'] or '--'} | CH{m0['ch']:02d} | {m0['enc'][:4]}",
                                f"RSSI : Cur {m0['cur']} | Min {m0['min']} | Med {m0['avg']} | Max {m0['max']}",
                                f"Estab: Spread {m0['spread']}dB (Jit {m0['jitter_db']}dB) {st_tag} {st_lbl}",
                                f"Dist : ~{m0['est_dist_m']}m indoor | Visto {m0['seen_count']}x",
                            ]
                            for extra in matches[1:4]:
                                out_tr.append(
                                    f"+ {extra['ssid'][:14]:<14} C{extra['ch']:02d} {extra['cur']:>4d}dBm ~{extra['est_dist_m']}m {extra['vendor'][:7]}"
                                )
                            _send_cyd_lines(out_tr)

                    elif rf_sub == "audit":
                        aud = wcol.get_rf_audit()
                        open_n = aud["open_networks"]
                        hid_n = aud["hidden_networks"]
                        wep_n = aud["wep_networks"]
                        multi_n = aud["multi_bssid_ssids"]
                        cong_c = aud["congested_channels"]

                        out_au = [
                            f"[WIFI] AUDITORIA RF PASSIVA ({aud['total_aps']} APs):",
                        ]
                        if open_n:
                            names = ", ".join(x["ssid"][:12] for x in open_n[:2])
                            out_au.append(f"[WARN] OPEN ({len(open_n)}): {names}")
                        else:
                            out_au.append("[OK] Redes Abertas (OPEN): 0")

                        if wep_n:
                            out_au.append(f"[WARN] Criptografia WEP fraca: {len(wep_n)} AP(s)")
                        else:
                            out_au.append("[OK] Redes WEP legadas: 0")

                        if hid_n:
                            chs_h = ",".join(f"C{x['ch']}" for x in hid_n[:4])
                            out_au.append(f"[WARN] SSIDs Ocultos (<OCULTA>): {len(hid_n)} ({chs_h})")
                        else:
                            out_au.append("[OK] SSIDs Ocultos (<OCULTA>): 0")

                        if multi_n:
                            m_desc = ", ".join(f"{m['ssid'][:11]}({m['count']}x)" for m in multi_n[:2])
                            out_au.append(f"[WIFI] Multi-BSSID/Mesh: {m_desc}")
                        else:
                            out_au.append("[OK] Multi-BSSID / Mesh: 0 duplicados")

                        if cong_c:
                            c_desc = ", ".join(f"CH{c['ch']:02d}({c['count']}APs)" for c in cong_c[:3])
                            out_au.append(f"[WARN] Canais cheios: {c_desc}")
                        else:
                            out_au.append("[OK] Canais congestionados (>=3 APs): 0")

                        _send_cyd_lines(out_au)

                    elif rf_sub == "diff":
                        df = wcol.get_diff_report()
                        added = df["added"]
                        removed = df["removed"]
                        changes = df["rssi_changes"]
                        out_df = [
                            f"[WIFI] RF DIFF (Base:{df['baseline_count']} -> Atual:{df['current_count']})",
                        ]
                        if not added and not removed and not changes:
                            out_df.append("[OK] Sem alteracoes de APs no espectro.")
                        for a in added[:3]:
                            out_df.append(f"+ {a.get('ssid','<OCULTA>')[:16]:<16} C{int(a.get('ch',0)):02d} {int(a.get('rssi',-100))}dBm")
                        for r in removed[:3]:
                            out_df.append(f"- {r.get('ssid','<OCULTA>')[:16]:<16} C{int(r.get('ch',0)):02d} (saiu)")
                        for chg in changes[:4]:
                            sign = "+" if chg["delta"] > 0 else ""
                            out_df.append(
                                f"~ {chg['ssid'][:14]:<14} {chg['prev_rssi']}->{chg['cur_rssi']}dBm ({sign}{chg['delta']}dB)"
                            )
                        _send_cyd_lines(out_df)

                    elif rf_sub == "export":
                        fmt_e = (rf_arg or "json").strip().lower()
                        try:
                            saved_p = wcol.export_report(fmt=fmt_e, out_dir="reports")
                            _send_cyd_lines([
                                f"[OK] Relatorio RF ({fmt_e.upper()}) exportado:",
                                f"Arq: {saved_p[:42]}",
                            ])
                        except Exception as ex_e:
                            _send_cyd_lines([f"[ERR] Falha ao exportar: {str(ex_e)[:32]}"])

                    else:
                        _send_cyd_lines([
                            f"[WARN] Subcomando RF desconhecido: '{rf_sub}'",
                            "Use: rf status|scan|spectrum|track|audit|diff",
                        ])

                # ================================== JITTER ================================
                elif verb == "jitter":
                    raw_t = (arg_rest or "1.1.1.1").strip()
                    if raw_t.lower() in ("gw", "router", "gateway", "roteador"):
                        gw_ip, _if, _lip = net_analyzer.detect_default_route()
                        target = gw_ip or "1.1.1.1"
                        lbl_t = f"GW {target}"
                    else:
                        target = re.sub(r"[^a-zA-Z0-9.\-:]", "", raw_t) or "1.1.1.1"
                        lbl_t = target
                    _send_cyd_lines([f"[WIFI] Medindo Jitter (10 pkts) -> {lbl_t[:20]}..."])
                    res = net_analyzer.run_jitter_test(target, count=10)
                    tag = "[OK]" if res["grade"] in ("EXCELENTE", "BOM") else ("[WARN]" if res["grade"] == "INSTAVEL" else "[ERR]")
                    _send_cyd_lines([
                        f"{tag} {res['host'][:18]}: {res['recv']}/{res['sent']} pkts (Loss {res['loss_pct']}%)",
                        f"RTT : min {res['min_ms']:.1f} | med {res['avg_ms']:.1f} | max {res['max_ms']:.1f} ms",
                        f"Jit : {res['jitter_ms']:.1f} ms | Status: {res['grade']}",
                    ])

                # ================================== TLS / SSL =============================
                elif verb in ("tls", "ssl"):
                    dom = (arg_rest or "").strip()
                    if not dom:
                        _send_cyd_lines([
                            "[WARN] Uso: tls <dominio[:porta]>",
                            "Ex: tls github.com ou tls cloudflare.com",
                        ])
                    else:
                        _send_cyd_lines([f"[WIFI] Inspecionando TLS {dom[:26]}..."])
                        res = net_analyzer.inspect_tls(dom)
                        if res.get("ok"):
                            d_left = res.get("days_left", -1)
                            v_tag = "[OK]" if d_left >= 15 else "[WARN]"
                            _send_cyd_lines([
                                f"[OK] TLS {res['host'][:18]}:{res['port']} ({res['tls_version']})",
                                f"CN   : {res['subject_cn'][:38]}",
                                f"Emiss: {res['issuer'][:38]}",
                                f"Valid: {d_left} dias restantes | HS: {res['handshake_ms']:.0f}ms {v_tag}",
                            ])
                        else:
                            _send_cyd_lines([f"[ERR] TLS {dom[:18]}: {res.get('error', 'Falha')[:30]}"])

                # ================================== MTU ===================================
                elif verb == "mtu":
                    raw_t = (arg_rest or "1.1.1.1").strip()
                    if raw_t.lower() in ("gw", "router", "gateway"):
                        target = net_analyzer.detect_default_route()[0] or "1.1.1.1"
                    else:
                        target = re.sub(r"[^a-zA-Z0-9.\-:]", "", raw_t) or "1.1.1.1"
                    _send_cyd_lines([f"[WIFI] Descobrindo Path MTU (DF) -> {target[:16]}..."])
                    res = net_analyzer.discover_path_mtu(target)
                    if res.get("ok"):
                        _send_cyd_lines([
                            f"[OK] Path MTU {res['host'][:16]}: {res['mtu']} bytes",
                            f"Payload max DF: {res['payload']} B (+28B IP/ICMP)",
                            f"Diag: {res['diagnosis'][:40]}",
                        ])
                    else:
                        _send_cyd_lines([f"[WARN] MTU {target[:16]}: {res.get('diagnosis', 'Falha')[:32]}"])

                # ================================== ROUTE =================================
                elif verb in ("route", "routes"):
                    r_lines = net_analyzer.get_route_table()
                    if not r_lines:
                        gw_ip, iface, local_ip = net_analyzer.detect_default_route()
                        r_lines = [f"default via {gw_ip} dev {iface} src {local_ip}"]
                    out_rt = [f"[OK] Tabela de Rotas IPv4 ({len(r_lines)} rotas):"]
                    for r_ln in r_lines[:8]:
                        out_rt.append(f" {r_ln[:46]}")
                    _send_cyd_lines(out_rt)

                # ================================== NETCHECK / DIAG =======================
                elif verb in ("netcheck", "diag"):
                    _send_cyd_lines(["[WIFI] Executando bateria completa netcheck..."])
                    gw_ip, iface, local_ip = net_analyzer.detect_default_route()
                    gw_p = net_analyzer.ping_stats(gw_ip, count=3) if gw_ip else {"up": False, "avg_ms": 0.0, "jitter_ms": 0.0, "loss_pct": 100}
                    wan_p = net_analyzer.ping_stats("1.1.1.1", count=3)
                    dns_ms = net_analyzer.measure_dns_ms("cloudflare.com")
                    h_code, h_hint = net_analyzer.check_router_http(gw_ip) if gw_ip else (0, "")
                    scanner_ip = ""
                    w_line = "[WARN] ESP32-32U: Offline (UDP :8889)"
                    if self.wifi_scan_col is not None:
                        ws = self.wifi_scan_col.get_ui_snapshot()
                        scanner_ip = ws.get("scanner_ip", "")
                        if ws.get("online"):
                            w_line = f"[OK] 32U: {ws['total']} APs | Livre CH{ws['free_ch']:02d} ({ws['best_rssi']}dBm)"
                        elif ws.get("total", 0) > 0:
                            w_line = f"[WARN] 32U Cache: {ws['total']} APs | Livre CH{ws['free_ch']:02d}"
                    hosts = net_analyzer.read_lan_neighbors(gw_ip=gw_ip, scanner_ip=scanner_ip)

                    gw_tag = "[OK]" if gw_p["up"] else "[ERR]"
                    wan_tag = "[OK]" if wan_p["up"] else "[ERR]"
                    dns_tag = "[OK]" if dns_ms >= 0 else "[ERR]"
                    http_tag = "[OK]" if h_code > 0 else "[WARN]"
                    overall_ok = gw_p["up"] and wan_p["up"] and dns_ms >= 0

                    _send_cyd_lines([
                        f"{gw_tag} GW {gw_ip or '--'} ({iface[:6]}) {gw_p['avg_ms']:.1f}ms J:{gw_p['jitter_ms']:.1f}ms",
                        f"{http_tag} Web GW: HTTP {h_code} {(h_hint or 'Admin')[:18]}",
                        f"{wan_tag} WAN 1.1.1.1: {wan_p['avg_ms']:.1f}ms J:{wan_p['jitter_ms']:.1f}ms L:{wan_p['loss_pct']}%",
                        f"{dns_tag} DNS cloudflare.com: {dns_ms if dns_ms >= 0 else 'ERR'} ms",
                        f"[OK] LAN ARP: {len(hosts)} hosts | PC {local_ip}",
                        w_line,
                        "[OK] Status Geral: REDE INTEGRA" if overall_ok else "[WARN] Status Geral: VERIFICAR LINK",
                    ])

                # ================================== WHOAMI ================================
                elif verb == "whoami":
                    user = getpass.getuser()
                    host = socket.gethostname()
                    lan = get_local_lan_ip()
                    _send_cyd_lines([
                        f"[OK] {user}@{host}",
                        f"OS: {platform.system()} {platform.release()[:20]} ({platform.machine()})",
                        f"LAN IP: {lan} | PID: {os.getpid()}",
                    ])

                # ================================== NEOFETCH ==============================
                elif verb == "neofetch":
                    user = getpass.getuser()
                    host = socket.gethostname()
                    os_str = get_linux_distro_name() if IS_LINUX else f"{platform.system()} {platform.release()}"
                    boot_t = psutil.boot_time()
                    up_s = int(time.time() - boot_t)
                    up_d, rem = divmod(up_s, 86400)
                    up_h, rem = divmod(rem, 3600)
                    up_m, _ = divmod(rem, 60)
                    up_str = f"{up_d}d {up_h}h {up_m}m" if up_d > 0 else f"{up_h}h {up_m}m"
                    cpu_name = get_linux_cpu_name() if IS_LINUX else (platform.processor() or "CPU")
                    if IS_WINDOWS:
                        try:
                            import winreg
                            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                            cpu_name, _ = winreg.QueryValueEx(k, "ProcessorNameString")
                            winreg.CloseKey(k)
                        except Exception:
                            pass
                    cpu_short = re.sub(r"(?i)\s*(Processor|8-Core|16-Thread|with Radeon Graphics|Six-Core|Eight-Core).*", "", cpu_name).strip()[:24]
                    if not cpu_short:
                        cpu_short = "x86_64 CPU"
                    vm = psutil.virtual_memory()
                    ram_used_gb = vm.used / (1024 ** 3)
                    ram_tot_gb = vm.total / (1024 ** 3)
                    gpu_short = "N/A"
                    if self.collector and getattr(self.collector, "last_gpu_name", None):
                        gpu_short = self.collector.last_gpu_name[:22]
                    elif IS_LINUX:
                        gpu_short = (get_linux_gpu_model_name() or "GPU Linux")[:22]
                    elif IS_WINDOWS:
                        try:
                            w_res = subprocess.run(
                                ["wmic", "path", "win32_VideoController", "get", "name"],
                                capture_output=True, text=True, timeout=1.5,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                            g_lines = [ln.strip() for ln in w_res.stdout.splitlines() if ln.strip() and "name" not in ln.lower()]
                            if g_lines:
                                gpu_short = g_lines[0][:22]
                        except Exception:
                            gpu_short = "GPU Integrada / Dedicada"

                    _send_cyd_lines([
                        f"  /\\_/\\     {user}@{host}"[:48],
                        f" ( o.o )    OS: {os_str[:22]}",
                        f"  > ^ <     Host: {host[:18]}",
                        f" CYBERDECK  Uptime: {up_str}",
                        f" v4.6 ESP   CPU: {cpu_short}",
                        f" [===>  ]   RAM: {ram_used_gb:.1f}G/{ram_tot_gb:.1f}G ({vm.percent:.0f}%)",
                        f"            GPU: {gpu_short}",
                    ])

                # ================================== DF -H =================================
                elif verb == "df" or low_full.startswith("df"):
                    lines_df = ["Filesystem    Size   Used  Avail Use%"]
                    parts_found = 0
                    for p in psutil.disk_partitions(all=False):
                        try:
                            usage = psutil.disk_usage(p.mountpoint)
                            tot_g = usage.total / (1024 ** 3)
                            used_g = usage.used / (1024 ** 3)
                            free_g = usage.free / (1024 ** 3)
                            dev = (p.device or p.mountpoint)[:12]
                            lines_df.append(f"{dev:<12} {tot_g:>5.0f}G {used_g:>5.0f}G {free_g:>5.0f}G {usage.percent:>3.0f}%")
                            parts_found += 1
                            if parts_found >= 6:
                                break
                        except Exception:
                            pass
                    if len(lines_df) == 1:
                        lines_df.append("Nenhuma particao de disco acessivel.")
                    _send_cyd_lines(lines_df)

                # ================================== FREE -M ===============================
                elif verb == "free" or low_full.startswith("free"):
                    vm = psutil.virtual_memory()
                    sw = psutil.swap_memory()
                    vm_tot = vm.total // (1024 * 1024)
                    vm_used = vm.used // (1024 * 1024)
                    vm_free = vm.available // (1024 * 1024)
                    sw_tot = sw.total // (1024 * 1024)
                    sw_used = sw.used // (1024 * 1024)
                    sw_free = sw.free // (1024 * 1024)
                    _send_cyd_lines([
                        "        total(M)  used(M)  free(M)  %use",
                        f"Mem:   {vm_tot:>8} {vm_used:>8} {vm_free:>8} {vm.percent:>5.1f}%",
                        f"Swap:  {sw_tot:>8} {sw_used:>8} {sw_free:>8} {sw.percent:>5.1f}%",
                    ])

                # ================================== UPTIME ================================
                elif verb == "uptime":
                    boot_t = psutil.boot_time()
                    up_s = int(time.time() - boot_t)
                    up_d, rem = divmod(up_s, 86400)
                    up_h, rem = divmod(rem, 3600)
                    up_m, up_sec = divmod(rem, 60)
                    dt_boot = datetime.fromtimestamp(boot_t).strftime("%Y-%m-%d %H:%M:%S")
                    d_txt = f"{up_d}d " if up_d else ""
                    _send_cyd_lines([
                        f"[OK] Uptime: {d_txt}{up_h:02d}:{up_m:02d}:{up_sec:02d}",
                        f"Boot: {dt_boot}",
                        f"Carga: CPU {psutil.cpu_percent():.0f}% | RAM {psutil.virtual_memory().percent:.0f}%",
                    ])

                # ================================== IP / IFCONFIG =========================
                elif verb in ("ip", "ifconfig", "ipconfig") or low_full.startswith("ip addr"):
                    if len(parts) > 1 and parts[1].lower() in ("route", "r"):
                        r_lines = net_analyzer.get_route_table()
                        out_rt = [f"[OK] Tabela de Rotas IPv4 ({len(r_lines)} rotas):"]
                        for r_ln in r_lines[:8]:
                            out_rt.append(f" {r_ln[:46]}")
                        _send_cyd_lines(out_rt)
                    else:
                        lines_ip = ["[OK] Interfaces de Rede Ativas:"]
                        try:
                            addrs = psutil.net_if_addrs()
                            stats = psutil.net_if_stats()
                            for if_name, if_addrs in addrs.items():
                                st = stats.get(if_name)
                                if st and not st.isup:
                                    continue
                                for a in if_addrs:
                                    if a.family == socket.AF_INET:
                                        ip_val = a.address
                                        if ip_val.startswith("127."):
                                            continue
                                        alias = if_name[:14]
                                        lines_ip.append(f" * {alias:<14}: {ip_val}")
                        except Exception as e_ip:
                            lines_ip.append(f" [ERR] {str(e_ip)[:30]}")
                        if len(lines_ip) == 1:
                            lines_ip.append(f" * IPv4 LAN: {get_local_lan_ip()}")
                        lines_ip.append(f"Host: {socket.gethostname()[:30]}")
                        _send_cyd_lines(lines_ip[:8])

                # ================================== NETSTAT ===============================
                elif verb in ("netstat", "ports") or low_full.startswith("netstat"):
                    lines_ns = ["[OK] Portas Abertas em Escuta (LISTEN):"]
                    try:
                        conns = psutil.net_connections(kind="inet")
                        seen_ports = set()
                        for c in conns:
                            if c.status == "LISTEN" and c.laddr:
                                port = c.laddr.port
                                if port in seen_ports:
                                    continue
                                seen_ports.add(port)
                                pname = "sys"
                                if c.pid:
                                    try:
                                        pname = psutil.Process(c.pid).name()[:14]
                                    except Exception:
                                        pass
                                lines_ns.append(f" :{port:<5} | PID {c.pid or 0:<6} ({pname})")
                                if len(lines_ns) >= 7:
                                    break
                    except Exception as ex:
                        lines_ns.append(f" [WARN] Requer admin: {str(ex)[:26]}")
                    if len(lines_ns) == 1:
                        lines_ns.append(" Nenhuma porta TCP/UDP LISTEN visivel.")
                    _send_cyd_lines(lines_ns)

                # ================================== SSH (Homelab/VPS) =====================
                elif verb == "ssh":
                    ssh_args = parts[1:]
                    if not ssh_args:
                        _send_cyd_lines([
                            "[WARN] Uso: ssh <user>@<host> [cmd]",
                            "Ex: ssh root@192.168.1.100 df -h",
                        ])
                    else:
                        target_spec = ssh_args[0]
                        remote_cmd = " ".join(ssh_args[1:]).strip() or "uname -a"
                        user = None
                        host = target_spec
                        port = 22
                        if "@" in target_spec:
                            user, host = target_spec.split("@", 1)
                        if ":" in host:
                            host, port_str = host.split(":", 1)
                            try:
                                port = int(port_str)
                            except Exception:
                                pass
                        _send_cyd_lines([f"[SSH] {user or 'auto'}@{host[:16]}:{port} -> {remote_cmd[:14]}"])

                        ran_ok = False
                        if paramiko is not None:
                            try:
                                client = paramiko.SSHClient()
                                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                client.connect(
                                    hostname=host,
                                    port=port,
                                    username=user,
                                    timeout=6.0,
                                    look_for_keys=True,
                                    allow_agent=True,
                                )
                                stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=8.0)
                                out_s = stdout.read().decode("utf-8", errors="ignore")
                                err_s = stderr.read().decode("utf-8", errors="ignore")
                                client.close()
                                out_lines = [ln.strip()[:48] for ln in (out_s + "\n" + err_s).splitlines() if ln.strip()]
                                if out_lines:
                                    _send_cyd_lines(out_lines[:8])
                                else:
                                    _send_cyd_lines(["[OK] SSH executado sem retorno."])
                                ran_ok = True
                            except Exception:
                                pass

                        if not ran_ok:
                            try:
                                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
                                sub_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-p", str(port), f"{user + '@' if user else ''}{host}", remote_cmd]
                                res = subprocess.run(
                                    sub_cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=9.0,
                                    encoding="utf-8",
                                    errors="ignore",
                                    creationflags=creation_flags,
                                )
                                out_txt = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                                out_lines = [ln.strip()[:48] for ln in out_txt.splitlines() if ln.strip()]
                                if out_lines:
                                    _send_cyd_lines(out_lines[:8])
                                else:
                                    _send_cyd_lines([f"[OK] SSH Code {res.returncode} concluido."])
                            except FileNotFoundError:
                                _send_cyd_lines(["[ERR] Cliente OpenSSH nao encontrado."])
                            except subprocess.TimeoutExpired:
                                _send_cyd_lines(["[ERR] Timeout (9s) aguardando SSH."])
                            except Exception as ex_sub:
                                _send_cyd_lines([f"[ERR] SSH: {str(ex_sub)[:34]}"])

                # ================================== PING ==================================
                elif verb == "ping":
                    target = arg_rest or "8.8.8.8"
                    if target.lower() in ("gw", "router", "gateway"):
                        target = net_analyzer.detect_default_route()[0] or "8.8.8.8"
                    else:
                        target = re.sub(r"[^a-zA-Z0-9.\-:]", "", target) or "8.8.8.8"
                    _send_cyd_lines([f"[PING] 4 pacotes ICMP -> {target[:22]}..."])
                    ping_cmd = ["ping", "-n", "4", "-w", "2000", target] if IS_WINDOWS else ["ping", "-c", "4", "-W", "2", target]
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
                    proc = subprocess.Popen(
                        ping_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="cp850" if IS_WINDOWS else "utf-8",
                        errors="ignore",
                        creationflags=creation_flags,
                    )
                    latencies = []
                    seq_n = 0
                    for raw_line in proc.stdout:
                        line_s = raw_line.strip()
                        if not line_s:
                            continue
                        m_time = re.search(r"(?:tempo|time)[=<]\s*([\d.]+)\s*ms", line_s, re.IGNORECASE)
                        m_ttl = re.search(r"TTL=(\d+)", line_s, re.IGNORECASE)
                        if m_time:
                            seq_n += 1
                            ms_val = float(m_time.group(1))
                            latencies.append(ms_val)
                            ttl_str = f" TTL={m_ttl.group(1)}" if m_ttl else ""
                            _send_cyd_lines([f" #{seq_n} {target[:16]}: {ms_val:.1f}ms{ttl_str} [OK]"])
                        elif "esgotado" in line_s.lower() or "timed out" in line_s.lower() or "unreachable" in line_s.lower():
                            seq_n += 1
                            _send_cyd_lines([f" #{seq_n} {target[:16]}: TIMEOUT [ERR]"])
                    proc.wait(timeout=10)
                    if latencies:
                        avg_ms = sum(latencies) / len(latencies)
                        _send_cyd_lines([
                            f"[OK] {len(latencies)}/4 pkts min={min(latencies):.0f} med={avg_ms:.1f} max={max(latencies):.0f}ms"
                        ])
                    else:
                        _send_cyd_lines([f"[ERR] {target[:20]}: Sem resposta (100% loss)"])

                # ================================== FETCH =================================
                elif verb in ("fetch", "curl", "http"):
                    url = arg_rest or "https://api.github.com"
                    if not url.startswith("http://") and not url.startswith("https://"):
                        url = "https://" + url
                    _send_cyd_lines([f"[FETCH] GET {url[:34]}..."])
                    t0 = time.perf_counter()
                    try:
                        req = urllib.request.Request(
                            url,
                            headers={
                                "User-Agent": "CYD-CyberDeck-Terminal/4.6",
                                "Accept": "*/*",
                            },
                        )
                        with urllib.request.urlopen(req, timeout=6.0) as resp:
                            elapsed_ms = (time.perf_counter() - t0) * 1000.0
                            code = getattr(resp, "status", 200)
                            srv = resp.headers.get("Server", "Web")[:14]
                            ctype = (resp.headers.get("Content-Type", "text/html").split(";")[0])[:20]
                            body_sample = resp.read(2048).decode("utf-8", errors="ignore")
                            _send_cyd_lines([
                                f"[OK] HTTP {code} OK ({elapsed_ms:.0f} ms)",
                                f"Srv: {srv} | Tipo: {ctype}",
                            ])
                            m_tit = re.search(r"<title[^>]*>(.*?)</title>", body_sample, re.IGNORECASE | re.DOTALL)
                            if m_tit:
                                clean_t = re.sub(r"\s+", " ", m_tit.group(1)).strip()[:39]
                                if clean_t:
                                    _send_cyd_lines([f"Title: {clean_t}"])
                    except urllib.error.HTTPError as he:
                        elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        _send_cyd_lines([f"[WARN] HTTP {he.code} ({str(he.reason)[:16]}) em {elapsed_ms:.0f}ms"])
                    except Exception as ex:
                        _send_cyd_lines([f"[ERR] Falha: {str(ex)[:34]}"])

                # ================================== DOCKER ================================
                elif verb == "docker":
                    sub_args = parts[1:]
                    if not sub_args or sub_args[0] == "ps":
                        sub_args = ["ps", "--format", "table {{.Names}}\t{{.Status}}"]
                    elif sub_args[0] == "stats":
                        sub_args = ["stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"]

                    _send_cyd_lines([f"[DOCKER] docker {' '.join(sub_args)[:30]}..."])
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
                    try:
                        res = subprocess.run(
                            ["docker"] + sub_args,
                            capture_output=True,
                            text=True,
                            timeout=8.0,
                            encoding="utf-8",
                            errors="ignore",
                            creationflags=creation_flags,
                        )
                        out_txt = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                        out_lines = [ln.strip()[:48] for ln in out_txt.splitlines() if ln.strip()]
                        if res.returncode == 0:
                            if out_lines:
                                _send_cyd_lines(out_lines[:10])
                            else:
                                _send_cyd_lines(["[OK] Docker concluido (0 containers)."])
                        else:
                            err_preview = out_lines[:3] if out_lines else ["Daemon Docker inacessivel."]
                            _send_cyd_lines([f"[ERR] Docker code {res.returncode}"] + err_preview)
                    except FileNotFoundError:
                        _send_cyd_lines(["[ERR] Docker CLI nao instalado no PC."])
                    except subprocess.TimeoutExpired:
                        _send_cyd_lines(["[ERR] Timeout (8s) no Docker Daemon."])
                    except Exception as ex:
                        _send_cyd_lines([f"[ERR] Docker: {str(ex)[:34]}"])

                # ================================== TOP ===================================
                elif verb in ("top", "procs"):
                    procs = []
                    for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
                        try:
                            info = p.info
                            if info["name"] and info["name"].lower() not in ("system idle process", "idle"):
                                procs.append((float(info.get("memory_percent") or 0.0), info["name"]))
                        except Exception:
                            pass
                    procs.sort(reverse=True)
                    lines_p = ["[OK] Top 5 Processos por Uso de RAM:"]
                    for idx_p, (mem_p, pname) in enumerate(procs[:5], 1):
                        lines_p.append(f" {idx_p}) {pname[:22]:<22} RAM: {mem_p:>4.1f}%")
                    _send_cyd_lines(lines_p)

                # ================================== ROUTER / GATEWAY ======================
                elif verb in ("router", "gateway", "gw"):
                    _send_cyd_lines(["[WIFI] Diagnosticando roteador / gateway..."])
                    gw_ip, iface, local_ip = net_analyzer.detect_default_route()
                    gw_p = net_analyzer.ping_stats(gw_ip, count=3)
                    h_code, h_hint = net_analyzer.check_router_http(gw_ip)
                    hosts = net_analyzer.read_lan_neighbors(gw_ip=gw_ip)
                    gw_mac = next((h["mac"] for h in hosts if h["ip"] == gw_ip), "--")
                    vend_gw = wifi_scanner.lookup_oui(gw_mac) if gw_mac != "--" else ""
                    v_str = f" ({vend_gw[:10]})" if vend_gw and vend_gw != "Desconhecido" else ""
                    tag = "[OK]" if gw_p["up"] else "[ERR]"
                    _send_cyd_lines([
                        f"{tag} GW: {gw_ip} via {iface[:10]}",
                        f"MAC : {gw_mac}{v_str}",
                        f"Ping: {gw_p['avg_ms']:.1f}ms | Jit: {gw_p['jitter_ms']:.1f}ms | Loss: {gw_p['loss_pct']}%",
                        f"Web : http://{gw_ip} (HTTP {h_code} {h_hint[:10]})",
                        f"LAN : {len(hosts)} vizinhos ARP | PC: {local_ip}",
                    ])

                # ================================== LAN / ARP =============================
                elif verb in ("lan", "arp", "hosts"):
                    gw_ip, _if, _ip = net_analyzer.detect_default_route()
                    hosts = net_analyzer.read_lan_neighbors(gw_ip=gw_ip)
                    lines_h = [f"[OK] Vizinhos ARP na LAN ({len(hosts)} hosts):"]
                    for h in hosts[:9]:
                        mac_s = h.get("mac", "")
                        vend_h = wifi_scanner.lookup_oui(mac_s)
                        tag_s = h.get("tag", "LAN")
                        if tag_s == "LAN" and vend_h != "Desconhecido":
                            tag_s = vend_h[:11]
                        lines_h.append(f" {h['ip']:<15} {mac_s:<17} {tag_s[:11]}")
                    _send_cyd_lines(lines_h)

                # ================================== DNS ===================================
                elif verb in ("dns", "dig", "nslookup"):
                    dom = re.sub(r"[^a-zA-Z0-9.\-]", "", arg_rest or "cloudflare.com") or "cloudflare.com"
                    t0 = time.perf_counter()
                    try:
                        infos = socket.getaddrinfo(dom, 443, socket.AF_INET)
                        ms = (time.perf_counter() - t0) * 1000.0
                        ips = sorted({x[4][0] for x in infos})[:3]
                        _send_cyd_lines([
                            f"[OK] DNS {dom[:24]} ({ms:.1f} ms):",
                            f" IPs: {', '.join(ips)}"[:48],
                        ])
                    except Exception as ex:
                        _send_cyd_lines([f"[ERR] DNS {dom[:18]}: {str(ex)[:26]}"])

                # ================================== TRACE / TRACEROUTE ====================
                elif verb in ("trace", "traceroute", "tracepath"):
                    tgt = re.sub(r"[^a-zA-Z0-9.\-:]", "", arg_rest or "1.1.1.1") or "1.1.1.1"
                    _send_cyd_lines([f"[WIFI] Traceroute -> {tgt[:22]} (8 hops)..."])
                    t_cmd = ["tracert", "-d", "-h", "8", "-w", "1000", tgt] if IS_WINDOWS else ["traceroute", "-n", "-m", "8", "-w", "1", "-q", "1", tgt]
                    out_t = net_analyzer._run_cmd(t_cmd, timeout=9.0)
                    t_lines = [ln.strip()[:48] for ln in out_t.splitlines() if ln.strip()][:9]
                    _send_cyd_lines(t_lines if t_lines else ["[WARN] Sem resposta / traceroute ausente."])

                # ================================== SPEEDTEST =============================
                elif verb in ("speed", "speedtest"):
                    _send_cyd_lines(["[WIFI] Testando Download/Upload Fibra (~4s)..."])
                    res = net_analyzer.run_cloudflare_speedtest()
                    if res.get("ok"):
                        _send_cyd_lines([
                            f"[OK] DL: {res['dl_mbps']:.1f} Mbps | UL: {res['ul_mbps']:.1f} Mbps",
                            f"Ping 1.1.1.1: {res['ping_ms']:.1f}ms | Jit: {res['jitter_ms']:.1f}ms",
                        ])
                    else:
                        _send_cyd_lines(["[ERR] Falha no teste de velocidade."])

                # ================================== AGENTE IA (GEMINI + LOCAL) ============
                elif verb in ("ai", "ia", "gemini"):
                    if self.ai_eng is None:
                        _send_cyd_lines(["[ERR] Modulo ai_analyst nao inicializado."])
                    else:
                        sub_ai = (parts[1].lower() if len(parts) > 1 else "status").strip()
                        rest_ai = " ".join(parts[2:]).strip() if len(parts) > 2 else ""
                        if sub_ai in ("status", "st", "info"):
                            st_ai = self.ai_eng.get_status_snapshot(probe_local=True)
                            g_ok = "PRONTO" if st_ai.get("gemini_key_set") else "SEM CHAVE"
                            l_ok = "ONLINE" if st_ai.get("local_online") else "OFFLINE"
                            l_mod = st_ai.get("active_local_model") or "--"
                            lines_ai = [
                                f"[OK] AGENTE IA | Modo: {st_ai.get('ai_provider','auto').upper()}",
                                f"Gemini: {g_ok} ({st_ai.get('gemini_model','')[:22]})",
                                f"Local : {l_ok} [{st_ai.get('local_kind','ollama')}] {l_mod[:18]}",
                                f"URL   : {st_ai.get('local_ai_url','')[:38]}",
                                f"Models: {len(st_ai.get('local_models', []))} local(is) detectados",
                            ]
                            if st_ai.get("last_report_path"):
                                lines_ai.append(f"Ultimo: {os.path.basename(st_ai['last_report_path'])[:38]}")
                            _send_cyd_lines(lines_ai)
                        elif sub_ai in ("models", "modelos", "list"):
                            online_l, mods_l, kind_l = self.ai_eng.list_local_models(timeout=2.5, force=True)
                            pub_ai = self.ai_eng.get_config_public()
                            lines_m = [
                                f"[OK] Gemini: {pub_ai.get('gemini_model','')} ({'OK' if pub_ai.get('gemini_key_set') else 'NO KEY'})",
                                f"[{'OK' if online_l else 'WARN'}] Local ({kind_l}): {len(mods_l)} modelo(s)",
                            ]
                            for m_name in mods_l[:7]:
                                lines_m.append(f" - {m_name[:43]}")
                            if not mods_l:
                                lines_m.append("Nenhum modelo local detectado.")
                            _send_cyd_lines(lines_m)
                        elif sub_ai in ("provider", "modo", "mode"):
                            if rest_ai.lower() in ("auto", "gemini", "local", "ollama"):
                                pub_new = self.ai_eng.configure(ai_provider=rest_ai.lower(), persist=True)
                                _send_cyd_lines([f"[OK] Provedor IA ajustado: {pub_new['ai_provider'].upper()}"])
                            else:
                                _send_cyd_lines(["[WARN] Uso: ai provider auto|gemini|local"])
                        elif sub_ai in ("report", "relatorio", "diag", "full", "rf", "spectrum"):
                            mode_req = "rf" if sub_ai in ("rf", "spectrum") else "full"
                            prov_override = rest_ai.lower() if rest_ai.lower() in ("auto", "gemini", "local") else None
                            _send_cyd_lines([f"[WIFI] IA analisando {'espectro RF' if mode_req == 'rf' else 'rede completa'}..."])
                            res_ai = self.ai_eng.generate_report(mode=mode_req, provider=prov_override, save_file=True)
                            if res_ai.get("ok"):
                                _send_cyd_lines(res_ai.get("cyd_lines", ["[OK] Relatorio IA gerado."]))
                            else:
                                _send_cyd_lines([f"[ERR] IA: {str(res_ai.get('error','falha'))[:40]}"])
                        elif sub_ai in ("ask", "perguntar", "q"):
                            if not rest_ai:
                                _send_cyd_lines(["[WARN] Uso: ai ask <sua pergunta sobre a rede>"])
                            else:
                                _send_cyd_lines(["[WIFI] Consultando Agente IA sobre a rede..."])
                                res_ai = self.ai_eng.generate_report(mode="ask", question=rest_ai, save_file=False)
                                if res_ai.get("ok"):
                                    _send_cyd_lines(res_ai.get("cyd_lines", ["[OK] Resposta IA recebida."]))
                                else:
                                    _send_cyd_lines([f"[ERR] IA: {str(res_ai.get('error','falha'))[:40]}"])
                        else:
                            # Permite `ai <pergunta direta>` como atalho para `ai ask`
                            q_direct = " ".join(parts[1:]).strip()
                            _send_cyd_lines(["[WIFI] Consultando Agente IA..."])
                            res_ai = self.ai_eng.generate_report(mode="ask", question=q_direct, save_file=False)
                            if res_ai.get("ok"):
                                _send_cyd_lines(res_ai.get("cyd_lines", ["[OK] Resposta IA recebida."]))
                            else:
                                _send_cyd_lines([f"[ERR] IA: {str(res_ai.get('error','falha'))[:40]}"])

                else:
                    _send_cyd_lines([
                        f"[ERR] Comando desconhecido: '{verb[:22]}'",
                        "Digite 'help' (rf | net | ai | sys | esp).",
                    ])

                if log_fn:
                    log_fn(f"💻 Terminal executou: {cmd_str}")
            finally:
                with self._lock:
                    self._busy = False
                done_ev.set()

        t_worker = threading.Thread(target=_runner, daemon=True)
        t_worker.start()
        if wait:
            done_ev.wait(timeout=max(0.5, float(timeout_s or 10.0)))
        return list(captured_lines)


# ========================================== INTERFACE MODERNA EM FLET (FLUTTER) ==
def launch_flet_gui(
    col: Collector,
    mkt_col: MarketCollector,
    media_col: MediaCollector,
    pomo_eng: PomodoroEngine,
    wth_col: WeatherCollector,
    gems_eng: NewsFeedCollector,
    cli_args,
    term_eng: CyberDeckTerminalEngine = None,
    wifi_scan_col: wifi_scanner.WiFiScannerCollector = None,
    net_col: net_analyzer.NetworkAnalyzerCollector = None,
    ai_eng: ai_analyst.NetworkAIAnalyst = None,
):
    import flet as ft

    if term_eng is None:
        term_eng = CyberDeckTerminalEngine(collector=col, wifi_scan_col=wifi_scan_col, net_col=net_col, ai_eng=ai_eng)
    else:
        if term_eng.collector is None:
            term_eng.collector = col
        if term_eng.wifi_scan_col is None:
            term_eng.wifi_scan_col = wifi_scan_col
        if term_eng.net_col is None:
            term_eng.net_col = net_col
        if term_eng.ai_eng is None and ai_eng is not None:
            term_eng.ai_eng = ai_eng

    # Helpers compativeis entre Flet 0.2x e Flet 1.0+
    _ICONS = getattr(ft, "Icons", getattr(ft, "icons", None))
    _Border = getattr(ft, "Border", getattr(ft, "border", None))
    _Padding = getattr(ft, "Padding", getattr(ft, "padding", None))
    _Button = getattr(ft, "Button", getattr(ft, "ElevatedButton", None))
    _dd_sig = inspect.signature(ft.Dropdown.__init__).parameters

    def icon_val(name: str):
        return getattr(_ICONS, name, None) if _ICONS else None

    def border_all(width: float, color: str):
        return _Border.all(width, color)

    def pad_sym(horizontal: float = 0, vertical: float = 0):
        return _Padding.symmetric(horizontal=horizontal, vertical=vertical)

    def set_btn_text(btn, txt: str):
        if hasattr(btn, "content") and not isinstance(getattr(btn, "content", None), ft.Control):
            btn.content = txt
        elif hasattr(btn, "text"):
            btn.text = txt

    def make_compat_dropdown(label: str, value: str, options: list, width: float = None, expand: bool = False, on_change=None):
        kw = {
            "label": label,
            "value": value,
            "options": options,
        }
        if width is not None:
            kw["width"] = width
        if expand:
            kw["expand"] = True
        if on_change is not None:
            if "on_change" in _dd_sig:
                kw["on_change"] = on_change
            elif "on_select" in _dd_sig:
                kw["on_select"] = on_change
        return ft.Dropdown(**kw)

    def build_app(page: ft.Page):
        page.title = "CYD Cyber Deck v4.2 — Terminal Administrativo, News Feed, Clima & Telemetria"
        page.bgcolor = "#07090E"
        page.padding = 14
        page.scroll = None  # Viewport fixo com abas independentes (zero poluicao visual!)
        page.theme_mode = ft.ThemeMode.DARK

        cfg = load_ui_config()
        state = {
            "active_tab": 0,
            "screen": int(cfg.get("screen", 1)),
            "hex_color": cfg.get("hex_color", "#00FF00").upper(),
            "color": cfg.get("color", "0x07E0"),
            "bg": cfg.get("bg", "none"),
            "brt": int(cfg.get("brt", 200)),
            "ticker": bool(cfg.get("ticker", True)),
            "sd_files": list(cfg.get("sd_files", [])),
            "sleep_enabled": bool(cfg.get("sleep_enabled", True)),
            "sleep_timeout_min": int(cfg.get("sleep_timeout_min", 15)),
            "night_mode_enabled": bool(cfg.get("night_mode_enabled", True)),
            "night_start_hour": int(cfg.get("night_start_hour", 22)),
            "night_end_hour": int(cfg.get("night_end_hour", 6)),
            "night_brightness": int(cfg.get("night_brightness", 40)),
            "alert_rules": [dict(r) for r in cfg.get("alert_rules", DEFAULT_ALERT_RULES)],
            "portfolio": [dict(p) for p in cfg.get("portfolio", DEFAULT_PORTFOLIO)],
            "portfolio_pnl_mode": str(cfg.get("portfolio_pnl_mode", "hist")),
            "pomo_work_min": int(cfg.get("pomo_work_min", 25)),
            "pomo_break_min": int(cfg.get("pomo_break_min", 5)),
            "pomo_long_min": int(cfg.get("pomo_long_min", 15)),
            "pomo_buzzer": bool(cfg.get("pomo_buzzer", True)),
            "media_source_pref": str(cfg.get("media_source_pref", "auto")),
            "media_auto_cover": bool(cfg.get("media_auto_cover", True)),
            "weather_city": str(cfg.get("weather_city", "Votuporanga")),
            "news_topics": list(cfg.get("news_topics", DEFAULT_NEWS_TOPICS)),
            "news_api_key": str(cfg.get("news_api_key", os.environ.get("NEWS_API_KEY", ""))),
            "udp_enabled": bool(cfg.get("udp_enabled", False)),
            "udp_ip": str(cfg.get("udp_ip", "") or ""),
            "udp_port": int(cfg.get("udp_port", UDP_DEFAULT_PORT) or UDP_DEFAULT_PORT),
            "esp_wifi_ssid": str(cfg.get("esp_wifi_ssid", "") or ""),
            "esp_wifi_pass": str(cfg.get("esp_wifi_pass", "") or ""),
            "scanner_enabled": bool(cfg.get("scanner_enabled", True)),
            "scanner_port": str(cfg.get("scanner_port", "") or ""),
            "scanner_interval_s": float(cfg.get("scanner_interval_s", 8.0) or 8.0),
            "term_auto_switch": True,
            "synced_cover_id": "",
            "sd_missing_warned": False,
            "current_effective_brt": int(cfg.get("brt", 200)),
            "running": True,
            "ui_dirty": True,
            "last_ui_sync": 0.0,
            "last_mkt_sync": 0.0,
            "last_brt_ev": 0.0,
            "rail_extended": True,
            "_last_news_sig": None,
            "_last_pf_sig": None,
        }
        mkt_col.set_custom_tickers([p.get("ticker", "") for p in state["portfolio"]])
        media_col.set_source_pref(state["media_source_pref"])
        pomo_eng.set_durations(state["pomo_work_min"], state["pomo_break_min"], state["pomo_long_min"])
        pomo_eng.buzzer_enabled = state["pomo_buzzer"]
        gems_eng.set_topics(state["news_topics"], state["news_api_key"])

        def safe_update(*controls):
            """
            State Management Eficiente (Clean UI):
            Atualiza apenas os controles específicos passados como argumento via `.update()` isolado,
            evitando re-renderizar a página inteira a cada ciclo de telemetria.
            """
            if not state.get("running", True):
                return
            if not controls:
                try:
                    page.update()
                except Exception:
                    pass
                return
            updated_any = False
            for ctrl in controls:
                if ctrl is None:
                    continue
                try:
                    if getattr(ctrl, "page", None) is not None:
                        ctrl.update()
                        updated_any = True
                except Exception:
                    pass
            if not updated_any:
                try:
                    page.update()
                except Exception:
                    pass

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
                serial_mgr.stop()
            except Exception:
                pass
            try:
                if wifi_scan_col is not None:
                    wifi_scan_col.stop()
            except Exception:
                pass
            try:
                if net_col is not None:
                    net_col.stop()
            except Exception:
                pass
            try:
                col.stop()
            except Exception:
                pass
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

        ico_file, png_file = get_app_icon_paths()
        win_icon_path = (png_file if IS_LINUX and png_file else ico_file) or png_file or ico_file
        try:
            if hasattr(page, "window") and page.window is not None:
                page.window.width = 1140
                page.window.height = 840
                page.window.min_width = 920
                page.window.min_height = 660
                page.window.prevent_close = True
                page.window.on_event = on_window_event
                if win_icon_path and os.path.exists(win_icon_path):
                    page.window.icon = win_icon_path
            if win_icon_path and os.path.exists(win_icon_path) and hasattr(page, "window_icon"):
                try:
                    page.window_icon = win_icon_path
                except Exception:
                    pass
        except Exception:
            pass

        # ---------------------- BANDEJA DO SISTEMA (SYSTEM TRAY) -------------
        tray_icon = None
        try:
            import pystray
            from PIL import Image, ImageDraw

            def create_tray_image():
                for candidate in (png_file, ico_file):
                    if candidate and os.path.exists(candidate):
                        try:
                            return Image.open(candidate)
                        except Exception:
                            pass
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
                "CYD Cyber Deck v4.0 (Ativo em Segundo Plano)",
                menu=tray_menu,
            )

            def _run_tray_safe():
                try:
                    tray_icon.run()
                except Exception:
                    pass

            threading.Thread(target=_run_tray_safe, daemon=True).start()
        except Exception:
            tray_icon = None

        serial_mgr = SerialManager(
            preferred_port=cli_args.port,
            baud=BAUD,
            udp_enabled=bool(cfg.get("udp_enabled", False)),
            udp_ip=str(cfg.get("udp_ip", "") or ""),
            udp_port=int(cfg.get("udp_port", UDP_DEFAULT_PORT) or UDP_DEFAULT_PORT),
            excluded_ports_fn=(wifi_scan_col.get_active_ports if wifi_scan_col is not None else None),
        )
        if wifi_scan_col is not None:
            wifi_scan_col.set_excluded_ports_fn(serial_mgr.get_active_ports)
        ui_event_queue = serial_mgr.event_queue
        transfer_queue = serial_mgr.transfer_queue
        ack_event = serial_mgr.ack_event
        last_ack = serial_mgr.last_ack
        log_lines = []
        upload_state = {
            "active": False,
            "pct": 0.0,
            "status": "",
            "target": "",
        }

        def get_ui_dict():
            bg = (state["bg"] or "none").strip()
            if bg.startswith("/"):
                bg = bg[1:]
            return {
                "screen": int(state["screen"]),
                "color": state["color"],
                "bg": bg,
                "brt": int(state.get("current_effective_brt", state["brt"])),
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
                "sleep_enabled": state["sleep_enabled"],
                "sleep_timeout_min": state["sleep_timeout_min"],
                "night_mode_enabled": state["night_mode_enabled"],
                "night_start_hour": state["night_start_hour"],
                "night_end_hour": state["night_end_hour"],
                "night_brightness": state["night_brightness"],
                "alert_rules": state["alert_rules"],
                "portfolio": state["portfolio"],
                "portfolio_pnl_mode": state["portfolio_pnl_mode"],
                "pomo_work_min": state["pomo_work_min"],
                "pomo_break_min": state["pomo_break_min"],
                "pomo_long_min": state["pomo_long_min"],
                "pomo_buzzer": state["pomo_buzzer"],
                "media_source_pref": state["media_source_pref"],
                "media_auto_cover": state["media_auto_cover"],
                "weather_city": state["weather_city"],
                "news_topics": state["news_topics"],
                "news_api_key": state["news_api_key"],
                "udp_enabled": state.get("udp_enabled", False),
                "udp_ip": state.get("udp_ip", ""),
                "udp_port": state.get("udp_port", UDP_DEFAULT_PORT),
                "esp_wifi_ssid": state.get("esp_wifi_ssid", ""),
                "esp_wifi_pass": state.get("esp_wifi_pass", ""),
                "scanner_enabled": state.get("scanner_enabled", True),
                "scanner_port": state.get("scanner_port", ""),
                "scanner_interval_s": state.get("scanner_interval_s", 8.0),
            })
            save_ui_config(cfg)
            serial_mgr.configure_udp(
                enabled=state.get("udp_enabled", False),
                ip=state.get("udp_ip", ""),
                port=state.get("udp_port", UDP_DEFAULT_PORT),
            )
            mkt_col.set_custom_tickers([p.get("ticker", "") for p in state["portfolio"]])
            portf_pkt, _ = mkt_col.compute_portfolio(state["portfolio"], state["portfolio_pnl_mode"])
            state["ui_dirty"] = True
            ev_pkt = {
                "ui": get_ui_dict(),
                "mkt": mkt_col.get_market_dict(),
                "portf": portf_pkt,
                "pomo": pomo_eng.get_payload(),
                "media": media_col.get_cyd_payload(state["synced_cover_id"]),
                "wth": wth_col.get_cyd_payload(),
                "news": gems_eng.get_cyd_news_payload(include_queue=True, force=True),
            }
            if wifi_scan_col is not None:
                ev_pkt["wrad"] = wifi_scan_col.get_cyd_payload()
            if net_col is not None:
                ev_pkt["neta"] = net_col.get_cyd_payload()
            serial_mgr.send_event(ev_pkt, coalesce=True)

        def append_log(msg: str):
            ts = datetime.now().strftime("%H:%M:%S")
            log_lines.append(f"[{ts}] {msg}")
            if len(log_lines) > 60:
                del log_lines[0]
            txt_console.value = "\n".join(log_lines)
            if state.get("active_tab") == 7:
                safe_update(txt_console)

        SCREEN_SHORT_NAMES = {
            0: "Gauges",
            1: "CPU+RAM",
            2: "Dual Graph",
            3: "GPU Focus",
            4: "4x Graphs",
            5: "Wallpaper",
            6: "Mercado",
            7: "Portfólio",
            8: "Pomodoro",
            9: "Mídia",
            10: "Clima & News",
            11: "Terminal CYD",
            12: "Radar Wi-Fi",
            13: "Rede & Roteador",
        }

        def switch_tab(tab_idx: int):
            state["active_tab"] = int(tab_idx)
            refresh_tabs_ui()

        # ------------------------ CABECALHO COMPACTO + NOVA IDENTIDADE VISUAL -
        hdr_brand_logo = (
            ft.Image(
                src=png_file,
                width=30,
                height=30,
                border_radius=7,
                fit=ft.BoxFit.CONTAIN if hasattr(ft, "BoxFit") else "contain",
            )
            if (png_file and os.path.exists(png_file))
            else ft.Icon(icon_val("MEMORY"), size=24, color=state["hex_color"])
        )
        lbl_title = ft.Text(
            "CYD CYBER DECK v4.0",
            size=17,
            weight=ft.FontWeight.BOLD,
            color=state["hex_color"],
            font_family="Consolas",
        )
        lbl_hdr_screen = ft.Text(
            f"📺 TELA {state['screen']} • {SCREEN_SHORT_NAMES.get(state['screen'], '')}",
            size=11,
            weight=ft.FontWeight.BOLD,
            color=state["hex_color"],
            font_family="Consolas",
        )
        chip_active_screen = ft.Container(
            content=lbl_hdr_screen,
            bgcolor="#111827",
            border=border_all(1, state["hex_color"]),
            border_radius=16,
            padding=pad_sym(horizontal=10, vertical=4),
            ink=True,
            tooltip="Clique para gerenciar as 12 telas da CYD (0 a 11)",
            on_click=lambda e: switch_tab(0),
        )

        # Micro-indicador global no Header: Hora + Data Atual + Temperatura na Região (Votuporanga)
        init_wth_snap = wth_col.get_ui_snapshot()
        lbl_hdr_weather = ft.Text(
            f"🕒 {datetime.now().strftime('%H:%M')} • 📅 {init_wth_snap['date_short']} • 🌡️ {init_wth_snap['temp']:.1f}°C ({init_wth_snap['city']})",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#38BDF8",
            font_family="Consolas",
        )
        pill_hdr_weather = ft.Container(
            content=lbl_hdr_weather,
            bgcolor="#0F172A",
            border=border_all(1, "#0284C7"),
            border_radius=16,
            padding=pad_sym(horizontal=10, vertical=4),
            ink=True,
            tooltip="Hora, Data e Clima Regional (Votuporanga) + News Feed — Clique para abrir Clima & News Feed",
            on_click=lambda e: switch_tab(3),
        )

        # Micro-indicador global Pomodoro no Header
        lbl_hdr_pomo = ft.Text("🍅 25:00", size=11, weight=ft.FontWeight.BOLD, color="#94A3B8", font_family="Consolas")
        pill_hdr_pomo = ft.Container(
            content=lbl_hdr_pomo,
            bgcolor="#111622",
            border=border_all(1, "#1E293B"),
            border_radius=16,
            padding=pad_sym(horizontal=10, vertical=4),
            ink=True,
            tooltip="Pomodoro Focus — Clique para abrir Foco & Mídia",
            on_click=lambda e: switch_tab(1),
        )

        # Micro-indicador global Spotify / YouTube Music no Header
        dot_hdr_media = ft.Container(width=8, height=8, border_radius=4, bgcolor="#475569")
        lbl_hdr_media = ft.Text(
            "Sem mídia ativa",
            size=11,
            weight=ft.FontWeight.W_600,
            color="#94A3B8",
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=135,
        )
        btn_hdr_media_pp = ft.IconButton(
            icon=icon_val("PLAY_ARROW"),
            icon_size=14,
            icon_color="#E2E8F0",
            tooltip="Play / Pause na mídia ativa",
            width=24,
            height=24,
            padding=0,
            on_click=lambda e: media_col.control("play_pause"),
        )
        pill_hdr_media = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Row([dot_hdr_media, lbl_hdr_media], spacing=6, tight=True),
                        on_click=lambda e: switch_tab(1),
                    ),
                    btn_hdr_media_pp,
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#111622",
            border=border_all(1, "#1E293B"),
            border_radius=16,
            padding=pad_sym(horizontal=10, vertical=2),
        )

        # Micro-indicador global Brilho / Sleep no Header
        lbl_hdr_power = ft.Text("☀️ 78%", size=11, weight=ft.FontWeight.W_600, color="#22C55E", font_family="Consolas")
        pill_hdr_power = ft.Container(
            content=lbl_hdr_power,
            bgcolor="#111622",
            border=border_all(1, "#1E293B"),
            border_radius=16,
            padding=pad_sym(horizontal=10, vertical=4),
            ink=True,
            tooltip="Brilho Dinâmico & Modo Sleep — Clique para abrir Estúdio & Energia",
            on_click=lambda e: switch_tab(5),
        )

        status_dot = ft.Container(
            width=9,
            height=9,
            border_radius=5,
            bgcolor="#F59E0B",
        )
        lbl_usb_status = ft.Text(
            "USB...",
            size=11,
            weight=ft.FontWeight.W_600,
            color="#E2E8F0",
            font_family="Consolas",
        )
        status_badge = ft.Container(
            content=ft.Row([status_dot, lbl_usb_status], spacing=6, tight=True),
            bgcolor="#111622",
            border=border_all(1, "#222B3D"),
            border_radius=20,
            padding=pad_sym(horizontal=11, vertical=5),
            ink=True,
            on_click=lambda e: switch_tab(7),
            tooltip="Status da Conexão Serial USB Assíncrona (115200 bps) — Clique para diagnóstico",
        )

        btn_hdr_qr = ft.IconButton(
            icon=icon_val("QR_CODE_2"),
            icon_size=18,
            icon_color="#94A3B8",
            tooltip="Abrir QR Code Controle pelo Celular (Wi-Fi)",
            on_click=lambda e: switch_tab(7),
        )
        btn_minimize = ft.IconButton(
            icon=icon_val("MINIMIZE"),
            icon_size=18,
            icon_color="#94A3B8",
            tooltip="Minimizar (continua em segundo plano)",
            on_click=lambda e: minimize_window(),
        )
        btn_quit = ft.IconButton(
            icon=icon_val("POWER_SETTINGS_NEW"),
            icon_size=18,
            icon_color="#EF4444",
            tooltip="Encerrar Agente",
            on_click=lambda e: quit_app(),
        )

        header_row = ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [hdr_brand_logo, lbl_title, chip_active_screen],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            pill_hdr_weather,
                            pill_hdr_pomo,
                            pill_hdr_media,
                            pill_hdr_power,
                            status_badge,
                            btn_hdr_qr,
                            btn_minimize,
                            btn_quit,
                        ],
                        spacing=6,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#0A0E17",
            border=border_all(1, "#182030"),
            border_radius=12,
            padding=pad_sym(horizontal=12, vertical=6),
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
        fin_sym_texts = []

        def make_fin_pill(symbol: str, init_price: str):
            sym_t = ft.Text(symbol, size=11, weight=ft.FontWeight.BOLD, color=state["hex_color"])
            fin_sym_texts.append(sym_t)
            p_txt = ft.Text(init_price, size=14, weight=ft.FontWeight.BOLD, color="#FFFFFF", font_family="Consolas")
            c_txt = ft.Text("0.00%", size=11, weight=ft.FontWeight.BOLD, color="#22C55E", font_family="Consolas")
            pill = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                sym_t,
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

        # Espelho compacto de cotações na Aba 2 (Mercado & Carteira) para ter dados nas duas abas sem conflito de pai
        m2_usd, lbl_m2_usd_p, lbl_m2_usd_c = make_fin_pill("💵 USD/BRL", "R$ --")
        m2_eur, lbl_m2_eur_p, lbl_m2_eur_c = make_fin_pill("💶 EUR/BRL", "R$ --")
        m2_btc, lbl_m2_btc_p, lbl_m2_btc_c = make_fin_pill("₿ BITCOIN", "$ --")
        m2_eth, lbl_m2_eth_p, lbl_m2_eth_c = make_fin_pill("Ξ ETHEREUM", "$ --")
        m2_sol, lbl_m2_sol_p, lbl_m2_sol_c = make_fin_pill("◎ SOLANA", "$ --")
        m2_ibov, lbl_m2_ibov_p, lbl_m2_ibov_c = make_fin_pill("📈 IBOV (B3)", "---k pts")

        def on_toggle_ticker(_e):
            state["ticker"] = not state["ticker"]
            new_lbl = (
                "📟 Letreiro Rodapé: ATIVO"
                if state["ticker"]
                else "📟 Letreiro Rodapé: OCULTO"
            )
            set_btn_text(btn_ticker_toggle, new_lbl)
            set_btn_text(btn_ticker_quick, new_lbl)
            persist_and_queue_ui()
            append_log(f"Letreiro infinito (Ticker Tape) {'ativado' if state['ticker'] else 'ocultado'} nas telas.")

        init_ticker_lbl = "📟 Letreiro Rodapé: ATIVO" if state["ticker"] else "📟 Letreiro Rodapé: OCULTO"
        btn_ticker_toggle = ft.OutlinedButton(init_ticker_lbl, on_click=on_toggle_ticker)
        btn_ticker_quick = ft.OutlinedButton(init_ticker_lbl, on_click=on_toggle_ticker)

        lbl_market_status = ft.Text(
            "🟢 Cripto: Ao Vivo (Coinbase / Binance • 3s) • 🟡 B3 & Câmbio: Fechado (Fim de semana)",
            size=11,
            color="#F59E0B",
            weight=ft.FontWeight.W_500,
        )
        lbl_market_time = ft.Text("Última cotação: --:--:--", size=11, color="#64748B", font_family="Consolas")

        def on_manual_mkt_refresh(_e):
            def run_refresh():
                set_btn_text(btn_refresh_mkt, "⏳ Atualizando...")
                btn_refresh_mkt.disabled = True
                try:
                    page.update()
                except Exception:
                    pass
                mkt_col.force_refresh()
                time.sleep(0.5)
                m = mkt_col.get_market_dict()
                append_log(f"Cotações atualizadas: BTC ${m.get('btc', 0):,.0f} | USD R$ {m.get('usd', 0):.2f}")
                set_btn_text(btn_refresh_mkt, "✅ Atualizado!")
                try:
                    page.update()
                except Exception:
                    pass
                time.sleep(1.2)
                set_btn_text(btn_refresh_mkt, "🔄 Atualizar Cotações")
                btn_refresh_mkt.disabled = False
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=run_refresh, daemon=True).start()

        btn_refresh_mkt = ft.OutlinedButton("🔄 Atualizar Cotações", on_click=on_manual_mkt_refresh)

        # Faixa compacta de mercado p/ Aba 0 (Dashboard Home)
        sec_market_quick = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("📊 RESUMO DE MERCADO & LETREIRO INFINITO", size=11, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            ft.Row(
                                [
                                    btn_ticker_quick,
                                    ft.OutlinedButton("💼 Carteira", on_click=lambda e: switch_tab(2)),
                                    ft.OutlinedButton("📰 Clima & News", on_click=lambda e: switch_tab(3)),
                                    ft.OutlinedButton("💻 Terminal CYD", on_click=lambda e: switch_tab(4)),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row([pill_usd, pill_eur, pill_btc, pill_eth, pill_sol, pill_ibov], spacing=8),
                ],
                spacing=6,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=12,
            padding=10,
        )

        # Card completo de mercado p/ Aba 2 (Mercado & Carteira)
        sec_market_live = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        "📊 MERCADO FINANCEIRO & CRIPTO AO VIVO (TELA 6)",
                                        size=13,
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
                                    ft.OutlinedButton("📺 Exibir Tela 6 na CYD", on_click=lambda e: on_select_screen(6)),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row([m2_usd, m2_eur, m2_btc, m2_eth, m2_sol, m2_ibov], spacing=8),
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=12,
        )

        # ---------------- 1. GERENCIADOR DE TELAS (12 MODOS 0..11) -----------
        screen_defs = [
            (0, "⚡ Tela 0: Resumo Gauges", "Gauges circulares de CPU & RAM + Disco/Rede", "SPEED"),
            (1, "🖥️ Tela 1: CPU + RAM", "Barras duplas + Gráficos CPU % e RAM % lado a lado", "TERMINAL"),
            (2, "📈 Tela 2: Gráfico Duplo", "Curvas sobrepostas de CPU % + RAM % em tela cheia", "SHOW_CHART"),
            (3, "🎮 Tela 3: GPU Focus", "Gauge Grande de GPU + VRAM + Watts/FPS", "VIDEOGAME_ASSET"),
            (4, "📊 Tela 4: 4x Gráficos", "Grid quádruplo: CPU %, RAM %, GPU % e TEMP °C", "GRID_VIEW"),
            (5, "🖼️ Tela 5: Wallpaper HUD", "Destaque para foto/GIF do SD + Dock CPU/RAM", "WALLPAPER"),
            (6, "📈 Tela 6: Mercado & Bolsa", "Dólar, Euro, IBOV, Top 5 Cripto + Curva Bitcoin 24h", "CURRENCY_BITCOIN"),
            (7, "💼 Tela 7: Meu Portfólio", "Patrimônio (R$), Lucro/Prejuízo Dinâmico + Top 3 Ativos", "ACCOUNT_BALANCE_WALLET"),
            (8, "🍅 Tela 8: Pomodoro Focus", "Cronômetro circular Foco 25m / Pausa 5m + Buzzer no fim", "TIMER"),
            (9, "🎵 Tela 9: Spotify & YT Music", "Capa 320x240 no SD + Overlay Translúcido Título/Artista", "ALBUM"),
            (10, "📰 Tela 10: Clima & News Feed", "Clima Regional (Votuporanga) + Manchetes Deslizantes (TFT_eSprite 15s)", "NEWSPAPER"),
            (11, "💻 Tela 11: Terminal Cyber Deck", "Console Verde Clássico c/ Scroll + ping, fetch, docker & Wi-Fi Scan", "TERMINAL"),
            (12, "📡 Tela 12: Radar Wi-Fi RF", "ESP32-WROOM-32U Antena Externa • Canais 2.4 GHz & Top Redes Próximas", "RADAR"),
            (13, "🌐 Tela 13: Rede & Roteador", "Gateway, Ping/Jitter, LAN ARP & Speedtest Fibra 700 Mbps", "ROUTER"),
        ]
        screen_cards = []

        def on_select_screen(scr_idx: int):
            state["screen"] = int(scr_idx)
            lbl_hdr_screen.value = f"📺 TELA {state['screen']} • {SCREEN_SHORT_NAMES.get(state['screen'], '')}"
            refresh_screen_cards()
            persist_and_queue_ui()
            append_log(f"Tela da CYD alterada para Tela {scr_idx} ({SCREEN_SHORT_NAMES.get(scr_idx, '')})")

        def refresh_screen_cards():
            for idx, cont, title_t, badge_t in screen_cards:
                active = (idx == state["screen"])
                cont.bgcolor = "#162032" if active else "#0F141F"
                cont.border = border_all(2 if active else 1, state["hex_color"] if active else "#1E2738")
                title_t.color = state["hex_color"] if active else "#E2E8F0"
                badge_t.bgcolor = state["hex_color"] if active else "#1A2234"
                badge_t.content.color = "#05070A" if active else "#94A3B8"
            safe_update(screens_grid, chip_active_screen)

        for idx, title, desc, _ic in screen_defs:
            active = (idx == state["screen"])
            title_t = ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=state["hex_color"] if active else "#E2E8F0")
            desc_t = ft.Text(desc, size=10, color="#8B95A8", max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
            badge_t = ft.Container(
                content=ft.Text(f"T{idx}", size=10, weight=ft.FontWeight.BOLD, color="#05070A" if active else "#94A3B8"),
                bgcolor=state["hex_color"] if active else "#1A2234",
                border_radius=6,
                padding=pad_sym(horizontal=7, vertical=2),
            )
            card_cont = ft.Container(
                content=ft.Column(
                    [
                        ft.Row([title_t, badge_t], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        desc_t,
                    ],
                    spacing=3,
                ),
                bgcolor="#162032" if active else "#0F141F",
                border=border_all(2 if active else 1, state["hex_color"] if active else "#1E2738"),
                border_radius=10,
                padding=9,
                ink=True,
                on_click=lambda e, i=idx: on_select_screen(i),
                expand=True,
            )
            screen_cards.append((idx, card_cont, title_t, badge_t))

        screens_grid = ft.Column(
            [
                ft.Text("TELEMETRIA DE HARDWARE (TELAS 0 A 5)", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                ft.Row([screen_cards[0][1], screen_cards[1][1], screen_cards[2][1]], spacing=8),
                ft.Row([screen_cards[3][1], screen_cards[4][1], screen_cards[5][1]], spacing=8),
                ft.Divider(height=4, color="#151C28"),
                ft.Text("CYD CYBER DECK v4.5 — FINANÇAS, FOCO, MÍDIA, NEWS, TERMINAL, RADAR RF & REDE (TELAS 6 A 13)", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                ft.Row([screen_cards[6][1], screen_cards[7][1], screen_cards[8][1]], spacing=8),
                ft.Row([screen_cards[9][1], screen_cards[10][1], screen_cards[11][1]], spacing=8),
                ft.Row([screen_cards[12][1], screen_cards[13][1]], spacing=8),
            ],
            spacing=7,
        )

        sec_screens = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🖥️ SELECIONE A TELA ATIVA NA CYD (12 MODOS CYBER DECK EM TEMPO REAL)", size=12, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            ft.Text("Troca instantânea via USB (< 50ms)", size=11, color="#64748B"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    screens_grid,
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=12,
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
            lbl_hdr_screen.color = h
            chip_active_screen.border = border_all(1, h)
            for sym_t in fin_sym_texts:
                sym_t.color = h
            try:
                sec_mobile_remote.border = border_all(1, h)
                lbl_mobile_title.color = h
                prog_upload.color = h
                prog_media_upload.color = h
                test_bz_switch.active_color = h
                sw_sleep.active_color = h
                sw_night.active_color = h
                sw_pomo_buzzer.active_color = h
                sw_media_autosync.active_color = h
                refresh_portfolio_ui()
                refresh_tabs_ui()
            except Exception:
                pass
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

        def start_file_transfer(filepath: str = None, filename: str = None, raw_bytes: bytes = None):
            if not filepath and not raw_bytes:
                return
            try:
                if raw_bytes is not None and filename:
                    target_name, data = prepare_image_bytes_for_cyd(filename, raw_bytes)
                else:
                    target_name, data = prepare_image_for_cyd(filepath)
            except Exception as ex:
                append_log(f"Erro ao preparar imagem: {ex}")
                return

            append_log(f"Iniciando envio de '{target_name}' ({len(data)/1024:.1f} KB) para o SD da CYD...")

            def worker():
                upload_state["active"] = True
                upload_state["pct"] = 0.0
                upload_state["status"] = f"Conectando com SD para gravar '{target_name}'..."
                upload_state["target"] = target_name
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
                    upload_state["active"] = False
                    upload_state["status"] = f"Falha ({resp})"
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
                        upload_state["active"] = False
                        upload_state["status"] = f"Erro no bloco {seq} ({resp})"
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
                    upload_state["pct"] = pct
                    upload_state["status"] = f"Gravando '{target_name}' no SD ({int(pct * 100)}%)..."
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
                    upload_state["active"] = False
                    upload_state["status"] = f"Falha ao fechar arquivo ({resp})"
                    prog_upload.visible = False
                    lbl_upload_status.value = f"❌ Falha ao finalizar arquivo ({resp})."
                    append_log(f"Upload: Falha ao fechar arquivo no SD ({resp}).")
                    try:
                        page.update()
                    except Exception:
                        pass
                    return

                # 4) Sucesso total!
                upload_state["active"] = False
                upload_state["pct"] = 1.0
                upload_state["status"] = f"'{target_name}' gravado com sucesso!"
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
                    init_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "imagens-referencia")
                    p = ""
                    # No Linux (Zorin OS / GNOME / KDE), prioriza diálogo GTK/Qt nativo (zenity / kdialog)
                    if IS_LINUX:
                        if shutil.which("zenity"):
                            cmd = [
                                "zenity", "--file-selection",
                                "--title=Selecione uma imagem para o Cartão SD da CYD (JPG, PNG, BMP, GIF)",
                                "--file-filter=Imagens (JPG, PNG, BMP, GIF) | *.jpg *.jpeg *.png *.bmp *.gif *.JPG *.JPEG *.PNG *.BMP *.GIF",
                            ]
                            if os.path.isdir(init_dir):
                                cmd.append(f"--filename={init_dir}/")
                            res = subprocess.run(cmd, capture_output=True, text=True)
                            if res.returncode == 0 and res.stdout.strip():
                                p = res.stdout.strip()
                            else:
                                return
                        elif shutil.which("kdialog"):
                            res = subprocess.run(
                                [
                                    "kdialog", "--getopenfilename",
                                    init_dir if os.path.isdir(init_dir) else os.path.expanduser("~"),
                                    "*.jpg *.jpeg *.png *.bmp *.gif|Imagens (JPG, PNG, BMP, GIF)",
                                ],
                                capture_output=True, text=True,
                            )
                            if res.returncode == 0 and res.stdout.strip():
                                p = res.stdout.strip()
                            else:
                                return
                    if not p:
                        import tkinter as tk
                        from tkinter import filedialog
                        r = tk.Tk()
                        r.withdraw()
                        r.attributes("-topmost", True)
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

        # ---------------- 5. SISTEMA DE ALERTAS FÍSICOS (BUZZER E LED RGB) ---
        test_bz_switch = ft.Switch(label="Buzzer", value=True, active_color=state["hex_color"])
        test_p_dropdown = make_compat_dropdown(
            label="Padrão",
            value="3",
            options=[
                ft.dropdown.Option("1", "P1: Info (1 Bipe)"),
                ft.dropdown.Option("2", "P2: Aviso (2 Bipes)"),
                ft.dropdown.Option("3", "P3: Crítico (3 Bipes)"),
            ],
            width=185,
        )

        def on_click_test_alert(_e):
            bz = bool(test_bz_switch.value)
            p_val = int(test_p_dropdown.value or 3)
            led_col = "0xF800" if p_val == 3 else ("0xFD20" if p_val == 2 else "0x07E0")
            ui_event_queue.put({"alrt": {"bz": bz, "led": led_col, "p": p_val}})
            append_log(f"🔔 Teste físico enviado à CYD: Buzzer={'ON' if bz else 'OFF'}, LED={led_col}, Padrão={p_val}")

        btn_test_alert = _Button(
            "🔔 Testar Alerta na CYD",
            icon=icon_val("NOTIFICATIONS_ACTIVE"),
            on_click=on_click_test_alert,
        )

        # Criador de novos gatilhos: [Ativo/Hardware] [Condição: > ou <] [Valor]
        dd_new_rule_src = make_compat_dropdown(
            label="Ativo / Hardware",
            value="btc",
            options=[
                ft.dropdown.Option("cput", "CPU Temp (°C)"),
                ft.dropdown.Option("gput", "GPU Temp (°C)"),
                ft.dropdown.Option("cpu", "CPU Uso (%)"),
                ft.dropdown.Option("ram", "RAM Uso (%)"),
                ft.dropdown.Option("gpu", "GPU Uso (%)"),
                ft.dropdown.Option("btc", "Bitcoin (USD)"),
                ft.dropdown.Option("eth", "Ethereum (USD)"),
                ft.dropdown.Option("sol", "Solana (USD)"),
                ft.dropdown.Option("usd", "Dólar (BRL)"),
                ft.dropdown.Option("ibov", "IBOVESPA (pts)"),
            ],
            width=165,
        )
        dd_new_rule_op = make_compat_dropdown(
            label="Cond.",
            value=">",
            options=[
                ft.dropdown.Option(">", "> Maior"),
                ft.dropdown.Option("<", "< Menor"),
            ],
            width=105,
        )
        txt_new_rule_val = ft.TextField(
            label="Valor Alvo",
            value="100000",
            width=115,
            height=46,
            text_size=12,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        sw_new_rule_bz = ft.Switch(label="Buzzer", value=True, active_color="#22C55E")
        dd_new_rule_p = make_compat_dropdown(
            label="Alerta",
            value="2",
            options=[
                ft.dropdown.Option("1", "P1 Verde"),
                ft.dropdown.Option("2", "P2 Laranja"),
                ft.dropdown.Option("3", "P3 Vermelho"),
            ],
            width=125,
        )

        alert_list_col = ft.Column(spacing=6)

        def rebuild_alert_rows():
            alert_list_col.controls.clear()
            for idx_r, r_item in enumerate(state["alert_rules"]):
                def make_toggle_handler(rule_ref):
                    def _handler(e):
                        rule_ref["enabled"] = bool(e.control.value)
                        persist_and_queue_ui()
                        append_log(f"Gatilho '{rule_ref['name']}' {'ATIVADO' if rule_ref['enabled'] else 'DESATIVADO'}")
                    return _handler

                def make_del_handler(rule_idx):
                    def _del(_e):
                        if 0 <= rule_idx < len(state["alert_rules"]):
                            removed = state["alert_rules"].pop(rule_idx)
                            rebuild_alert_rows()
                            persist_and_queue_ui()
                            append_log(f"Gatilho '{removed.get('name', '')}' removido.")
                            try:
                                page.update()
                            except Exception:
                                pass
                    return _del

                sw = ft.Switch(
                    value=r_item.get("enabled", True),
                    active_color="#22C55E",
                    on_change=make_toggle_handler(r_item),
                )
                src_k = str(r_item.get("source", "")).lower()
                cond_badge = f"{src_k.upper()} {r_item.get('op', '>')} {r_item.get('val', 0)}"
                if src_k in ("cput", "gput"):
                    cond_badge += "°C"
                elif src_k in ("cpu", "ram", "gpu"):
                    cond_badge += "%"
                elif src_k in ("btc", "eth", "sol"):
                    cond_badge += " USD"
                elif src_k in ("usd", "eur"):
                    cond_badge += " BRL"

                btn_del_r = ft.IconButton(
                    icon=icon_val("DELETE_OUTLINE"),
                    icon_size=16,
                    icon_color="#EF4444",
                    tooltip="Excluir gatilho",
                    on_click=make_del_handler(idx_r),
                )

                row_item = ft.Container(
                    content=ft.Row(
                        [
                            ft.Row(
                                [
                                    sw,
                                    ft.Text(r_item.get("name", ""), size=12, weight=ft.FontWeight.W_600, color="#E2E8F0"),
                                ],
                                spacing=10,
                            ),
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Text(cond_badge, size=11, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                                        bgcolor="#07090E",
                                        padding=pad_sym(horizontal=8, vertical=4),
                                        border_radius=6,
                                    ),
                                    ft.Text(
                                        f"🔊 {'Buzzer' if r_item.get('bz') else 'Mudo'} • 💡 LED {r_item.get('led', '0xF800')} • P{r_item.get('p', 1)}",
                                        size=11,
                                        color="#64748B",
                                    ),
                                    btn_del_r,
                                ],
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor="#07090E",
                    border=border_all(1, "#151C28"),
                    border_radius=8,
                    padding=pad_sym(horizontal=8, vertical=4),
                )
                alert_list_col.controls.append(row_item)

        def on_add_alert_rule(_e):
            try:
                src = str(dd_new_rule_src.value or "btc").strip().lower()
                op = str(dd_new_rule_op.value or ">").strip()
                val = float(str(txt_new_rule_val.value or "0").replace(",", "."))
                p_val = int(dd_new_rule_p.value or 2)
                led_map = {1: "0x07E0", 2: "0xFD20", 3: "0xF800"}
                new_r = {
                    "id": f"custom_{src}_{int(time.time())}",
                    "name": f"Alerta {src.upper()} {op} {val:g}",
                    "source": src,
                    "op": op,
                    "val": val,
                    "bz": bool(sw_new_rule_bz.value),
                    "led": led_map.get(p_val, "0xFD20"),
                    "p": p_val,
                    "enabled": True,
                    "cooldown_s": 45.0,
                }
                state["alert_rules"].append(new_r)
                rebuild_alert_rows()
                persist_and_queue_ui()
                append_log(f"🔔 Novo gatilho criado: {new_r['name']}")
                page.update()
            except Exception as ex:
                append_log(f"⚠️ Valor inválido ao criar gatilho: {ex}")

        rebuild_alert_rows()

        sec_alerts = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🔔 5. SISTEMA DE ALERTAS FÍSICOS (BUZZER & LED RGB)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            ft.Text("Módulo 1 • Feedback Físico Não-Bloqueante", size=11, color="#64748B"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text("Configure gatilhos de Hardware ou Ativos para acionar o Buzzer e o LED RGB traseiro da CYD:", size=11, color="#8B95A8"),
                    ft.Row(
                        [
                            dd_new_rule_src,
                            dd_new_rule_op,
                            txt_new_rule_val,
                            sw_new_rule_bz,
                            dd_new_rule_p,
                            _Button("➕ Criar Gatilho", on_click=on_add_alert_rule),
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alert_list_col,
                    ft.Divider(height=4, color="#151C28"),
                    ft.Row(
                        [
                            test_bz_switch,
                            test_p_dropdown,
                            btn_test_alert,
                        ],
                        spacing=12,
                        alignment=ft.MainAxisAlignment.START,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 6. CONTROLE DE BRILHO DINÂMICO & MODO SLEEP --------
        lbl_power_status = ft.Text("Status: Ativo (Ocioso: 0s)", size=11, color="#22C55E", font_family="Consolas")

        def on_toggle_sleep(e):
            state["sleep_enabled"] = bool(e.control.value)
            persist_and_queue_ui()
            append_log(f"Modo Sleep por Inatividade {'ATIVADO' if state['sleep_enabled'] else 'DESATIVADO'}")

        def on_change_sleep_timeout(_e):
            state["sleep_timeout_min"] = int(dd_sleep_timeout.value or 15)
            persist_and_queue_ui()
            append_log(f"Tempo de inatividade para Sleep ajustado para {state['sleep_timeout_min']} minutos")

        def on_toggle_night(e):
            state["night_mode_enabled"] = bool(e.control.value)
            persist_and_queue_ui()
            append_log(f"Modo Noturno Inteligente {'ATIVADO' if state['night_mode_enabled'] else 'DESATIVADO'}")

        def on_change_night_brt(e):
            val = int(e.control.value)
            state["night_brightness"] = val
            lbl_night_brt_val.value = f"{val} ({int(val * 100 / 255)}%)"
            persist_and_queue_ui()
            try:
                page.update()
            except Exception:
                pass

        sw_sleep = ft.Switch(
            label="Modo Sleep (Desliga display se PC ocioso)",
            value=state.get("sleep_enabled", True),
            active_color=state["hex_color"],
            on_change=on_toggle_sleep,
        )

        dd_sleep_timeout = make_compat_dropdown(
            label="Inatividade",
            value=str(state.get("sleep_timeout_min", 15)),
            options=[
                ft.dropdown.Option("5", "5 minutos"),
                ft.dropdown.Option("10", "10 minutos"),
                ft.dropdown.Option("15", "15 minutos (Padrão)"),
                ft.dropdown.Option("30", "30 minutos"),
                ft.dropdown.Option("60", "1 hora"),
            ],
            width=185,
            on_change=on_change_sleep_timeout,
        )

        sw_night = ft.Switch(
            label="Modo Noturno (Atenua entre 22h e 06h)",
            value=state.get("night_mode_enabled", True),
            active_color=state["hex_color"],
            on_change=on_toggle_night,
        )

        lbl_night_brt_val = ft.Text(
            f"{state.get('night_brightness', 40)} ({int(state.get('night_brightness', 40) * 100 / 255)}%)",
            size=11,
            color="#E2E8F0",
            font_family="Consolas",
        )

        slider_night_brt = ft.Slider(
            min=10,
            max=120,
            divisions=11,
            value=state.get("night_brightness", 40),
            active_color="#818CF8",
            on_change=on_change_night_brt,
            expand=True,
        )

        sec_sleep = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🌙 6. CONTROLE DE BRILHO DINÂMICO & MODO SLEEP", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            lbl_power_status,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text("Economia de energia (PWM) com fade suave e conforto visual noturno automático:", size=11, color="#8B95A8"),
                    ft.Row(
                        [
                            sw_sleep,
                            dd_sleep_timeout,
                        ],
                        spacing=16,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=4, color="#151C28"),
                    ft.Row(
                        [
                            sw_night,
                            ft.Row(
                                [
                                    ft.Text("Brilho Noturno:", size=11, color="#94A3B8"),
                                    slider_night_brt,
                                    lbl_night_brt_val,
                                ],
                                spacing=8,
                                expand=True,
                            ),
                        ],
                        spacing=16,
                    ),
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 7. GESTÃO DE PORTFÓLIO DE INVESTIMENTOS (TELA 7) ---
        lbl_portf_tot = ft.Text("R$ 0,00", size=20, weight=ft.FontWeight.BOLD, color="#F8FAFC", font_family="Consolas")
        lbl_portf_pnl = ft.Text("+R$ 0,00 (+0.00%)", size=13, weight=ft.FontWeight.BOLD, color="#22C55E", font_family="Consolas")
        lbl_portf_day = ft.Text("Hoje (24h): +0.00%", size=11, color="#94A3B8", font_family="Consolas")

        txt_pf_ticker = ft.TextField(
            label="Ticker (ex: BTC, PETR4)",
            value="",
            width=155,
            height=46,
            text_size=12,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        txt_pf_qty = ft.TextField(
            label="Quantidade",
            value="",
            width=125,
            height=46,
            text_size=12,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        txt_pf_avg = ft.TextField(
            label="Preço Médio",
            value="",
            width=135,
            height=46,
            text_size=12,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        dd_pf_cur = make_compat_dropdown(
            label="Moeda PM",
            value="BRL",
            options=[
                ft.dropdown.Option("BRL", "R$ (BRL)"),
                ft.dropdown.Option("USD", "US$ (USD)"),
            ],
            width=120,
        )

        def on_change_pnl_mode(_e):
            state["portfolio_pnl_mode"] = str(dd_pf_pnl_mode.value or "hist")
            refresh_portfolio_ui()
            persist_and_queue_ui()
            append_log(f"Modo de PnL na Tela 7 alterado para: {'Diário (24h)' if state['portfolio_pnl_mode'] == 'day' else 'Histórico (vs Preço Médio)'}")

        dd_pf_pnl_mode = make_compat_dropdown(
            label="PnL na CYD",
            value=state.get("portfolio_pnl_mode", "hist"),
            options=[
                ft.dropdown.Option("hist", "Histórico (PM)"),
                ft.dropdown.Option("day", "Diário (24h)"),
            ],
            width=155,
            on_change=on_change_pnl_mode,
        )

        portfolio_rows_col = ft.Column(spacing=6)

        def refresh_portfolio_ui():
            pf_summary, pf_rows = mkt_col.compute_portfolio(state["portfolio"], state["portfolio_pnl_mode"])
            tot_v = pf_summary["tot"]
            pnl_v = pf_summary["pnl_val"]
            pnl_p = pf_summary["pnl_pct"]
            day_p = pf_summary["day_pct"]

            lbl_portf_tot.value = f"R$ {tot_v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            sign = "+" if pnl_v >= 0 else "-"
            abs_pnl_str = f"R$ {abs(pnl_v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            lbl_portf_pnl.value = f"{sign}{abs_pnl_str} ({'+' if pnl_p >= 0 else ''}{pnl_p:.2f}%)"
            lbl_portf_pnl.color = "#22C55E" if pnl_v >= 0 else "#EF4444"
            lbl_portf_day.value = f"Variação 24h: {'+' if day_p >= 0 else ''}{day_p:.2f}%  •  Top 3: {', '.join(pf_summary['top3']) or 'Nenhum'}"
            lbl_portf_day.color = "#22C55E" if day_p >= 0 else "#F59E0B"

            pf_sig = (
                state["hex_color"],
                state["portfolio_pnl_mode"],
                tuple((r["ticker"], r["qty"], r["avg_price"], round(r["pos_val_brl"], 1)) for r in pf_rows),
            )
            if pf_sig == state.get("_last_pf_sig"):
                return
            state["_last_pf_sig"] = pf_sig

            portfolio_rows_col.controls.clear()
            if not pf_rows:
                portfolio_rows_col.controls.append(
                    ft.Text("Nenhum ativo cadastrado. Adicione acima (ex: BTC, ETH, SOL, PETR4, VALE3, NVDA).", size=11, color="#64748B")
                )
                return

            for row_d in pf_rows:
                sym = row_d["ticker"]

                def make_edit_pf(item_d):
                    def _edit(_e):
                        txt_pf_ticker.value = item_d["ticker"]
                        txt_pf_qty.value = f"{item_d['qty']:g}"
                        txt_pf_avg.value = f"{item_d['avg_price']:g}"
                        dd_pf_cur.value = item_d["currency"]
                        try:
                            page.update()
                        except Exception:
                            pass
                    return _edit

                def make_del_pf(sym_del):
                    def _del(_e):
                        state["portfolio"] = [p for p in state["portfolio"] if str(p.get("ticker", "")).upper() != sym_del]
                        refresh_portfolio_ui()
                        persist_and_queue_ui()
                        append_log(f"💼 Ativo '{sym_del}' removido do portfólio.")
                        try:
                            page.update()
                        except Exception:
                            pass
                    return _del

                p_up = row_d["pnl_val"] >= 0
                pnl_col = "#22C55E" if p_up else "#EF4444"
                cur_sym_txt = "US$" if row_d["currency"] == "USD" else "R$"
                pos_str = f"R$ {row_d['pos_val_brl']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                pnl_row_str = f"{'+' if p_up else '-'}R$ {abs(row_d['pnl_val']):,.2f} ({'+' if row_d['pnl_pct'] >= 0 else ''}{row_d['pnl_pct']:.2f}%)"

                portfolio_rows_col.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Container(
                                            content=ft.Text(sym, size=12, weight=ft.FontWeight.BOLD, color="#05070A"),
                                            bgcolor=state["hex_color"],
                                            padding=pad_sym(horizontal=8, vertical=3),
                                            border_radius=6,
                                        ),
                                        ft.Text(
                                            f"Qtd: {row_d['qty']:g}  •  PM: {cur_sym_txt} {row_d['avg_price']:,.2f}  •  Peso: {row_d['weight_pct']:.1f}%",
                                            size=11,
                                            color="#94A3B8",
                                        ),
                                    ],
                                    spacing=10,
                                ),
                                ft.Row(
                                    [
                                        ft.Text(pos_str, size=12, weight=ft.FontWeight.BOLD, color="#F8FAFC", font_family="Consolas"),
                                        ft.Container(
                                            content=ft.Text(pnl_row_str, size=11, weight=ft.FontWeight.BOLD, color=pnl_col, font_family="Consolas"),
                                            bgcolor="#0B1320",
                                            padding=pad_sym(horizontal=8, vertical=4),
                                            border_radius=6,
                                        ),
                                        ft.IconButton(
                                            icon=icon_val("EDIT"),
                                            icon_size=16,
                                            icon_color="#38BDF8",
                                            tooltip="Editar ativo",
                                            on_click=make_edit_pf(row_d),
                                        ),
                                        ft.IconButton(
                                            icon=icon_val("DELETE_OUTLINE"),
                                            icon_size=16,
                                            icon_color="#EF4444",
                                            tooltip="Remover ativo",
                                            on_click=make_del_pf(sym),
                                        ),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        bgcolor="#07090E",
                        border=border_all(1, "#151C28"),
                        border_radius=8,
                        padding=pad_sym(horizontal=10, vertical=4),
                    )
                )

        def on_save_portfolio_asset(_e):
            sym = (txt_pf_ticker.value or "").strip().upper()
            if not sym:
                append_log("⚠️ Informe o Ticker do ativo (ex: BTC, PETR4, ETH, VALE3).")
                return
            try:
                qty = float(str(txt_pf_qty.value or "0").replace(",", "."))
                avg_p = float(str(txt_pf_avg.value or "0").replace(",", "."))
            except ValueError:
                append_log("⚠️ Quantidade ou Preço Médio inválido. Use números (ex: 0.05 ou 36.50).")
                return
            if qty <= 0 or avg_p < 0:
                append_log("⚠️ A quantidade deve ser maior que zero.")
                return

            cur_v = str(dd_pf_cur.value or "BRL").upper()
            updated_existing = False
            for existing in state["portfolio"]:
                if str(existing.get("ticker", "")).upper() == sym:
                    existing["qty"] = qty
                    existing["avg_price"] = avg_p
                    existing["currency"] = cur_v
                    updated_existing = True
                    break
            if not updated_existing:
                state["portfolio"].append({
                    "ticker": sym,
                    "qty": qty,
                    "avg_price": avg_p,
                    "currency": cur_v,
                })

            txt_pf_ticker.value = ""
            txt_pf_qty.value = ""
            txt_pf_avg.value = ""
            mkt_col.set_custom_tickers([p.get("ticker", "") for p in state["portfolio"]])
            mkt_col.force_refresh()
            refresh_portfolio_ui()
            persist_and_queue_ui()
            append_log(f"💼 Ativo '{sym}' {'atualizado' if updated_existing else 'adicionado'} no Portfólio (Qtd: {qty:g}, PM: {cur_v} {avg_p:g}).")
            try:
                page.update()
            except Exception:
                pass

        refresh_portfolio_ui()

        sec_portfolio = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text("💼 7. GESTÃO DE PORTFÓLIO DE INVESTIMENTOS (TELA 7)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                                    ft.Text("Patrimônio pessoal em tempo real com suporte a Cripto, Câmbio, B3 (PETR4, VALE3) e EUA:", size=11, color="#8B95A8"),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    dd_pf_pnl_mode,
                                    ft.OutlinedButton("📺 Abrir Tela 7 na CYD", on_click=lambda e: on_select_screen(7)),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("PATRIMÔNIO CONSOLIDADO", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                                        lbl_portf_tot,
                                    ],
                                    spacing=2,
                                ),
                                ft.Column(
                                    [
                                        ft.Text("RESULTADO (LUCRO / PREJUÍZO)", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                                        lbl_portf_pnl,
                                        lbl_portf_day,
                                    ],
                                    spacing=2,
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        bgcolor="#07090E",
                        border=border_all(1, "#1E293B"),
                        border_radius=10,
                        padding=12,
                    ),
                    ft.Row(
                        [
                            txt_pf_ticker,
                            txt_pf_qty,
                            txt_pf_avg,
                            dd_pf_cur,
                            _Button("💾 Salvar Ativo", icon=icon_val("SAVE"), on_click=on_save_portfolio_asset),
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    portfolio_rows_col,
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 8. MÓDULO 3: PRODUTIVIDADE & MULTIMÍDIA (TELAS 8 E 9)
        prog_media_upload = ft.ProgressBar(value=0.0, visible=False, color=state["hex_color"], bgcolor="#1A2130", height=6)
        lbl_media_sync_status = ft.Text(
            "Pronto para sincronizar capas 320x240 automaticamente no Cartão SD.",
            size=11,
            color="#94A3B8",
        )

        def start_media_cover_transfer(cid: str, cyd_bytes: bytes, manual: bool = False):
            if not cyd_bytes or upload_state["active"]:
                return
            upload_state["active"] = True

            def _cov_worker():
                target_name = "_media_cov.jpg"
                upload_state["pct"] = 0.0
                upload_state["status"] = "Sincronizando capa do álbum no SD..."
                upload_state["target"] = target_name
                prog_media_upload.visible = True
                prog_media_upload.value = 0.0
                lbl_media_sync_status.value = f"⏳ Conectando ao SD p/ gravar capa ({len(cyd_bytes)/1024:.1f} KB)..."
                lbl_media_sync_status.color = "#38BDF8"
                try:
                    page.update()
                except Exception:
                    pass

                def _wait_ack(expected_prefix: str, timeout: float = 4.0):
                    t0 = time.time()
                    while time.time() - t0 < timeout:
                        if ack_event.wait(timeout=0.06):
                            ack_event.clear()
                            val = last_ack.get("val") or ""
                            if val.startswith("ERR_NO_SD"):
                                return False, "ERR_NO_SD"
                            if val.startswith("ERR_OPEN"):
                                return False, "ERR_OPEN"
                            if val.startswith(expected_prefix):
                                return True, val
                    return False, "TIMEOUT"

                ack_event.clear()
                transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "w"})
                ok, resp = _wait_ack("ACK_START", timeout=4.0)
                if not ok:
                    upload_state["active"] = False
                    prog_media_upload.visible = False
                    if resp == "ERR_NO_SD":
                        lbl_media_sync_status.value = "⚠️ Cartão SD ausente na CYD — exibindo player vetorial sem capa."
                        lbl_media_sync_status.color = "#F59E0B"
                        if not state["sd_missing_warned"] or manual:
                            state["sd_missing_warned"] = True
                            append_log("🎵 Player de Mídia: Cartão SD não detectado na CYD (usando visualizador estúdio).")
                        # Marca cid para não ficar tentando reenviar em loop sem SD inserido
                        state["synced_cover_id"] = cid
                    else:
                        lbl_media_sync_status.value = f"⚠️ Aguardando conexão estável da CYD ({resp})."
                        lbl_media_sync_status.color = "#F59E0B"
                    try:
                        page.update()
                    except Exception:
                        pass
                    return

                chunk_size = 512
                total = len(cyd_bytes)
                seq = 0
                for i in range(0, total, chunk_size):
                    chunk = cyd_bytes[i:i + chunk_size]
                    b64 = base64.b64encode(chunk).decode("ascii")
                    ack_event.clear()
                    transfer_queue.put({
                        "file_name": f"/{target_name}",
                        "file_mode": "a",
                        "seq": seq,
                        "file_data": b64,
                    })
                    ok, resp = _wait_ack("ACK_CHUNK", timeout=3.2)
                    if not ok:
                        upload_state["active"] = False
                        prog_media_upload.visible = False
                        lbl_media_sync_status.value = f"❌ Falha ao transmitir bloco {seq} da capa ({resp})."
                        lbl_media_sync_status.color = "#EF4444"
                        try:
                            page.update()
                        except Exception:
                            pass
                        return
                    seq += 1
                    pct = min((i + len(chunk)) / float(total), 1.0)
                    upload_state["pct"] = pct
                    prog_media_upload.value = pct
                    lbl_media_sync_status.value = f"⏳ Gravando capa no SD da CYD ({int(pct * 100)}%)..."

                ack_event.clear()
                transfer_queue.put({
                    "file_name": f"/{target_name}",
                    "file_mode": "eof",
                    "is_cover": True,
                    "cid": cid,
                })
                ok, resp = _wait_ack("ACK_EOF", timeout=4.5)
                upload_state["active"] = False
                prog_media_upload.visible = False

                if ok:
                    state["synced_cover_id"] = cid
                    state["sd_missing_warned"] = False
                    lbl_media_sync_status.value = f"✅ Capa 320x240 sincronizada no Cartão SD (ID #{cid})"
                    lbl_media_sync_status.color = "#22C55E"
                    ui_event_queue.put({"media": media_col.get_cyd_payload(cid)})
                    append_log(f"🎵 Capa do álbum sincronizada no SD da CYD (_media_cov.jpg • {len(cyd_bytes)/1024:.1f} KB)")
                else:
                    lbl_media_sync_status.value = f"⚠️ Falha ao finalizar capa no SD ({resp})."
                    lbl_media_sync_status.color = "#F59E0B"
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=_cov_worker, daemon=True).start()

        # ---- Controles Pomodoro (Coluna Esquerda da Aba 1) ----
        lbl_pomo_clock = ft.Text("25:00", size=46, weight=ft.FontWeight.BOLD, color="#FFFFFF", font_family="Consolas")
        lbl_pomo_phase_badge = ft.Text("🔥 FOCO PROFUNDO (TRABALHO)", size=12, weight=ft.FontWeight.BOLD, color="#F97316")
        bar_pomo_prog = ft.ProgressBar(value=0.0, color="#F97316", bgcolor="#1A2130", height=8, border_radius=4)
        lbl_pomo_cycles = ft.Text("Ciclos hoje: #0  •  ⚪ ⚪ ⚪ ⚪  •  Total focado: 0 min", size=11, color="#94A3B8", font_family="Consolas")

        def on_pomo_toggle(_e=None):
            running = pomo_eng.toggle()
            refresh_focus_media_ui()
            ui_event_queue.put({"pomo": pomo_eng.get_payload()})
            append_log(f"🍅 Pomodoro {'INICIADO' if running else 'PAUSADO'} ({pomo_eng.state})")
            try:
                page.update()
            except Exception:
                pass

        def on_pomo_reset(_e=None):
            pomo_eng.reset()
            refresh_focus_media_ui()
            ui_event_queue.put({"pomo": pomo_eng.get_payload()})
            append_log("🍅 Timer Pomodoro resetado.")
            try:
                page.update()
            except Exception:
                pass

        def on_pomo_skip(_e=None):
            nxt = pomo_eng.skip()
            refresh_focus_media_ui()
            ui_event_queue.put({"pomo": pomo_eng.get_payload()})
            append_log(f"🍅 Fase Pomodoro avançada manualmente para {nxt}.")
            try:
                page.update()
            except Exception:
                pass

        def on_pomo_select_phase(ph: str):
            pomo_eng.set_phase(ph)
            refresh_focus_media_ui()
            ui_event_queue.put({"pomo": pomo_eng.get_payload()})
            append_log(f"🍅 Modo Pomodoro selecionado: {ph}")
            try:
                page.update()
            except Exception:
                pass

        btn_pomo_start = _Button("▶ Iniciar Foco", icon=icon_val("PLAY_ARROW"), on_click=on_pomo_toggle)
        btn_pomo_reset = ft.OutlinedButton("↺ Resetar", on_click=on_pomo_reset)
        btn_pomo_skip = ft.OutlinedButton("⏭ Pular", on_click=on_pomo_skip)

        txt_pomo_w = ft.TextField(label="Foco (m)", value=str(state["pomo_work_min"]), width=82, height=44, text_size=12, content_padding=pad_sym(8, 6))
        txt_pomo_b = ft.TextField(label="Curta (m)", value=str(state["pomo_break_min"]), width=82, height=44, text_size=12, content_padding=pad_sym(8, 6))
        txt_pomo_l = ft.TextField(label="Longa (m)", value=str(state["pomo_long_min"]), width=82, height=44, text_size=12, content_padding=pad_sym(8, 6))

        def on_save_pomo_times(_e):
            try:
                wm = max(1, min(120, int(txt_pomo_w.value or 25)))
                bm = max(1, min(60, int(txt_pomo_b.value or 5)))
                lm = max(1, min(90, int(txt_pomo_l.value or 15)))
                state["pomo_work_min"] = wm
                state["pomo_break_min"] = bm
                state["pomo_long_min"] = lm
                pomo_eng.set_durations(wm, bm, lm)
                refresh_focus_media_ui()
                persist_and_queue_ui()
                append_log(f"🍅 Tempos Pomodoro salvos: Foco {wm}m / Curta {bm}m / Longa {lm}m.")
                page.update()
            except Exception as ex:
                append_log(f"⚠️ Valor inválido nos minutos do Pomodoro: {ex}")

        def on_toggle_pomo_bz(e):
            val = bool(e.control.value)
            state["pomo_buzzer"] = val
            pomo_eng.buzzer_enabled = val
            persist_and_queue_ui()
            append_log(f"🍅 Alerta sonoro (Buzzer) no fim do ciclo Pomodoro: {'ATIVADO' if val else 'DESATIVADO'}")

        sw_pomo_buzzer = ft.Switch(
            label="🔔 Acionar Buzzer & LED RGB da CYD ao concluir cada ciclo",
            value=state["pomo_buzzer"],
            active_color=state["hex_color"],
            on_change=on_toggle_pomo_bz,
        )

        def make_phase_pill(code: str, label: str, col_hex: str):
            return ft.Container(
                content=ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=col_hex),
                bgcolor="#111827",
                border=border_all(1, col_hex),
                border_radius=8,
                padding=pad_sym(horizontal=10, vertical=5),
                ink=True,
                on_click=lambda e, c=code: on_pomo_select_phase(c),
            )

        sec_pomodoro = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🍅 POMODORO FOCUS HUB (TELA 8)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            ft.OutlinedButton("📺 Exibir Tela 8 na CYD", on_click=lambda e: on_select_screen(8)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            make_phase_pill("WORK", "🔥 Trabalho", "#F97316"),
                            make_phase_pill("BREAK", "☕ Pausa Curta", "#22C55E"),
                            make_phase_pill("LONG", "🌴 Pausa Longa", "#38BDF8"),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                lbl_pomo_phase_badge,
                                lbl_pomo_clock,
                                bar_pomo_prog,
                                lbl_pomo_cycles,
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=6,
                        ),
                        bgcolor="#07090E",
                        border=border_all(1, "#1E293B"),
                        border_radius=12,
                        padding=14,
                        width=float("inf"),
                    ),
                    ft.Row(
                        [btn_pomo_start, btn_pomo_reset, btn_pomo_skip],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    ft.Divider(height=4, color="#151C28"),
                    ft.Row(
                        [
                            txt_pomo_w,
                            txt_pomo_b,
                            txt_pomo_l,
                            ft.OutlinedButton("💾 Salvar Minutos", on_click=on_save_pomo_times),
                        ],
                        spacing=8,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    sw_pomo_buzzer,
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
            expand=5,
        )

        # ---- Controles Multimídia Spotify & YouTube Music (Coluna Direita da Aba 1) ----
        lbl_media_src_pill = ft.Text("⚪ AGUARDANDO PLAYER", size=10, weight=ft.FontWeight.BOLD, color="#94A3B8")
        cont_media_src_pill = ft.Container(
            content=lbl_media_src_pill,
            bgcolor="#141B29",
            border=border_all(1, "#334155"),
            border_radius=12,
            padding=pad_sym(horizontal=10, vertical=4),
        )

        cover_placeholder_icon = ft.Icon(icon_val("ALBUM"), size=46, color="#475569")
        cover_preview_box = ft.Container(
            content=cover_placeholder_icon,
            width=114,
            height=114,
            bgcolor="#07090E",
            border=border_all(1, "#1E293B"),
            border_radius=12,
            alignment=ft.Alignment(0, 0) if hasattr(ft, "Alignment") else None,
        )
        last_rendered_ui_cov = {"cid": ""}

        lbl_media_title = ft.Text(
            "Abra o Spotify ou YouTube Music",
            size=16,
            weight=ft.FontWeight.BOLD,
            color="#FFFFFF",
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        lbl_media_artist = ft.Text(
            "Reproduza uma música no Desktop ou Navegador",
            size=13,
            color="#CBD5E1",
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        lbl_media_album = ft.Text(
            "Integração Linux MPRIS2 / D-Bus ativa" if IS_LINUX else "Integração Windows GSMTC (winrt) ativa",
            size=11,
            color="#64748B",
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        bar_media_pos = ft.ProgressBar(value=0.0, color="#1DB954", bgcolor="#1A2130", height=6, border_radius=3)
        lbl_media_time = ft.Text("00:00 / 00:00", size=11, color="#94A3B8", font_family="Consolas")

        btn_media_prev = ft.OutlinedButton("⏮ Anterior", on_click=lambda e: media_col.control("prev"))
        btn_media_pp = _Button("⏯ Play / Pause", on_click=lambda e: media_col.control("play_pause"))
        btn_media_next = ft.OutlinedButton("⏭ Próxima", on_click=lambda e: media_col.control("next"))

        def on_change_media_pref(_e):
            pref = str(dd_media_pref.value or "auto")
            state["media_source_pref"] = pref
            media_col.set_source_pref(pref)
            persist_and_queue_ui()
            append_log(f"🎵 Filtro de fonte multimídia alterado para: {pref.upper()}")

        dd_media_pref = make_compat_dropdown(
            label="Fonte Preferida (Spotify / YouTube Music)",
            value=state["media_source_pref"],
            options=[
                ft.dropdown.Option("auto", "Automático (Priorizar Spotify & YouTube Music)"),
                ft.dropdown.Option("spotify", "Apenas Spotify (App / Web)"),
                ft.dropdown.Option("ytmusic", "Apenas YouTube Music (Web / PWA / App)"),
                ft.dropdown.Option("all", "Qualquer Mídia do Windows"),
            ],
            expand=True,
            on_change=on_change_media_pref,
        )

        def on_toggle_media_autosync(e):
            state["media_auto_cover"] = bool(e.control.value)
            persist_and_queue_ui()
            append_log(f"🎵 Envio automático de capa 320x240 para o SD: {'ATIVADO' if state['media_auto_cover'] else 'DESATIVADO'}")

        sw_media_autosync = ft.Switch(
            label="🖼️ Sincronizar capa 320x240 no SD automaticamente ao trocar de faixa",
            value=state["media_auto_cover"],
            active_color=state["hex_color"],
            on_change=on_toggle_media_autosync,
        )

        def on_manual_cover_sync(_e):
            _tk, cid, c_bytes = media_col.get_cover_for_sd()
            if not c_bytes:
                append_log("⚠️ Nenhuma capa de álbum disponível na faixa atual para enviar.")
                return
            state["synced_cover_id"] = ""
            start_media_cover_transfer(cid or "manual", c_bytes, manual=True)

        sec_media = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Text("🎵 MULTIMÍDIA: SPOTIFY & YT MUSIC (TELA 9)", size=13, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                                    cont_media_src_pill,
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.OutlinedButton("📺 Exibir Tela 9 na CYD", on_click=lambda e: on_select_screen(9)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Row(
                            [
                                cover_preview_box,
                                ft.Column(
                                    [
                                        lbl_media_title,
                                        lbl_media_artist,
                                        lbl_media_album,
                                        bar_media_pos,
                                        ft.Row([lbl_media_time], alignment=ft.MainAxisAlignment.END),
                                    ],
                                    spacing=4,
                                    expand=True,
                                ),
                            ],
                            spacing=14,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        bgcolor="#07090E",
                        border=border_all(1, "#1E293B"),
                        border_radius=12,
                        padding=12,
                    ),
                    ft.Row(
                        [btn_media_prev, btn_media_pp, btn_media_next],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=12,
                    ),
                    dd_media_pref,
                    ft.Container(
                        content=ft.Column(
                            [
                                sw_media_autosync,
                                ft.Row(
                                    [
                                        ft.OutlinedButton(
                                            "📤 Reenviar Capa 320x240 p/ SD Agora",
                                            icon=icon_val("IMAGE"),
                                            on_click=on_manual_cover_sync,
                                        ),
                                        ft.Container(content=lbl_media_sync_status, expand=True),
                                    ],
                                    spacing=10,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                prog_media_upload,
                            ],
                            spacing=6,
                        ),
                        bgcolor="#07090E",
                        border=border_all(1, "#151C28"),
                        border_radius=10,
                        padding=10,
                    ),
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
            expand=6,
        )

        def refresh_focus_media_ui():
            # 1) Atualiza UI Pomodoro + Chip no Header
            ps = pomo_eng.get_ui_snapshot()
            mm, ss = ps["rem"] // 60, ps["rem"] % 60
            clock_str = f"{mm:02d}:{ss:02d}"
            lbl_pomo_clock.value = clock_str
            bar_pomo_prog.value = ps["pct"]

            ph_col = "#F97316" if ps["state"] == "WORK" else ("#22C55E" if ps["state"] == "BREAK" else "#38BDF8")
            ph_name = (
                "🔥 FOCO PROFUNDO (TRABALHO)"
                if ps["state"] == "WORK"
                else ("☕ PAUSA CURTA (DESCANSO)" if ps["state"] == "BREAK" else "🌴 PAUSA LONGA (15 MIN)")
            )
            lbl_pomo_phase_badge.value = ph_name if ps["running"] else f"⏸ PAUSADO • {ph_name}"
            lbl_pomo_phase_badge.color = ph_col
            bar_pomo_prog.color = ph_col

            mod_c = ps["cycles"] % 4
            dots = " ".join("🍅" if i < mod_c else "⚪" for i in range(4))
            lbl_pomo_cycles.value = f"Ciclos: #{ps['cycles']}  •  {dots}  •  Foco hoje: {ps['focus_min_today']} min"
            set_btn_text(btn_pomo_start, "⏸ Pausar Timer" if ps["running"] else "▶ Iniciar Timer")

            if ps["running"]:
                short_ph = "FOCO" if ps["state"] == "WORK" else "PAUSA"
                lbl_hdr_pomo.value = f"🍅 {short_ph} {clock_str} • #{ps['cycles']}"
                lbl_hdr_pomo.color = ph_col
                pill_hdr_pomo.border = border_all(1.2, ph_col)
                pill_hdr_pomo.bgcolor = "#162032"
            else:
                lbl_hdr_pomo.value = f"🍅 {clock_str}"
                lbl_hdr_pomo.color = "#94A3B8"
                pill_hdr_pomo.border = border_all(1, "#1E293B")
                pill_hdr_pomo.bgcolor = "#111622"

            # 2) Atualiza UI Multimídia (Spotify / YouTube Music) + Chip no Header
            ms = media_col.get_ui_snapshot()
            src = ms["source"]
            if src == "SPOTIFY":
                src_col = "#1DB954"
                lbl_media_src_pill.value = "🟢 SPOTIFY"
                cont_media_src_pill.bgcolor = "#0F291A"
                cont_media_src_pill.border = border_all(1, src_col)
            elif src == "YT MUSIC":
                src_col = "#FF0033"
                lbl_media_src_pill.value = "🔴 YOUTUBE MUSIC"
                cont_media_src_pill.bgcolor = "#2B1118"
                cont_media_src_pill.border = border_all(1, src_col)
            elif src == "MEDIA":
                src_col = state["hex_color"]
                lbl_media_src_pill.value = "🔵 WINDOWS MEDIA"
                cont_media_src_pill.bgcolor = "#141E30"
                cont_media_src_pill.border = border_all(1, src_col)
            else:
                src_col = "#64748B"
                lbl_media_src_pill.value = "⚪ AGUARDANDO PLAYER"
                cont_media_src_pill.bgcolor = "#141B29"
                cont_media_src_pill.border = border_all(1, "#334155")

            lbl_media_src_pill.color = src_col
            bar_media_pos.color = src_col if src != "NONE" else "#475569"

            if src != "NONE" and (ms["title"] or ms["artist"]):
                lbl_media_title.value = ms["title"] or "Faixa Desconhecida"
                lbl_media_artist.value = ms["artist"] or src
                lbl_media_album.value = ms["album"] if ms["album"] else f"Reproduzindo via {src}"
                dur_s = max(0, int(ms["dur"]))
                pos_s = max(0, int(ms["pos"]))
                bar_media_pos.value = min(1.0, pos_s / float(dur_s)) if dur_s > 0 else 0.0
                if dur_s > 0:
                    lbl_media_time.value = f"{pos_s // 60:02d}:{pos_s % 60:02d} / {dur_s // 60:02d}:{dur_s % 60:02d}"
                else:
                    lbl_media_time.value = f"{pos_s // 60:02d}:{pos_s % 60:02d} / AO VIVO"
                set_btn_text(btn_media_pp, "⏸ Pausar" if ms["playing"] else "▶ Reproduzir")

                # Header Mini-Player
                dot_hdr_media.bgcolor = src_col
                hdr_txt = f"{ms['artist']} — {ms['title']}" if ms["artist"] else ms["title"]
                lbl_hdr_media.value = hdr_txt
                lbl_hdr_media.color = "#F8FAFC" if ms["playing"] else "#94A3B8"
                btn_hdr_media_pp.icon = icon_val("PAUSE" if ms["playing"] else "PLAY_ARROW")
                pill_hdr_media.border = border_all(1, src_col if ms["playing"] else "#1E293B")
            else:
                lbl_media_title.value = "Abra o Spotify ou YouTube Music"
                lbl_media_artist.value = "Nenhuma sessão de mídia ativa no momento"
                lbl_media_album.value = "Suporte a Spotify Desktop/Web e YouTube Music"
                bar_media_pos.value = 0.0
                lbl_media_time.value = "00:00 / 00:00"
                dot_hdr_media.bgcolor = "#475569"
                lbl_hdr_media.value = "Sem mídia ativa"
                lbl_hdr_media.color = "#64748B"
                btn_hdr_media_pp.icon = icon_val("PLAY_ARROW")
                pill_hdr_media.border = border_all(1, "#1E293B")

            # Atualiza preview da capa no Flet somente quando o hash cid mudar
            if ms["cover_b64"] and ms["cover_id"] != last_rendered_ui_cov["cid"]:
                last_rendered_ui_cov["cid"] = ms["cover_id"]
                cover_preview_box.content = ft.Image(
                    src=f"data:image/jpeg;base64,{ms['cover_b64']}",
                    width=114,
                    height=114,
                    fit=ft.BoxFit.COVER if hasattr(ft, "BoxFit") else "cover",
                    border_radius=11,
                    gapless_playback=True,
                )
            elif not ms["cover_b64"] and last_rendered_ui_cov["cid"] != "":
                last_rendered_ui_cov["cid"] = ""
                cover_preview_box.content = cover_placeholder_icon

        refresh_focus_media_ui()

        # ---------------- 10. CLIMA REGIONAL (VOTUPORANGA) & GEMINI GEMS (TELA 10) ---
        txt_weather_city = ft.TextField(
            label="Cidade / Região (Ex: Votuporanga, São José do Rio Preto, São Paulo)",
            value=state["weather_city"],
            expand=True,
            height=42,
            text_size=12,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        lbl_wth_temp_big = ft.Text("29.0°C", size=34, weight=ft.FontWeight.BOLD, color="#38BDF8", font_family="Consolas")
        lbl_wth_city_badge = ft.Text("📍 VOTUPORANGA - SP", size=12, weight=ft.FontWeight.BOLD, color="#F8FAFC", font_family="Consolas")
        lbl_wth_date_badge = ft.Text("📅 SAB 07/11/2026", size=12, weight=ft.FontWeight.BOLD, color="#FACC15", font_family="Consolas")
        lbl_wth_cond = ft.Text("Céu Limpo", size=13, weight=ft.FontWeight.BOLD, color="#22C55E")
        lbl_wth_details = ft.Text(
            "Sensação: 30°C • Mín/Máx: 20°/33°C • Umidade: 52% • Vento: 12 km/h • Chuva: 10%",
            size=11,
            color="#94A3B8",
            font_family="Consolas",
        )
        lbl_wth_alert_banner = ft.Text(
            "🟢 Clima Estável na Região — Sem alertas severos no momento",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#22C55E",
        )
        cont_wth_alert_box = ft.Container(
            content=lbl_wth_alert_banner,
            bgcolor="#0B1915",
            border=border_all(1, "#10B981"),
            border_radius=8,
            padding=pad_sym(horizontal=10, vertical=6),
        )

        def on_save_weather_city(_e):
            new_c = (txt_weather_city.value or "").strip() or "Votuporanga"
            state["weather_city"] = new_c
            wth_col.set_city(new_c)
            persist_and_queue_ui()
            append_log(f"🌦️ Localidade alterada para '{new_c}'. Buscando temperatura e previsão...")

        def on_refresh_weather(_e):
            wth_col.force_refresh()
            append_log(f"🌦️ Atualizando clima e temperatura de {state['weather_city']}...")

        btn_sim_storm = ft.OutlinedButton(
            "⛈️ Simular Aviso de Tempestade na CYD",
            on_click=lambda e: on_toggle_storm_sim(),
        )

        def on_toggle_storm_sim():
            snap_w = wth_col.get_ui_snapshot()
            is_sim = not snap_w.get("sim_storm", False)
            wth_col.trigger_storm_simulation(
                active=is_sim,
                custom_msg=f"ALERTA DE TEMPESTADE EM {state['weather_city'].upper()}: CHUVA FORTE E RAIOS!",
            )
            set_btn_text(
                btn_sim_storm,
                "🛑 Desativar Simulação de Tempestade" if is_sim else "⛈️ Simular Aviso de Tempestade na CYD",
            )
            w_pkt = wth_col.get_cyd_payload()
            ev = {"wth": w_pkt}
            if is_sim:
                ev["alrt"] = {"bz": True, "led": "0xF800", "p": 3}
                append_log(f"⛈️ AVISO DE TEMPESTADE ATIVADO NA CYD ({state['weather_city']})! Banner de emergência + Buzzer/LED disparados.")
            else:
                append_log("🌤️ Simulação de tempestade encerrada na CYD.")
            ui_event_queue.put(ev)
            refresh_weather_gems_ui()
            try:
                page.update()
            except Exception:
                pass

        sec_weather_regional = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Text("🌦️ CLIMA REGIONAL, DATA & ALERTAS SEVEROS", size=12, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                                ],
                                spacing=8,
                            ),
                            ft.OutlinedButton("📺 Exibir Tela 10 na CYD", on_click=lambda e: on_select_screen(10)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        lbl_wth_city_badge,
                                        lbl_wth_date_badge,
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Row(
                                    [
                                        lbl_wth_temp_big,
                                        ft.Column(
                                            [
                                                lbl_wth_cond,
                                                lbl_wth_details,
                                            ],
                                            spacing=2,
                                            expand=True,
                                        ),
                                    ],
                                    spacing=14,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                cont_wth_alert_box,
                            ],
                            spacing=6,
                        ),
                        bgcolor="#060911",
                        border=border_all(1, "#1E293B"),
                        border_radius=12,
                        padding=12,
                    ),
                    ft.Row(
                        [
                            txt_weather_city,
                            ft.OutlinedButton("💾 Salvar Região", on_click=on_save_weather_city),
                            ft.OutlinedButton("🔄 Atualizar", on_click=on_refresh_weather),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            btn_sim_storm,
                            ft.Text(
                                "Exibe Data + Temp no topo de TODAS as telas e alerta piscante em caso de tempestade.",
                                size=10,
                                color="#64748B",
                                expand=True,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=9,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=13,
            expand=True,
        )

        # ---- Painel Direito (Aba 3): Módulo 1 — Feed de Notícias Customizável (SCR_NEWS / Tela 10) ----
        lbl_news_status = ft.Text(
            "Sincronizando manchetes via RSS/API...",
            size=10,
            color="#94A3B8",
            font_family="Consolas",
        )
        lbl_news_active_topic = ft.Text(
            "📰 [POLÍTICA]",
            size=12,
            weight=ft.FontWeight.BOLD,
            color="#38BDF8",
            font_family="Consolas",
        )
        lbl_news_active_timer = ft.Text(
            "Próxima em 15s • Fonte: RSS",
            size=10,
            color="#FACC15",
            font_family="Consolas",
        )
        lbl_news_active_headline = ft.Text(
            "Carregando manchetes em tempo real...",
            size=12,
            weight=ft.FontWeight.BOLD,
            color="#F8FAFC",
            font_family="Consolas",
            selectable=True,
        )

        txt_custom_topic = ft.TextField(
            label="Adicionar Tópico Customizado (Ex: Inteligência Artificial, Linux, Agronegócio)",
            value="",
            expand=True,
            height=40,
            text_size=12,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )
        txt_news_api_key = ft.TextField(
            label="NewsAPI.org Key (Opcional — sem chave usa Google/Bing News RSS Gratuito)",
            value=state["news_api_key"],
            password=True,
            can_reveal_password=True,
            width=260,
            height=40,
            text_size=11,
            content_padding=pad_sym(horizontal=10, vertical=6),
        )

        topic_chips_row = ft.Row(wrap=True, spacing=6, run_spacing=6)
        news_queue_col = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, height=150)

        def on_toggle_news_topic(topic_name: str):
            curr = list(state["news_topics"])
            if topic_name in curr:
                if len(curr) <= 1:
                    append_log("⚠️ Mantenha pelo menos 1 tópico ativo no Feed de Notícias.")
                    return
                curr.remove(topic_name)
                append_log(f"📰 Tópico '{topic_name}' removido do Feed de Notícias.")
            else:
                curr.append(topic_name)
                append_log(f"📰 Tópico '{topic_name}' ativado no Feed de Notícias.")
            state["news_topics"] = curr
            gems_eng.set_topics(curr, state["news_api_key"])
            persist_and_queue_ui()
            refresh_weather_gems_ui()

        def on_add_custom_news_topic(_e=None):
            new_t = (txt_custom_topic.value or "").strip()
            api_k = (txt_news_api_key.value or "").strip()
            state["news_api_key"] = api_k
            if new_t and new_t not in state["news_topics"]:
                state["news_topics"].append(new_t)
                txt_custom_topic.value = ""
                append_log(f"📰 Tópico customizado '{new_t}' adicionado ao Feed de Notícias!")
            gems_eng.set_topics(state["news_topics"], state["news_api_key"])
            persist_and_queue_ui()
            refresh_weather_gems_ui()

        txt_custom_topic.on_submit = on_add_custom_news_topic

        def on_manual_news_refresh(_e=None):
            def _w():
                append_log("📰 Atualizando manchetes de todos os tópicos selecionados (Async RSS/API)...")
                gems_eng.fetch_now()
                ui_event_queue.put({"news": gems_eng.get_cyd_news_payload(include_queue=True, force=True)})
                refresh_weather_gems_ui()
                append_log("✅ Feed de Notícias sincronizado e enviado para a SCR_NEWS (Tela 10)!")
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=_w, daemon=True).start()

        def on_next_news_headline(_e=None):
            nxt = gems_eng.next_headline()
            ui_event_queue.put({"news": gems_eng.get_cyd_news_payload(include_queue=False, force=True)})
            refresh_weather_gems_ui()
            append_log(f"📰 Manchete avançada na CYD: [{nxt.get('topic', '')}] {nxt.get('headline', '')[:55]}...")

        def on_select_news_item(idx_q: int):
            sel = gems_eng.select_index(idx_q)
            ui_event_queue.put({"news": gems_eng.get_cyd_news_payload(include_queue=False, force=True)})
            refresh_weather_gems_ui()
            append_log(f"📰 Manchete #{idx_q + 1} enviada para a CYD: [{sel.get('topic', '')}] {sel.get('headline', '')[:55]}...")

        def rebuild_news_topics_and_queue_ui(ns: dict):
            news_sig = (
                tuple(state["news_topics"]),
                ns.get("active_index", 0),
                len(ns.get("queue", [])),
                ns.get("active_headline", ""),
            )
            if news_sig == state.get("_last_news_sig"):
                return
            state["_last_news_sig"] = news_sig

            topic_chips_row.controls.clear()
            all_topics = list(ALL_PRESET_NEWS_TOPICS)
            for ct in state["news_topics"]:
                if ct not in all_topics:
                    all_topics.append(ct)

            for t_name in all_topics:
                active = t_name in state["news_topics"]
                chip = ft.Container(
                    content=ft.Row(
                        [
                            ft.Text("✓" if active else "+", size=11, weight=ft.FontWeight.BOLD, color="#05070A" if active else "#94A3B8"),
                            ft.Text(t_name, size=11, weight=ft.FontWeight.BOLD if active else ft.FontWeight.W_500, color="#05070A" if active else "#E2E8F0"),
                        ],
                        spacing=5,
                        tight=True,
                    ),
                    bgcolor="#38BDF8" if active else "#111827",
                    border=border_all(1, "#38BDF8" if active else "#1E293B"),
                    border_radius=14,
                    padding=pad_sym(horizontal=10, vertical=4),
                    ink=True,
                    on_click=lambda e, tn=t_name: on_toggle_news_topic(tn),
                )
                topic_chips_row.controls.append(chip)

            news_queue_col.controls.clear()
            q_items = ns.get("queue", [])
            act_idx = ns.get("active_index", 0)
            for idx_i, item in enumerate(q_items):
                is_curr = (idx_i == act_idx)
                row_card = ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    item.get("topic", "News")[:16].upper(),
                                    size=9,
                                    weight=ft.FontWeight.BOLD,
                                    color="#05070A" if is_curr else "#38BDF8",
                                    font_family="Consolas",
                                ),
                                bgcolor="#38BDF8" if is_curr else "#0F172A",
                                border=border_all(1, "#38BDF8"),
                                border_radius=5,
                                padding=pad_sym(horizontal=6, vertical=2),
                            ),
                            ft.Text(
                                item.get("headline", ""),
                                size=11,
                                weight=ft.FontWeight.BOLD if is_curr else ft.FontWeight.NORMAL,
                                color="#FFFFFF" if is_curr else "#CBD5E1",
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                            ft.Text(
                                item.get("src", "RSS")[:14],
                                size=10,
                                color="#64748B",
                                font_family="Consolas",
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor="#132038" if is_curr else "#0A0E17",
                    border=border_all(1, "#38BDF8" if is_curr else "#161F30"),
                    border_radius=7,
                    padding=pad_sym(horizontal=8, vertical=5),
                    ink=True,
                    on_click=lambda e, ii=idx_i: on_select_news_item(ii),
                )
                news_queue_col.controls.append(row_card)

        sec_news_feed = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("📰 MÓDULO 1: FEED DE NOTÍCIAS CUSTOMIZÁVEL (TELA 10 • SCR_NEWS)", size=12, weight=ft.FontWeight.BOLD, color="#38BDF8"),
                            lbl_news_status,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text("Selecione os tópicos para monitorar (clique para ativar/desativar na fila serial de 15s):", size=11, color="#94A3B8"),
                    topic_chips_row,
                    ft.Row(
                        [
                            txt_custom_topic,
                            txt_news_api_key,
                            ft.OutlinedButton("➕ Salvar Tópico", on_click=on_add_custom_news_topic),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        lbl_news_active_topic,
                                        lbl_news_active_timer,
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                lbl_news_active_headline,
                            ],
                            spacing=4,
                        ),
                        bgcolor="#060D1A",
                        border=border_all(1.5, "#0284C7"),
                        border_radius=10,
                        padding=10,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton("⏭️ Próxima Manchete (15s)", on_click=on_next_news_headline),
                            ft.OutlinedButton("🔄 Buscar Últimas Manchetes", on_click=on_manual_news_refresh),
                            ft.OutlinedButton("📺 Abrir SCR_NEWS (Tela 10)", on_click=lambda e: on_select_screen(10)),
                        ],
                        spacing=8,
                    ),
                    ft.Text("FILA DE MANCHETES ATIVAS (DESLIZANDO NO SPRITE DA CYD A CADA 15s):", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                    news_queue_col,
                ],
                spacing=7,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=13,
            expand=True,
        )

        # ---------------- 11. MÓDULO 2: O TERMINAL CYD (CYBER DECK • TELA 11 / SCR_TERMINAL) ---
        lbl_term_status_badge = ft.Text(
            "🟢 TERMINAL PRONTO • 115200 bps",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#22C55E",
            font_family="Consolas",
        )
        txt_term_screen = ft.Text(
            value=term_eng.get_snapshot()["text"],
            size=12,
            color="#22C55E",
            font_family="Consolas",
            selectable=True,
        )
        term_scroll_col = ft.Column(
            [txt_term_screen],
            scroll=ft.ScrollMode.ALWAYS,
            auto_scroll=True,
            expand=True,
        )
        txt_term_input = ft.TextField(
            hint_text="Digite um comando (ex: neofetch, df -h, free -m, ip addr, netstat -tuln, esp mem, cmatrix, ping)...",
            value="",
            expand=True,
            height=44,
            text_size=13,
            color="#22C55E",
            bgcolor="#030508",
            border_color="#22C55E",
            focused_border_color="#4ADE80",
            cursor_color="#22C55E",
            text_style=ft.TextStyle(font_family="Consolas", weight=ft.FontWeight.BOLD),
            prefix="root@cyd-deck:~# ",
            prefix_style=ft.TextStyle(font_family="Consolas", color="#4ADE80", weight=ft.FontWeight.BOLD),
            content_padding=pad_sym(horizontal=12, vertical=8),
        )
        sw_term_autoscr = ft.Switch(
            label="Abrir Tela 11 (SCR_TERMINAL) automaticamente na CYD ao executar comando",
            value=state["term_auto_switch"],
            active_color="#22C55E",
            on_change=lambda e: state.update({"term_auto_switch": bool(e.control.value)}),
        )

        term_history_idx = -1

        def refresh_terminal_ui():
            snap_t = term_eng.get_snapshot()
            txt_term_screen.value = snap_t["text"]
            if snap_t["busy"]:
                lbl_term_status_badge.value = f"⏳ EXECUTANDO: {snap_t['last_cmd']}"
                lbl_term_status_badge.color = "#FACC15"
            else:
                lbl_term_status_badge.value = f"🟢 PRONTO • Último: {snap_t['last_cmd']}"
                lbl_term_status_badge.color = "#22C55E"
            if state.get("active_tab") == 4:
                safe_update(txt_term_screen, lbl_term_status_badge, txt_term_input)
                try:
                    term_scroll_col.scroll_to(offset=-1, duration=50)
                except Exception:
                    pass

        def on_term_keyboard_event(e: ft.KeyboardEvent):
            nonlocal term_history_idx
            if state.get("active_tab") != 4:
                return
            key_name = (e.key or "").strip()
            snap_t = term_eng.get_snapshot()
            hist = snap_t.get("history", [])
            if not hist:
                return

            if key_name in ("Arrow Up", "Up", "ArrowUp"):
                if term_history_idx == -1:
                    term_history_idx = len(hist) - 1
                else:
                    term_history_idx = max(0, term_history_idx - 1)
                txt_term_input.value = hist[term_history_idx]
                safe_update(txt_term_input)

            elif key_name in ("Arrow Down", "Down", "ArrowDown"):
                if term_history_idx == -1:
                    return
                if term_history_idx + 1 < len(hist):
                    term_history_idx += 1
                    txt_term_input.value = hist[term_history_idx]
                else:
                    term_history_idx = -1
                    txt_term_input.value = ""
                safe_update(txt_term_input)

        page.on_keyboard_event = on_term_keyboard_event

        def run_terminal_command(cmd_raw: str = None, wait: bool = False, timeout_s: float = 10.0) -> list[str]:
            nonlocal term_history_idx
            cmd_to_run = (cmd_raw if cmd_raw is not None else (txt_term_input.value or "")).strip()
            if not cmd_to_run:
                return []
            term_history_idx = -1
            if cmd_raw is None:
                txt_term_input.value = ""

            if state.get("term_auto_switch", True) and state["screen"] != 11:
                state["screen"] = 11
                lbl_hdr_screen.value = f"📺 TELA 11 • {SCREEN_SHORT_NAMES.get(11, 'Terminal CYD')}"
                refresh_screen_cards()

            def _dispatch_to_cyd(pkt: dict):
                ui_event_queue.put(pkt)
                refresh_terminal_ui()

            out_lines = term_eng.execute_command(
                cmd_to_run,
                dispatch_fn=_dispatch_to_cyd,
                log_fn=lambda m: (append_log(m), refresh_terminal_ui()),
                auto_switch_screen=bool(state.get("term_auto_switch", True)),
                wait=wait,
                timeout_s=timeout_s,
            )
            refresh_terminal_ui()
            return out_lines

        txt_term_input.on_submit = lambda e: run_terminal_command()

        def make_cmd_chip(label: str, cmd_str: str, accent_col: str = "#22C55E"):
            return ft.Container(
                content=ft.Text(label, size=11, weight=ft.FontWeight.BOLD, color=accent_col, font_family="Consolas"),
                bgcolor="#091310",
                border=border_all(1, accent_col),
                border_radius=8,
                padding=pad_sym(horizontal=10, vertical=5),
                ink=True,
                tooltip=f"Executar '{cmd_str}' e transmitir para a SCR_TERMINAL da CYD",
                on_click=lambda e, c=cmd_str: run_terminal_command(c),
            )

        sec_cyber_terminal = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        "💻 MÓDULO 2: O TERMINAL CYD — FERRAMENTAS DE REDE E SISTEMA (TELA 11 • SCR_TERMINAL)",
                                        size=13,
                                        weight=ft.FontWeight.BOLD,
                                        color="#22C55E",
                                        font_family="Consolas",
                                    ),
                                    ft.Text(
                                        "Execute comandos Unix-like (neofetch, df, free, uptime, ip, netstat, ssh, docker) e comandos nativos no ESP32:",
                                        size=11,
                                        color="#94A3B8",
                                    ),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    lbl_term_status_badge,
                                    ft.OutlinedButton("📺 Exibir Tela 11 na CYD", on_click=lambda e: on_select_screen(11)),
                                ],
                                spacing=10,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            make_cmd_chip("🤖 ai report", "ai report", "#C084FC"),
                            make_cmd_chip("🧠 ai rf", "ai rf", "#E879F9"),
                            make_cmd_chip("⚙️ ai status", "ai status", "#A855F7"),
                            make_cmd_chip("📡 rf scan", "rf scan", "#38BDF8"),
                            make_cmd_chip("📊 rf spectrum", "rf spectrum", "#22C55E"),
                            make_cmd_chip("🛡️ rf audit", "rf audit", "#FACC15"),
                            make_cmd_chip("🔄 rf diff", "rf diff", "#38BDF8"),
                            make_cmd_chip("🩺 netcheck", "netcheck", "#4ADE80"),
                            make_cmd_chip("📈 jitter", "jitter", "#34D399"),
                            make_cmd_chip("📏 mtu", "mtu", "#A855F7"),
                            make_cmd_chip("🔀 route", "route", "#60A5FA"),
                            make_cmd_chip("📶 wifi scan", "wifi scan", "#38BDF8"),
                            make_cmd_chip("ℹ️ esp info", "esp info", "#38BDF8"),
                            make_cmd_chip("🧠 esp mem", "esp mem", "#38BDF8"),
                            make_cmd_chip("🔄 esp reboot", "esp reboot", "#F87171"),
                            make_cmd_chip("🟢 cmatrix (Rain)", "cmatrix", "#4ADE80"),
                            make_cmd_chip("🖥️ neofetch", "neofetch", "#C084FC"),
                            make_cmd_chip("💾 df -h", "df -h", "#60A5FA"),
                            make_cmd_chip("📊 free -m", "free -m", "#34D399"),
                            make_cmd_chip("⏱️ uptime", "uptime", "#FBBF24"),
                            make_cmd_chip("👤 whoami", "whoami", "#F472B6"),
                            make_cmd_chip("🌐 ip addr", "ip addr", "#38BDF8"),
                            make_cmd_chip("🔌 netstat -tuln", "netstat -tuln", "#F59E0B"),
                            make_cmd_chip("⚡ ping 8.8.8.8", "ping 8.8.8.8", "#22C55E"),
                            make_cmd_chip("🌐 fetch github", "fetch https://api.github.com", "#A855F7"),
                            make_cmd_chip("🐳 docker ps", "docker ps", "#F59E0B"),
                            make_cmd_chip("🐳 docker stats", "docker stats", "#FB923C"),
                            make_cmd_chip("❓ help", "help", "#22C55E"),
                            make_cmd_chip("🧹 clear", "clear", "#EF4444"),
                        ],
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                    ),
                    ft.Container(
                        content=term_scroll_col,
                        bgcolor="#030508",
                        border=border_all(1.5, "#15803D"),
                        border_radius=10,
                        padding=12,
                        height=300,
                        width=float("inf"),
                    ),
                    ft.Row(
                        [
                            txt_term_input,
                            _Button(
                                "▶ Executar na CYD",
                                icon=icon_val("SEND"),
                                on_click=lambda e: run_terminal_command(),
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    sw_term_autoscr,
                ],
                spacing=10,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=14,
        )

        def refresh_weather_gems_ui():
            ws = wth_col.get_ui_snapshot()
            ns = gems_eng.get_ui_snapshot()
            now_hm = datetime.now().strftime("%H:%M")

            # Atualiza o Header Superior (Hora + Data + Temperatura na Região)
            if ws["alert"]:
                lbl_hdr_weather.value = f"⛈️ ALERTA {ws['city'].upper()} • {ws['temp']:.1f}°C • 📅 {ws['date_short']} {now_hm}"
                lbl_hdr_weather.color = "#FEF08A"
                pill_hdr_weather.bgcolor = "#7F1D1D"
                pill_hdr_weather.border = border_all(1.5, "#EF4444")
            else:
                lbl_hdr_weather.value = f"🕒 {now_hm} • 📅 {ws['date_short']} • 🌡️ {ws['temp']:.1f}°C ({ws['city']})"
                lbl_hdr_weather.color = "#38BDF8"
                pill_hdr_weather.bgcolor = "#0F172A"
                pill_hdr_weather.border = border_all(1, "#0284C7")

            lbl_wth_temp_big.value = f"{ws['temp']:.1f}°C"
            lbl_wth_city_badge.value = f"📍 {ws['city'].upper()} - {ws['region']}"
            lbl_wth_date_badge.value = f"📅 {ws['date_full']}"
            lbl_wth_cond.value = f"{ws['cond']} (Atualizado {ws['updated']})"
            lbl_wth_details.value = (
                f"Sensação: {ws['feels']:.0f}°C • Mín/Máx: {ws['tmin']:.0f}°/{ws['tmax']:.0f}°C • "
                f"Umidade: {ws['hum']}% • Vento: {ws['wind']:.0f} km/h • Chuva: {ws['rain_prob']}%"
            )

            if ws["alert"]:
                lbl_wth_alert_banner.value = f"⛈️ ALERTA NA PLACA CYD: {ws['alert_msg']}"
                lbl_wth_alert_banner.color = "#FEF08A"
                cont_wth_alert_box.bgcolor = "#450A0A"
                cont_wth_alert_box.border = border_all(1.5, "#EF4444")
            else:
                lbl_wth_alert_banner.value = f"🟢 Clima Estável em {ws['city']} — Sem alertas severos no momento"
                lbl_wth_alert_banner.color = "#22C55E"
                cont_wth_alert_box.bgcolor = "#0B1915"
                cont_wth_alert_box.border = border_all(1, "#10B981")

            lbl_news_status.value = ns.get("status_msg", "")
            lbl_news_active_topic.value = f"📰 [{ns.get('active_topic', 'Notícias').upper()}] ({ns.get('active_index', 0) + 1}/{max(1, ns.get('total', 1))})"
            lbl_news_active_timer.value = f"⏱️ Troca em {ns.get('remain_sec', 15)}s • Fonte: {ns.get('active_source', 'RSS')} ({ns.get('active_time', '--:--')})"
            lbl_news_active_headline.value = ns.get("active_headline", "")
            rebuild_news_topics_and_queue_ui(ns)

        refresh_weather_gems_ui()

        # ---------------- 12. TELEMETRIA WI-FI (UDP) & COMUNICAÇÃO SEM FIO ----
        sw_udp_enabled = ft.Switch(
            label="Ativar Transmissão de Telemetria via Wi-Fi (Protocolo UDP)",
            value=state.get("udp_enabled", False),
            active_color="#38BDF8",
        )
        txt_udp_ip = ft.TextField(
            label="IP da Placa CYD na Rede Local",
            value=state.get("udp_ip", ""),
            hint_text="ex: 192.168.0.150",
            width=260,
            text_size=13,
            color="#38BDF8",
            bgcolor="#05070B",
            border_color="#1E293B",
            focused_border_color="#38BDF8",
            text_style=ft.TextStyle(font_family="Consolas", weight=ft.FontWeight.BOLD),
        )
        txt_udp_port = ft.TextField(
            label="Porta UDP",
            value=str(state.get("udp_port", UDP_DEFAULT_PORT)),
            hint_text="8888",
            width=110,
            text_size=13,
            color="#38BDF8",
            bgcolor="#05070B",
            border_color="#1E293B",
            focused_border_color="#38BDF8",
            text_style=ft.TextStyle(font_family="Consolas"),
        )
        lbl_udp_route_badge = ft.Text(
            "🔌 ROTA ATIVA: USB SERIAL",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#22C55E",
            font_family="Consolas",
        )
        lbl_udp_diag = ft.Text(
            "UDP: Standby (Sem IP ativo) • Porta 8888",
            size=10,
            color="#64748B",
            font_family="Consolas",
        )

        def on_save_udp_settings(_e=None):
            new_en = bool(sw_udp_enabled.value)
            new_ip = (txt_udp_ip.value or "").strip()
            try:
                new_port = int(txt_udp_port.value or UDP_DEFAULT_PORT)
            except Exception:
                new_port = UDP_DEFAULT_PORT
            state["udp_enabled"] = new_en
            state["udp_ip"] = new_ip
            state["udp_port"] = new_port
            persist_and_queue_ui()
            refresh_serial_indicators()
            append_log(f"Configuração Wi-Fi UDP salva: Ativo={new_en} • Destino={new_ip}:{new_port}")

        sw_udp_enabled.on_change = on_save_udp_settings
        txt_udp_ip.on_submit = on_save_udp_settings
        txt_udp_port.on_submit = on_save_udp_settings

        def on_detect_ip(_e):
            det = (serial_mgr.detected_ip or "").strip()
            if det:
                txt_udp_ip.value = det
                state["udp_ip"] = det
                persist_and_queue_ui()
                safe_update(txt_udp_ip)
                append_log(f"IP detectado da CYD aplicado: {det}")
            else:
                append_log("Nenhum IP detectado ainda. Conecte a CYD via USB ou digite o IP manualmente.")

        def on_test_udp_ping(_e):
            target_ip = (txt_udp_ip.value or state.get("udp_ip", "")).strip()
            if not target_ip:
                append_log("⚠️ Digite o IP da placa CYD antes de disparar o Ping UDP.")
                return
            serial_mgr.send_event({"cmd": "udp_ping"})
            append_log(f"📡 Heartbeat 'udp_ping' disparado para {target_ip}:{state.get('udp_port', UDP_DEFAULT_PORT)}...")

        txt_esp_ssid = ft.TextField(
            label="Nome da Rede Wi-Fi (SSID)",
            value=state.get("esp_wifi_ssid", ""),
            hint_text="ex: MinhaCasa_2.4G",
            width=220,
            text_size=12,
            color="#FFFFFF",
            bgcolor="#05070B",
            border_color="#1E293B",
            focused_border_color="#38BDF8",
        )
        txt_esp_pass = ft.TextField(
            label="Senha da Rede Wi-Fi",
            value=state.get("esp_wifi_pass", ""),
            hint_text="********",
            password=True,
            can_reveal_password=True,
            width=200,
            text_size=12,
            color="#FFFFFF",
            bgcolor="#05070B",
            border_color="#1E293B",
            focused_border_color="#38BDF8",
        )

        def on_send_wifi_cfg_to_esp(_e):
            ssid_v = (txt_esp_ssid.value or "").strip()
            pass_v = (txt_esp_pass.value or "").strip()
            if not ssid_v:
                append_log("⚠️ Digite o nome da rede (SSID) antes de enviar para a CYD.")
                return
            state["esp_wifi_ssid"] = ssid_v
            state["esp_wifi_pass"] = pass_v
            cfg["esp_wifi_ssid"] = ssid_v
            cfg["esp_wifi_pass"] = pass_v
            save_ui_config(cfg)
            serial_mgr.send_event({"wifi_cfg": {"ssid": ssid_v, "pass": pass_v}}, route="serial")
            append_log(f"📡 Credenciais Wi-Fi enviadas para gravação no NVS da CYD: SSID '{ssid_v}'")

        sec_wifi_udp = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(icon_val("WIFI") or ft.Icons.WIFI, size=20, color="#38BDF8"),
                                    ft.Text("MÓDULO DE TRANSMISSÃO WI-FI (UDP) & COMUNICAÇÃO SEM FIO", size=13, weight=ft.FontWeight.BOLD, color="#38BDF8"),
                                ],
                                spacing=8,
                            ),
                            lbl_udp_route_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(
                        "Transmita telemetria, notícias e comandos do terminal sem fios via UDP (Porta 8888). "
                        "A porta USB Serial permanece ativa simultaneamente como canal de fallback e debug:",
                        size=11,
                        color="#94A3B8",
                    ),
                    ft.Row(
                        [
                            sw_udp_enabled,
                            lbl_udp_diag,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            txt_udp_ip,
                            txt_udp_port,
                            ft.OutlinedButton("Salvar Destino", icon=icon_val("SAVE"), on_click=on_save_udp_settings),
                            ft.OutlinedButton("🔍 Preencher IP Detectado", on_click=on_detect_ip),
                            ft.OutlinedButton("⚡ Ping UDP", icon=icon_val("FLASH_ON"), on_click=on_test_udp_ping),
                        ],
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color="#1E293B"),
                    ft.Row(
                        [
                            ft.Text("PROVISIONAMENTO WI-FI DA PLACA CYD (GRAVAÇÃO DIRETA NO NVS):", size=11, weight=ft.FontWeight.BOLD, color="#64748B"),
                        ],
                    ),
                    ft.Row(
                        [
                            txt_esp_ssid,
                            txt_esp_pass,
                            _Button("📡 Salvar Wi-Fi na Placa", icon=icon_val("SEND"), on_click=on_send_wifi_cfg_to_esp),
                        ],
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=9,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#38BDF844"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 13. RADAR WI-FI RF (ESP32-WROOM-32U ANTENA EXTERNA • TELA 12) --
        lbl_wrad_status = ft.Text(
            "📡 Aguardando ESP32-WROOM-32U (Antena Externa)...",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#F59E0B",
            font_family="Consolas",
        )
        lbl_wrad_summary = ft.Text(
            "Redes: 0 • Melhor: -- dBm • Canal Livre: CH1 • Mais Cheio: --",
            size=11,
            color="#94A3B8",
            font_family="Consolas",
        )
        wrad_list_col = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=165)

        def on_wrad_force_scan(_e=None):
            if wifi_scan_col is not None:
                wifi_scan_col.force_scan()
                append_log("📡 Varredura passiva disparada na ESP32-WROOM-32U (Antena Externa)...")

        def refresh_wifi_radar_ui():
            if wifi_scan_col is None:
                return
            ws = wifi_scan_col.get_ui_snapshot()
            lbl_wrad_status.value = f"{'🟢' if ws['online'] else '🟡'} {ws['status_msg']}"
            lbl_wrad_status.color = "#22C55E" if ws["online"] else "#F59E0B"
            best_s = f"{ws['best_rssi']} dBm" if ws["total"] > 0 else "-- dBm"
            bch_s = f"CH{ws['busiest_ch']}" if ws["busiest_ch"] > 0 else "--"
            lbl_wrad_summary.value = (
                f"Redes: {ws['total']} (Scan #{ws['scan_count']} • {ws['last_scan_str']}) • "
                f"Melhor: {best_s} • Livre: CH{ws['free_ch']} • Cheio: {bch_s}"
            )
            wrad_list_col.controls.clear()
            nets = ws.get("networks", [])
            if not nets:
                wrad_list_col.controls.append(
                    ft.Text("Nenhuma rede escaneada ainda. Conecte a ESP32-WROOM-32U na USB.", size=11, color="#64748B")
                )
            else:
                for net in nets[:15]:
                    rssi_v = int(net.get("rssi", -100))
                    r_col = "#22C55E" if rssi_v >= -62 else ("#FACC15" if rssi_v >= -75 else ("#F97316" if rssi_v >= -84 else "#EF4444"))
                    wrad_list_col.controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Text(f"{net.get('ssid', '<OCULTA>')[:24]:<24}", size=11, weight=ft.FontWeight.BOLD, color="#E2E8F0", font_family="Consolas"),
                                    ft.Text(f"CH{int(net.get('ch', 0)):02d}", size=11, color="#38BDF8", font_family="Consolas"),
                                    ft.Text(f"{rssi_v:>4d} dBm ({net.get('quality', 0):>3d}%)", size=11, weight=ft.FontWeight.BOLD, color=r_col, font_family="Consolas"),
                                    ft.Text(net.get("bssid", ""), size=10, color="#64748B", font_family="Consolas"),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            bgcolor="#07090E",
                            border=border_all(1, "#151C28"),
                            border_radius=7,
                            padding=pad_sym(horizontal=8, vertical=4),
                        )
                    )

        sec_wifi_radar = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("📡 RADAR WI-FI RF — ESP32-WROOM-32U ANTENA EXTERNA (TELA 12)", size=13, weight=ft.FontWeight.BOLD, color="#22C55E"),
                            ft.Row(
                                [
                                    ft.OutlinedButton("🔄 Escanear Agora", on_click=on_wrad_force_scan),
                                    ft.OutlinedButton("📺 Exibir Tela 12 na CYD", on_click=lambda e: on_select_screen(12)),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    lbl_wrad_status,
                    lbl_wrad_summary,
                    wrad_list_col,
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#22C55E44"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 14. ANALISE DE REDE, ROTEADOR & FIBRA 700M (TELA 13) --
        lbl_neta_gw = ft.Text(
            "🌐 Roteador / Gateway: detectando...",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#38BDF8",
            font_family="Consolas",
        )
        lbl_neta_spd = ft.Text(
            "Link: ↓0.0 ↑0.0 Mbps • Speedtest: aguarde 'cyd speed' ou clique abaixo",
            size=11,
            color="#94A3B8",
            font_family="Consolas",
        )
        neta_lan_col = ft.Column(spacing=3, scroll=ft.ScrollMode.AUTO, height=110)

        def on_neta_speedtest(_e=None):
            if net_col is not None:
                net_col.trigger_speedtest()
                append_log("⚡ Speedtest Fibra iniciado (acompanhe na Tela 13 da CYD)...")

        def on_neta_open_router(_e=None):
            if net_col is not None:
                url = net_col.get_ui_snapshot().get("admin_url", "")
                if url:
                    webbrowser.open(url)
                    append_log(f"🌐 Abrindo painel de administração do roteador: {url}")

        def refresh_net_analyzer_ui():
            if net_col is None:
                return
            ns = net_col.get_ui_snapshot()
            spd = ns.get("speedtest", {})
            lbl_neta_gw.value = (
                f"{'🟢' if ns.get('gw_up') else '🔴'} GW {ns.get('gateway_ip','--')} ({ns.get('gw_ms',0):.1f}ms • jit {ns.get('gw_jit',0):.1f}ms • loss {ns.get('gw_loss',0)}%) • "
                f"WAN {ns.get('wan_ms',0):.1f}ms • DNS {ns.get('dns_ms',0)}ms • ISP: {ns.get('isp','--')}"
            )
            if spd.get("running"):
                spd_s = "⏳ Medindo velocidade..."
            elif spd.get("dl_mbps", 0) > 0:
                spd_s = f"DL {spd['dl_mbps']:.1f} Mbps ({spd.get('plan_pct',0)}%) | UL {spd['ul_mbps']:.1f} Mbps ({spd.get('time_str')})"
            else:
                spd_s = "Sem teste recente"
            lbl_neta_spd.value = (
                f"Tempo real: ↓{ns.get('rx_mbps',0):.1f} ↑{ns.get('tx_mbps',0):.1f} Mbps (Plano {ns.get('plan_mbps',700)}M) • Speedtest: {spd_s}"
            )
            neta_lan_col.controls.clear()
            for h in ns.get("lan_hosts", [])[:10]:
                neta_lan_col.controls.append(
                    ft.Text(
                        f"  • {h.get('ip',''):<15}  {h.get('mac',''):<17}  [{h.get('tag','')}] ({h.get('state','')})",
                        size=10,
                        color="#CBD5E1",
                        font_family="Consolas",
                    )
                )

        sec_net_analyzer = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🌐 ANÁLISE DE REDE, ROTEADOR & LINK FIBRA 700 Mbps (TELA 13)", size=13, weight=ft.FontWeight.BOLD, color="#38BDF8"),
                            ft.Row(
                                [
                                    ft.OutlinedButton("⚡ Speedtest Fibra", on_click=on_neta_speedtest),
                                    ft.OutlinedButton("🌐 Abrir Roteador", on_click=on_neta_open_router),
                                    ft.OutlinedButton("📺 Exibir Tela 13 na CYD", on_click=lambda e: on_select_screen(13)),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    lbl_neta_gw,
                    lbl_neta_spd,
                    neta_lan_col,
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#38BDF844"),
            border_radius=14,
            padding=14,
        )

        # ---------------- 14. AGENTE IA DE REDES (GEMINI + IA LOCAL) ----------
        lbl_ai_status = ft.Text(
            "🤖 Agente IA: inicializando...",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#C084FC",
            font_family="Consolas",
        )
        txt_ai_question = ft.TextField(
            hint_text="Pergunte ao Agente IA sobre sua rede/RF (ex: qual melhor canal 2.4GHz agora?)",
            expand=True,
            text_size=12,
            color="#E2E8F0",
            bgcolor="#05070B",
            border_color="#2E1065",
            focused_border_color="#C084FC",
        )
        txt_ai_output = ft.Text(
            value="Clique em 'Relatório Completo' ou 'Analisar RF' para gerar diagnóstico inteligente via Gemini ou IA Local (Ollama).",
            size=11,
            color="#CBD5E1",
            font_family="Consolas",
            selectable=True,
        )

        def refresh_ai_ui():
            if ai_eng is None:
                return
            st_a = ai_eng.get_status_snapshot(probe_local=False)
            g_s = f"Gemini:{'ON' if st_a.get('gemini_key_set') else 'NO-KEY'} ({st_a.get('gemini_model','')})"
            l_s = f"Local:{'ON' if st_a.get('local_online') else 'OFF'} ({st_a.get('active_local_model') or '--'})"
            lbl_ai_status.value = f"🤖 Modo: {st_a.get('ai_provider','auto').upper()} • {g_s} • {l_s}"
            if st_a.get("last_markdown_preview"):
                txt_ai_output.value = st_a["last_markdown_preview"]

        def _run_ai_gui(mode_req: str, question_s: str = ""):
            if ai_eng is None:
                return
            lbl_ai_status.value = f"⏳ Agente IA processando análise ({mode_req})..."
            safe_update(lbl_ai_status)

            def _bg():
                res = ai_eng.generate_report(mode=mode_req, question=question_s, save_file=(mode_req != "ask"))
                if res.get("ok"):
                    cyd_lns = res.get("cyd_lines", [])
                    if cyd_lns:
                        for ln in cyd_lns:
                            term_eng.append_line(ln)
                        for i in range(0, len(cyd_lns), 4):
                            serial_mgr.send_event({"term": {"lines": cyd_lns[i : i + 4], "cmd": f"ai {mode_req}", "auto_scr": (i == 0)}})
                    txt_ai_output.value = (res.get("markdown", "") or "")[:3500]
                    append_log(f"🤖 Relatório IA ({mode_req}) via {res.get('provider_used')}/{res.get('model_used')} ({res.get('elapsed_s')}s)")
                else:
                    txt_ai_output.value = f"Erro IA: {res.get('error', 'desconhecido')}"
                refresh_ai_ui()
                safe_update(lbl_ai_status, txt_ai_output)

            threading.Thread(target=_bg, daemon=True).start()

        refresh_ai_ui()

        sec_ai_analyst = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("🤖 AGENTE IA DE REDES (GOOGLE GEMINI + IA LOCAL OLLAMA)", size=13, weight=ft.FontWeight.BOLD, color="#C084FC"),
                            ft.Row(
                                [
                                    ft.OutlinedButton("🧠 Relatório Completo", on_click=lambda e: _run_ai_gui("full")),
                                    ft.OutlinedButton("📡 Analisar Espectro RF", on_click=lambda e: _run_ai_gui("rf")),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    lbl_ai_status,
                    ft.Row(
                        [
                            txt_ai_question,
                            _Button("💬 Perguntar IA", on_click=lambda e: _run_ai_gui("ask", txt_ai_question.value or "")),
                        ],
                        spacing=8,
                    ),
                    ft.Container(
                        content=ft.Column([txt_ai_output], scroll=ft.ScrollMode.AUTO, height=170),
                        bgcolor="#05070B",
                        border=border_all(1, "#2E1065"),
                        border_radius=8,
                        padding=10,
                        width=float("inf"),
                    ),
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#A855F744"),
            border_radius=14,
            padding=14,
        )

        # ---------------- CONSOLE SERIAL & LOG (COM COPIAR E LIMPAR) ---------
        txt_console = ft.Text(
            value="Inicializando CYD Cyber Deck v4.0 (Telemetria, Clima Regional, News Feed, Terminal CYD, Mercado, Portfólio, Pomodoro & Mídia)...",
            size=11,
            color="#94A3B8",
            font_family="Consolas",
            selectable=True,
        )

        def on_copy_logs(_e):
            if txt_console.value:
                copy_text_to_clipboard(txt_console.value, page)

        def on_clear_logs(_e):
            log_lines.clear()
            txt_console.value = "Console limpo."
            try:
                page.update()
            except Exception:
                pass

        sec_console = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("📡 CONSOLE SERIAL & DIAGNÓSTICO EM TEMPO REAL", size=12, weight=ft.FontWeight.BOLD, color="#94A3B8"),
                            ft.Row(
                                [
                                    ft.OutlinedButton("📋 Copiar Log", on_click=on_copy_logs),
                                    ft.OutlinedButton("🗑️ Limpar", on_click=on_clear_logs),
                                ],
                                spacing=8,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=txt_console,
                        bgcolor="#05070B",
                        border=border_all(1, "#151C28"),
                        border_radius=8,
                        padding=10,
                        width=float("inf"),
                    ),
                ],
                spacing=8,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, "#1A2232"),
            border_radius=14,
            padding=12,
        )

        # ---------------- SERVIDOR WEB / REST API MOBILE (WI-FI) -------------
        class MobileRequestHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Mantem o terminal limpo

            def _send_cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

            def do_OPTIONS(self):
                self.send_response(204)
                self._send_cors()
                self.end_headers()

            def _build_mobile_status(self) -> dict:
                return {
                    "screen": state["screen"],
                    "hex_color": state["hex_color"],
                    "color": state["color"],
                    "bg": state["bg"],
                    "brt": state["brt"],
                    "ticker": state["ticker"],
                    "sleep_enabled": state["sleep_enabled"],
                    "night_mode_enabled": state["night_mode_enabled"],
                    "sd_files": state["sd_files"],
                    "sys": col.sample_sys() if col else {},
                    "mkt": mkt_col.get_market_dict() if mkt_col else {},
                    "portf": mkt_col.compute_portfolio(state["portfolio"], state["portfolio_pnl_mode"])[0] if mkt_col else {},
                    "pomodoro": pomo_eng.get_ui_snapshot() if pomo_eng else {},
                    "media": media_col.get_ui_snapshot() if media_col else {},
                    "weather": wth_col.get_ui_snapshot() if wth_col else {},
                    "news": gems_eng.get_ui_snapshot() if gems_eng else {},
                    "gems": gems_eng.get_ui_snapshot() if gems_eng else {},
                    "terminal": term_eng.get_snapshot() if term_eng else {},
                    "wifi_radar": wifi_scan_col.get_ui_snapshot() if wifi_scan_col else {},
                    "net_analyzer": net_col.get_ui_snapshot() if net_col else {},
                    "ai": ai_eng.get_status_snapshot(probe_local=False) if ai_eng else {},
                    "upload": upload_state,
                    "connected": True,
                }

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                p = parsed.path

                if p in ("/", "/index.html"):
                    content = mobile_web.HTML_MOBILE_APP.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "no-cache")
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(content)

                elif p == "/api/status":
                    payload = self._build_mobile_status()
                    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(content)

                elif p == "/api/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self._send_cors()
                    self.end_headers()
                    while state["running"]:
                        payload = self._build_mobile_status()
                        chunk = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
                            break
                        time.sleep(1.0)

                elif p == "/api/screen":
                    qs = urllib.parse.parse_qs(parsed.query)
                    val = qs.get("s", qs.get("screen", [None]))[0]
                    if val is not None:
                        try:
                            scr_idx = int(val)
                            if 0 <= scr_idx <= 13:
                                on_select_screen(scr_idx)
                                append_log(f"📱 Smartphone selecionou Tela {scr_idx}")
                        except Exception:
                            pass
                    content = json.dumps({"ok": True, "screen": state["screen"]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(content)

                else:
                    self.send_response(404)
                    self._send_cors()
                    self.end_headers()

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                p = parsed.path
                length = int(self.headers.get("Content-Length", 0))
                body = {}
                if length > 0:
                    try:
                        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
                        body = json.loads(raw)
                    except Exception:
                        pass

                ok = True
                err_msg = ""

                if p == "/api/screen":
                    scr = int(body.get("screen", state["screen"]))
                    if 0 <= scr <= 13:
                        on_select_screen(scr)
                        append_log(f"📱 Smartphone selecionou Tela {scr}")
                    else:
                        ok = False
                        err_msg = "Tela inválida (0-13)"

                elif p == "/api/net_analyzer":
                    act = str(body.get("action", "refresh")).lower()
                    if net_col is not None:
                        if act == "speedtest":
                            net_col.trigger_speedtest()
                            append_log("⚡ Speedtest Fibra disparado via Web/CLI")
                        elif act == "set_plan" and body.get("plan_mbps"):
                            pm = int(body["plan_mbps"])
                            net_col.set_plan_mbps(pm)
                            cfg["net_plan_mbps"] = pm
                            save_ui_config(cfg)
                        elif act == "router_diag":
                            diag = net_col.get_router_diagnostics()
                            content = json.dumps({"ok": True, "diag": diag}, ensure_ascii=False).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            self.send_header("Content-Length", str(len(content)))
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(content)
                            return
                        else:
                            net_col.force_refresh()

                elif p == "/api/wifi_radar":
                    act = str(body.get("action", "scan")).lower()
                    if wifi_scan_col is not None:
                        if act == "config":
                            wifi_scan_col.configure(
                                enabled=body.get("enabled"),
                                port=body.get("port"),
                                interval_s=body.get("interval_s"),
                            )
                        else:
                            wifi_scan_col.force_scan()
                            append_log("📡 Smartphone/Web solicitou varredura no Radar Wi-Fi RF")

                elif p == "/api/weather":
                    act = str(body.get("action", "refresh")).lower()
                    if act == "city" and body.get("city"):
                        txt_weather_city.value = str(body["city"]).strip()
                        on_save_weather_city(None)
                    elif act == "storm":
                        on_toggle_storm_sim()
                    else:
                        on_refresh_weather(None)

                elif p in ("/api/news", "/api/gem"):
                    act = str(body.get("action", "next")).lower()
                    if act == "toggle_topic" and body.get("topic"):
                        on_toggle_news_topic(str(body["topic"]).strip())
                    elif act == "topics" and isinstance(body.get("topics"), list):
                        state["news_topics"] = [str(x).strip() for x in body["topics"] if str(x).strip()]
                        gems_eng.set_topics(state["news_topics"], state["news_api_key"])
                        persist_and_queue_ui()
                        refresh_weather_gems_ui()
                    elif act == "refresh":
                        on_manual_news_refresh(None)
                    else:
                        on_next_news_headline(None)

                elif p == "/api/terminal":
                    cmd_str = str(body.get("cmd", "")).strip()
                    wait_flag = bool(body.get("wait", False))
                    req_to = body.get("timeout")
                    is_ai_cmd = cmd_str.lower().startswith(("ai ", "ia ", "gemini ")) or cmd_str.lower() in ("ai", "ia", "gemini")
                    eff_to = float(req_to) if req_to else (90.0 if is_ai_cmd else 10.0)
                    if cmd_str:
                        snap_pre = term_eng.get_snapshot()
                        lines_before = len(snap_pre.get("lines", []))
                        seq_before = snap_pre.get("seq", lines_before)
                        out_lines = run_terminal_command(cmd_str, wait=wait_flag, timeout_s=eff_to)
                        res_t = {
                            "ok": True,
                            "state": get_ui_dict(),
                            "seq": seq_before,
                            "lines_before": lines_before,
                            "output": out_lines,
                        }
                        content = json.dumps(res_t, ensure_ascii=False).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Length", str(len(content)))
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    else:
                        ok = False
                        err_msg = "Comando vazio"

                elif p == "/api/ai":
                    if ai_eng is None:
                        ok, err_msg = False, "Modulo ai_analyst indisponivel"
                    else:
                        act = str(body.get("action", "status")).lower().strip()
                        if act == "status":
                            res_a = {"ok": True, "ai": ai_eng.get_status_snapshot(probe_local=True)}
                        elif act == "models":
                            onl, mods, knd = ai_eng.list_local_models(timeout=2.5, force=True)
                            res_a = {
                                "ok": True,
                                "local_online": onl,
                                "local_kind": knd,
                                "local_models": mods,
                                "ai": ai_eng.get_status_snapshot(probe_local=False),
                            }
                        elif act == "config":
                            pub = ai_eng.configure(
                                ai_provider=body.get("ai_provider"),
                                gemini_api_key=body.get("gemini_api_key"),
                                gemini_model=body.get("gemini_model"),
                                local_ai_url=body.get("local_ai_url"),
                                local_ai_model=body.get("local_ai_model"),
                                persist=True,
                            )
                            append_log(f"🤖 Config IA atualizada: provedor={pub['ai_provider']} | gemini_key={'SET' if pub['gemini_key_set'] else 'UNSET'}")
                            res_a = {"ok": True, "config": pub, "ai": ai_eng.get_status_snapshot(probe_local=True)}
                        elif act in ("report", "full", "rf", "ask"):
                            mode_req = "rf" if act == "rf" else ("ask" if act == "ask" else "full")
                            prov_req = body.get("provider")
                            q_req = str(body.get("question", "")).strip()
                            res_a = ai_eng.generate_report(
                                mode=mode_req,
                                provider=prov_req,
                                question=q_req,
                                save_file=(mode_req != "ask"),
                            )
                            if res_a.get("ok") and body.get("push_cyd", True):
                                cyd_lns = res_a.get("cyd_lines", [])
                                if cyd_lns:
                                    for ln in cyd_lns:
                                        term_eng.append_line(ln)
                                    for i in range(0, len(cyd_lns), 4):
                                        serial_mgr.send_event({
                                            "term": {
                                                "lines": cyd_lns[i : i + 4],
                                                "cmd": f"ai {mode_req}",
                                                "auto_scr": (i == 0 and bool(body.get("switch_screen", True))),
                                            }
                                        })
                                    if body.get("switch_screen", True):
                                        state["screen"] = 11
                        else:
                            res_a = {"ok": False, "error": f"Acao IA desconhecida: {act}"}
                        content = json.dumps(res_a, ensure_ascii=False).encode("utf-8")
                        self.send_response(200 if res_a.get("ok", True) else 400)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Length", str(len(content)))
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(content)
                        return

                elif p == "/api/color":
                    hex_c = body.get("hex", state["hex_color"])
                    apply_new_hex(hex_c, update_sliders=True)
                    append_log(f"📱 Smartphone alterou cor para {hex_c}")

                elif p == "/api/brightness":
                    brt = max(0, min(255, int(body.get("brt", state["brt"]))))
                    slider_brt.value = brt
                    lbl_brt_value.value = f"{int(round(brt / 255.0 * 100))}% ({brt}/255)"
                    state["brt"] = brt
                    persist_and_queue_ui()
                    append_log(f"📱 Smartphone alterou brilho para {brt}")

                elif p == "/api/bg":
                    bg_val = body.get("bg", state["bg"])
                    state["bg"] = bg_val
                    dd_bg.value = bg_val
                    persist_and_queue_ui()
                    append_log(f"📱 Smartphone alterou fundo para '{bg_val}'")

                elif p == "/api/ticker":
                    if "ticker" in body:
                        state["ticker"] = bool(body["ticker"])
                    else:
                        state["ticker"] = not state["ticker"]
                    new_lbl = "📟 Letreiro Rodapé: ATIVO" if state["ticker"] else "📟 Letreiro Rodapé: OCULTO"
                    set_btn_text(btn_ticker_toggle, new_lbl)
                    set_btn_text(btn_ticker_quick, new_lbl)
                    persist_and_queue_ui()
                    append_log(f"📱 Smartphone alterou letreiro para {'ATIVO' if state['ticker'] else 'OCULTO'}")

                elif p == "/api/pomodoro":
                    act = str(body.get("action", "toggle")).lower()
                    if act == "toggle":
                        on_pomo_toggle()
                    elif act == "reset":
                        on_pomo_reset()
                    elif act == "skip":
                        on_pomo_skip()
                    elif act == "phase":
                        on_pomo_select_phase(str(body.get("phase", "WORK")))

                elif p == "/api/media":
                    act = str(body.get("action", "play_pause")).lower()
                    if act in ("play_pause", "next", "prev"):
                        media_col.control(act)
                        append_log(f"📱 Smartphone enviou comando de mídia: {act}")
                    elif act == "sync_cover":
                        on_manual_cover_sync(None)

                elif p == "/api/power":
                    if "sleep_enabled" in body:
                        state["sleep_enabled"] = bool(body["sleep_enabled"])
                        sw_sleep.value = state["sleep_enabled"]
                    if "night_mode_enabled" in body:
                        state["night_mode_enabled"] = bool(body["night_mode_enabled"])
                        sw_night.value = state["night_mode_enabled"]
                    persist_and_queue_ui()
                    try:
                        page.update()
                    except Exception:
                        pass

                elif p == "/api/test_alert":
                    ui_event_queue.put({"alrt": {"bz": True, "led": state["color"], "p": 2}})
                    append_log("📱 Smartphone disparou teste de Buzzer & LED RGB na CYD")

                elif p == "/api/refresh_sd":
                    request_sd_files()
                    append_log("📱 Smartphone solicitou sincronização com Cartão SD")

                elif p == "/api/upload":
                    fname = body.get("filename", "mobile_wall.jpg")
                    b64_data = body.get("data", "")
                    if b64_data:
                        try:
                            raw_bytes = base64.b64decode(b64_data)
                            start_file_transfer(filename=fname, raw_bytes=raw_bytes)
                            append_log(f"📱 Smartphone enviou foto '{fname}' ({len(raw_bytes)/1024:.1f} KB)")
                        except Exception as ex:
                            ok = False
                            err_msg = str(ex)
                    else:
                        ok = False
                        err_msg = "Nenhum dado de imagem recebido"

                else:
                    self.send_response(404)
                    self._send_cors()
                    self.end_headers()
                    return

                res_payload = {"ok": ok, "state": get_ui_dict()}
                if err_msg:
                    res_payload["error"] = err_msg
                content = json.dumps(res_payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._send_cors()
                self.end_headers()
                self.wfile.write(content)

        class _MobileHTTPServer(http.server.ThreadingHTTPServer):
            allow_reuse_address = not IS_WINDOWS

            def server_bind(self):
                if IS_WINDOWS and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    try:
                        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    except OSError:
                        pass
                super().server_bind()

        mobile_port = 8088
        mobile_server = None
        for test_port in (8088, 8089, 8550, 8551, 8552):
            try:
                mobile_server = _MobileHTTPServer(("0.0.0.0", test_port), MobileRequestHandler)
                mobile_port = test_port
                break
            except OSError:
                continue

        lan_ip = get_local_lan_ip()
        mobile_url = f"http://{lan_ip}:{mobile_port}"
        qr_b64 = generate_qr_base64(mobile_url)

        if mobile_server:
            threading.Thread(target=mobile_server.serve_forever, daemon=True).start()

        lbl_mobile_title = ft.Text(
            "📱 CONTROLE REMOTO PELO CELULAR (WI-FI)",
            size=13,
            weight=ft.FontWeight.BOLD,
            color=state["hex_color"],
        )

        def on_copy_url(_e):
            try:
                copy_text_to_clipboard(mobile_url, page)
                append_log(f"Link copiado: {mobile_url}")
            except Exception:
                pass

        def on_open_browser(_e):
            try:
                webbrowser.open(mobile_url)
                append_log(f"Abrindo interface mobile no navegador: {mobile_url}")
            except Exception:
                pass

        qr_widget = (
            ft.Image(
                src=f"data:image/png;base64,{qr_b64}",
                width=100,
                height=100,
                fit="contain",
            )
            if qr_b64
            else ft.Icon(icon_val("QR_CODE_2") or ft.Icons.QR_CODE_2, size=70, color=state["hex_color"])
        )

        sec_mobile_remote = ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    lbl_mobile_title,
                                    ft.Container(
                                        content=ft.Text(f"PORTA {mobile_port} • SSE ATIVO", size=10, weight=ft.FontWeight.BOLD, color="#22C55E"),
                                        bgcolor="#142B1F",
                                        border=border_all(1, "#22C55E44"),
                                        border_radius=6,
                                        padding=pad_sym(horizontal=8, vertical=2),
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Text(
                                "Aponte a câmera do seu celular para o QR Code ou acesse o link abaixo na mesma rede Wi-Fi.\n"
                                "Alterne as 12 telas, veja o Clima de Votuporanga, customize o News Feed e execute comandos no Terminal CYD!",
                                size=11,
                                color="#94A3B8",
                            ),
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Text(mobile_url, size=13, weight=ft.FontWeight.BOLD, font_family="Consolas", color="#FFFFFF"),
                                        bgcolor="#05070B",
                                        border=border_all(1, "#1E2738"),
                                        border_radius=8,
                                        padding=pad_sym(horizontal=12, vertical=6),
                                    ),
                                    ft.OutlinedButton("Copiar Link", icon=icon_val("CONTENT_COPY"), on_click=on_copy_url),
                                    ft.OutlinedButton("Abrir no PC", icon=icon_val("OPEN_IN_BROWSER"), on_click=on_open_browser),
                                ],
                                spacing=8,
                            ),
                        ],
                        spacing=6,
                        expand=True,
                    ),
                    ft.Column(
                        [
                            ft.Container(
                                content=qr_widget,
                                bgcolor="#FFFFFF",
                                padding=4,
                                border_radius=8,
                                border=border_all(1, "#FFFFFF33"),
                            ),
                            ft.Text("Aponte a câmera", size=10, color="#64748B", weight=ft.FontWeight.W_500),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=4,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#0B0F17",
            border=border_all(1, state["hex_color"]),
            border_radius=14,
            padding=14,
        )

        # ---------------- NAVIGATION RAIL LATERAL EXPANSIVEL (CLEAN UI) ------
        tab_defs = [
            (0, "Painel & Telas", "DASHBOARD"),
            (1, "Foco & Mídia", "ALBUM"),
            (2, "Mercado & Carteira", "ACCOUNT_BALANCE_WALLET"),
            (3, "Clima & News", "NEWSPAPER"),
            (4, "Terminal CYD", "TERMINAL"),
            (5, "Estúdio & Energia", "PALETTE"),
            (6, "Alertas Físicos", "NOTIFICATIONS_ACTIVE"),
            (7, "Wi-Fi & Remoto", "WIFI"),
        ]

        tab_views = [
            # Aba 0: Painel Geral & Seletor de 12 Telas (Home limpa e rápida)
            ft.Column(
                [telemetry_row, sec_market_quick, sec_screens],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=True,
            ),
            # Aba 1: Produtividade Pomodoro (Tela 8) + Spotify & YouTube Music (Tela 9)
            ft.Column(
                [ft.Row([sec_pomodoro, sec_media], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
            # Aba 2: Finanças — Cotações ao Vivo (Tela 6) + Portfólio Pessoal (Tela 7)
            ft.Column(
                [sec_market_live, sec_portfolio],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
            # Aba 3: Módulo 1 — Clima Regional (Votuporanga) + Feed de Notícias Customizável (Tela 10 / SCR_NEWS)
            ft.Column(
                [ft.Row([sec_weather_regional, sec_news_feed], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
            # Aba 4: Módulo 2 — O Terminal CYD: Ferramentas de Rede e Sistema (Tela 11 / SCR_TERMINAL)
            ft.Column(
                [sec_cyber_terminal],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
            # Aba 5: Aparência & Energia — Cores RGB565 + Wallpaper SD + Brilho PWM + Sleep/Noturno
            ft.Column(
                [sec_colors, sec_bg_and_brt, sec_sleep],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
            # Aba 6: Alertas Físicos Avançados (Buzzer & LED RGB)
            ft.Column(
                [sec_alerts],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
            # Aba 7: Radar Wi-Fi RF (Tela 12) + Análise de Rede (Tela 13) + Agente IA + Wi-Fi UDP + Controle Remoto + Console
            ft.Column(
                [sec_ai_analyst, sec_wifi_radar, sec_net_analyzer, sec_wifi_udp, sec_mobile_remote, sec_console],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                visible=False,
            ),
        ]

        rail_destinations = []
        for t_idx, t_title, t_icon_name in tab_defs:
            rail_destinations.append(
                ft.NavigationRailDestination(
                    icon=ft.Icon(icon_val(t_icon_name), size=19, color="#64748B"),
                    selected_icon=ft.Icon(icon_val(t_icon_name), size=20, color=state["hex_color"]),
                    label=t_title,
                )
            )

        def on_rail_change(e):
            try:
                idx_sel = int(e.control.selected_index)
            except Exception:
                idx_sel = 0
            switch_tab(idx_sel)

        nav_rail = ft.NavigationRail(
            selected_index=state["active_tab"],
            extended=bool(state.get("rail_extended", True)),
            min_width=64,
            min_extended_width=192,
            bgcolor="#0A0E17",
            indicator_color="#162032",
            destinations=rail_destinations,
            on_change=on_rail_change,
            expand=True,
        )

        lbl_rail_brand = ft.Text(
            "CYBER DECK",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#E2E8F0",
            font_family="Consolas",
            visible=bool(state.get("rail_extended", True)),
        )
        rail_logo_widget = (
            ft.Image(
                src=png_file,
                width=22,
                height=22,
                border_radius=5,
                fit=ft.BoxFit.CONTAIN if hasattr(ft, "BoxFit") else "contain",
            )
            if (png_file and os.path.exists(png_file))
            else ft.Icon(icon_val("MEMORY"), size=18, color=state["hex_color"])
        )

        # Card lateral de diagnóstico da Conexão Serial no rodapé do NavigationRail
        rail_serial_dot = ft.Container(width=9, height=9, border_radius=5, bgcolor="#F59E0B")
        lbl_rail_serial_title = ft.Text(
            "USB: Buscando...",
            size=11,
            weight=ft.FontWeight.BOLD,
            color="#E2E8F0",
            font_family="Consolas",
            visible=bool(state.get("rail_extended", True)),
        )
        lbl_rail_serial_sub = ft.Text(
            "115200 bps • Fila 0",
            size=9,
            color="#64748B",
            font_family="Consolas",
            visible=bool(state.get("rail_extended", True)),
        )
        btn_rail_reconnect = ft.IconButton(
            icon=icon_val("SYNC"),
            icon_size=14,
            icon_color="#38BDF8",
            tooltip="Forçar Reconexão / Flush Serial (115200 bps)",
            width=24,
            height=24,
            padding=0,
            visible=bool(state.get("rail_extended", True)),
            on_click=lambda e: (
                serial_mgr.request_reconnect(),
                append_log("🔄 Reconexão e flush de buffers Serial solicitados manualmente."),
            ),
        )
        rail_serial_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row([rail_serial_dot, lbl_rail_serial_title], spacing=6, tight=True),
                            btn_rail_reconnect,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    lbl_rail_serial_sub,
                ],
                spacing=2,
                tight=True,
            ),
            bgcolor="#0F172A",
            border=border_all(1, "#1E293B"),
            border_radius=10,
            padding=pad_sym(horizontal=10, vertical=7),
            ink=True,
            tooltip="Diagnóstico Serial Assíncrono (115200 bps) — Clique para abrir Remoto & Serial",
            on_click=lambda e: switch_tab(7),
        )

        def toggle_rail_extended(e):
            ext = not bool(state.get("rail_extended", True))
            state["rail_extended"] = ext
            nav_rail.extended = ext
            lbl_rail_brand.visible = ext
            lbl_rail_serial_title.visible = ext
            lbl_rail_serial_sub.visible = ext
            btn_rail_reconnect.visible = ext
            btn_rail_toggle.icon = icon_val("MENU_OPEN" if ext else "MENU")
            sidebar_rail_box.width = 204 if ext else 74
            safe_update(sidebar_rail_box)

        btn_rail_toggle = ft.IconButton(
            icon=icon_val("MENU_OPEN" if state.get("rail_extended", True) else "MENU"),
            icon_size=17,
            icon_color="#94A3B8",
            tooltip="Expandir / Recolher Menu Lateral (Clean UI)",
            width=28,
            height=28,
            padding=0,
            on_click=toggle_rail_extended,
        )

        rail_brand_header = ft.Container(
            content=ft.Row(
                [
                    ft.Row([rail_logo_widget, lbl_rail_brand], spacing=7, tight=True),
                    btn_rail_toggle,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=pad_sym(horizontal=8, vertical=4),
        )

        sidebar_rail_box = ft.Container(
            content=ft.Column(
                [
                    rail_brand_header,
                    ft.Divider(height=1, color="#182030"),
                    ft.Container(content=nav_rail, expand=True),
                    ft.Divider(height=1, color="#182030"),
                    rail_serial_card,
                ],
                spacing=6,
                expand=True,
            ),
            width=204 if state.get("rail_extended", True) else 74,
            bgcolor="#0A0E17",
            border=border_all(1, "#182030"),
            border_radius=12,
            padding=pad_sym(horizontal=6, vertical=8),
        )

        def refresh_tabs_ui():
            h = state["hex_color"]
            act = int(state["active_tab"])
            nav_rail.selected_index = act
            for idx_t, dest in enumerate(rail_destinations):
                try:
                    if hasattr(dest, "selected_icon") and dest.selected_icon is not None:
                        dest.selected_icon.color = h
                except Exception:
                    pass
                tab_views[idx_t].visible = (idx_t == act)

            # Ao alternar para uma aba, sincroniza imediatamente seus controles em cache
            if act == 1:
                refresh_focus_media_ui()
            elif act == 2:
                refresh_portfolio_ui()
            elif act == 3:
                refresh_weather_gems_ui()
            elif act == 4:
                refresh_terminal_ui()
            elif act == 7:
                refresh_wifi_radar_ui()
                refresh_net_analyzer_ui()
                txt_console.value = "\n".join(log_lines)

            safe_update(nav_rail, tabs_viewport)

        tabs_viewport = ft.Container(
            content=ft.Stack(tab_views, expand=True),
            expand=True,
        )

        body_split_row = ft.Row(
            [sidebar_rail_box, tabs_viewport],
            spacing=10,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        page.add(
            header_row,
            body_split_row,
        )

        # ---------------- SERIAL CALLBACKS & STATE MANAGEMENT GRANULAR -------
        def refresh_serial_indicators(snap: dict | None = None):
            s = snap or serial_mgr.get_status_snapshot()
            st_code = str(s.get("state", "searching")).lower()
            port_str = s.get("port") or ""
            tx_cnt = s.get("tx_packets", 0)
            bps = s.get("tx_bytes_sec", 0)
            transport = str(s.get("transport", "NONE")).upper()

            if transport == "UDP":
                c_hex = "#38BDF8"
                b_hex = "#0284C7"
                target_str = s.get("udp_target", "") or "UDP:8888"
                rtt = s.get("udp_rtt_ms", 0)
                hdr_txt = f"Wi-Fi • {target_str}"
                rail_t = "Wi-Fi UDP"
                rail_s = f"{target_str} • {rtt}ms"
            elif s.get("connected") and st_code == "connected":
                c_hex = "#22C55E"
                b_hex = "#14532D"
                hdr_txt = f"{port_str} • 115k"
                rail_t = f"ON • {port_str}"
                rail_s = f"115200 • TX {tx_cnt} ({bps} B/s)"
            elif st_code in ("connecting", "reconnecting"):
                c_hex = "#38BDF8"
                b_hex = "#0284C7"
                hdr_txt = f"Abrindo {port_str}..."
                rail_t = f"Sync {port_str}..."
                rail_s = "Handshake USB..."
            elif st_code in ("error", "disconnected") and s.get("last_error"):
                c_hex = "#EF4444"
                b_hex = "#7F1D1D"
                hdr_txt = "Reconectando..."
                rail_t = "Erro USB"
                rail_s = (s.get("last_error") or "Reconectando...")[:24]
            else:
                c_hex = "#F59E0B"
                b_hex = "#78350F"
                hdr_txt = "Buscando CYD..."
                rail_t = "Sem Conexão"
                rail_s = "Aguardando USB/Wi-Fi..."

            status_dot.bgcolor = c_hex
            status_badge.border = border_all(1, b_hex)
            lbl_usb_status.value = hdr_txt

            rail_serial_dot.bgcolor = c_hex
            rail_serial_card.border = border_all(1, b_hex)
            lbl_rail_serial_title.value = rail_t
            lbl_rail_serial_sub.value = rail_s

            if transport == "UDP":
                lbl_udp_route_badge.value = f"📶 ROTA ATIVA: WI-FI UDP ({s.get('udp_target', '8888')})"
                lbl_udp_route_badge.color = "#38BDF8"
            elif s.get("connected") and st_code == "connected":
                lbl_udp_route_badge.value = f"🔌 ROTA ATIVA: USB SERIAL ({port_str})"
                lbl_udp_route_badge.color = "#22C55E"
            else:
                lbl_udp_route_badge.value = "⚠️ NENHUM TRANSPORTE CONECTADO"
                lbl_udp_route_badge.color = "#F59E0B"

            rtt_val = s.get("udp_rtt_ms", 0)
            tx_udp = s.get("udp_tx", 0)
            drp = s.get("udp_drop", 0)
            target = s.get("udp_target", "") or "Sem IP configurado"
            lbl_udp_diag.value = f"Destino: {target} • RTT: {rtt_val}ms • TX UDP: {tx_udp} • Drops: {drp}"

            dirty_list = [status_badge, rail_serial_card]
            if state.get("active_tab") == 7:
                dirty_list.extend([lbl_udp_route_badge, lbl_udp_diag])
            safe_update(*dirty_list)

        def on_serial_status_change(snap: dict):
            st_code = str(snap.get("state", "")).lower()
            port_str = snap.get("port", "")
            if st_code == "connected":
                state["ui_dirty"] = True
                append_log(f"✅ SerialManager conectado em {port_str} ({snap.get('baud', BAUD)} bps — I/O Assíncrono)")
                request_sd_files()
            elif st_code in ("error", "disconnected"):
                append_log(f"⚠️ Serial desconectada ({snap.get('last_error', 'erro I/O')}). Tentando reconectar...")
            refresh_serial_indicators(snap)

        def on_serial_rx_line(raw: str):
            if raw.startswith("TERM_LOG:"):
                t_line = raw.split("TERM_LOG:", 1)[1].strip()
                if t_line:
                    term_eng.append_line(t_line)
                    if state.get("active_tab") == 4:
                        refresh_terminal_ui()
                        safe_update(sec_cyber_terminal)
            elif raw == "MONITOR_READY":
                state["ui_dirty"] = True
                state["synced_cover_id"] = ""  # Reenvia capa atual após reboot da CYD
                request_sd_files()
            elif raw.startswith("SD_FILES:"):
                try:
                    files = json.loads(raw.split("SD_FILES:", 1)[1])
                    if isinstance(files, list):
                        base_opts = ["none", "terminal", "z1p0"]
                        merged = base_opts + [f for f in files if f not in base_opts and not str(f).startswith("_media")]
                        state["sd_files"] = merged
                        cfg["sd_files"] = merged
                        save_ui_config(cfg)
                        dd_bg.options = make_dropdown_options(merged)
                        if state.get("active_tab") == 5:
                            safe_update(dd_bg)
                        if files:
                            append_log(f"SD Card sincronizado: {len(files)} imagem(ns) encontrada(s): {', '.join(files)}")
                        else:
                            append_log("SD Card sincronizado: Nenhuma imagem encontrada ou cartão não detectado.")
                except Exception:
                    pass
            elif raw.startswith("SD_INIT:OK"):
                state["sd_missing_warned"] = False
                append_log(f"Cartão MicroSD detectado e montado com sucesso ({raw}).")
            elif raw.startswith("SD_INIT:FAIL"):
                append_log("⚠️ Cartão MicroSD não detectado pela placa CYD. Verifique se está inserido e formatado em FAT32.")
            elif raw.startswith("JPG_ERR:"):
                append_log(f"⚠️ Erro no hardware CYD ao decodificar imagem JPEG ({raw}).")

        serial_mgr.set_callbacks(on_rx_line=on_serial_rx_line, on_status_change=on_serial_status_change)

        def _fmt_chg(lbl_c, chg_val: float):
            lbl_c.value = f"{'+' if chg_val >= 0 else ''}{chg_val:.2f}%"
            lbl_c.color = "#22C55E" if chg_val >= 0 else "#EF4444"

        def update_pc_telemetry_cards(sys_m: dict, mkt_m: dict):
            active_tab = int(state.get("active_tab", 0))

            # 1) Atualiza valores em memória (operações leves de atributo Python)
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

            if mkt_m.get("usd", 0) > 0:
                lbl_usd_p.value = lbl_m2_usd_p.value = f"R$ {mkt_m['usd']:.2f}"
                _fmt_chg(lbl_usd_c, mkt_m.get("usdc", 0.0))
                _fmt_chg(lbl_m2_usd_c, mkt_m.get("usdc", 0.0))
            if mkt_m.get("eur", 0) > 0:
                lbl_eur_p.value = lbl_m2_eur_p.value = f"R$ {mkt_m['eur']:.2f}"
                _fmt_chg(lbl_eur_c, mkt_m.get("eurc", 0.0))
                _fmt_chg(lbl_m2_eur_c, mkt_m.get("eurc", 0.0))
            if mkt_m.get("btc", 0) > 0:
                lbl_btc_p.value = lbl_m2_btc_p.value = f"$ {mkt_m['btc']:,.0f}"
                _fmt_chg(lbl_btc_c, mkt_m.get("btcc", 0.0))
                _fmt_chg(lbl_m2_btc_c, mkt_m.get("btcc", 0.0))
            if mkt_m.get("eth", 0) > 0:
                lbl_eth_p.value = lbl_m2_eth_p.value = f"$ {mkt_m['eth']:,.0f}"
                _fmt_chg(lbl_eth_c, mkt_m.get("ethc", 0.0))
                _fmt_chg(lbl_m2_eth_c, mkt_m.get("ethc", 0.0))
            if mkt_m.get("sol", 0) > 0:
                lbl_sol_p.value = lbl_m2_sol_p.value = f"$ {mkt_m['sol']:.2f}"
                _fmt_chg(lbl_sol_c, mkt_m.get("solc", 0.0))
                _fmt_chg(lbl_m2_sol_c, mkt_m.get("solc", 0.0))
            if mkt_m.get("ibov", 0) > 0:
                lbl_ibov_p.value = lbl_m2_ibov_p.value = f"{mkt_m['ibov']/1000.0:.1f}k pts"
                _fmt_chg(lbl_ibov_c, mkt_m.get("ibovc", 0.0))
                _fmt_chg(lbl_m2_ibov_c, mkt_m.get("ibovc", 0.0))

            # Atualiza pílulas do Header e apenas a aba ativa (State Management isolado)
            try:
                refresh_focus_media_ui()
                refresh_weather_gems_ui()
                if active_tab == 2:
                    refresh_portfolio_ui()
                elif active_tab == 4:
                    refresh_terminal_ui()
                elif active_tab == 7:
                    refresh_wifi_radar_ui()
                    refresh_net_analyzer_ui()
            except Exception:
                pass

            # Atualiza status de energia (Sleep / Modo Noturno) + Chip no Header
            try:
                idle_s = get_system_idle_seconds()
                eff_brt, reason = calculate_dynamic_brightness(state["brt"], state)
                pct_b = int(round(eff_brt * 100 / 255.0))
                if eff_brt == 0:
                    lbl_power_status.value = f"🌙 Sleep Mode (Ocioso: {int(idle_s)}s)"
                    lbl_power_status.color = "#818CF8"
                    lbl_hdr_power.value = "🌙 Sleep"
                    lbl_hdr_power.color = "#818CF8"
                elif "Noturno" in reason:
                    lbl_power_status.value = f"🌃 Modo Noturno (Brilho: {eff_brt} • Ocioso: {int(idle_s)}s)"
                    lbl_power_status.color = "#38BDF8"
                    lbl_hdr_power.value = f"🌃 {pct_b}%"
                    lbl_hdr_power.color = "#38BDF8"
                else:
                    lbl_power_status.value = f"🟢 Ativo (Brilho: {eff_brt} • Ocioso: {int(idle_s)}s)"
                    lbl_power_status.color = "#22C55E"
                    lbl_hdr_power.value = f"☀️ {pct_b}%"
                    lbl_hdr_power.color = "#22C55E"
            except Exception:
                pass

            if mkt_m.get("last_str") and mkt_m["last_str"] != "--:--:--":
                lbl_market_time.value = f"Última cotação: {mkt_m['last_str']}"

            now_br = brasilia_now()
            if now_br.weekday() in (5, 6):
                lbl_market_status.value = "🟢 Cripto: Ao Vivo (Coinbase / Binance • 3s) • 🟡 B3 & Câmbio: Fechado (Fim de semana)"
                lbl_market_status.color = "#F59E0B"
            else:
                lbl_market_status.value = "🟢 Cripto: Ao Vivo (Coinbase / 3s) • 🟢 B3 & Câmbio: Mercado Aberto"
                lbl_market_status.color = "#10B981"

            # Atualiza indicador Serial (taxa B/s e pacotes) sem re-renderizar toda a árvore
            refresh_serial_indicators()

            # State Management Granular: atualiza APENAS os controles visíveis na aba ativa + Header
            dirty_controls = [header_row]
            if active_tab == 0:
                dirty_controls.extend([telemetry_row, sec_market_quick])
            elif active_tab == 1:
                dirty_controls.extend([sec_pomodoro, sec_media])
            elif active_tab == 2:
                dirty_controls.extend([sec_market_live, sec_portfolio])
            elif active_tab == 3:
                dirty_controls.extend([sec_weather_regional, sec_news_feed])
            elif active_tab == 4:
                dirty_controls.append(sec_cyber_terminal)
            elif active_tab == 5:
                dirty_controls.append(lbl_power_status)
            elif active_tab == 7:
                dirty_controls.extend([sec_wifi_radar, sec_net_analyzer])
            safe_update(*dirty_controls)

        def orchestrator_worker():
            """
            Worker leve de orquestração (sem qualquer I/O Serial bloqueante).
            Consome snapshots em cache O(1) do Collector e alimenta o SerialManager assíncrono.
            """
            last_telemetry_t = 0.0
            last_fired_alerts = {}
            last_dispatched_brt = -1
            last_storm_alert_state = False
            pending_cov_id = ""
            pending_cov_t0 = 0.0

            while state["running"]:
                try:
                    now = time.time()
                    mkt_metrics = mkt_col.get_market_dict()

                    # Tick contínuo do Pomodoro mesmo se a CYD estiver desconectada
                    pomo_done_ev = pomo_eng.tick()
                    if pomo_done_ev:
                        fin_p = pomo_done_ev["finished_phase"]
                        nxt_p = pomo_done_ev["next_phase"]
                        append_log(f"🍅 CICLO POMODORO CONCLUÍDO ({fin_p} -> {nxt_p})! Ciclos hoje: #{pomo_done_ev['cycles']}")
                        if pomo_done_ev.get("buzzer", True):
                            led_c = "0x07FF" if fin_p == "WORK" else "0x07E0"
                            serial_mgr.send_event({
                                "pomo": pomo_eng.get_payload(done_flag=True),
                                "alrt": {"bz": True, "led": led_c, "p": 3},
                            })

                    # Avaliação do Brilho Dinâmico (Modo Sleep & Modo Noturno)
                    eff_brt, brt_reason = calculate_dynamic_brightness(state["brt"], state)
                    state["current_effective_brt"] = eff_brt
                    if eff_brt != last_dispatched_brt:
                        prev_b = last_dispatched_brt
                        last_dispatched_brt = eff_brt
                        serial_mgr.send_event({"ui": {"brt": eff_brt}})
                        if eff_brt == 0:
                            append_log("🌙 CYD em Modo Sleep (Inatividade de teclado/mouse detectada - Backlight = 0)")
                        elif prev_b == 0:
                            append_log(f"☀️ CYD acordando do Modo Sleep (Backlight restaurado para {eff_brt})")
                        elif "Noturno" in brt_reason:
                            append_log(f"🌃 CYD em Modo Noturno (Backlight atenuado para {eff_brt})")

                    # Sincronização automática da capa de álbum 320x240 p/ Cartão SD (com debounce de 1.3s)
                    if state["media_auto_cover"] and not upload_state["active"] and transfer_queue.empty():
                        _tk, cov_id, cov_bytes = media_col.get_cover_for_sd()
                        if cov_id and cov_bytes and cov_id != state["synced_cover_id"]:
                            if cov_id != pending_cov_id:
                                pending_cov_id = cov_id
                                pending_cov_t0 = now
                            elif now - pending_cov_t0 >= 1.3:
                                pending_cov_t0 = now + 8.0
                                start_media_cover_transfer(cov_id, cov_bytes, manual=False)

                    if now - last_telemetry_t >= cli_args.interval:
                        last_telemetry_t = now
                        # Coleta instantânea em O(1) do cache preparado pelo worker de background
                        sys_metrics = col.sample_sys()

                        # Tick de rotação de 15s do Feed de Notícias (Módulo 1)
                        rotated_news = gems_eng.tick_scheduler()
                        if rotated_news is not None:
                            serial_mgr.send_event({
                                "news": gems_eng.get_cyd_news_payload(include_queue=False, force=True),
                            })

                        update_pc_telemetry_cards(sys_metrics, mkt_metrics)

                        wth_payload = wth_col.get_cyd_payload()
                        payload = {
                            "sys": sys_metrics,
                            "pomo": pomo_eng.get_payload(),
                            "media": media_col.get_cyd_payload(state["synced_cover_id"]),
                            "wth": wth_payload,
                        }

                        # Alerta físico automático quando aviso de tempestade entra em vigor
                        curr_storm = bool(wth_payload.get("alrt", False))
                        if curr_storm and not last_storm_alert_state:
                            payload["alrt"] = {"bz": True, "led": "0xF800", "p": 3}
                            append_log(f"⛈️ ALERTA METEOROLÓGICO EM {wth_payload.get('city', 'Votuporanga').upper()}: {wth_payload.get('amsg', '')}")
                        last_storm_alert_state = curr_storm

                        # Avaliação de Alertas Físicos (Buzzer & LED RGB)
                        trig = evaluate_alert_rules(state.get("alert_rules", []), sys_metrics, mkt_metrics, last_fired_alerts, now)
                        if trig:
                            payload["alrt"] = trig["alrt"]
                            append_log(f"🚨 ALERTA ATIVADO: {trig['rule_name']} ({trig['curr_val']:.1f} {trig['op']} {trig['target_val']:.1f}) -> Disparando Buzzer/LED na CYD!")

                        if state["ui_dirty"] or (now - state["last_ui_sync"] >= 10.0):
                            payload["ui"] = get_ui_dict()
                            state["ui_dirty"] = False
                            state["last_ui_sync"] = now

                        if (now - state["last_mkt_sync"] >= 2.0) or ("ui" in payload):
                            if mkt_metrics.get("usd", 0) > 0 or mkt_metrics.get("btc", 0) > 0:
                                payload["mkt"] = mkt_metrics
                                state["last_mkt_sync"] = now
                            payload["portf"] = mkt_col.compute_portfolio(
                                state["portfolio"],
                                state["portfolio_pnl_mode"],
                            )[0]
                            payload["news"] = gems_eng.get_cyd_news_payload(
                                include_queue=("ui" in payload),
                                force=("ui" in payload),
                            )
                            if wifi_scan_col is not None:
                                payload["wrad"] = wifi_scan_col.get_cyd_payload()
                            if net_col is not None:
                                payload["neta"] = net_col.get_cyd_payload()

                        # Envia de forma 100% não-bloqueante para o SerialManager (substitui amostra obsoleta se ocupada)
                        serial_mgr.send_telemetry(payload)

                except Exception as ex:
                    append_log(f"Erro no orquestrador: {ex}")

                time.sleep(0.10)

            serial_mgr.stop()

        threading.Thread(target=orchestrator_worker, daemon=True, name="OrchestratorThread").start()

    # Inicializa Flet compativel com versoes 1.0+ (ft.run) e 0.2x (ft.app)
    if hasattr(ft, "run"):
        ft.run(build_app)
    else:
        ft.app(target=build_app)


def run_headless_daemon(
    col: Collector,
    mkt_col: MarketCollector,
    media_col: MediaCollector,
    pomo_eng: PomodoroEngine,
    wth_col: WeatherCollector,
    gems_eng: NewsFeedCollector,
    cli_args,
    term_eng: CyberDeckTerminalEngine = None,
    wifi_scan_col: wifi_scanner.WiFiScannerCollector = None,
    net_col: net_analyzer.NetworkAnalyzerCollector = None,
    ai_eng: ai_analyst.NetworkAIAnalyst = None,
):
    """Executa o agente CYD em segundo plano puro (sem janela Flet), ideal para systemd --user."""
    import signal

    if term_eng is None:
        term_eng = CyberDeckTerminalEngine(collector=col, wifi_scan_col=wifi_scan_col, net_col=net_col, ai_eng=ai_eng)
    else:
        if term_eng.collector is None:
            term_eng.collector = col
        if term_eng.wifi_scan_col is None:
            term_eng.wifi_scan_col = wifi_scan_col
        if term_eng.net_col is None:
            term_eng.net_col = net_col
        if term_eng.ai_eng is None and ai_eng is not None:
            term_eng.ai_eng = ai_eng

    cfg = load_ui_config()
    state = {
        "screen": int(cfg.get("screen", 1)),
        "hex_color": cfg.get("hex_color", "#00FF00").upper(),
        "color": cfg.get("color", "0x07E0"),
        "bg": cfg.get("bg", "none"),
        "brt": int(cfg.get("brt", 200)),
        "ticker": bool(cfg.get("ticker", True)),
        "sd_files": list(cfg.get("sd_files", [])),
        "sleep_enabled": bool(cfg.get("sleep_enabled", True)),
        "sleep_timeout_min": int(cfg.get("sleep_timeout_min", 15)),
        "night_mode_enabled": bool(cfg.get("night_mode_enabled", True)),
        "night_start_hour": int(cfg.get("night_start_hour", 22)),
        "night_end_hour": int(cfg.get("night_end_hour", 6)),
        "night_brightness": int(cfg.get("night_brightness", 40)),
        "alert_rules": [dict(r) for r in cfg.get("alert_rules", DEFAULT_ALERT_RULES)],
        "portfolio": [dict(p) for p in cfg.get("portfolio", DEFAULT_PORTFOLIO)],
        "portfolio_pnl_mode": str(cfg.get("portfolio_pnl_mode", "hist")),
        "pomo_work_min": int(cfg.get("pomo_work_min", 25)),
        "pomo_break_min": int(cfg.get("pomo_break_min", 5)),
        "pomo_long_min": int(cfg.get("pomo_long_min", 15)),
        "pomo_buzzer": bool(cfg.get("pomo_buzzer", True)),
        "media_source_pref": str(cfg.get("media_source_pref", "auto")),
        "media_auto_cover": bool(cfg.get("media_auto_cover", True)),
        "weather_city": str(cfg.get("weather_city", "Votuporanga")),
        "news_topics": list(cfg.get("news_topics", DEFAULT_NEWS_TOPICS)),
        "news_api_key": str(cfg.get("news_api_key", os.environ.get("NEWS_API_KEY", ""))),
        "udp_enabled": bool(cfg.get("udp_enabled", False)),
        "udp_ip": str(cfg.get("udp_ip", "") or ""),
        "udp_port": int(cfg.get("udp_port", UDP_DEFAULT_PORT) or UDP_DEFAULT_PORT),
        "esp_wifi_ssid": str(cfg.get("esp_wifi_ssid", "") or ""),
        "esp_wifi_pass": str(cfg.get("esp_wifi_pass", "") or ""),
        "term_auto_switch": True,
        "synced_cover_id": "",
        "sd_missing_warned": False,
        "current_effective_brt": int(cfg.get("brt", 200)),
        "running": True,
        "ui_dirty": True,
        "last_ui_sync": 0.0,
        "last_mkt_sync": 0.0,
    }

    mkt_col.set_custom_tickers([p.get("ticker", "") for p in state["portfolio"]])
    media_col.set_source_pref(state["media_source_pref"])
    pomo_eng.set_durations(state["pomo_work_min"], state["pomo_break_min"], state["pomo_long_min"])
    pomo_eng.buzzer_enabled = state["pomo_buzzer"]
    gems_eng.set_topics(state["news_topics"], state["news_api_key"])

    def log_h(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

    serial_mgr = SerialManager(
        preferred_port=cli_args.port,
        baud=BAUD,
        udp_enabled=bool(cfg.get("udp_enabled", False)),
        udp_ip=str(cfg.get("udp_ip", "") or ""),
        udp_port=int(cfg.get("udp_port", UDP_DEFAULT_PORT) or UDP_DEFAULT_PORT),
        excluded_ports_fn=(wifi_scan_col.get_active_ports if wifi_scan_col is not None else None),
        on_log=log_h,
    )
    if wifi_scan_col is not None:
        wifi_scan_col.set_excluded_ports_fn(serial_mgr.get_active_ports)
        wifi_scan_col.set_log_callback(log_h)
    if net_col is not None:
        net_col.set_log_callback(log_h)
    if ai_eng is not None:
        ai_eng.set_log_callback(log_h)
    ui_event_queue = serial_mgr.event_queue
    transfer_queue = serial_mgr.transfer_queue
    ack_event = serial_mgr.ack_event
    last_ack = serial_mgr.last_ack
    upload_state = {"active": False, "pct": 0.0, "status": "", "target": ""}

    def get_ui_dict():
        bg = (state["bg"] or "none").strip()
        if bg.startswith("/"):
            bg = bg[1:]
        return {
            "screen": int(state["screen"]),
            "color": state["color"],
            "bg": bg,
            "brt": int(state.get("current_effective_brt", state["brt"])),
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
            "sleep_enabled": state["sleep_enabled"],
            "sleep_timeout_min": state["sleep_timeout_min"],
            "night_mode_enabled": state["night_mode_enabled"],
            "night_start_hour": state["night_start_hour"],
            "night_end_hour": state["night_end_hour"],
            "night_brightness": state["night_brightness"],
            "alert_rules": state["alert_rules"],
            "portfolio": state["portfolio"],
            "portfolio_pnl_mode": state["portfolio_pnl_mode"],
            "pomo_work_min": state["pomo_work_min"],
            "pomo_break_min": state["pomo_break_min"],
            "pomo_long_min": state["pomo_long_min"],
            "pomo_buzzer": state["pomo_buzzer"],
            "media_source_pref": state["media_source_pref"],
            "media_auto_cover": state["media_auto_cover"],
            "weather_city": state["weather_city"],
            "news_topics": state["news_topics"],
            "news_api_key": state["news_api_key"],
            "udp_enabled": state.get("udp_enabled", False),
            "udp_ip": state.get("udp_ip", ""),
            "udp_port": state.get("udp_port", UDP_DEFAULT_PORT),
            "esp_wifi_ssid": state.get("esp_wifi_ssid", ""),
            "esp_wifi_pass": state.get("esp_wifi_pass", ""),
        })
        save_ui_config(cfg)
        serial_mgr.configure_udp(
            enabled=state.get("udp_enabled", False),
            ip=state.get("udp_ip", ""),
            port=state.get("udp_port", UDP_DEFAULT_PORT),
        )
        mkt_col.set_custom_tickers([p.get("ticker", "") for p in state["portfolio"]])
        portf_pkt, _ = mkt_col.compute_portfolio(state["portfolio"], state["portfolio_pnl_mode"])
        state["ui_dirty"] = True
        ev_pkt = {
            "ui": get_ui_dict(),
            "mkt": mkt_col.get_market_dict(),
            "portf": portf_pkt,
            "pomo": pomo_eng.get_payload(),
            "media": media_col.get_cyd_payload(state["synced_cover_id"]),
            "wth": wth_col.get_cyd_payload(),
            "news": gems_eng.get_cyd_news_payload(include_queue=True, force=True),
        }
        if wifi_scan_col is not None:
            ev_pkt["wrad"] = wifi_scan_col.get_cyd_payload()
        if net_col is not None:
            ev_pkt["neta"] = net_col.get_cyd_payload()
        serial_mgr.send_event(ev_pkt, coalesce=True)

    def request_sd_files():
        ui_event_queue.put({"cmd": "list_sd"})

    def _wait_ack(expected_prefix: str, timeout: float = 4.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if ack_event.wait(timeout=0.06):
                ack_event.clear()
                val = last_ack.get("val") or ""
                if val.startswith("ERR_NO_SD"):
                    return False, "ERR_NO_SD"
                if val.startswith("ERR_OPEN"):
                    return False, "ERR_OPEN"
                if val.startswith(expected_prefix):
                    return True, val
        return False, "TIMEOUT"

    def start_file_transfer(filename: str, raw_bytes: bytes):
        if not raw_bytes or upload_state["active"]:
            return
        try:
            target_name, data = prepare_image_bytes_for_cyd(filename, raw_bytes)
        except Exception as ex:
            log_h(f"Erro ao preparar imagem: {ex}")
            return

        def _worker():
            upload_state.update({"active": True, "pct": 0.0, "status": f"Gravando '{target_name}'...", "target": target_name})
            ack_event.clear()
            transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "w"})
            ok, resp = _wait_ack("ACK_START", timeout=4.5)
            if not ok:
                upload_state.update({"active": False, "status": f"Falha ({resp})"})
                return
            total = len(data)
            seq = 0
            for i in range(0, total, 512):
                chunk = data[i:i + 512]
                b64 = base64.b64encode(chunk).decode("ascii")
                ack_event.clear()
                transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "a", "seq": seq, "file_data": b64})
                ok, resp = _wait_ack("ACK_CHUNK", timeout=3.5)
                if not ok:
                    upload_state.update({"active": False, "status": f"Erro bloco {seq} ({resp})"})
                    return
                seq += 1
                upload_state["pct"] = min((i + len(chunk)) / float(total), 1.0)
            ack_event.clear()
            transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "eof"})
            ok, resp = _wait_ack("ACK_EOF", timeout=5.0)
            upload_state["active"] = False
            if ok:
                upload_state.update({"pct": 1.0, "status": f"'{target_name}' gravado!"})
                if target_name not in state["sd_files"]:
                    state["sd_files"].append(target_name)
                state["bg"] = target_name
                persist_and_queue_ui()
                log_h(f"Upload SD concluído: {target_name}")
            else:
                upload_state["status"] = f"Falha EOF ({resp})"

        threading.Thread(target=_worker, daemon=True).start()

    def start_media_cover_transfer(cid: str, cyd_bytes: bytes):
        if not cyd_bytes or upload_state["active"]:
            return
        upload_state["active"] = True

        def _cov_worker():
            target_name = "_media_cov.jpg"
            upload_state.update({"pct": 0.0, "status": "Sincronizando capa no SD...", "target": target_name})
            ack_event.clear()
            transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "w"})
            ok, resp = _wait_ack("ACK_START", timeout=4.0)
            if not ok:
                upload_state["active"] = False
                if resp == "ERR_NO_SD":
                    if not state["sd_missing_warned"]:
                        state["sd_missing_warned"] = True
                        log_h("Cartão SD não detectado na CYD (capa ignorada).")
                    state["synced_cover_id"] = cid
                return
            total = len(cyd_bytes)
            seq = 0
            for i in range(0, total, 512):
                chunk = cyd_bytes[i:i + 512]
                b64 = base64.b64encode(chunk).decode("ascii")
                ack_event.clear()
                transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "a", "seq": seq, "file_data": b64})
                ok, _resp = _wait_ack("ACK_CHUNK", timeout=3.2)
                if not ok:
                    upload_state["active"] = False
                    return
                seq += 1
                upload_state["pct"] = min((i + len(chunk)) / float(total), 1.0)
            ack_event.clear()
            transfer_queue.put({"file_name": f"/{target_name}", "file_mode": "eof", "is_cover": True, "cid": cid})
            ok, _resp = _wait_ack("ACK_EOF", timeout=4.5)
            upload_state["active"] = False
            if ok:
                state["synced_cover_id"] = cid
                state["sd_missing_warned"] = False
                ui_event_queue.put({"media": media_col.get_cyd_payload(cid)})
                log_h(f"Capa sincronizada no SD ({len(cyd_bytes)/1024:.1f} KB)")

        threading.Thread(target=_cov_worker, daemon=True).start()

    def on_serial_status_change(snap: dict):
        st_code = str(snap.get("state", "")).lower()
        port_str = snap.get("port", "")
        if st_code == "connected":
            state["ui_dirty"] = True
            log_h(f"SerialManager conectado em {port_str} ({snap.get('baud', BAUD)} bps)")
            request_sd_files()
        elif st_code in ("error", "disconnected"):
            log_h(f"Serial desconectada ({snap.get('last_error', 'erro I/O')}). Tentando reconectar...")

    def on_serial_rx_line(raw: str):
        if raw.startswith("TERM_LOG:"):
            t_line = raw.split("TERM_LOG:", 1)[1].strip()
            if t_line:
                term_eng.append_line(t_line)
        elif raw == "MONITOR_READY":
            state["ui_dirty"] = True
            state["synced_cover_id"] = ""
            request_sd_files()
        elif raw.startswith("SD_FILES:"):
            try:
                files = json.loads(raw.split("SD_FILES:", 1)[1])
                if isinstance(files, list):
                    base_opts = ["none", "terminal", "z1p0"]
                    merged = base_opts + [f for f in files if f not in base_opts and not str(f).startswith("_media")]
                    state["sd_files"] = merged
                    cfg["sd_files"] = merged
                    save_ui_config(cfg)
            except Exception:
                pass
        elif raw.startswith("SD_INIT:OK"):
            state["sd_missing_warned"] = False
            log_h(f"Cartão MicroSD montado ({raw}).")

    serial_mgr.set_callbacks(on_rx_line=on_serial_rx_line, on_status_change=on_serial_status_change)

    class HeadlessMobileHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def do_OPTIONS(self):
            self.send_response(204)
            self._send_cors()
            self.end_headers()

        def _build_mobile_status(self) -> dict:
            return {
                "screen": state["screen"],
                "hex_color": state["hex_color"],
                "color": state["color"],
                "bg": state["bg"],
                "brt": state["brt"],
                "ticker": state["ticker"],
                "sleep_enabled": state["sleep_enabled"],
                "night_mode_enabled": state["night_mode_enabled"],
                "sd_files": state["sd_files"],
                "sys": col.sample_sys() if col else {},
                "mkt": mkt_col.get_market_dict() if mkt_col else {},
                "portf": mkt_col.compute_portfolio(state["portfolio"], state["portfolio_pnl_mode"])[0] if mkt_col else {},
                "pomodoro": pomo_eng.get_ui_snapshot() if pomo_eng else {},
                "media": media_col.get_ui_snapshot() if media_col else {},
                "weather": wth_col.get_ui_snapshot() if wth_col else {},
                "news": gems_eng.get_ui_snapshot() if gems_eng else {},
                "gems": gems_eng.get_ui_snapshot() if gems_eng else {},
                "terminal": term_eng.get_snapshot() if term_eng else {},
                "wifi_radar": wifi_scan_col.get_ui_snapshot() if wifi_scan_col else {},
                "net_analyzer": net_col.get_ui_snapshot() if net_col else {},
                "ai": ai_eng.get_status_snapshot(probe_local=False) if ai_eng else {},
                "upload": upload_state,
                "connected": True,
            }

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            p = parsed.path
            if p in ("/", "/index.html"):
                content = mobile_web.HTML_MOBILE_APP.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache")
                self._send_cors()
                self.end_headers()
                self.wfile.write(content)
            elif p == "/api/status":
                content = json.dumps(self._build_mobile_status(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._send_cors()
                self.end_headers()
                self.wfile.write(content)
            elif p == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self._send_cors()
                self.end_headers()
                while state["running"]:
                    chunk = f"data: {json.dumps(self._build_mobile_status(), ensure_ascii=False)}\n\n".encode("utf-8")
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
                        break
                    time.sleep(1.0)
            elif p == "/api/screen":
                qs = urllib.parse.parse_qs(parsed.query)
                val = qs.get("s", qs.get("screen", [None]))[0]
                if val is not None:
                    try:
                        scr_idx = int(val)
                        if 0 <= scr_idx <= 13:
                            state["screen"] = scr_idx
                            persist_and_queue_ui()
                    except Exception:
                        pass
                content = json.dumps({"ok": True, "screen": state["screen"]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._send_cors()
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self._send_cors()
                self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            p = parsed.path
            length = int(self.headers.get("Content-Length", 0))
            body = {}
            if length > 0:
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8", errors="ignore"))
                except Exception:
                    pass

            ok = True
            err_msg = ""
            if p == "/api/screen":
                scr = int(body.get("screen", state["screen"]))
                if 0 <= scr <= 13:
                    state["screen"] = scr
                    persist_and_queue_ui()
                else:
                    ok, err_msg = False, "Tela inválida (0-13)"
            elif p == "/api/net_analyzer":
                act = str(body.get("action", "refresh")).lower()
                if net_col is not None:
                    if act == "speedtest":
                        net_col.trigger_speedtest()
                        log_h("Speedtest Fibra disparado via Web/CLI")
                    elif act == "set_plan" and body.get("plan_mbps"):
                        pm = int(body["plan_mbps"])
                        net_col.set_plan_mbps(pm)
                        cfg["net_plan_mbps"] = pm
                        save_ui_config(cfg)
                        log_h(f"Plano de internet ajustado para {pm} Mbps")
                    elif act == "router_diag":
                        diag = net_col.get_router_diagnostics()
                        content = json.dumps({"ok": True, "diag": diag}, ensure_ascii=False).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Length", str(len(content)))
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    else:
                        net_col.force_refresh()
            elif p == "/api/wifi_radar":
                act = str(body.get("action", "scan")).lower()
                if wifi_scan_col is not None:
                    if act == "config":
                        wifi_scan_col.configure(
                            enabled=body.get("enabled"),
                            port=body.get("port"),
                            interval_s=body.get("interval_s"),
                        )
                    else:
                        wifi_scan_col.force_scan()
                        log_h("Varredura manual solicitada via API para ESP32-WROOM-32U")
            elif p == "/api/weather":
                act = str(body.get("action", "refresh")).lower()
                if act == "city" and body.get("city"):
                    state["weather_city"] = str(body["city"]).strip() or "Votuporanga"
                    wth_col.set_city(state["weather_city"])
                    persist_and_queue_ui()
                elif act == "storm":
                    is_sim = not wth_col.get_ui_snapshot().get("sim_storm", False)
                    wth_col.trigger_storm_simulation(active=is_sim)
                    ui_event_queue.put({"wth": wth_col.get_cyd_payload()})
                else:
                    wth_col.force_refresh()
            elif p in ("/api/news", "/api/gem"):
                act = str(body.get("action", "next")).lower()
                if act == "toggle_topic" and body.get("topic"):
                    t_name = str(body["topic"]).strip()
                    curr = list(state["news_topics"])
                    if t_name in curr and len(curr) > 1:
                        curr.remove(t_name)
                    elif t_name not in curr:
                        curr.append(t_name)
                    state["news_topics"] = curr
                    gems_eng.set_topics(curr, state["news_api_key"])
                    persist_and_queue_ui()
                elif act == "topics" and isinstance(body.get("topics"), list):
                    state["news_topics"] = [str(x).strip() for x in body["topics"] if str(x).strip()]
                    gems_eng.set_topics(state["news_topics"], state["news_api_key"])
                    persist_and_queue_ui()
                elif act == "refresh":
                    threading.Thread(
                        target=lambda: (gems_eng.fetch_now(), ui_event_queue.put({"news": gems_eng.get_cyd_news_payload(include_queue=True, force=True)})),
                        daemon=True,
                    ).start()
                else:
                    gems_eng.next_headline()
                    ui_event_queue.put({"news": gems_eng.get_cyd_news_payload(include_queue=False, force=True)})
            elif p == "/api/terminal":
                cmd_str = str(body.get("cmd", "")).strip()
                wait_flag = bool(body.get("wait", False))
                req_to = body.get("timeout")
                is_ai_cmd = cmd_str.lower().startswith(("ai ", "ia ", "gemini ")) or cmd_str.lower() in ("ai", "ia", "gemini")
                eff_to = float(req_to) if req_to else (90.0 if is_ai_cmd else 10.0)
                if cmd_str:
                    if state.get("term_auto_switch", True):
                        state["screen"] = 11
                    snap_pre = term_eng.get_snapshot()
                    lines_before = len(snap_pre.get("lines", []))
                    seq_before = snap_pre.get("seq", lines_before)
                    out_lines = term_eng.execute_command(
                        cmd_str,
                        dispatch_fn=lambda pkt: ui_event_queue.put(pkt),
                        log_fn=log_h,
                        auto_switch_screen=True,
                        wait=wait_flag,
                        timeout_s=eff_to,
                    )
                    res_t = {
                        "ok": True,
                        "state": get_ui_dict(),
                        "seq": seq_before,
                        "lines_before": lines_before,
                        "output": out_lines,
                    }
                    content = json.dumps(res_t, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(content)
                    return
                else:
                    ok, err_msg = False, "Comando vazio"
            elif p == "/api/ai":
                if ai_eng is None:
                    ok, err_msg = False, "Modulo ai_analyst indisponivel"
                else:
                    act = str(body.get("action", "status")).lower().strip()
                    if act == "status":
                        res_a = {"ok": True, "ai": ai_eng.get_status_snapshot(probe_local=True)}
                    elif act == "models":
                        onl, mods, knd = ai_eng.list_local_models(timeout=2.5, force=True)
                        res_a = {
                            "ok": True,
                            "local_online": onl,
                            "local_kind": knd,
                            "local_models": mods,
                            "ai": ai_eng.get_status_snapshot(probe_local=False),
                        }
                    elif act == "config":
                        pub = ai_eng.configure(
                            ai_provider=body.get("ai_provider"),
                            gemini_api_key=body.get("gemini_api_key"),
                            gemini_model=body.get("gemini_model"),
                            local_ai_url=body.get("local_ai_url"),
                            local_ai_model=body.get("local_ai_model"),
                            persist=True,
                        )
                        log_h(f"Config IA atualizada: provedor={pub['ai_provider']} | gemini_key={'SET' if pub['gemini_key_set'] else 'UNSET'}")
                        res_a = {"ok": True, "config": pub, "ai": ai_eng.get_status_snapshot(probe_local=True)}
                    elif act in ("report", "full", "rf", "ask"):
                        mode_req = "rf" if act == "rf" else ("ask" if act == "ask" else "full")
                        prov_req = body.get("provider")
                        q_req = str(body.get("question", "")).strip()
                        res_a = ai_eng.generate_report(
                            mode=mode_req,
                            provider=prov_req,
                            question=q_req,
                            save_file=(mode_req != "ask"),
                        )
                        if res_a.get("ok") and body.get("push_cyd", True):
                            cyd_lns = res_a.get("cyd_lines", [])
                            if cyd_lns:
                                for ln in cyd_lns:
                                    term_eng.append_line(ln)
                                for i in range(0, len(cyd_lns), 4):
                                    ui_event_queue.put({
                                        "term": {
                                            "lines": cyd_lns[i : i + 4],
                                            "cmd": f"ai {mode_req}",
                                            "auto_scr": (i == 0 and bool(body.get("switch_screen", True))),
                                        }
                                    })
                                if body.get("switch_screen", True):
                                    state["screen"] = 11
                    else:
                        res_a = {"ok": False, "error": f"Acao IA desconhecida: {act}"}
                    content = json.dumps(res_a, ensure_ascii=False).encode("utf-8")
                    self.send_response(200 if res_a.get("ok", True) else 400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(content)
                    return
            elif p == "/api/color":
                h = str(body.get("hex", state["hex_color"])).strip().upper()
                if not h.startswith("#"):
                    h = "#" + h
                if len(h) == 7:
                    state["hex_color"] = h
                    state["color"] = rgb_hex_to_rgb565_str(h)
                    persist_and_queue_ui()
            elif p == "/api/brightness":
                state["brt"] = max(0, min(255, int(body.get("brt", state["brt"]))))
                persist_and_queue_ui()
            elif p == "/api/bg":
                state["bg"] = body.get("bg", state["bg"])
                persist_and_queue_ui()
            elif p == "/api/ticker":
                state["ticker"] = bool(body["ticker"]) if "ticker" in body else (not state["ticker"])
                persist_and_queue_ui()
            elif p == "/api/pomodoro":
                act = str(body.get("action", "toggle")).lower()
                if act == "toggle":
                    pomo_eng.toggle()
                elif act == "reset":
                    pomo_eng.reset()
                elif act == "skip":
                    pomo_eng.skip()
                elif act == "phase":
                    pomo_eng.set_phase(str(body.get("phase", "WORK")))
                ui_event_queue.put({"pomo": pomo_eng.get_payload()})
            elif p == "/api/media":
                act = str(body.get("action", "play_pause")).lower()
                if act in ("play_pause", "next", "prev"):
                    media_col.control(act)
                elif act == "sync_cover":
                    _tk, cid, c_bytes = media_col.get_cover_for_sd()
                    if c_bytes:
                        state["synced_cover_id"] = ""
                        start_media_cover_transfer(cid or "manual", c_bytes)
            elif p == "/api/power":
                if "sleep_enabled" in body:
                    state["sleep_enabled"] = bool(body["sleep_enabled"])
                if "night_mode_enabled" in body:
                    state["night_mode_enabled"] = bool(body["night_mode_enabled"])
                persist_and_queue_ui()
            elif p == "/api/test_alert":
                ui_event_queue.put({"alrt": {"bz": True, "led": state["color"], "p": 2}})
            elif p == "/api/refresh_sd":
                request_sd_files()
            elif p == "/api/upload":
                fname = body.get("filename", "mobile_wall.jpg")
                b64_data = body.get("data", "")
                if b64_data:
                    try:
                        start_file_transfer(fname, base64.b64decode(b64_data))
                    except Exception as ex:
                        ok, err_msg = False, str(ex)
                else:
                    ok, err_msg = False, "Nenhum dado de imagem recebido"
            else:
                self.send_response(404)
                self._send_cors()
                self.end_headers()
                return

            res_payload = {"ok": ok, "state": get_ui_dict()}
            if err_msg:
                res_payload["error"] = err_msg
            content = json.dumps(res_payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors()
            self.end_headers()
            self.wfile.write(content)

    class _HeadlessHTTPServer(http.server.ThreadingHTTPServer):
        allow_reuse_address = True

    mobile_server = None
    mobile_port = 8088
    for test_port in (8088, 8089, 8550, 8551, 8552):
        try:
            mobile_server = _HeadlessHTTPServer(("0.0.0.0", test_port), HeadlessMobileHandler)
            mobile_port = test_port
            break
        except OSError:
            continue

    if mobile_server:
        threading.Thread(target=mobile_server.serve_forever, daemon=True, name="HeadlessMobileHTTP").start()
        log_h(f"Painel Web/Mobile ativo em http://{get_local_lan_ip()}:{mobile_port} (http://127.0.0.1:{mobile_port})")

    def _handle_stop(signum, _frame):
        log_h(f"Sinal {signum} recebido. Encerrando agente CYD headless...")
        state["running"] = False

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log_h("CYD Cyber Deck iniciado em modo HEADLESS (segundo plano).")
    last_telemetry_t = 0.0
    last_fired_alerts = {}
    last_dispatched_brt = -1
    last_storm_alert_state = False
    pending_cov_id = ""
    pending_cov_t0 = 0.0

    try:
        while state["running"]:
            try:
                now = time.time()
                mkt_metrics = mkt_col.get_market_dict()

                pomo_done_ev = pomo_eng.tick()
                if pomo_done_ev and pomo_done_ev.get("buzzer", True):
                    led_c = "0x07FF" if pomo_done_ev["finished_phase"] == "WORK" else "0x07E0"
                    serial_mgr.send_event({
                        "pomo": pomo_eng.get_payload(done_flag=True),
                        "alrt": {"bz": True, "led": led_c, "p": 3},
                    })

                eff_brt, _brt_reason = calculate_dynamic_brightness(state["brt"], state)
                state["current_effective_brt"] = eff_brt
                if eff_brt != last_dispatched_brt:
                    last_dispatched_brt = eff_brt
                    serial_mgr.send_event({"ui": {"brt": eff_brt}})

                if state["media_auto_cover"] and not upload_state["active"] and transfer_queue.empty():
                    _tk, cov_id, cov_bytes = media_col.get_cover_for_sd()
                    if cov_id and cov_bytes and cov_id != state["synced_cover_id"]:
                        if cov_id != pending_cov_id:
                            pending_cov_id = cov_id
                            pending_cov_t0 = now
                        elif now - pending_cov_t0 >= 1.3:
                            pending_cov_t0 = now + 8.0
                            start_media_cover_transfer(cov_id, cov_bytes)

                if now - last_telemetry_t >= cli_args.interval:
                    last_telemetry_t = now
                    sys_metrics = col.sample_sys()

                    rotated_news = gems_eng.tick_scheduler()
                    if rotated_news is not None:
                        serial_mgr.send_event({
                            "news": gems_eng.get_cyd_news_payload(include_queue=False, force=True),
                        })

                    wth_payload = wth_col.get_cyd_payload()
                    payload = {
                        "sys": sys_metrics,
                        "pomo": pomo_eng.get_payload(),
                        "media": media_col.get_cyd_payload(state["synced_cover_id"]),
                        "wth": wth_payload,
                    }

                    curr_storm = bool(wth_payload.get("alrt", False))
                    if curr_storm and not last_storm_alert_state:
                        payload["alrt"] = {"bz": True, "led": "0xF800", "p": 3}
                    last_storm_alert_state = curr_storm

                    trig = evaluate_alert_rules(state.get("alert_rules", []), sys_metrics, mkt_metrics, last_fired_alerts, now)
                    if trig:
                        payload["alrt"] = trig["alrt"]
                        log_h(f"ALERTA: {trig['rule_name']} ({trig['curr_val']:.1f} {trig['op']} {trig['target_val']:.1f})")

                    if state["ui_dirty"] or (now - state["last_ui_sync"] >= 10.0):
                        payload["ui"] = get_ui_dict()
                        state["ui_dirty"] = False
                        state["last_ui_sync"] = now

                    if (now - state["last_mkt_sync"] >= 2.0) or ("ui" in payload):
                        if mkt_metrics.get("usd", 0) > 0 or mkt_metrics.get("btc", 0) > 0:
                            payload["mkt"] = mkt_metrics
                            state["last_mkt_sync"] = now
                        payload["portf"] = mkt_col.compute_portfolio(
                            state["portfolio"],
                            state["portfolio_pnl_mode"],
                        )[0]
                        payload["news"] = gems_eng.get_cyd_news_payload(
                            include_queue=("ui" in payload),
                            force=("ui" in payload),
                        )
                        if wifi_scan_col is not None:
                            payload["wrad"] = wifi_scan_col.get_cyd_payload()
                        if net_col is not None:
                            payload["neta"] = net_col.get_cyd_payload()

                    serial_mgr.send_telemetry(payload)
            except Exception as ex:
                log_h(f"Erro no loop headless: {ex}")
            time.sleep(0.10)
    finally:
        serial_mgr.stop()
        if wifi_scan_col is not None:
            try:
                wifi_scan_col.stop()
            except Exception:
                pass
        if net_col is not None:
            try:
                net_col.stop()
            except Exception:
                pass
        try:
            col.stop()
        except Exception:
            pass
        if mobile_server:
            try:
                mobile_server.shutdown()
            except Exception:
                pass
        log_h("Agente CYD headless encerrado.")


def main():
    ap = argparse.ArgumentParser(description="Agente CYD Cyber Deck v4.0 — Terminal, News Feed, Clima & Telemetria (Flet / Flutter Edition)")
    ap.add_argument("-p", "--port", help="Porta serial da CYD, ex: COM5 ou /dev/ttyUSB0")
    ap.add_argument("--scanner-port", default="", help="Porta serial da ESP32 Scanner Wi-Fi, ex: /dev/ttyUSB1")
    ap.add_argument("-i", "--interval", type=float, default=INTERVAL)
    ap.add_argument("--stdout", action="store_true", help="Imprime o JSON no terminal e nao abre GUI")
    ap.add_argument("--once", action="store_true", help="Coleta uma amostra JSON e sai")
    ap.add_argument("--headless", action="store_true", help="Executa em segundo plano sem interface grafica (ideal para systemd)")
    ap.add_argument("--game-proc", action="append", default=[], help="Processo extra de jogo")
    args = ap.parse_args()

    cfg = load_ui_config()
    col = Collector(game_processes=args.game_proc)
    mkt_col = MarketCollector(crypto_interval=3.0, stock_interval=12.0)
    media_col = MediaCollector(source_pref=cfg.get("media_source_pref", "auto"))
    pomo_eng = PomodoroEngine(
        work_min=cfg.get("pomo_work_min", 25),
        break_min=cfg.get("pomo_break_min", 5),
        long_min=cfg.get("pomo_long_min", 15),
        buzzer_enabled=cfg.get("pomo_buzzer", True),
    )
    wth_col = WeatherCollector(city=cfg.get("weather_city", "Votuporanga"), interval=300.0)
    news_col = NewsFeedCollector(
        topics=cfg.get("news_topics", DEFAULT_NEWS_TOPICS),
        news_api_key=cfg.get("news_api_key", ""),
        rotate_sec=15.0,
    )
    wifi_scan_col = wifi_scanner.WiFiScannerCollector(
        preferred_port=(args.scanner_port or str(cfg.get("scanner_port", "") or "")),
        scan_interval_s=float(cfg.get("scanner_interval_s", 8.0) or 8.0),
        enabled=bool(cfg.get("scanner_enabled", True)) and not (args.stdout or args.once),
        auto_start=not (args.stdout or args.once),
    )
    net_col = net_analyzer.NetworkAnalyzerCollector(
        plan_mbps=int(cfg.get("net_plan_mbps", 700) or 700),
        scanner_ip_fn=lambda: wifi_scan_col.get_ui_snapshot().get("scanner_ip", ""),
        auto_start=not (args.stdout or args.once),
    )
    def _persist_ai_cfg(delta: dict):
        try:
            cur_cfg = load_ui_config()
            cur_cfg.update(delta)
            save_ui_config(cur_cfg)
        except Exception:
            pass

    ai_eng = ai_analyst.NetworkAIAnalyst(
        collector=col,
        wifi_scan_col=wifi_scan_col,
        net_col=net_col,
        ai_provider=str(cfg.get("ai_provider", "auto") or "auto"),
        gemini_api_key=str(cfg.get("gemini_api_key", "") or ""),
        gemini_model=str(cfg.get("gemini_model", "gemini-2.5-flash") or "gemini-2.5-flash"),
        local_ai_url=str(cfg.get("local_ai_url", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"),
        local_ai_model=str(cfg.get("local_ai_model", "") or ""),
        on_config_persist=_persist_ai_cfg,
    )
    term_eng = CyberDeckTerminalEngine(
        collector=col,
        wifi_scan_col=wifi_scan_col,
        net_col=net_col,
        ai_eng=ai_eng,
    )
    time.sleep(0.55)

    if args.stdout or args.once:
        mkt_col.set_custom_tickers([p.get("ticker", "") for p in cfg.get("portfolio", [])])
        mkt_col.fetch_once()
        while True:
            pomo_eng.tick()
            sys_s = col.sample_sys()
            mkt_s = mkt_col.get_market_dict()
            portf_s, _ = mkt_col.compute_portfolio(
                cfg.get("portfolio", []),
                cfg.get("portfolio_pnl_mode", "hist"),
            )
            news_col.tick_scheduler()
            eff_brt, _ = calculate_dynamic_brightness(cfg["brt"], cfg)
            payload = {
                "sys": sys_s,
                "mkt": mkt_s,
                "portf": portf_s,
                "pomo": pomo_eng.get_payload(),
                "media": media_col.get_cyd_payload(),
                "wth": wth_col.get_cyd_payload(),
                "news": news_col.get_cyd_news_payload(include_queue=False, force=True),
                "ui": {
                    "screen": cfg["screen"],
                    "color": cfg["color"],
                    "bg": cfg["bg"],
                    "brt": eff_brt,
                    "ticker": cfg.get("ticker", True),
                },
            }
            print(json.dumps(payload, ensure_ascii=False))
            sys.stdout.flush()
            if args.once:
                return
            time.sleep(args.interval)

    if args.headless:
        run_headless_daemon(col, mkt_col, media_col, pomo_eng, wth_col, news_col, args, term_eng=term_eng, wifi_scan_col=wifi_scan_col, net_col=net_col, ai_eng=ai_eng)
        return

    launch_flet_gui(col, mkt_col, media_col, pomo_eng, wth_col, news_col, args, term_eng=term_eng, wifi_scan_col=wifi_scan_col, net_col=net_col, ai_eng=ai_eng)


if __name__ == "__main__":
    main()
