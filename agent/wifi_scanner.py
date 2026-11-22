#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wifi_scanner.py - Modulo de Telemetria RF & Radar Wi-Fi para o CYD Cyber Deck.

Recebe telemetria sem fio via Wi-Fi UDP (porta 8889) da placa ESP32-WROOM-32U
com antena externa (alimentada por cabo micro-USB somente de energia) e tambem
suporta leitura opcional por Serial USB quando uma porta for explicitamente
informada.

Consolida metricas de redes proximas (SSID, RSSI, Canal, BSSID, Criptografia e
ocupacao dos canais 1..13) para exibicao na Tela 12 da CYD (SCR_WIFI_RADAR),
no Painel Desktop Flet e na interface Web/Mobile (:8088).
"""

import csv
import json
import os
import re
import socket
import threading
import time
import unicodedata
from datetime import datetime

UDP_SCANNER_LISTEN_PORT = 8889   # Porta onde a ESP32-WROOM-32U envia broadcasts JSON
UDP_SCANNER_CMD_PORT    = 8890   # Porta onde a ESP32-WROOM-32U escuta {"cmd":"scan_now"}
UDP_OFFLINE_TIMEOUT_S   = 30.0   # Marca offline se ficar >30s sem pacote UDP

SCANNER_SIGNATURES = (
    "lista redes wi-fi",
    "escaneando redes",
    "[ofensiva]",
    "wrad_json:",
    "esp32-wroom-32u wi-fi radar",
    "radar_status:",
)

CYD_SIGNATURES = (
    "MONITOR_READY",
    "SD_FILES:",
    "SD_INIT:",
    "UDP_PONG:",
    "WIFI_IP:",
    "TERM_LOG:",
    "ACK_START",
)

# Dicionario offline OUI (Organizationally Unique Identifier) com prefixos MAC
# reais comuns no Brasil, provedores de fibra (HGU) e equipamentos de homelab/IoT.
OUI_VENDORS: dict[str, str] = {
    # TP-Link
    "30:DE:4B": "TP-Link",
    "AC:15:A2": "TP-Link",
    "C0:25:2F": "TP-Link",
    "84:D8:1B": "TP-Link",
    "B8:1E:61": "TP-Link",
    "50:C7:BF": "TP-Link",
    "F4:F2:6D": "TP-Link",
    "18:D6:C7": "TP-Link",
    "E8:DE:27": "TP-Link",
    "98:DA:C4": "TP-Link",
    "D8:07:B6": "TP-Link",
    "60:32:B1": "TP-Link",
    "B0:95:75": "TP-Link",
    # Intelbras
    "4C:1B:86": "Intelbras",
    "58:10:8C": "Intelbras",
    "00:1A:3F": "Intelbras",
    "78:32:1B": "Intelbras",
    "D4:7C:44": "Intelbras",
    "38:71:DE": "Intelbras",
    "80:7D:3A": "Intelbras",
    # Huawei
    "48:4C:29": "Huawei",
    "00:E0:FC": "Huawei",
    "28:6E:D4": "Huawei",
    "88:28:B3": "Huawei",
    "C8:D1:5E": "Huawei",
    "F4:63:1F": "Huawei",
    "04:F9:38": "Huawei",
    "4C:FB:45": "Huawei",
    # ZTE
    "34:4B:50": "ZTE",
    "74:A7:8E": "ZTE",
    "9C:6F:52": "ZTE",
    "D0:15:4A": "ZTE",
    "EC:1D:7F": "ZTE",
    # MitraStar (Vivo Fibra HGU)
    "10:72:23": "MitraStar",
    "B0:B3:69": "MitraStar",
    "D8:FB:5E": "MitraStar",
    "7C:26:64": "MitraStar",
    "A8:4E:3F": "MitraStar",
    "E8:AD:A6": "MitraStar",
    # Askey (Vivo Fibra HGU)
    "E4:AB:89": "Askey",
    "70:5A:9E": "Askey",
    "B8:D9:4D": "Askey",
    "C8:B4:22": "Askey",
    "38:3B:C8": "Askey",
    # Ubiquiti (UniFi)
    "24:5A:4C": "Ubiquiti",
    "78:8A:20": "Ubiquiti",
    "80:2A:A8": "Ubiquiti",
    "F0:9F:C2": "Ubiquiti",
    "B4:FB:E4": "Ubiquiti",
    "68:D7:9A": "Ubiquiti",
    "E0:63:DA": "Ubiquiti",
    # MikroTik (RouterBOARD)
    "4C:5E:0C": "MikroTik",
    "64:D1:54": "MikroTik",
    "B8:69:F4": "MikroTik",
    "C4:AD:34": "MikroTik",
    "DC:2C:6E": "MikroTik",
    "E4:8D:8C": "MikroTik",
    "18:FD:74": "MikroTik",
    # Cisco / Linksys
    "00:1B:D5": "Cisco",
    "00:24:14": "Cisco",
    "58:AC:78": "Cisco",
    "F8:7B:20": "Cisco",
    "C0:25:5C": "Cisco",
    # Asus
    "04:92:26": "Asus",
    "2C:56:DC": "Asus",
    "38:D5:47": "Asus",
    "AC:9E:17": "Asus",
    "F0:79:59": "Asus",
    # D-Link
    "00:1C:F0": "D-Link",
    "1C:7E:E5": "D-Link",
    "28:10:7B": "D-Link",
    "C8:BE:19": "D-Link",
    "BC:F6:85": "D-Link",
    # Tenda
    "C8:3A:35": "Tenda",
    "D8:32:14": "Tenda",
    "50:0F:F5": "Tenda",
    "04:95:E6": "Tenda",
    # Mercusys
    "00:31:92": "Mercusys",
    "7C:C2:C6": "Mercusys",
    "C0:06:C3": "Mercusys",
    "40:AE:30": "Mercusys",
    # Espressif (ESP32 / ESP8266)
    "20:50:0D": "Espressif",
    "30:76:F5": "Espressif",
    "24:6F:28": "Espressif",
    "3C:71:BF": "Espressif",
    "84:CC:A8": "Espressif",
    "A4:CF:12": "Espressif",
    "B4:E6:2D": "Espressif",
    "C4:4F:33": "Espressif",
    "EC:FA:BC": "Espressif",
    "94:B9:7E": "Espressif",
    "7C:9E:BD": "Espressif",
    # Apple
    "00:17:F2": "Apple",
    "28:CF:E9": "Apple",
    "3C:22:FB": "Apple",
    "A4:83:E7": "Apple",
    "F0:18:98": "Apple",
    "BC:D0:74": "Apple",
    # Samsung
    "00:16:32": "Samsung",
    "28:39:5E": "Samsung",
    "50:01:BB": "Samsung",
    "8C:77:12": "Samsung",
    "BC:72:B1": "Samsung",
    # Xiaomi
    "28:6C:07": "Xiaomi",
    "64:09:80": "Xiaomi",
    "7C:1D:D9": "Xiaomi",
    "F8:A4:5F": "Xiaomi",
    "AC:C1:EE": "Xiaomi",
    # Realtek
    "00:E0:4C": "Realtek",
    "52:54:00": "Realtek",
    "74:DA:38": "Realtek",
    # Raspberry Pi
    "B8:27:EB": "RaspberryPi",
    "DC:A6:32": "RaspberryPi",
    "E4:5F:01": "RaspberryPi",
    "28:CD:C1": "RaspberryPi",
    "D8:3A:DD": "RaspberryPi",
    # Intel / FiberHome / Sagemcom / Arris / Multilaser
    "00:13:E8": "Intel",
    "3C:97:0E": "Intel",
    "8C:8D:28": "Intel",
    "A4:34:D9": "Intel",
    "00:0A:C2": "FiberHome",
    "74:B5:7E": "FiberHome",
    "F8:DF:A8": "FiberHome",
    "68:A3:78": "Sagemcom",
    "7C:03:D8": "Sagemcom",
    "00:1D:CE": "Arris",
    "90:03:B7": "Arris",
    "00:01:36": "Multilaser",
    "2C:3A:E8": "Multilaser",
}


def lookup_oui(bssid: str) -> str:
    """Resolve o fabricante (OUI) offline a partir de um endereco MAC / BSSID."""
    if not bssid:
        return "Desconhecido"
    hex_clean = re.sub(r"[^0-9A-Fa-f]", "", str(bssid)).upper()
    if len(hex_clean) < 6:
        return "Desconhecido"
    prefix = f"{hex_clean[0:2]}:{hex_clean[2:4]}:{hex_clean[4:6]}"
    if prefix in OUI_VENDORS:
        return OUI_VENDORS[prefix]
    try:
        first_octet = int(hex_clean[0:2], 16)
        if first_octet & 0x02:
            return "Local/Mesh"
    except Exception:
        pass
    return "Desconhecido"


def estimate_distance_m(rssi: int, tx_power_1m: float = -40.0, path_loss_exp: float = 2.7) -> float:
    """Estima a distancia indoor aproximada (em metros) via modelo log-distance / FSPL 2.4 GHz."""
    try:
        r = float(rssi)
    except Exception:
        return 99.9
    if r >= -25.0:
        return 0.5
    dist = 10.0 ** ((tx_power_1m - r) / (10.0 * path_loss_exp))
    return round(max(0.5, min(150.0, dist)), 1)


def _ascii_clean(text: str, max_len: int = 24) -> str:
    if not text:
        return "<OCULTA>"
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip()
    return (s or "<OCULTA>")[:max_len]


def _canonical_port(port: str | None) -> str:
    if not port:
        return ""
    try:
        return os.path.realpath(port)
    except Exception:
        return str(port)


def rssi_to_quality_pct(rssi: int) -> int:
    if rssi >= -45:
        return 100
    if rssi <= -95:
        return 0
    return int(round((rssi + 95) * 100.0 / 50.0))


def rssi_to_label(rssi: int) -> str:
    if rssi >= -60:
        return "Excelente"
    if rssi >= -72:
        return "Bom"
    if rssi >= -82:
        return "Medio"
    return "Fraco"


def is_scanner_banner_line(line: str) -> bool:
    low = (line or "").strip().lower()
    if not low:
        return False
    return any(sig in low for sig in SCANNER_SIGNATURES)


def is_cyd_banner_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    return any(s.startswith(sig) for sig in CYD_SIGNATURES)


class WiFiScannerCollector:
    """
    Coletor assincrono de telemetria Wi-Fi RF via Wi-Fi UDP (porta 8889).
    - Nao disputa portas USB com a CYD (a ESP32-WROOM-32U roda sem fio no cabo de energia).
    - Escuta broadcasts UDP em 0.0.0.0:8889 da ESP32-WROOM-32U.
    - Dispara scan remoto sob demanda via UDP :8890 ({"cmd":"scan_now"}).
    - Opcionalmente aceita `preferred_port` (ex: /dev/ttyUSB1) se conectada via cabo de dados.
    """

    def __init__(
        self,
        preferred_port: str = "",
        baud: int = 115200,
        scan_interval_s: float = 8.0,
        enabled: bool = True,
        excluded_ports_fn=None,
        on_log=None,
        auto_start: bool = True,
        udp_port: int = UDP_SCANNER_LISTEN_PORT,
    ):
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._preferred_port = (preferred_port or "").strip()
        self._baud = int(baud)
        self._scan_interval_s = max(4.0, min(120.0, float(scan_interval_s or 8.0)))
        self._udp_port = int(udp_port or UDP_SCANNER_LISTEN_PORT)
        self._excluded_ports_fn = excluded_ports_fn
        self._on_log = on_log
        self._on_ble_command = None

        self._running = False
        self._udp_thread: threading.Thread | None = None
        self._serial_thread: threading.Thread | None = None
        self._udp_sock: socket.socket | None = None

        self._active_port: str = ""       # Porta serial ativa (se usada)
        self._scanner_ip: str = ""        # IP Wi-Fi detectado da ESP32-WROOM-32U
        self._transport: str = "UDP"      # UDP | SERIAL
        self._online: bool = False
        self._scanning: bool = False
        self._ble_connected: bool = False
        self._ble_clients: int = 0
        self._ble_pwr: int = 9
        self._ble_name: str = "CYD-RADAR-32U"
        self._ble_last_push_ts: float = 0.0
        self._status_msg: str = f"Aguardando ESP32-WROOM-32U via Wi-Fi UDP :{self._udp_port}..."
        self._last_error: str = ""
        self._last_rx_mono: float = 0.0
        self._last_scan_ts: float = 0.0
        self._last_scan_str: str = "--:--:--"
        self._scan_count: int = 0
        self._total_reported: int = 0
        self._open_count: int = 0
        self._networks: list[dict] = []
        self._prev_bssids: set[str] = set()
        self._new_count: int = 0
        self._ch_counts: list[int] = [0] * 13
        self._busiest_ch: int = 0
        self._free_ch: int = 1
        self._best_rssi: int = -100
        self._avg_rssi: int = -100
        self._history: list[dict] = []
        self._ap_stats: dict[str, dict] = {}
        self._baseline_bssids: set[str] = set()
        self._prev_scan_map: dict[str, dict] = {}
        self._last_diff: dict = {
            "added": [],
            "removed": [],
            "rssi_changes": [],
            "ts": "--:--:--",
        }

        if auto_start:
            self.start()

    # -------------------------------------------------------------- API publica
    @property
    def active_port(self) -> str:
        with self._lock:
            return self._active_port

    def get_active_ports(self) -> set[str]:
        with self._lock:
            return {self._active_port} if self._active_port else set()

    def set_excluded_ports_fn(self, fn):
        self._excluded_ports_fn = fn

    def set_log_callback(self, fn):
        self._on_log = fn

    def set_ble_command_callback(self, fn):
        """Define callback chamado quando o smartphone conectado via BLE na ESP32-32U envia um comando."""
        self._on_ble_command = fn

    def is_ble_connected(self) -> bool:
        with self._lock:
            return bool(self._is_alive_locked() and self._ble_connected)

    def push_ble_snapshot(self, snap: dict):
        """Envia snapshot consolidado (HW + Rede + Seguranca/IDS + Mercado) via UDP :8890 para a ESP32-32U transmitir via BLE."""
        if not isinstance(snap, dict):
            return
        pkt = {"cmd": "ble_push", "snap": snap}
        try:
            raw = (json.dumps(pkt, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        except Exception:
            return
        if len(raw) > 1380:
            # Reduz logs caso exceda MTU UDP
            snap_trim = dict(snap)
            if isinstance(snap_trim.get("sec"), dict) and isinstance(snap_trim["sec"].get("logs"), list):
                snap_trim["sec"] = dict(snap_trim["sec"])
                snap_trim["sec"]["logs"] = snap_trim["sec"]["logs"][:3]
            raw = (json.dumps({"cmd": "ble_push", "snap": snap_trim}, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

        sock = self._udp_sock
        if sock is not None:
            self._send_udp_ctrl(sock, raw)
            with self._lock:
                self._ble_last_push_ts = time.time()
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._send_udp_ctrl(s, raw)
            s.close()
            with self._lock:
                self._ble_last_push_ts = time.time()
        except Exception:
            pass

    def start(self):
        if self._running:
            return
        self._running = True
        self._udp_thread = threading.Thread(
            target=self._udp_worker,
            daemon=True,
            name="WiFiRadarUdpThread",
        )
        self._udp_thread.start()

        if self._preferred_port:
            self._serial_thread = threading.Thread(
                target=self._serial_worker,
                daemon=True,
                name="WiFiRadarSerialThread",
            )
            self._serial_thread.start()

    def stop(self):
        self._running = False
        sock = self._udp_sock
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
            self._udp_sock = None

    def _resolve_scanner_targets(self) -> list[str]:
        """Resolve possiveis IPs unicast da ESP32-WROOM-32U (mDNS cyd-radar.local, IP conhecido e broadcast)."""
        targets: list[str] = []
        with self._lock:
            known_ip = self._scanner_ip
        if known_ip:
            targets.append(known_ip)
        # Tenta resolver mDNS (cyd-radar.local) automaticamente caso o IP mude no DHCP
        try:
            mdns_ip = socket.gethostbyname("cyd-radar.local")
            if mdns_ip and mdns_ip not in targets:
                targets.append(mdns_ip)
        except Exception:
            pass
        # Broadcast da sub-rede local como fallback de descoberta
        try:
            s_tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s_tmp.connect(("8.8.8.8", 80))
            local_ip = s_tmp.getsockname()[0]
            s_tmp.close()
            parts = local_ip.split(".")
            if len(parts) == 4:
                bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                if bcast not in targets:
                    targets.append(bcast)
        except Exception:
            pass
        if "255.255.255.255" not in targets:
            targets.append("255.255.255.255")
        return targets

    def _send_udp_ctrl(self, sock, cmd_bytes: bytes):
        if sock is None:
            return
        for dst in self._resolve_scanner_targets():
            try:
                sock.sendto(cmd_bytes, (dst, UDP_SCANNER_CMD_PORT))
            except OSError:
                pass

    def force_scan(self):
        """Envia comando UDP {"cmd":"scan_now"} na porta 8890 para a ESP32-WROOM-32U."""
        with self._lock:
            self._scanning = True
        sock = self._udp_sock
        if sock is not None:
            self._send_udp_ctrl(sock, b'{"cmd":"scan_now"}\n')
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._send_udp_ctrl(s, b'{"cmd":"scan_now"}\n')
            s.close()
        except Exception:
            pass

    def configure(self, enabled: bool = None, port: str = None, interval_s: float = None):
        start_serial = False
        with self._lock:
            if enabled is not None:
                self._enabled = bool(enabled)
            if port is not None:
                self._preferred_port = (port or "").strip()
                if self._preferred_port and self._running and (self._serial_thread is None or not self._serial_thread.is_alive()):
                    start_serial = True
            if interval_s is not None:
                try:
                    self._scan_interval_s = max(4.0, min(120.0, float(interval_s)))
                except Exception:
                    pass
        if start_serial:
            self._serial_thread = threading.Thread(
                target=self._serial_worker,
                daemon=True,
                name="WiFiRadarSerialThread",
            )
            self._serial_thread.start()

    def _emit_log(self, msg: str):
        if self._on_log:
            try:
                self._on_log(msg)
            except Exception:
                pass

    def _is_alive_locked(self) -> bool:
        if not self._online or self._last_rx_mono <= 0.0:
            return False
        return (time.monotonic() - self._last_rx_mono) <= UDP_OFFLINE_TIMEOUT_S

    # ------------------------------------------------------ payloads de saida
    def get_cyd_payload(self) -> dict:
        """Retorna payload compacto (~450 B) para o bloco 'wrad' da Tela 12 da CYD."""
        with self._lock:
            alive = self._is_alive_locked()
            age_s = int(max(0.0, time.time() - self._last_scan_ts)) if self._last_scan_ts > 0 else 999
            top_aps = []
            for net in self._networks[:6]:
                top_aps.append([
                    _ascii_clean(net.get("ssid", ""), 16),
                    int(net.get("rssi", -100)),
                    int(net.get("ch", 0)),
                    str(net.get("bssid", ""))[:17],
                ])
            src_lbl = f"UDP:{self._scanner_ip}" if self._scanner_ip else (os.path.basename(self._active_port) if self._active_port else "")
            return {
                "on": bool(alive),
                "scan": bool(self._scanning and alive),
                "port": src_lbl,
                "tot": int(self._total_reported or len(self._networks)),
                "open": int(self._open_count),
                "new": int(self._new_count),
                "best": int(self._best_rssi) if self._networks else 0,
                "avg": int(self._avg_rssi) if self._networks else 0,
                "bch": int(self._busiest_ch),
                "fch": int(self._free_ch),
                "age": min(age_s, 999),
                "sc": int(self._scan_count),
                "ble": 1 if (alive and self._ble_connected) else 0,
                "bcli": int(self._ble_clients if alive else 0),
                "bpwr": int(self._ble_pwr),
                "ch": list(self._ch_counts),
                "aps": top_aps,
            }

    def get_ui_snapshot(self) -> dict:
        """Retorna snapshot completo para a interface Desktop Flet e Painel Web/Mobile."""
        with self._lock:
            alive = self._is_alive_locked()
            age_s = int(max(0.0, time.time() - self._last_scan_ts)) if self._last_scan_ts > 0 else -1
            status = self._status_msg
            if not alive and self._scan_count > 0:
                status = f"ESP32-WROOM-32U sem sinal ha {max(0, age_s)}s (UDP :{self._udp_port})"
            return {
                "enabled": bool(self._enabled),
                "online": bool(alive),
                "scanning": bool(self._scanning and alive),
                "transport": self._transport,
                "scanner_ip": self._scanner_ip,
                "port": self._scanner_ip or self._active_port or f"UDP:{self._udp_port}",
                "preferred_port": self._preferred_port,
                "interval_s": self._scan_interval_s,
                "status_msg": status,
                "last_error": self._last_error,
                "last_scan_str": self._last_scan_str,
                "age_s": age_s,
                "scan_count": self._scan_count,
                "total": int(self._total_reported or len(self._networks)),
                "open_count": int(self._open_count),
                "new_count": self._new_count,
                "best_rssi": self._best_rssi if self._networks else 0,
                "avg_rssi": self._avg_rssi if self._networks else 0,
                "busiest_ch": self._busiest_ch,
                "free_ch": self._free_ch,
                "ble_connected": bool(alive and self._ble_connected),
                "ble_clients": int(self._ble_clients if alive else 0),
                "ble_pwr_dbm": int(self._ble_pwr),
                "ble_name": str(self._ble_name or "CYD-RADAR-32U"),
                "ch_counts": list(self._ch_counts),
                "networks": [dict(n) for n in self._networks],
                "history": list(self._history),
            }

    # ------------------------------------------------------ inteligencia RF & analise
    def wait_for_fresh_scan(self, timeout_s: float = 6.0) -> dict:
        """Dispara force_scan() e aguarda scan_count incrementar (ou retorna o snapshot atual apos timeout)."""
        with self._lock:
            sc0 = self._scan_count
            is_running = self._running
            alive = self._is_alive_locked()
        self.force_scan()
        if not is_running or not alive:
            # Em modo offline/teste sem socket ativo aguarda apenas uma janela curta
            wait_limit = min(float(timeout_s or 0.0), 0.25) if not is_running else min(float(timeout_s or 0.0), 1.5)
        else:
            wait_limit = max(0.2, float(timeout_s or 6.0))
        deadline = time.monotonic() + wait_limit
        while time.monotonic() < deadline:
            with self._lock:
                if self._scan_count > sc0:
                    break
            time.sleep(0.1)
        return self.get_ui_snapshot()

    def get_spectrum_analysis(self) -> dict:
        """
        Analisa ocupacao e interferencia ponderada por canal 1..13 (co-canal + adjacentes +-2)
        e classifica os 3 canais nao-sobrepostos (1, 6 e 11) com nota e recomendacao.
        """
        with self._lock:
            ch_counts = list(self._ch_counts)
            nets = [dict(n) for n in self._networks]

        # Pesos de interferencia por sobreposicao de espectro 2.4 GHz (20 MHz bandwidth)
        overlap_weights = {0: 1.0, 1: 0.55, 2: 0.25}
        channels_info: dict[int, dict] = {}
        channel_list: list[dict] = []

        for ch in range(1, 14):
            co_aps = [n for n in nets if int(n.get("ch", 0)) == ch]
            cnt = ch_counts[ch - 1] if (0 <= ch - 1 < len(ch_counts)) else len(co_aps)
            cnt = max(cnt, len(co_aps))
            max_rssi = max((int(n.get("rssi", -100)) for n in co_aps), default=-100)

            adj_cnt = 0
            weighted_score = 0.0
            if nets:
                for n in nets:
                    ap_ch = int(n.get("ch", 0))
                    dist = abs(ap_ch - ch)
                    if dist in overlap_weights:
                        if dist > 0:
                            adj_cnt += 1
                        rssi_v = int(n.get("rssi", -85))
                        # Peso por potencia do sinal: -45 dBm -> 1.35x, -70 dBm -> 0.85x, -90 dBm -> 0.45x
                        sig_factor = max(0.35, min(1.5, (rssi_v + 112.0) / 50.0))
                        weighted_score += overlap_weights[dist] * sig_factor
            else:
                for other_ch in range(1, 14):
                    dist = abs(other_ch - ch)
                    if dist in overlap_weights:
                        c_other = ch_counts[other_ch - 1]
                        if dist > 0:
                            adj_cnt += c_other
                        weighted_score += overlap_weights[dist] * float(c_other)

            score_r = round(weighted_score, 2)
            if score_r <= 0.8 and cnt == 0:
                grade = "LIVRE"
            elif score_r <= 2.5:
                grade = "BOM"
            elif score_r <= 4.5:
                grade = "MODERADO"
            else:
                grade = "CONGESTIONADO"

            info = {
                "ch": ch,
                "count": int(cnt),
                "adj_count": int(adj_cnt),
                "max_rssi": int(max_rssi),
                "interference": score_r,
                "score": score_r,
                "grade": grade,
            }
            channels_info[ch] = info
            channel_list.append(info)

        non_overlap_chs = [1, 6, 11]
        ranking = []
        for ch in non_overlap_chs:
            ci = dict(channels_info[ch])
            # Nota de 0 a 10 (10 = espectro totalmente limpo)
            rating = round(max(0.0, 10.0 - ci["score"] * 1.4), 1)
            ci["rating"] = rating
            ci["recommendation"] = f"CH{ch:02d}: {ci['grade']} ({ci['count']} APs, adj {ci['adj_count']}, nota {rating}/10)"
            ranking.append(ci)

        ranking.sort(key=lambda x: (x["score"], x["count"], x["adj_count"], x["max_rssi"]))
        best = ranking[0]
        busiest = max(channel_list, key=lambda x: (x["count"], x["score"])) if any(x["count"] > 0 for x in channel_list) else channels_info[1]

        return {
            "ch_counts": [channels_info[c]["count"] for c in range(1, 14)],
            "channels": channels_info,
            "channel_list": channel_list,
            "non_overlapping": ranking,
            "ranking": ranking,
            "best_channel": best["ch"],
            "best_grade": best["grade"],
            "best_score": best["score"],
            "busiest_channel": busiest["ch"] if busiest["count"] > 0 else 0,
            "recommendation": f"Use CH{best['ch']:02d} ({best['grade']} | {best['count']} APs | nota {best['rating']}/10)",
        }

    def get_rf_audit(self) -> dict:
        """
        Auditoria passiva e defensiva do espectro Wi-Fi 2.4 GHz:
        - Redes abertas (OPEN)
        - Redes com SSID oculto (<OCULTA>)
        - Redes com criptografia legada/fraca (WEP)
        - SSIDs com multiplos BSSIDs (Mesh / Roaming / APs duplicados)
        - Canais congestionados (>= 3 APs)
        """
        with self._lock:
            nets = [dict(n) for n in self._networks]
            ch_counts = list(self._ch_counts)

        open_nets = [n for n in nets if str(n.get("enc", "")).upper() in ("OPEN", "NONE", "")]
        hidden_nets = [n for n in nets if not n.get("ssid") or n.get("ssid") == "<OCULTA>"]
        wep_nets = [n for n in nets if "WEP" in str(n.get("enc", "")).upper()]

        by_ssid: dict[str, list[dict]] = {}
        for n in nets:
            s = str(n.get("ssid") or "").strip()
            if not s or s == "<OCULTA>":
                continue
            by_ssid.setdefault(s, []).append(n)

        multi_bssid = []
        for s, items in by_ssid.items():
            bssids = sorted({str(x.get("bssid") or "") for x in items if x.get("bssid")})
            if len(bssids) >= 2 or len(items) >= 2:
                multi_bssid.append({
                    "ssid": s,
                    "count": max(len(bssids), len(items)),
                    "bssids": bssids,
                    "channels": sorted({int(x.get("ch", 0)) for x in items}),
                    "vendors": sorted({str(x.get("vendor") or lookup_oui(x.get("bssid", ""))) for x in items}),
                })
        multi_bssid.sort(key=lambda x: x["count"], reverse=True)

        congested = []
        for idx, c in enumerate(ch_counts):
            ch_num = idx + 1
            actual_c = max(int(c), sum(1 for n in nets if int(n.get("ch", 0)) == ch_num))
            if actual_c >= 3:
                congested.append({"ch": ch_num, "count": actual_c})
        congested.sort(key=lambda x: x["count"], reverse=True)

        findings = len(open_nets) + len(wep_nets) + len(congested)
        status = "WARN" if findings > 0 else "OK"

        return {
            "total_aps": len(nets),
            "open_networks": open_nets,
            "hidden_networks": hidden_nets,
            "wep_networks": wep_nets,
            "multi_bssid_ssids": multi_bssid,
            "congested_channels": congested,
            "status": status,
        }

    def track_ap(self, query: str) -> list[dict]:
        """
        Busca por substring em SSID ou BSSID (case-insensitive) e retorna estatisticas
        historicas (cur, min, avg, max, spread, ch, enc, vendor, est_dist_m).
        """
        q = (query or "").strip().lower()
        with self._lock:
            stats_all = [dict(v, rssi_samples=list(v.get("rssi_samples", []))) for v in self._ap_stats.values()]
            active_bssids = {n.get("bssid") for n in self._networks if n.get("bssid")}
            active_ssids = {n.get("ssid") for n in self._networks if n.get("ssid")}

        results = []
        for st in stats_all:
            ssid = str(st.get("ssid") or "<OCULTA>")
            bssid = str(st.get("bssid") or "")
            vendor = str(st.get("vendor") or lookup_oui(bssid))
            if q and q not in ("*", "all"):
                if q not in ssid.lower() and q not in bssid.lower() and q not in vendor.lower():
                    continue
            samples = st.get("rssi_samples") or [int(st.get("rssi_cur", -100))]
            cur_r = int(st.get("rssi_cur", samples[-1]))
            min_r = int(st.get("rssi_min", min(samples)))
            max_r = int(st.get("rssi_max", max(samples)))
            avg_r = round(sum(samples) / float(len(samples)), 1)
            spread_db = int(max_r - min_r)
            if len(samples) > 1:
                diffs = [abs(samples[i] - samples[i - 1]) for i in range(1, len(samples))]
                jitter_db = round(sum(diffs) / float(len(diffs)), 1)
            else:
                jitter_db = 0.0

            is_active = (bssid in active_bssids) if bssid else (ssid in active_ssids)
            results.append({
                "ssid": ssid,
                "bssid": bssid,
                "cur": cur_r,
                "min": min_r,
                "avg": avg_r,
                "max": max_r,
                "spread": spread_db,
                "jitter_db": jitter_db,
                "ch": int(st.get("ch", 0)),
                "enc": str(st.get("enc", "WPA")),
                "vendor": vendor,
                "est_dist_m": estimate_distance_m(cur_r),
                "seen_count": int(st.get("seen_count", 1)),
                "first_seen": str(st.get("first_seen", "--:--:--")),
                "last_seen": str(st.get("last_seen", "--:--:--")),
                "active": bool(is_active),
            })

        results.sort(key=lambda x: (1 if x["active"] else 0, x["cur"], x["max"]), reverse=True)
        return results

    def get_diff_report(self) -> dict:
        """Retorna diferencas de redes (novas, ausentes e variacoes de RSSI) vs scan anterior e baseline."""
        with self._lock:
            baseline = set(self._baseline_bssids)
            cur_nets = [dict(n) for n in self._networks]
            last_diff = {
                "added": [dict(x) for x in self._last_diff.get("added", [])],
                "removed": [dict(x) for x in self._last_diff.get("removed", [])],
                "rssi_changes": [dict(x) for x in self._last_diff.get("rssi_changes", [])],
                "ts": self._last_diff.get("ts", self._last_scan_str),
            }
            ap_stats_copy = {k: dict(v) for k, v in self._ap_stats.items()}

        cur_bssids = {n.get("bssid") for n in cur_nets if n.get("bssid")}
        base_added_bssids = cur_bssids - baseline if baseline else set()
        base_removed_bssids = baseline - cur_bssids if baseline else set()

        base_added = [n for n in cur_nets if n.get("bssid") in base_added_bssids]
        base_removed = [
            ap_stats_copy.get(b, {"bssid": b, "ssid": "<ANTERIOR>", "ch": 0, "rssi": -100})
            for b in sorted(base_removed_bssids)
        ]

        added_out = last_diff["added"] if last_diff["added"] else base_added
        removed_out = last_diff["removed"] if last_diff["removed"] else base_removed

        return {
            "baseline_count": len(baseline),
            "current_count": len(cur_nets),
            "added": added_out,
            "removed": removed_out,
            "rssi_changes": last_diff["rssi_changes"],
            "baseline_added": base_added,
            "baseline_removed": base_removed,
            "ts": last_diff["ts"],
        }

    def export_report(self, fmt: str = "json", out_dir: str = "reports") -> str:
        """Salva relatorio RF completo em reports/rf_report_YYYYMMDD_HHMMSS.json (ou .csv)."""
        fmt_clean = (fmt or "json").strip().lower()
        if fmt_clean not in ("json", "csv"):
            fmt_clean = "json"
        os.makedirs(out_dir, exist_ok=True)
        ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"rf_report_{ts_file}.{fmt_clean}")

        snap = self.get_ui_snapshot()
        spec = self.get_spectrum_analysis()
        audit = self.get_rf_audit()
        tracked = self.track_ap("*")
        diff = self.get_diff_report()

        if fmt_clean == "csv":
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ssid", "bssid", "vendor", "ch", "enc",
                    "cur_rssi", "min_rssi", "avg_rssi", "max_rssi",
                    "spread_db", "jitter_db", "est_dist_m",
                    "seen_count", "first_seen", "last_seen", "active",
                ])
                for row in tracked:
                    writer.writerow([
                        row["ssid"], row["bssid"], row["vendor"], row["ch"], row["enc"],
                        row["cur"], row["min"], row["avg"], row["max"],
                        row["spread"], row["jitter_db"], row["est_dist_m"],
                        row["seen_count"], row["first_seen"], row["last_seen"], row["active"],
                    ])
        else:
            report_doc = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "scanner": {
                    "online": snap["online"],
                    "transport": snap["transport"],
                    "scanner_ip": snap["scanner_ip"],
                    "scan_count": snap["scan_count"],
                    "last_scan_str": snap["last_scan_str"],
                },
                "summary": {
                    "total_aps": snap["total"],
                    "open_count": snap["open_count"],
                    "best_rssi": snap["best_rssi"],
                    "avg_rssi": snap["avg_rssi"],
                    "free_ch": spec["best_channel"],
                    "busiest_ch": spec["busiest_channel"],
                    "recommendation": spec["recommendation"],
                },
                "spectrum": spec,
                "audit": audit,
                "diff": diff,
                "ap_history": tracked,
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report_doc, f, indent=2, ensure_ascii=False)

        return out_path

    # ------------------------------------------------------ ingestao JSON
    def _ingest_packet(self, doc: dict, src_ip: str = "", transport: str = "UDP"):
        blk = doc.get("wrad_full") or doc.get("wrad")
        if not isinstance(blk, dict):
            return

        raw_aps = blk.get("aps") or []
        networks: list[dict] = []
        seen_bssid: set[str] = set()

        for row in raw_aps:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            ssid_raw = str(row[0] or "").strip()
            try:
                rssi = int(row[1])
                ch = int(row[2])
            except Exception:
                continue
            bssid = str(row[3] if len(row) > 3 else "").upper().strip()
            enc = str(row[4] if len(row) > 4 else "WPA").upper().strip()
            key = bssid or f"{ssid_raw}_{ch}_{rssi}"
            if key in seen_bssid:
                continue
            seen_bssid.add(key)
            vendor = lookup_oui(bssid)
            networks.append({
                "ssid": ssid_raw or "<OCULTA>",
                "ssid_ascii": _ascii_clean(ssid_raw, 24),
                "ch": ch,
                "rssi": rssi,
                "bssid": bssid,
                "oui": bssid[:8] if len(bssid) >= 8 else "",
                "vendor": vendor,
                "enc": enc,
                "quality": rssi_to_quality_pct(rssi),
                "label": rssi_to_label(rssi),
                "est_dist_m": estimate_distance_m(rssi),
            })

        networks.sort(key=lambda x: x["rssi"], reverse=True)

        ch_raw = blk.get("ch")
        if isinstance(ch_raw, list) and len(ch_raw) == 13:
            ch_counts = [max(0, int(v)) for v in ch_raw]
        else:
            ch_counts = [0] * 13
            for n in networks:
                if 1 <= n["ch"] <= 13:
                    ch_counts[n["ch"] - 1] += 1

        tot = int(blk.get("tot", len(networks)))
        open_cnt = int(blk.get("open", sum(1 for n in networks if n.get("enc") == "OPEN")))
        best_rssi = int(blk.get("best", networks[0]["rssi"] if networks else 0))
        avg_rssi = int(blk.get("avg", round(sum(n["rssi"] for n in networks) / len(networks)) if networks else 0))
        busiest_ch = int(blk.get("bch", (ch_counts.index(max(ch_counts)) + 1) if any(ch_counts) else 0))
        free_ch = int(blk.get("fch", 1))
        ip_str = str(blk.get("ip") or src_ip or "").strip()

        now_ts = time.time()
        now_m = time.monotonic()
        now_str = datetime.now().strftime("%H:%M:%S")
        cur_bssids = {n["bssid"] for n in networks if n["bssid"]}
        cur_map = {(n["bssid"] or f"{n['ssid']}_{n['ch']}"): dict(n) for n in networks}

        first_online = False
        with self._lock:
            was_online = self._is_alive_locked()
            first_online = not was_online
            if not self._baseline_bssids and cur_bssids:
                self._baseline_bssids = set(cur_bssids)

            if self._prev_scan_map:
                prev_keys = set(self._prev_scan_map.keys())
                cur_keys = set(cur_map.keys())
                added_list = [dict(cur_map[k]) for k in sorted(cur_keys - prev_keys)]
                removed_list = [dict(self._prev_scan_map[k]) for k in sorted(prev_keys - cur_keys)]
                rssi_changes = []
                for k in (cur_keys & prev_keys):
                    prev_r = int(self._prev_scan_map[k].get("rssi", -100))
                    cur_r = int(cur_map[k].get("rssi", -100))
                    delta = cur_r - prev_r
                    if delta != 0:
                        rssi_changes.append({
                            "bssid": cur_map[k].get("bssid", ""),
                            "ssid": cur_map[k].get("ssid", "<OCULTA>"),
                            "ch": cur_map[k].get("ch", 0),
                            "prev_rssi": prev_r,
                            "cur_rssi": cur_r,
                            "delta": delta,
                        })
                rssi_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
                self._last_diff = {
                    "added": added_list,
                    "removed": removed_list,
                    "rssi_changes": rssi_changes,
                    "ts": now_str,
                }
            if cur_map:
                self._prev_scan_map = cur_map

            for n in networks:
                bkey = n["bssid"] or f"{n['ssid']}_CH{n['ch']}"
                st = self._ap_stats.get(bkey)
                if st is None:
                    self._ap_stats[bkey] = {
                        "bssid": n["bssid"],
                        "ssid": n["ssid"],
                        "ch": n["ch"],
                        "enc": n["enc"],
                        "vendor": n["vendor"],
                        "first_seen": now_str,
                        "last_seen": now_str,
                        "seen_count": 1,
                        "rssi_cur": n["rssi"],
                        "rssi_min": n["rssi"],
                        "rssi_max": n["rssi"],
                        "rssi_samples": [n["rssi"]],
                    }
                else:
                    if n["ssid"] and n["ssid"] != "<OCULTA>":
                        st["ssid"] = n["ssid"]
                    st["ch"] = n["ch"]
                    st["enc"] = n["enc"]
                    st["vendor"] = n["vendor"]
                    st["last_seen"] = now_str
                    st["seen_count"] = int(st.get("seen_count", 0)) + 1
                    st["rssi_cur"] = n["rssi"]
                    st["rssi_min"] = min(int(st.get("rssi_min", n["rssi"])), n["rssi"])
                    st["rssi_max"] = max(int(st.get("rssi_max", n["rssi"])), n["rssi"])
                    samples = list(st.get("rssi_samples", []))
                    samples.append(n["rssi"])
                    if len(samples) > 12:
                        samples = samples[-12:]
                    st["rssi_samples"] = samples

            new_cnt = len(cur_bssids - self._prev_bssids) if self._prev_bssids else 0
            if cur_bssids:
                self._prev_bssids = cur_bssids
            self._networks = networks
            self._total_reported = max(tot, len(networks))
            self._open_count = open_cnt
            self._new_count = new_cnt
            self._ch_counts = ch_counts
            self._busiest_ch = busiest_ch
            self._free_ch = free_ch
            self._best_rssi = best_rssi
            self._avg_rssi = avg_rssi
            self._last_scan_ts = now_ts
            self._last_rx_mono = now_m
            self._last_scan_str = now_str
            self._scan_count += 1
            self._online = True
            self._scanning = False
            self._transport = transport
            if "ble" in blk:
                self._ble_connected = bool(int(blk.get("ble") or 0))
            if "bcli" in blk:
                self._ble_clients = max(0, int(blk.get("bcli") or 0))
            if "bpwr" in blk:
                self._ble_pwr = int(blk.get("bpwr") or 9)
            if blk.get("bnam"):
                self._ble_name = str(blk.get("bnam"))[:24]
            if ip_str:
                self._scanner_ip = ip_str
            self._last_error = ""
            via_str = f"Wi-Fi {self._scanner_ip}" if transport == "UDP" and self._scanner_ip else transport
            ble_tag = f" • BLE ON ({self._ble_clients})" if self._ble_connected else " • BLE +9dBm"
            self._status_msg = (
                f"ESP32-WROOM-32U Online ({via_str}{ble_tag}) • "
                f"{self._total_reported} redes • Livre: CH{free_ch}"
            )
            self._history.append({"t": now_str, "tot": self._total_reported, "best": best_rssi})
            if len(self._history) > 30:
                del self._history[0]

        if first_online:
            self._emit_log(
                f"📡 ESP32-WROOM-32U conectada via {transport} ({ip_str or self._active_port}) — "
                f"{self._total_reported} redes detectadas (Livre: CH{free_ch})"
            )

    # ------------------------------------------------------ worker UDP (:8889)
    def _udp_worker(self):
        while self._running:
            if not self._enabled:
                time.sleep(0.8)
                continue

            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except OSError:
                        pass
                sock.bind(("0.0.0.0", self._udp_port))
                sock.settimeout(1.0)
                self._udp_sock = sock
            except Exception as ex:
                with self._lock:
                    self._last_error = f"UDP bind :{self._udp_port} falhou: {str(ex)[:45]}"
                time.sleep(2.5)
                continue

            last_sub_t = 0.0
            while self._running and self._enabled:
                now_m = time.monotonic()
                # Renova inscricao unicast a cada 12s (ou 4s enquanto offline) na porta :8890
                sub_period = 12.0 if self._is_alive_locked() else 4.0
                if (now_m - last_sub_t) >= sub_period:
                    last_sub_t = now_m
                    self._send_udp_ctrl(sock, b'{"cmd":"sub"}\n')
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    continue
                raw = data.decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                try:
                    doc = json.loads(raw)
                    if isinstance(doc, dict):
                        if "wrad" in doc or "wrad_full" in doc:
                            self._ingest_packet(doc, src_ip=addr[0], transport="UDP")
                        elif "ble_cmd" in doc:
                            cb = self._on_ble_command
                            if cb is not None:
                                try:
                                    cb(doc["ble_cmd"], src_ip=addr[0])
                                except Exception:
                                    pass
                except Exception:
                    continue

            try:
                sock.close()
            except Exception:
                pass
            self._udp_sock = None

    # ---------------------------------------- worker Serial opcional (debug USB)
    def _serial_worker(self):
        import serial

        while self._running:
            with self._lock:
                pref = self._preferred_port
                enabled = self._enabled
            if not enabled or not pref:
                time.sleep(1.5)
                continue

            ser = None
            try:
                ser = serial.Serial(port=pref, baudrate=self._baud, timeout=0.5)
                with self._lock:
                    self._active_port = pref
                while self._running and self._enabled:
                    raw_b = ser.readline()
                    if not raw_b:
                        continue
                    ln = raw_b.decode("utf-8", errors="ignore").strip()
                    if ln.startswith("WRAD_JSON:"):
                        try:
                            doc = json.loads(ln.split("WRAD_JSON:", 1)[1])
                            self._ingest_packet(doc, src_ip="", transport="SERIAL")
                        except Exception:
                            pass
            except Exception as ex:
                with self._lock:
                    self._last_error = str(ex)[:60]
            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
                with self._lock:
                    self._active_port = ""
            time.sleep(2.0)
