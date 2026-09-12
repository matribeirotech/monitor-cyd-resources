#!/usr/bin/env python3
"""
mike_agent.py - Agente de telemetria do PC (Linux ou Windows) para o CYD
"Mike Monitor".

Le CPU / GPU / RAM / disco / rede / temperaturas e envia uma linha JSON por
segundo pela porta serial USB do ESP32.

Uso:
    python3 mike_agent.py                  # auto-detecta a porta
    python3 mike_agent.py -p /dev/ttyUSB0  # porta fixa (Linux)
    python3 mike_agent.py -p COM5          # porta fixa (Windows)
    python3 mike_agent.py --stdout         # so imprime o JSON (teste)
    python3 mike_agent.py --once           # uma amostra e sai

Requisitos: pip install -r requirements.txt (pyserial, psutil; no Windows
tambem puxa wmi + pywin32, opcionais -- ver README, secao "Windows").
"""

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import mmap
import struct
import ctypes
from collections import deque
from datetime import datetime, timedelta, timezone

IS_WINDOWS = platform.system() == "Windows"

try:
    import psutil
except ImportError:
    sys.exit("Faltando psutil. Rode: pip install psutil pyserial")

BAUD = 115200
INTERVAL = 1.0

# Relogio sempre em horario de Brasilia, independente do fuso do PC que roda
# o agente. Usa zoneinfo (stdlib) quando o SO tem a base IANA disponivel;
# senao cai para o offset fixo -03:00 (Brasil aboliu o horario de verao em
# 2019, entao America/Sao_Paulo e' sempre UTC-3).
try:
    from zoneinfo import ZoneInfo
    TZ_BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:
    TZ_BRASILIA = timezone(timedelta(hours=-3))


def brasilia_now():
    return datetime.now(TZ_BRASILIA)

# VID:PID dos conversores USB-serial usados nas placas CYD
KNOWN_USB_IDS = {
    (0x1A86, 0x7523),  # CH340
    (0x1A86, 0x55D4),  # CH9102
    (0x10C4, 0xEA60),  # CP2102
    (0x0403, 0x6001),  # FT232
}

# "modo game": nome de processo (substring, case-insensitive) que faz o Mike
# trocar pra tela de jogo. So' emuladores/executaveis de jogo aqui de proposito
# -- launchers genericos (Steam, Lutris, Heroic...) ficam de fora: eles passam
# a maior parte do tempo abertos sem nenhum jogo em andamento (o processo de
# UI da Steam, por exemplo, roda o tempo todo so' com o cliente aberto), entao
# um nome de launcher aqui deixava o modo game ligado o tempo inteiro por
# engano. Jogo rodando *pela* Steam e' detectado a parte, pelo caminho do
# executavel -- ver _is_steam_game(). Complete a lista com --game-proc.
DEFAULT_GAME_PROCESSES = (
    "pcsx2", "rpcs3", "dolphin-emu", "yuzu", "ryujinx", "cemu", "citra",
    "ppsspp", "duckstation", "mupen64plus", "retroarch", "xemu",
)


def _is_steam_game(exe_path):
    """Um jogo de verdade instalado pela Steam mora em .../steamapps/common/...
    -- ao contrario do cliente da Steam em si (Steam.exe/steamwebhelper), que
    roda de outro diretorio e fica aberto o tempo todo, com ou sem jogo."""
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


# raiz do disco a medir: "/" no Linux, a unidade do sistema (normalmente
# "C:\") no Windows -- os.path.abspath(os.sep) resolve os dois sozinho
SYSTEM_ROOT = os.path.abspath(os.sep)


def load_average():
    """Media de carga (1 min). So' existe em Unix -- Windows nao tem esse
    conceito, entao a metrica fica ausente por la (igual outro sensor que
    falte), em vez de derrubar o agente."""
    try:
        return round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        return None

