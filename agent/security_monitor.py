#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
security_monitor.py - Modulo de Seguranca, IDS & Logs/Erros do Sistema (Tela 14).

Monitora em tempo real (baixo consumo de CPU, <0.5%) eventos de seguranca,
tentativas de invasao e erros criticos do sistema operacional para exibicao na
Tela 14 da CYD (SCR_SECURITY), alerta fisico (Buzzer + LED RGB vermelho),
Painel Web/Mobile (:8088 / :8443), Bluetooth Longo Alcance (ESP32-32U) e CLI `cyd sec`.

Fontes defensivas monitoradas:
  1) Autenticacao / Invasao (journalctl: sshd, sudo, su, polkit, PAM, firewalld/UFW).
  2) Erros de Sistema / Kernel (journalctl -p err..emerg, falhas de servico, OOM, segfault).
  3) Conexoes e Portas (psutil.net_connections: novas portas LISTEN, surto SYN_RECV / port-scan,
     acessos remotos externos em SSH/RDP/VNC/Telnet/SMB).
  4) Perimetro LAN & ARP Spoofing (integrado com NetworkAnalyzerCollector: troca de MAC do
     gateway/roteador e novos dispositivos desconhecidos na LAN).
  5) Perimetro Wi-Fi RF (integrado com WiFiScannerCollector: deteccao basica de Evil Twin /
     AP aberto clonando SSID protegido).
