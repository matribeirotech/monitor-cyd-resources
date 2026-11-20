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

        self._running = False
        self._udp_thread: threading.Thread | None = None
        self._serial_thread: threading.Thread | None = None
        self._udp_sock: socket.socket | None = None

        self._active_port: str = ""       # Porta serial ativa (se usada)
        self._scanner_ip: str = ""        # IP Wi-Fi detectado da ESP32-WROOM-32U
        self._transport: str = "UDP"      # UDP | SERIAL
        self._online: bool = False
        self._scanning: bool = False
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
                "ch_counts": list(self._ch_counts),
                "networks": [dict(n) for n in self._networks],
                "history": list(self._history),
            }

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
            networks.append({
                "ssid": ssid_raw or "<OCULTA>",
                "ssid_ascii": _ascii_clean(ssid_raw, 24),
                "ch": ch,
                "rssi": rssi,
                "bssid": bssid,
                "oui": bssid[:8] if len(bssid) >= 8 else "",
                "enc": enc,
                "quality": rssi_to_quality_pct(rssi),
                "label": rssi_to_label(rssi),
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

        first_online = False
        with self._lock:
            was_online = self._is_alive_locked()
            first_online = not was_online
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
            if ip_str:
                self._scanner_ip = ip_str
            self._last_error = ""
            via_str = f"Wi-Fi {self._scanner_ip}" if transport == "UDP" and self._scanner_ip else transport
            self._status_msg = (
                f"ESP32-WROOM-32U Online ({via_str}) • "
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
                    if isinstance(doc, dict) and ("wrad" in doc or "wrad_full" in doc):
                        self._ingest_packet(doc, src_ip=addr[0], transport="UDP")
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