def get_rtss_fps():
    """Lê o FPS do RTSS (RivaTuner Statistics Server) compartilhado na memória."""
    if not IS_WINDOWS:
        return None
    try:
        shmem = mmap.mmap(-1, 32768, "RTSSSharedMemoryV2", access=mmap.ACCESS_READ)
        sig = struct.unpack('<I', shmem[0:4])[0]
        if sig != 0x52545353:
            shmem.close()
            return None
            
        app_arr_offset = struct.unpack('<I', shmem[12:16])[0]
        app_arr_size = struct.unpack('<I', shmem[16:20])[0]
        app_entry_size = struct.unpack('<I', shmem[8:12])[0]
        total_size = app_arr_offset + app_arr_size * app_entry_size
        shmem.close()
        
        shmem = mmap.mmap(-1, total_size, "RTSSSharedMemoryV2", access=mmap.ACCESS_READ)
        
        # Iterar pelas AppEntries para encontrar o jogo rodando
        for i in range(app_arr_size):
            offset = app_arr_offset + i * app_entry_size
            proc_id = struct.unpack('<I', shmem[offset:offset+4])[0]
            if proc_id == 0:
                continue
            
            frame_time = struct.unpack('<I', shmem[offset+280:offset+284])[0]
            if frame_time > 0:
                fps = 1000000.0 / frame_time
                if fps > 0 and fps < 2000:
                    shmem.close()
                    return int(fps + 0.5)
        shmem.close()
        return None
    except Exception:
        return None



# ------------------------------------- sensores no Windows (LibreHardwareMonitor) ---
# O Windows nao tem hwmon/sysfs, entao psutil.sensors_temperatures()/sensors_fans()
# simplesmente nao existem la (viram AttributeError, ja tratado abaixo). Se o
# LibreHardwareMonitor -- ou o antigo OpenHardwareMonitor -- estiver rodando
# como administrador com "Remote Web Server"/WMI habilitado (ligado por padrao),
# o agente completa temperatura, fan e GPU lendo o WMI dele. Precisa do pacote
# `wmi` (so' instala no Windows, ver requirements.txt); sem isso, ou sem o
# programa rodando, essas metricas ficam ausentes -- igual quando falta
# lm-sensors no Linux, o resto do agente funciona normal.
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
            w.Sensor()  # confere se o namespace responde de verdade
            _lhm = w
            break
        except Exception:
            continue
    return _lhm


def _lhm_sensors(kind):
    """Sensores WMI do LibreHardwareMonitor de um tipo: Temperature/Load/Fan/Power."""
    w = _lhm_connect()
    if not w:
        return []
    try:
        return [s for s in w.Sensor() if s.SensorType == kind]
    except Exception:
        return []


# ------------------------------------------------------------ temperatura ---
CPU_TEMP_KEYS = ("k10temp", "zenpower", "coretemp", "cpu_thermal",
                 "acpitz", "soc_thermal", "thinkpad")
CPU_LABEL_HINTS = ("tctl", "tdie", "package", "cpu", "core 0", "composite")



import urllib.request
import json

def _get_lhm_web_data():
    try:
        with urllib.request.urlopen('http://localhost:8085/data.json', timeout=1) as url:
            return json.loads(url.read().decode())
    except Exception:
        return None

def _find_web_sensors(node, kind, name_hints=None):
    results = []
    if not node: return results
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
            num = float(r.split()[0].replace(',', '.'))
            parsed.append(num)
        except:
            pass
    return parsed


def cpu_temperature():
    """Melhor palpite para a temperatura da CPU, em graus C."""
    # psutil.sensors_temperatures so' existe em builds Linux/BSD -- no Windows
    # o atributo nem existe, e isso ja cai no except (vira AttributeError).
    temps = None
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        pass

    if temps:
        # 1) chip conhecido + label que parece do pacote/CPU
        for chip in CPU_TEMP_KEYS:
            for name, entries in temps.items():
                if chip not in name.lower():
                    continue
                for e in entries:
                    if e.label and any(h in e.label.lower() for h in CPU_LABEL_HINTS):
                        return round(e.current, 1)
                if entries:
                    return round(entries[0].current, 1)

        # 2) fallback: maior temperatura vista
        best = None
        for entries in temps.values():
            for e in entries:
                if e.current and 0 < e.current < 130:
                    best = e.current if best is None else max(best, e.current)
        if best:
            return round(best, 1)

    # 3) Windows sem hwmon: tenta o LibreHardwareMonitor (ver _lhm_sensors)
    cpu_sensors = [s for s in _lhm_sensors("Temperature")
                   if "cpu" in (s.Name or "").lower()
                   or "cpu" in (s.Parent or "").lower()]
    for s in cpu_sensors:
        n = (s.Name or "").lower()
        if any(h in n for h in ("package", "tctl", "tdie", "core max", "average")):
            return round(s.Value, 1)
    if cpu_sensors:
        return round(cpu_sensors[0].Value, 1)

    # 4) Tenta o Web Server do LibreHardwareMonitor
    web_data = _get_lhm_web_data()
    if web_data:
        web_temps = _find_web_sensors(web_data, "temperature", ["cpu", "package", "tctl", "tdie", "core"])
        if web_temps:
            return round(max(web_temps), 1)

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
_gpu_kind = None       # "nvidia" | "amd" | "intel" | "none"
_amd_paths = {}
_nvidia_smi = None      # caminho resolvido do executavel