"""

import os
import platform
import re
import subprocess
import threading
import time
import unicodedata
from datetime import datetime

import psutil

IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

REMOTE_SHELL_PORTS = {22, 23, 3389, 5900, 5901, 445}

AUTH_FAIL_PATTERNS = (
    re.compile(r"failed password for(?: invalid user)?\s+(\S+)\s+from\s+([\d.a-fA-F:]+)", re.I),
    re.compile(r"invalid user\s+(\S+)\s+from\s+([\d.a-fA-F:]+)", re.I),
    re.compile(r"connection closed by authenticating user\s+(\S+)\s+([\d.a-fA-F:]+)", re.I),
    re.compile(r"possible break-in attempt", re.I),
    re.compile(r"authentication failure.*rhost=([\d.a-fA-F:]*)", re.I),
    re.compile(r"incorrect password attempts", re.I),
    re.compile(r"user NOT in sudoers", re.I),
    re.compile(r"pam_unix\([^)]+\):\s+authentication failure", re.I),
    re.compile(r"failed to authenticate", re.I),
)

FIREWALL_DROP_PATTERNS = (
    re.compile(r"(?:UFW BLOCK|FINAL_REJECT|REJECT|DROP).*SRC=([\d.a-fA-F:]+)", re.I),
)

SYS_ERR_NOISE_IGNORE = (
    "irqbalance",
    "gsd-media-keys",
    "mpris",
    "could not get current screen",
    "bluetoothd",
    "pulseaudio",
    "pipewire",
)

IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _ascii_clean(text: str, max_len: int = 44) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


def _run_cmd(cmd: list[str], timeout: float = 3.5) -> str:
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


class SecurityMonitorCollector:
    """
    Coletor assincrono de Seguranca, IDS & Logs de Erro para a Tela 14 da CYD.
    """

    def __init__(
        self,
        net_col=None,
        wifi_scan_col=None,
        poll_interval_s: float = 4.0,
        auto_start: bool = True,
        on_log=None,
    ):
        self._net_col = net_col
        self._wifi_scan_col = wifi_scan_col
        self._poll_interval = max(2.0, float(poll_interval_s))
        self._on_log = on_log

        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        # Estado consolidado
        self._level = 0  # 0=SEGURO, 1=ATENCAO, 2=INVASAO/CRIT
        self._status = "SEGURO"
        self._auth_fails = 0
        self._sys_errors = 0
        self._fw_blocks = 0
        self._port_scans = 0
        self._unknown_lan = 0
        self._rogue_aps = 0
        self._arp_spoof = False
        self._open_ports: list[int] = []
        self._ext_conns: list[dict] = []
        self._last_ip = "---"
        self._last_alert_msg = ""
        self._last_scan_str = "--:--:--"
        self._scan_count = 0

        # Baselines defensivos (aprendidos no inicio ou via trust_baseline)
        self._baseline_lan_macs: set[str] = set()
        self._baseline_gw_mac: str = ""
        self._baseline_listen_ports: set[int] = set()
        self._baseline_ready = False

        # Controle de deduplicacao de logs e cooldown de alarme fisico
        self._seen_keys: set[str] = set()
        self._seen_order: list[str] = []
        self._events: list[dict] = []  # mais recente no final
        self._pending_alarm: dict | None = None
        self._last_alarm_ts: float = 0.0
        self._sim_active = False

        self._add_event(0, "SYS", "IDS CYD iniciado • Perimetro ativo", "")

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

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="SecurityMonitorThread",
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def force_scan(self):
        threading.Thread(target=self._run_once, daemon=True).start()

    def _add_event(self, sev: int, cat: str, msg: str, ip: str = "", dedup_key: str = "") -> bool:
        now_hm = datetime.now().strftime("%H:%M")
        now_hms = datetime.now().strftime("%H:%M:%S")
        msg_clean = _ascii_clean(msg, 64)
        with self._lock:
            if dedup_key:
                if dedup_key in self._seen_keys:
                    return False
                self._seen_keys.add(dedup_key)
                self._seen_order.append(dedup_key)
                if len(self._seen_order) > 400:
                    old = self._seen_order.pop(0)
                    self._seen_keys.discard(old)

            ev = {
                "sev": int(sev),  # 0=INFO, 1=WARN, 2=CRIT
                "cat": str(cat)[:8].upper(),
                "hm": now_hm,
                "ts": now_hms,
                "msg": msg_clean,
                "ip": str(ip or "")[:24],
            }
            self._events.append(ev)
            if len(self._events) > 50:
                del self._events[0]

            if ip and ip not in ("127.0.0.1", "::1", "0.0.0.0"):
                self._last_ip = str(ip)[:20]

            if sev >= 2:
                self._last_alert_msg = f"{ev['cat']}: {msg_clean}"
                now_t = time.time()
                if (now_t - self._last_alarm_ts) >= 20.0:
                    self._last_alarm_ts = now_t
                    self._pending_alarm = {
                        "alrt": {"bz": True, "led": "0xF800", "p": 3},
                        "msg": self._last_alert_msg,
                        "ip": self._last_ip,
                    }
        if sev >= 2:
            self._emit_log(f"🚨 [IDS CRITICO] {cat}: {msg_clean}")
        elif sev == 1:
            self._emit_log(f"⚠️ [IDS AVISO] {cat}: {msg_clean}")
        return True

    def consume_pending_alarm(self) -> dict | None:
        with self._lock:
            al = self._pending_alarm
            self._pending_alarm = None
            return al

    def ack_alerts(self):
        """Reconhece alertas ativos, zera contadores de alarme e retorna status para SEGURO."""
        with self._lock:
            self._sim_active = False
            self._auth_fails = 0
            self._port_scans = 0
            self._fw_blocks = 0
            self._arp_spoof = False
            self._rogue_aps = 0
            self._unknown_lan = 0
            self._level = 0
            self._status = "SEGURO"
            self._last_alert_msg = ""
            self._pending_alarm = None
        self.trust_baseline()
        self._add_event(0, "IDS", "Alertas reconhecidos pelo operador", "")

    def trust_baseline(self):
        """Aceita os hosts LAN, MAC do gateway e portas LISTEN atuais como baseline confiavel."""
        cur_macs: set[str] = set()
        gw_mac = ""
        if self._net_col is not None:
            try:
                ns = self._net_col.get_ui_snapshot()
                gw_mac = str(ns.get("gateway_mac") or "").upper().strip()
                for h in ns.get("lan_hosts", []):
                    mac = str(h.get("mac") or "").upper().strip()
                    if mac and mac != "--":
                        cur_macs.add(mac)
            except Exception:
                pass
        cur_ports = self._scan_listening_ports_raw()
        with self._lock:
            if cur_macs:
                self._baseline_lan_macs = set(cur_macs)
            if gw_mac:
                self._baseline_gw_mac = gw_mac
            if cur_ports:
                self._baseline_listen_ports = set(cur_ports)
            self._baseline_ready = True
            self._unknown_lan = 0
            self._arp_spoof = False
        self._add_event(0, "LAN", f"Baseline confiavel: {len(cur_macs)} MACs, {len(cur_ports)} portas", "")

    def simulate_intrusion(self, attacker_ip: str = "192.168.0.250"):
        """Simula tentativa de invasao (SSH brute-force + port-scan) para testar CYD + Buzzer + LED + BLE."""
        with self._lock:
            self._sim_active = True
            self._auth_fails += 5
            self._port_scans += 1
            self._last_ip = attacker_ip
            self._level = 2
            self._status = "INVASAO!"
            self._last_alarm_ts = 0.0  # garante disparo imediato do buzzer/LED
        self._add_event(2, "SSH", f"SIMULACAO: 5x SSH fail root @ {attacker_ip}", attacker_ip)
        self._add_event(2, "SCAN", f"SIMULACAO: Port-scan detectado de {attacker_ip}", attacker_ip)

    # ------------------------------------------------------ Coletas especificas
    def _scan_listening_ports_raw(self) -> set[int]:
        ports: set[int] = set()
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.status == psutil.CONN_LISTEN and c.laddr:
                    ports.add(int(c.laddr.port))
        except Exception:
            pass
        return ports

    def _check_network_sockets(self):
        listen_ports: set[int] = set()
        syn_recv_ips: set[str] = set()
        ext_conns: list[dict] = []
        suspicious_remote: list[tuple[str, int]] = []

        try:
            conns = psutil.net_connections(kind="inet")
        except Exception:
            conns = []

        for c in conns:
            st = getattr(c, "status", "")
            laddr = c.laddr
            raddr = c.raddr
            if st == psutil.CONN_LISTEN and laddr:
                listen_ports.add(int(laddr.port))
            elif st == "SYN_RECV" and raddr:
                rip = str(raddr.ip)
                if rip not in ("127.0.0.1", "::1"):
                    syn_recv_ips.add(rip)
            elif st == psutil.CONN_ESTABLISHED and laddr and raddr:
                rip = str(raddr.ip)
                lport = int(laddr.port)
                rport = int(raddr.port)
                if rip not in ("127.0.0.1", "::1", "0.0.0.0"):
                    ext_conns.append({"ip": rip, "lport": lport, "rport": rport})
                    if lport in REMOTE_SHELL_PORTS:
                        suspicious_remote.append((rip, lport))

        with self._lock:
            if not self._baseline_ready and listen_ports:
                self._baseline_listen_ports = set(listen_ports)
            new_ports = sorted(listen_ports - self._baseline_listen_ports) if self._baseline_listen_ports else []
            self._open_ports = sorted(listen_ports)
            self._ext_conns = ext_conns[:20]

        for p in new_ports[:4]:
            # Ignora portas efemeras altas (>32768)
            if p < 32768:
                self._add_event(1, "PORT", f"Nova porta aberta LISTEN :{p}", "", dedup_key=f"lport:{p}")

        if len(syn_recv_ips) >= 3:
            sample_ip = sorted(syn_recv_ips)[0]
            with self._lock:
                self._port_scans += 1
            self._add_event(
                2,
                "SCAN",
                f"Surto SYN_RECV ({len(syn_recv_ips)} IPs) ex: {sample_ip}",
                sample_ip,
                dedup_key=f"syn:{len(syn_recv_ips)}:{int(time.time() // 30)}",
            )

        for rip, lport in suspicious_remote[:3]:
            self._add_event(
                2,
                "SHELL",
                f"Acesso remoto ativo porta :{lport} de {rip}",
                rip,
                dedup_key=f"rshell:{rip}:{lport}",
            )

    def _check_lan_and_rf(self):
        # 1) Perimetro LAN / ARP (via net_col)
        if self._net_col is not None:
            try:
                ns = self._net_col.get_ui_snapshot()
                gw_mac = str(ns.get("gateway_mac") or "").upper().strip()
                hosts = ns.get("lan_hosts", []) or []
                cur_macs = {}
                for h in hosts:
                    mac = str(h.get("mac") or "").upper().strip()
                    ip = str(h.get("ip") or "").strip()
                    if mac and mac != "--":
                        cur_macs[mac] = ip

                with self._lock:
                    if not self._baseline_ready and cur_macs:
                        self._baseline_lan_macs = set(cur_macs.keys())
                        if gw_mac:
                            self._baseline_gw_mac = gw_mac
                        self._baseline_ready = True

                    # Deteccao de ARP Spoofing (MAC do roteador mudou!)
                    if self._baseline_gw_mac and gw_mac and gw_mac != self._baseline_gw_mac:
                        self._arp_spoof = True
                        spoof_msg = f"ARP SPOOF! GW MAC mudou p/ {gw_mac}"
                    else:
                        spoof_msg = ""

                    unknown = {m: ip for m, ip in cur_macs.items() if self._baseline_lan_macs and m not in self._baseline_lan_macs}
                    self._unknown_lan = len(unknown)

                if spoof_msg:
                    self._add_event(2, "ARP", spoof_msg, str(ns.get("gateway_ip") or ""), dedup_key=f"arpspoof:{gw_mac}")

                for mac, ip in list(unknown.items())[:3]:
                    self._add_event(
                        1,
                        "LAN",
                        f"Novo host LAN {ip} ({mac[-8:]})",
                        ip,
                        dedup_key=f"newmac:{mac}",
                    )
            except Exception:
                pass

        # 2) Perimetro Wi-Fi RF (via wifi_scan_col - deteccao de Evil Twin)
        if self._wifi_scan_col is not None:
            try:
                ws = self._wifi_scan_col.get_ui_snapshot()
                nets = ws.get("networks", []) or []
                by_ssid: dict[str, list[dict]] = {}
                for n in nets:
                    ss = str(n.get("ssid") or "").strip()
                    if ss and ss != "<OCULTA>":
                        by_ssid.setdefault(ss, []).append(n)
                rogues = []
                for ss, items in by_ssid.items():
                    encs = {str(x.get("enc") or "WPA").upper() for x in items}
                    if "OPEN" in encs and len(encs) > 1:
                        rogues.append(ss)
                with self._lock:
                    self._rogue_aps = len(rogues)
                for ss in rogues[:2]:
                    self._add_event(
                        2,
                        "WIFI",
                        f"Possivel Evil Twin OPEN: {ss[:18]}",
                        "",
                        dedup_key=f"eviltwin:{ss}",
                    )
            except Exception:
                pass

    def _check_linux_journal(self):
        if not IS_LINUX:
            return

        # 1) Logs de autenticacao / SSH / sudo / firewall nos ultimos 10 minutos
        out_auth = _run_cmd(
            ["journalctl", "--since", "-10 min", "-n", "120", "--no-pager", "-o", "short-iso"],
            timeout=3.5,
        )
        new_auth_fails = 0
        new_fw_blocks = 0
        if out_auth:
            for ln in out_auth.splitlines():
                low = ln.lower()
                # Checa padroes de invasao / autenticacao falhada
                matched_auth = False
                for pat in AUTH_FAIL_PATTERNS:
                    m = pat.search(ln)
                    if m:
                        matched_auth = True
                        ip_m = IP_RE.search(ln)
                        src_ip = ip_m.group(1) if ip_m else ""
                        key = f"auth:{ln[:48]}:{src_ip}"
                        sev = 2 if ("ssh" in low or "break-in" in low or "sudoers" in low) else 1
                        short_txt = ln.split(": ", 1)[-1] if ": " in ln else ln
                        if self._add_event(sev, "AUTH", short_txt[:56], src_ip, dedup_key=key):
                            new_auth_fails += 1
                        break
                if matched_auth:
                    continue

                for pat in FIREWALL_DROP_PATTERNS:
                    m = pat.search(ln)
                    if m:
                        src_ip = m.group(1)
                        key = f"fw:{ln[:32]}:{src_ip}"
                        if self._add_event(1, "FW", f"Firewall bloqueou {src_ip}", src_ip, dedup_key=key):
                            new_fw_blocks += 1
                        break

        # 2) Erros criticos do sistema / kernel (priority err..emerg) nos ultimos 15 minutos
        out_err = _run_cmd(
            ["journalctl", "-p", "err..emerg", "--since", "-15 min", "-n", "40", "--no-pager", "-o", "short-iso"],
            timeout=3.0,
        )
        err_count = 0
        if out_err:
            for ln in out_err.splitlines():
                if not ln.strip() or ln.startswith("--"):
                    continue
                low = ln.lower()
                if any(ig in low for ig in SYS_ERR_NOISE_IGNORE):
                    continue
                err_count += 1
                # Extrai servico + mensagem
                parts = ln.split(" ", 3)
                body = parts[3] if len(parts) >= 4 else ln
                key = f"err:{body[:52]}"
                sev = 2 if ("segfault" in low or "out of memory" in low or "kernel panic" in low or "i/o error" in low) else 1
                self._add_event(sev, "ERR", body[:56], "", dedup_key=key)

        with self._lock:
            self._auth_fails += new_auth_fails
            self._fw_blocks += new_fw_blocks
            self._sys_errors = max(self._sys_errors, err_count) if err_count > 0 else err_count

    def _recompute_threat_level(self):
        with self._lock:
            if (
                self._sim_active
                or self._arp_spoof
                or self._rogue_aps > 0
                or self._auth_fails >= 3
                or self._port_scans >= 1
                or any(e["sev"] >= 2 for e in self._events[-6:])
            ):
                self._level = 2
                self._status = "INVASAO!"
            elif (
                self._auth_fails >= 1
                or self._unknown_lan >= 1
                or self._fw_blocks >= 2
                or self._sys_errors >= 3
            ):
                self._level = 1
                self._status = "ATENCAO"
            else:
                self._level = 0
                self._status = "SEGURO"

            self._last_scan_str = datetime.now().strftime("%H:%M:%S")
            self._scan_count += 1

    def _run_once(self):
        try:
            self._check_network_sockets()
            self._check_lan_and_rf()
            self._check_linux_journal()
            self._recompute_threat_level()
        except Exception:
            pass

    def _worker(self):
        # Primeira passagem rapida apos boot dos outros coletores
        time.sleep(1.2)
        while self._running:
            self._run_once()
            for _ in range(int(self._poll_interval * 5)):
                if not self._running:
                    break
                time.sleep(0.2)

    # ------------------------------------------------------ Payloads de saida
    def get_cyd_payload(self) -> dict:
        """Payload compacto (~360 bytes) para o bloco 'sec' da Tela 14 da CYD."""
        with self._lock:
            recent = list(self._events[-6:])
            recent.reverse()  # mais recente no topo da Tela 14
            logs_compact = []
            for e in recent:
                logs_compact.append([
                    int(e["sev"]),
                    str(e["hm"]),
                    _ascii_clean(f"{e['cat']} {e['msg']}", 38),
                ])
            return {
                "lvl": int(self._level),
                "st": str(self._status),
                "af": int(self._auth_fails),
                "er": int(self._sys_errors),
                "ps": int(self._port_scans + self._fw_blocks),
                "un": int(self._unknown_lan + self._rogue_aps + (1 if self._arp_spoof else 0)),
                "op": len(self._open_ports),
                "ex": len(self._ext_conns),
                "ip": str(self._last_ip),
                "al": _ascii_clean(self._last_alert_msg, 44),
                "tm": str(self._last_scan_str),
                "logs": logs_compact,
            }

    def get_ui_snapshot(self) -> dict:
        """Snapshot completo para Web PWA, Flet UI, BLE Mobile e CLI `cyd sec`."""
        with self._lock:
            return {
                "level": int(self._level),
                "status": str(self._status),
                "auth_fails": int(self._auth_fails),
                "sys_errors": int(self._sys_errors),
                "fw_blocks": int(self._fw_blocks),
                "port_scans": int(self._port_scans),
                "unknown_lan": int(self._unknown_lan),
                "rogue_aps": int(self._rogue_aps),
                "arp_spoof": bool(self._arp_spoof),
                "open_ports": list(self._open_ports[:24]),
                "open_ports_count": len(self._open_ports),
                "ext_conns_count": len(self._ext_conns),
                "ext_conns": list(self._ext_conns[:12]),
                "last_ip": str(self._last_ip),
                "last_alert_msg": str(self._last_alert_msg),
                "last_scan_str": str(self._last_scan_str),
                "scan_count": int(self._scan_count),
                "sim_active": bool(self._sim_active),
                "baseline_macs": len(self._baseline_lan_macs),
                "events": list(reversed(self._events[-25:])),
            }