def _find_nvidia_smi():
    """No Linux o nvidia-smi quase sempre esta no PATH; no Windows o instalador
    do driver as vezes nao poe (ou poe so' pro instalador), entao completa com
    os dois caminhos padrao."""
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
    # AMD via sysfs (amdgpu) -- so' existe no Linux, no Windows o glob abaixo
    # simplesmente nao acha nada e cai pro LibreHardwareMonitor em gpu_stats()
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
    # Intel integrada: so temperatura via hwmon i915
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


def gpu_stats():
    if _gpu_kind is None:
        _detect_gpu()

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
                "gpu": num(0),
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
            "gpu": busy,
            "gput": round(temp / 1000.0, 1) if temp else None,
            "vram": round(100.0 * vu / vt, 1) if vu and vt else None,
            "vramu": round(vu / 1073741824.0, 1) if vu else None,
            "vramt": round(vt / 1073741824.0, 1) if vt else None,
            "gpuw": round(pw / 1000000.0, 1) if pw else None,
            "gpufan": read_int(_amd_paths.get("fan") or ""),
            "gpuname": "AMD",
        }

    if _gpu_kind == "intel":
        temp = read_int(_amd_paths.get("temp") or "")
        return {"gput": round(temp / 1000.0, 1) if temp else None, "gpuname": "INTEL"}

    # Nada achado pelos metodos de cima (tipico do Windows sem NVIDIA): tenta
    # o LibreHardwareMonitor, que expoe GPU AMD/Intel/NVIDIA de forma generica
    lhm = _lhm_gpu_stats()
    if lhm:
        return lhm
        
    web = _lhm_gpu_stats_web()
    if web:
        return web

    return {"gpuname": None}


def _lhm_gpu_stats():
    """GPU generica via LibreHardwareMonitor -- cobre AMD/Intel no Windows,
    onde nao tem sysfs/hwmon pra ler direto."""
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
        "gpu": round(gpu_load, 1) if gpu_load is not None else None,
        "gput": round(gpu_temp, 1),
        "gpuw": round(gpu_power, 1) if gpu_power is not None else None,
        "gpuname": name,
    }

def _lhm_gpu_stats_web():
    web_data = _get_lhm_web_data()
    if not web_data:
        return None
    gpu_temps = _find_web_sensors(web_data, "temperature", ["gpu"])
    if not gpu_temps:
        return None
    gpu_loads = _find_web_sensors(web_data, "load", ["gpu"])
    gpu_powers = _find_web_sensors(web_data, "power", ["gpu"])
    return {
        "gpu": round(max(gpu_loads), 1) if gpu_loads else None,
        "gput": round(max(gpu_temps), 1),
        "gpuw": round(max(gpu_powers), 1) if gpu_powers else None,
        "gpuname": "GPU",
    }



# ------------------------------------------------------------- journalctl ---
# Prioridades do syslog: 0 emerg, 1 alert, 2 crit, 3 err, 4 warning,
#                        5 notice, 6 info, 7 debug
PRIO_ERR = 3
PRIO_WARN = 4
PRIO_CRIT = 2

# Limites casados com a tela de logs: a fonte 1 do TFT_eSPI tem 6px por
# caractere, e "[E] unit: msg" precisa caber nos 316px uteis.
MSG_MAX = 36
UNIT_MAX = 10
SEND_MAX = 3          # linhas novas por pacote
RATE_WINDOW = 60.0    # janela da taxa de erros, em segundos

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_WS = re.compile(r"\s+")


def clean_msg(s):
    """Deixa a mensagem em ASCII curto: as fontes do display nao tem acento."""
    s = _ANSI.sub("", s or "")
    s = _WS.sub(" ", s).strip()
    s = (s.replace("ç", "c").replace("ã", "a").replace("á", "a").replace("é", "e")
          .replace("í", "i").replace("ó", "o").replace("ú", "u").replace("â", "a")
          .replace("ê", "e").replace("ô", "o").replace("õ", "o").replace("à", "a"))
    s = s.encode("ascii", "ignore").decode("ascii")
    return s[:MSG_MAX]


class JournalFollower(threading.Thread):
    """Segue `journalctl -f` numa thread e acumula o que interessa.

    Guarda contadores, taxa de erros e as linhas novas ainda nao enviadas.
    O snapshot() devolve o delta e limpa o que ja foi entregue.
    """

    daemon = True

    def __init__(self, units=None, since_boot=False):
        super().__init__()
        self.units = units or []
        self.since_boot = since_boot
        self.lock = threading.Lock()
        self.pending = deque(maxlen=20)
        self.err_total = 0
        self.warn_total = 0
        self.err_times = deque()
        self.crit_seen = False
        self.ok = False
        self.error = None
        self.proc = None

    # -------------------------------------------------------------- setup --
    @staticmethod
    def available():
        return shutil.which("journalctl") is not None

    def _cmd(self):
        cmd = ["journalctl", "-f", "-o", "json", "--no-pager"]
        # -n 0 = nao despeja o historico, so o que chegar daqui pra frente
        cmd += ["-n", "0"] if not self.since_boot else ["-b"]
        # PRIORITY<=4 ja filtra no journald: menos dado atravessando o pipe
        cmd += ["-p", "4"]
        for u in self.units:
            cmd += ["-u", u]
        return cmd

    # ---------------------------------------------------------------- run --
    def run(self):
        try:
            self.proc = subprocess.Popen(
                self._cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
        except Exception as e:
            self.error = str(e)
            return

        self.ok = True
        for line in self.proc.stdout:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                ent = json.loads(line)
            except Exception:
                continue
            self._ingest(ent)

    def _ingest(self, ent):
        try:
            prio = int(ent.get("PRIORITY", 6))
        except (TypeError, ValueError):
            prio = 6
        if prio > PRIO_WARN:
            return

        unit = (ent.get("_SYSTEMD_UNIT") or ent.get("SYSLOG_IDENTIFIER")
                or ent.get("_COMM") or "?")
        unit = unit.replace(".service", "")[:UNIT_MAX]
        msg = ent.get("MESSAGE")
        if isinstance(msg, list):      # journald pode devolver bytes como lista
            try:
                msg = bytes(msg).decode("utf-8", "ignore")
            except Exception:
                msg = str(msg)
        msg = clean_msg(msg)
        if not msg:
            return

        now = time.time()
        with self.lock:
            if prio <= PRIO_ERR:
                self.err_total += 1
                self.err_times.append(now)
                if prio <= PRIO_CRIT:
                    self.crit_seen = True
            else:
                self.warn_total += 1
            self.pending.append((prio, unit, msg))

    # ----------------------------------------------------------- snapshot --
    def snapshot(self):
        now = time.time()
        with self.lock:
            while self.err_times and now - self.err_times[0] > RATE_WINDOW:
                self.err_times.popleft()
            rate = len(self.err_times) * (60.0 / RATE_WINDOW)

            new = []
            # prioriza as mais graves quando estoura o limite do pacote
            items = sorted(self.pending, key=lambda t: t[0])[:SEND_MAX]
            for prio, unit, msg in items:
                new.append([prio, unit, msg])
            n_new = len(self.pending)
            self.pending.clear()

            crit = self.crit_seen
            self.crit_seen = False

            out = {
                "le": self.err_total,
                "lw": self.warn_total,
                "lr": round(rate, 1),
                "ln": n_new,
                "lc": 1 if crit else 0,
            }
            if new:
                out["lg"] = new
            return out

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass


# --------------------------------------------------------------- coletor ----
class Collector:
    def __init__(self, journal=None, game_processes=()):
        self.journal = journal
        psutil.cpu_percent(interval=None)
        self.host = socket.gethostname()[:14]
        self.prev_net = psutil.net_io_counters()
        self.prev_disk = psutil.disk_io_counters()
        self.prev_t = time.time()
        self.cores = psutil.cpu_count(logical=True)
        self.game_processes = tuple(g.lower() for g in DEFAULT_GAME_PROCESSES + tuple(game_processes))

    def sample(self):
        now = time.time()
        dt = max(now - self.prev_t, 0.1)

        cpu = psutil.cpu_percent(interval=None)
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

        # processo que mais consome CPU, e se tem algo de jogo rodando --
        # os dois precisam varrer todo mundo, entao fazem isso numa passada so
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

        br = brasilia_now()

        d = {
            "cpu": round(cpu, 1),
            "cput": cpu_temperature(),
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
            "fan": fan_rpm(),
            "host": self.host,
            "top": top,
            "game": gaming,
            "fps": get_rtss_fps() if gaming else None,
        }
        d.update(gpu_stats())
        # remove chaves nulas -> linha serial menor
        d = {k: v for k, v in d.items() if v is not None}
        if self.journal is not None:
            d.update(self.journal.snapshot())
        return d


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
    # so' chega aqui se o VID:PID nao bateu com nenhum chip conhecido -- pega
    # qualquer coisa com nome de porta serial (ttyUSB/ttyACM no Linux, COM* no
    # Windows) como ultimo palpite
    for p in cands:
        if re.search(r"ttyUSB|ttyACM|^COM\d+$", p.device):
            return p.device
    return None


def main():
    ap = argparse.ArgumentParser(description="Agente Mike Monitor (CYD)")
    ap.add_argument("-p", "--port", help="porta serial, ex: /dev/ttyUSB0")
    ap.add_argument("-i", "--interval", type=float, default=INTERVAL)
    ap.add_argument("--stdout", action="store_true", help="imprime o JSON em vez de enviar")
    ap.add_argument("--once", action="store_true", help="coleta uma amostra e sai")
    ap.add_argument("--no-logs", action="store_true", help="nao acompanha o journalctl")
    ap.add_argument("-u", "--unit", action="append", default=[],
                    help="limita os logs a uma unit (pode repetir)")
    ap.add_argument("--log-boot", action="store_true",
                    help="conta tambem os erros que ja estavam no journal deste boot")
    ap.add_argument("--game-proc", action="append", default=[],
                    help="nome de processo extra para o modo game (pode repetir)")
    args = ap.parse_args()

    journal = None
    if not args.no_logs:
        if JournalFollower.available():
            journal = JournalFollower(units=args.unit, since_boot=args.log_boot)
            journal.start()
            time.sleep(0.4)
            if journal.error:
                print(f"[mike] journalctl falhou: {journal.error}", file=sys.stderr)
                journal = None
        else:
            print("[mike] journalctl nao encontrado, seguindo sem logs", file=sys.stderr)

    col = Collector(journal, game_processes=args.game_proc)
    time.sleep(0.3)

    if args.stdout or args.once:
        while True:
            print(json.dumps(col.sample(), ensure_ascii=False))
            sys.stdout.flush()
            if args.once:
                return
            time.sleep(args.interval)
            
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        import queue
        import base64
        import os
        
        class AgentGUI:
            def __init__(self, root, col, args):
                self.root = root
                self.col = col
                self.args = args
                self.cmd_queue = queue.Queue()
                self.transfer_queue = queue.Queue()
                self.current_color = "#00FF00"
                
                self.root.title("CYD Hardware Monitor - Controle")
                self.root.geometry("480x620")
                self.root.configure(bg="#050505")
                
                self.style = ttk.Style()
                if "clam" in self.style.theme_names():
                    self.style.theme_use("clam")
                
                self.update_styles()
        
                self.setup_ui()
                
                self.running = True
                self.thread = threading.Thread(target=self.serial_loop, daemon=True)
                self.thread.start()
                
                self.root.protocol("WM_DELETE_WINDOW", self.on_close)
                
            def update_styles(self):
                self.style.configure(".", background="#050505", foreground=self.current_color, font=("Consolas", 10))
                self.style.configure("TFrame", background="#050505")
                self.style.configure("TLabel", background="#050505", foreground=self.current_color)
                self.style.configure("TButton", background="#1a1a1a", foreground=self.current_color, borderwidth=1, bordercolor=self.current_color)
                self.style.map("TButton", background=[("active", "#333333")])
                self.style.configure("TRadiobutton", background="#050505", foreground=self.current_color)
                self.style.configure("Horizontal.TScale", background="#050505")
        
            def setup_ui(self):
                self.frame = ttk.Frame(self.root, padding=15)
                self.frame.pack(fill=tk.BOTH, expand=True)
        
                ttk.Label(self.frame, text="CYD HARDWARE MONITOR", font=("Consolas", 16, "bold")).pack(pady=5)
                
                self.lbl_status = ttk.Label(self.frame, text="Status: Aguardando conexão...")
                self.lbl_status.pack(pady=5)
                
                # Cores
                self.lf_color = tk.LabelFrame(self.frame, text=" Cor da Chuva Matrix ", bg="#050505", fg=self.current_color, font=("Consolas", 10))
                self.lf_color.pack(fill=tk.X, pady=5, padx=5)
                
                self.color_var = tk.IntVar(value=0)
                colors = [("Verde", 0, "#00FF00"), ("Ciano", 1, "#00FFFF"), ("Laranja", 2, "#FFA500"), ("Magenta", 3, "#FF00FF"), ("Vermelho", 4, "#FF0000")]
                
                col_frame = tk.Frame(self.lf_color, bg="#050505")
                col_frame.pack(fill=tk.X, padx=10, pady=5)
                for text, val, hex_col in colors:
                    rb = tk.Radiobutton(col_frame, text=text, variable=self.color_var, value=val, 
                                        bg="#050505", fg=hex_col, selectcolor="#1a1a1a", activebackground="#333333", activeforeground=hex_col,
                                        command=lambda h=hex_col: self.change_color(h))
                    rb.pack(side=tk.LEFT, padx=3)

                # Tema
                self.lf_theme = tk.LabelFrame(self.frame, text=" Tema do Monitor ", bg="#050505", fg=self.current_color, font=("Consolas", 10))
                self.lf_theme.pack(fill=tk.X, pady=5, padx=5)
                
                self.theme_var = tk.IntVar(value=0)
                ttk.Radiobutton(self.lf_theme, text="Terminal Minimalista", variable=self.theme_var, value=0, command=self.send_commands).pack(anchor=tk.W, padx=10, pady=2)
                ttk.Radiobutton(self.lf_theme, text="z1p0 (Cannabis Bg)", variable=self.theme_var, value=1, command=self.send_commands).pack(anchor=tk.W, padx=10, pady=2)
                ttk.Radiobutton(self.lf_theme, text="GIF do Cartão SD", variable=self.theme_var, value=2, command=self.send_commands).pack(anchor=tk.W, padx=10, pady=2)
                ttk.Radiobutton(self.lf_theme, text="Heavy Metal (heavymetal.gif)", variable=self.theme_var, value=3, command=self.send_commands).pack(anchor=tk.W, padx=10, pady=2)
                
                # CYD Remote Control
                btn_frame_remote = tk.Frame(self.lf_theme, bg="#050505")
                btn_frame_remote.pack(fill=tk.X, padx=10, pady=5)
                ttk.Button(btn_frame_remote, text="Abrir Configurações na Placa", command=lambda: self.cmd_queue.put({"cmd_settings": 1})).pack(side=tk.LEFT, padx=5)
                
                # Brilho
                self.lf_bright = tk.LabelFrame(self.frame, text=" Brilho ", bg="#050505", fg=self.current_color, font=("Consolas", 10))
                self.lf_bright.pack(fill=tk.X, pady=5, padx=5)
                
                self.bright_var = tk.DoubleVar(value=128)
                scale = ttk.Scale(self.lf_bright, from_=10, to=255, variable=self.bright_var, orient=tk.HORIZONTAL)
                scale.pack(fill=tk.X, padx=10, pady=5)
                scale.bind("<ButtonRelease-1>", lambda e: self.send_commands())
                
                # GIF do SD
                self.lf_gif = tk.LabelFrame(self.frame, text=" Cartão SD (GIFs) ", bg="#050505", fg=self.current_color, font=("Consolas", 10))
                self.lf_gif.pack(fill=tk.X, pady=5, padx=5)
                
                self.txt_gif = tk.Entry(self.lf_gif, bg="#1a1a1a", fg=self.current_color, insertbackground=self.current_color, font=("Consolas", 10))
                self.txt_gif.insert(0, "/background.gif")
                self.txt_gif.pack(fill=tk.X, padx=10, pady=5)
                
                btn_frame = tk.Frame(self.lf_gif, bg="#050505")
                btn_frame.pack(fill=tk.X, padx=10, pady=5)
                ttk.Button(btn_frame, text="Tocar este GIF", command=self.send_commands).pack(side=tk.LEFT, padx=5)
                ttk.Button(btn_frame, text="Transferir GIF...", command=self.upload_gif).pack(side=tk.RIGHT, padx=5)
                
                self.prog_var = tk.DoubleVar()
                self.prog_bar = ttk.Progressbar(self.lf_gif, variable=self.prog_var, maximum=100)
                
                # Log
                self.txt_log = tk.Text(self.frame, height=8, bg="#0a0a0a", fg=self.current_color, font=("Consolas", 8))
                self.txt_log.pack(fill=tk.BOTH, expand=True, pady=5)

            def change_color(self, hex_col):
                self.current_color = hex_col
                self.update_styles()
                self.lf_color.config(fg=hex_col)
                self.lf_theme.config(fg=hex_col)
                self.lf_bright.config(fg=hex_col)
                self.lf_gif.config(fg=hex_col)
                self.txt_gif.config(fg=hex_col, insertbackground=hex_col)
                self.txt_log.config(fg=hex_col)
                self.send_commands()

            def upload_gif(self):
                filepath = filedialog.askopenfilename(title="Selecione um arquivo GIF", filetypes=[("Arquivos GIF", "*.gif")])
                if not filepath: return
                filename = "/" + os.path.basename(filepath)
                if len(filename) > 30:
                    messagebox.showerror("Erro", "Nome do arquivo muito longo.")
                    return
                try:
                    with open(filepath, "rb") as f:
                        data = f.read()
                except Exception as e:
                    messagebox.showerror("Erro", str(e))
                    return
                    
                self.txt_gif.delete(0, tk.END)
                self.txt_gif.insert(0, filename)
                
                def transfer_task():
                    self.prog_var.set(0)
                    self.prog_bar.pack(fill=tk.X, padx=10, pady=5)
                    chunk_size = 512
                    total = len(data)
                    self.transfer_queue.put({"file_name": filename, "file_mode": "w", "file_data": ""})
                    for i in range(0, total, chunk_size):
                        chunk = data[i:i+chunk_size]
                        b64 = base64.b64encode(chunk).decode('ascii')
                        self.transfer_queue.put({"file_name": filename, "file_mode": "a", "file_data": b64})
                        pct = (i + len(chunk)) / total * 100
                        self.root.after(0, lambda p=pct: self.prog_var.set(p))
                    self.root.after(0, lambda: self.prog_bar.pack_forget())
                    self.root.after(0, lambda: messagebox.showinfo("Sucesso", "GIF transferido com sucesso!"))
                    self.root.after(0, self.send_commands) # Força o tema a tocar o novo GIF
        
                threading.Thread(target=transfer_task, daemon=True).start()

            def log(self, msg):
                self.txt_log.insert(tk.END, msg + "\n")
                self.txt_log.see(tk.END)
                if int(self.txt_log.index('end-1c').split('.')[0]) > 50:
                    self.txt_log.delete('1.0', '2.0')
                
            def send_commands(self):
                cmd = {
                    "cmd_theme": self.theme_var.get(),
                    "cmd_bright": int(self.bright_var.get()),
                    "cmd_gif": self.txt_gif.get(),
                    "cmd_color": self.color_var.get()
                }
                self.cmd_queue.put(cmd)
        
            def on_close(self):
                self.root.withdraw()
                threading.Thread(target=self.setup_tray, daemon=True).start()
                
            def setup_tray(self):
                try:
                    import pystray
                    from PIL import Image, ImageDraw
                    
                    def create_image():
                        image = Image.new('RGB', (64, 64), color=(0, 0, 0))
                        dc = ImageDraw.Draw(image)
                        dc.rectangle((16, 16, 48, 48), fill=(0, 255, 0))
                        return image

                    def show_window(icon, item):
                        icon.stop()
                        self.root.after(0, self.root.deiconify)
                        
                    def quit_app(icon, item):
                        icon.stop()
                        self.running = False
                        self.root.after(0, self.root.destroy)
                        
                    menu = pystray.Menu(
                        pystray.MenuItem('Abrir CYD Monitor', show_window, default=True),
                        pystray.MenuItem('Sair', quit_app)
                    )
                    
                    self.tray_icon = pystray.Icon("CYDMonitor", create_image(), "CYD Hardware Monitor", menu)
                    self.tray_icon.run()
                except ImportError:
                    # Fallback se pystray não estiver instalado
                    self.running = False
                    self.root.after(0, self.root.destroy)
                
            def serial_loop(self):
                import serial
                ser = None
                while self.running:
                    try:
                        if ser is None:
                            port = self.args.port or find_port()
                            if not port:
                                self.root.after(0, lambda: self.lbl_status.config(text="Status: Nenhuma porta serial encontrada..."))
                                time.sleep(3)
                                continue
                            ser = serial.Serial(port, BAUD, timeout=1)
                            time.sleep(2.0)
                            ser.reset_input_buffer()
                            msg = f"Conectado em {port}"
                            self.root.after(0, lambda m=msg: self.lbl_status.config(text=f"Status: {m}"))
                            self.root.after(0, lambda m=msg: self.log(f"[{m}]"))
        
                        if not self.transfer_queue.empty():
                            pkt = self.transfer_queue.get_nowait()
                            line = json.dumps(pkt, separators=(",", ":")) + "\n"
                            ser.write(line.encode())
                            ser.flush()
                            time.sleep(0.05)
                            continue
                            
                        pkt = self.col.sample()
                        while not self.cmd_queue.empty():
                            cmd = self.cmd_queue.get_nowait()
                            pkt.update(cmd)
                        
                        line = json.dumps(pkt, separators=(",", ":")) + "\n"
                        ser.write(line.encode())
                        ser.flush()
                        
                        if "fps" in pkt:
                            fps_txt = f"FPS: {pkt['fps']:>3} | "
                        else:
                            fps_txt = ""
                        log_msg = f"{fps_txt}CPU: {pkt.get('cpu',0):>4}% | RAM: {pkt.get('ram',0):>4}% | T: {pkt.get('cput',0):>3}°C"
                        self.root.after(0, lambda m=log_msg: self.log(m))
        
                    except Exception as e:
                        self.root.after(0, lambda err=e: self.lbl_status.config(text=f"Status: Erro de conexão"))
                        if ser:
                            try:
                                ser.close()
                            except:
                                pass
                        ser = None
                        time.sleep(3)
                        continue
        
                    time.sleep(self.args.interval)
        
                if ser:
                    ser.close()

        root = tk.Tk()
        app = AgentGUI(root, col, args)
        root.mainloop()
        
    except ImportError:
        # Fallback to CLI if tkinter is missing
        print("[mike] Tkinter não encontrado. Rodando em modo texto.")
        import serial
        ser = None
        while True:
            try:
                if ser is None:
                    port = args.port or find_port()
                    if not port:
                        time.sleep(3)
                        continue
                    ser = serial.Serial(port, BAUD, timeout=1)
                    time.sleep(2.0)
                    ser.reset_input_buffer()
                line = json.dumps(col.sample(), separators=(",", ":")) + "\n"
                ser.write(line.encode())
                ser.flush()
            except KeyboardInterrupt:
                break
            except Exception:
                if ser:
                    try:
                        ser.close()
                    except:
                        pass
                ser = None
                time.sleep(3)
                continue
            time.sleep(args.interval)
        if ser:
            ser.close()

if __name__ == "__main__":
    main()
