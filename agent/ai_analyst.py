#!/usr/bin/env python3
"""
ai_analyst.py - Agente IA Hibrido (Google Gemini + IA Local Ollama/OpenAI-compat)
para analise defensiva/passiva de redes, espectro RF 2.4GHz (ESP32-WROOM-32U) e
relatorios otimizados no CYD Cyber Deck (v4.7).

- Zero dependencias externas (usa apenas biblioteca padrao Python: urllib, json, etc.).
- 100% defensivo e passivo: analisa apenas telemetria ja coletada localmente.
- Saida dupla:
    1) Resumo compacto (<= 10 linhas x 48 colunas ASCII) formatado para a Tela 11 da CYD.
    2) Relatorio completo em Markdown salvo em reports/ai_<modo>_YYYYMMDD_HHMMSS.md.
- Nunca registra ou expoe chaves de API em logs ou payloads publicos.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable

try:
    import wifi_scanner
except ImportError:
    try:
        from . import wifi_scanner
    except Exception:
        wifi_scanner = None

try:
    import net_analyzer
except ImportError:
    try:
        from . import net_analyzer
    except Exception:
        net_analyzer = None


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash")
DEFAULT_LOCAL_URL = "http://127.0.0.1:11434"
PREFERRED_LOCAL_PREFIXES = (
    "qwen2.5:7b",
    "qwen2.5",
    "qwen3",
    "llama3.2",
    "llama3.1",
    "llama3",
    "gemma3",
    "gemma2",
    "mistral",
    "phi4",
    "phi3",
    "deepseek",
)

SYSTEM_PROMPT_ANALYST = (
    "Voce e o Agente Especialista em Engenharia de Redes e Espectro RF do CYD Cyber Deck. "
    "Sua atuacao e 100% DEFENSIVA, PASSIVA e EDUCACIONAL: analise exclusivamente a telemetria "
    "fornecida (roteador/gateway, WAN, DNS, LAN ARP, Speedtest Fibra e varredura passiva 2.4 GHz "
    "da ESP32-WROOM-32U com antena externa). Nunca sugira acoes ofensivas ou invasivas.\n\n"
    "Responda em Portugues do Brasil de forma objetiva, tecnica e acionavel.\n"
    "OBRIGATORIO: Inicie sua resposta com um bloco de resumo ultra-compacto para o display "
    "monoespacado de 48 colunas da placa CYD usando EXATAMENTE os delimitadores abaixo:\n"
    "<<<CYD_SUMMARY>>>\n"
    "[OK] ou [WARN] ou [ERR] ou [WIFI] seguido de resumo (6 a 8 linhas, MAXIMO 46 caracteres por linha, sem acentos ou emojis)\n"
    "<<<END_CYD_SUMMARY>>>\n\n"
    "Logo apos <<<END_CYD_SUMMARY>>>, escreva o relatorio completo em Markdown bem estruturado, "
    "citando numeros reais da telemetria (dBm, canais 1-13, ms, jitter, perda %, Mbps, plano contratado, "
    "fabricantes OUI, redes abertas/ocultas/mesh e recomendacoes praticas priorizadas)."
)

SYSTEM_PROMPT_ASK = (
    "Voce e o Agente Especialista em Redes & RF do CYD Cyber Deck (100% defensivo/passivo). "
    "Responda a pergunta do usuario em Portugues do Brasil usando os dados reais de telemetria fornecidos.\n"
    "OBRIGATORIO: Comece com um bloco curto para o display de 48 colunas da CYD:\n"
    "<<<CYD_SUMMARY>>>\n"
    "4 a 7 linhas curtas (MAXIMO 46 caracteres por linha, ASCII sem acentos, usando prefixos [OK]/[WARN]/[WIFI])\n"
    "<<<END_CYD_SUMMARY>>>\n\n"
    "Depois escreva a explicacao completa em Markdown."
)


def _to_ascii_cyd(text: str) -> str:
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text))
    ascii_s = norm.encode("ascii", "ignore").decode("ascii")
    ascii_s = re.sub(r"[^\x20-\x7E]", " ", ascii_s)
    return re.sub(r"\s+", " ", ascii_s).strip()


def _sanitize_error(err_text: str) -> str:
    s = str(err_text or "")
    s = re.sub(r"key=[^&\s\"']+", "key=***", s, flags=re.IGNORECASE)
    s = re.sub(r"Bearer\s+\S+", "Bearer ***", s, flags=re.IGNORECASE)
    return s.strip()


def _mask_key(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "*" * len(k)
    return f"{k[:4]}...{k[-4:]}"


def _resolve_reports_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    rdir = os.path.join(root, "reports")
    os.makedirs(rdir, exist_ok=True)
    return rdir


class NetworkAIAnalyst:
    """Motor hibrido Gemini + IA Local (Ollama / OpenAI-compatible) para analise de redes e RF."""

    TERM_COLS = 48

    def __init__(
        self,
        collector=None,
        wifi_scan_col=None,
        net_col=None,
        ai_provider: str = "auto",
        gemini_api_key: str = "",
        gemini_model: str = DEFAULT_GEMINI_MODEL,
        local_ai_url: str = DEFAULT_LOCAL_URL,
        local_ai_model: str = "",
        on_log: Callable[[str], None] | None = None,
        on_config_persist: Callable[[dict], None] | None = None,
    ):
        self._lock = threading.Lock()
        self.collector = collector
        self.wifi_scan_col = wifi_scan_col
        self.net_col = net_col
        self._on_log = on_log
        self._on_config_persist = on_config_persist

        self.ai_provider = self._norm_provider(ai_provider)
        env_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.gemini_api_key = (gemini_api_key or "").strip() or env_key
        gm = (gemini_model or "").strip()
        if not gm or gm == "gemini-3.8-flash":
            gm = DEFAULT_GEMINI_MODEL
        self.gemini_model = gm
        self.local_ai_url = (local_ai_url or DEFAULT_LOCAL_URL).strip().rstrip("/")
        self.local_ai_model = (local_ai_model or "").strip()

        self._busy = False
        self._last_report_path = ""
        self._last_report_time = ""
        self._last_provider_used = ""
        self._last_model_used = ""
        self._last_mode = ""
        self._last_cyd_lines: list[str] = []
        self._last_markdown = ""
        self._last_error = ""
        self._cached_local_check_ts = 0.0
        self._cached_local_online = False
        self._cached_local_models: list[str] = []
        self._cached_local_kind = "ollama"

    @staticmethod
    def _norm_provider(val: str | None) -> str:
        p = str(val or "auto").strip().lower()
        if p in ("gemini", "google", "cloud"):
            return "gemini"
        if p in ("local", "ollama", "lmstudio", "offline"):
            return "local"
        return "auto"

    def _log(self, msg: str):
        if self._on_log:
            try:
                self._on_log(msg)
            except Exception:
                pass

    def set_log_callback(self, fn: Callable[[str], None] | None):
        self._on_log = fn

    def set_config_persist_callback(self, fn: Callable[[dict], None] | None):
        self._on_config_persist = fn

    def configure(
        self,
        ai_provider: str | None = None,
        gemini_api_key: str | None = None,
        gemini_model: str | None = None,
        local_ai_url: str | None = None,
        local_ai_model: str | None = None,
        persist: bool = True,
    ) -> dict:
        with self._lock:
            if ai_provider is not None and str(ai_provider).strip():
                self.ai_provider = self._norm_provider(ai_provider)
            if gemini_api_key is not None:
                k = str(gemini_api_key).strip()
                if k.lower() in ("clear", "none", "unset"):
                    self.gemini_api_key = ""
                else:
                    self.gemini_api_key = k
            if gemini_model is not None and str(gemini_model).strip():
                self.gemini_model = str(gemini_model).strip()
            if local_ai_url is not None and str(local_ai_url).strip():
                self.local_ai_url = str(local_ai_url).strip().rstrip("/")
                self._cached_local_check_ts = 0.0
            if local_ai_model is not None:
                m = str(local_ai_model).strip()
                self.local_ai_model = "" if m.lower() in ("auto", "default") else m

            cfg_delta = {
                "ai_provider": self.ai_provider,
                "gemini_api_key": self.gemini_api_key,
                "gemini_model": self.gemini_model,
                "local_ai_url": self.local_ai_url,
                "local_ai_model": self.local_ai_model,
            }

        if persist and self._on_config_persist:
            try:
                self._on_config_persist(cfg_delta)
            except Exception:
                pass
        return self.get_config_public()

    def get_config_public(self) -> dict:
        with self._lock:
            key = self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip()
            return {
                "ai_provider": self.ai_provider,
                "gemini_key_set": bool(key),
                "gemini_key_masked": _mask_key(key),
                "gemini_model": self.gemini_model,
                "local_ai_url": self.local_ai_url,
                "local_ai_model": self.local_ai_model,
            }

    # ========================================== DESCOBERTA DE IA LOCAL ========
    def list_local_models(self, timeout: float = 2.0, force: bool = False) -> tuple[bool, list[str], str]:
        """Detecta modelos em Ollama (/api/tags) ou servidor OpenAI-compat (/v1/models)."""
        now = time.time()
        with self._lock:
            url = self.local_ai_url
            if not force and (now - self._cached_local_check_ts) < 12.0:
                return self._cached_local_online, list(self._cached_local_models), self._cached_local_kind

        online = False
        models: list[str] = []
        kind = "ollama"

        # 1) Tenta Ollama nativo (/api/tags)
        try:
            req = urllib.request.Request(f"{url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                raw_models = data.get("models", [])
                if isinstance(raw_models, list):
                    models = [str(m.get("name", "")).strip() for m in raw_models if m.get("name")]
                    online = True
                    kind = "ollama"
        except Exception:
            pass

        # 2) Fallback OpenAI-compatible (/v1/models — LM Studio, llama.cpp, vLLM)
        if not online:
            try:
                base_v1 = url if url.endswith("/v1") else f"{url}/v1"
                req = urllib.request.Request(f"{base_v1}/models", method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    raw_models = data.get("data", [])
                    if isinstance(raw_models, list):
                        models = [str(m.get("id", "")).strip() for m in raw_models if m.get("id")]
                        online = True
                        kind = "openai"
            except Exception:
                pass

        with self._lock:
            self._cached_local_check_ts = now
            self._cached_local_online = online
            self._cached_local_models = list(models)
            self._cached_local_kind = kind

        return online, models, kind

    def _pick_local_model(self, available: list[str]) -> str:
        with self._lock:
            pinned = self.local_ai_model
        if pinned:
            if not available or pinned in available:
                return pinned
            # Permite prefix match (ex: "qwen2.5" -> "qwen2.5:7b")
            for m in available:
                if m.lower().startswith(pinned.lower()):
                    return m
            return pinned
        if not available:
            return ""
        low_map = [(m, m.lower()) for m in available]
        for pref in PREFERRED_LOCAL_PREFIXES:
            for orig, low in low_map:
                if low == pref or low.startswith(pref):
                    return orig
        return available[0]

    def get_status_snapshot(self, probe_local: bool = False) -> dict:
        if probe_local:
            online, models, kind = self.list_local_models(timeout=1.8, force=True)
        else:
            # Usa cache leve (ou dispara probe rapido se nunca checado)
            with self._lock:
                never_checked = self._cached_local_check_ts == 0.0
            if never_checked:
                online, models, kind = self.list_local_models(timeout=0.8, force=False)
            else:
                with self._lock:
                    online = self._cached_local_online
                    models = list(self._cached_local_models)
                    kind = self._cached_local_kind

        active_local = self._pick_local_model(models)
        pub = self.get_config_public()
        with self._lock:
            return {
                **pub,
                "local_online": online,
                "local_kind": kind,
                "local_models": models,
                "active_local_model": active_local,
                "busy": self._busy,
                "last_report_path": self._last_report_path,
                "last_report_time": self._last_report_time,
                "last_provider_used": self._last_provider_used,
                "last_model_used": self._last_model_used,
                "last_mode": self._last_mode,
                "last_cyd_lines": list(self._last_cyd_lines),
                "last_markdown_preview": (self._last_markdown[:1800] if self._last_markdown else ""),
                "last_error": self._last_error,
            }

    # ========================================== COLETA DE TELEMETRIA ==========
    def collect_network_context(self) -> dict:
        """Agrega telemetria defensiva real da ESP32-WROOM-32U, Rede/Roteador e Host PC."""
        ctx: dict = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rf_radar": {},
            "network": {},
            "host": {},
        }

        # 1) Radar Wi-Fi RF 2.4GHz (ESP32-WROOM-32U)
        if self.wifi_scan_col is not None:
            try:
                ws = self.wifi_scan_col.get_ui_snapshot()
                spec = self.wifi_scan_col.analyze_spectrum() if hasattr(self.wifi_scan_col, "analyze_spectrum") else {}
                audit = self.wifi_scan_col.audit_networks() if hasattr(self.wifi_scan_col, "audit_networks") else {}
                diff = self.wifi_scan_col.diff_networks() if hasattr(self.wifi_scan_col, "diff_networks") else {}
                nets_compact = []
                for n in ws.get("networks", [])[:10]:
                    bssid = str(n.get("bssid", ""))
                    vendor = wifi_scanner.lookup_oui(bssid) if wifi_scanner and hasattr(wifi_scanner, "lookup_oui") else ""
                    nets_compact.append({
                        "ssid": n.get("ssid", "<OCULTA>"),
                        "bssid": bssid,
                        "vendor": vendor,
                        "ch": n.get("ch", 0),
                        "rssi": n.get("rssi", -100),
                        "enc": n.get("enc", ""),
                    })
                ctx["rf_radar"] = {
                    "online": bool(ws.get("online", False)),
                    "scanner_ip": ws.get("scanner_ip", ""),
                    "total_aps": int(ws.get("total", 0)),
                    "scan_count": int(ws.get("scan_count", 0)),
                    "last_scan": ws.get("last_scan_str", "--"),
                    "best_rssi_dbm": ws.get("best_rssi", -100),
                    "recommended_ch": spec.get("best_ch", ws.get("free_ch", 1)),
                    "busiest_ch": ws.get("busiest_ch", 0),
                    "channel_counts": ws.get("channel_counts", {}),
                    "spectrum_scores": spec.get("scores", {}),
                    "audit": {
                        "open_count": len(audit.get("open_nets", [])),
                        "open_ssids": [x.get("ssid", "") for x in audit.get("open_nets", [])[:5]],
                        "wep_count": len(audit.get("wep_nets", [])),
                        "hidden_count": len(audit.get("hidden_nets", [])),
                        "mesh_groups": audit.get("mesh_groups", [])[:5],
                        "congested_channels": audit.get("congested_channels", []),
                    },
                    "diff": {
                        "added": len(diff.get("added", [])),
                        "removed": len(diff.get("removed", [])),
                    },
                    "top_networks": nets_compact,
                }
            except Exception as ex:
                ctx["rf_radar"] = {"error": str(ex)}

        # 2) Analise de Rede, Roteador/Gateway, WAN, DNS, LAN e Speedtest
        if self.net_col is not None:
            try:
                na = self.net_col.get_ui_snapshot()
                lan_hosts = []
                for h in na.get("lan_hosts", [])[:12]:
                    mac = str(h.get("mac", ""))
                    vend = wifi_scanner.lookup_oui(mac) if wifi_scanner and hasattr(wifi_scanner, "lookup_oui") else ""
                    lan_hosts.append({
                        "ip": h.get("ip", ""),
                        "mac": mac,
                        "vendor": vend,
                        "tag": h.get("tag", "LAN"),
                    })
                ctx["network"] = {
                    "gateway_ip": na.get("gateway_ip", ""),
                    "iface": na.get("iface", ""),
                    "local_ip": na.get("local_ip", ""),
                    "gw_up": bool(na.get("gw_up", False)),
                    "gw_ms": na.get("gw_ms", 0.0),
                    "gw_jitter_ms": na.get("gw_jitter_ms", 0.0),
                    "gw_loss_pct": na.get("gw_loss_pct", 0),
                    "gw_http_code": na.get("gw_http_code", 0),
                    "wan_up": bool(na.get("wan_up", False)),
                    "wan_ms": na.get("wan_ms", 0.0),
                    "wan_jitter_ms": na.get("wan_jitter_ms", 0.0),
                    "wan_loss_pct": na.get("wan_loss_pct", 0),
                    "dns_ms": na.get("dns_ms", 0.0),
                    "isp": na.get("isp", ""),
                    "public_ip": na.get("public_ip", ""),
                    "rx_mbps": na.get("rx_mbps", 0.0),
                    "tx_mbps": na.get("tx_mbps", 0.0),
                    "plan_mbps": na.get("plan_mbps", 700),
                    "speedtest": na.get("speedtest", {}),
                    "lan_count": int(na.get("lan_count", len(lan_hosts))),
                    "lan_hosts": lan_hosts,
                }
            except Exception as ex:
                ctx["network"] = {"error": str(ex)}

        # 3) Telemetria resumida do PC Host
        if self.collector is not None:
            try:
                s = self.collector.sample_sys()
                ctx["host"] = {
                    "cpu_pct": s.get("cpu", 0),
                    "ram_pct": s.get("ram", 0),
                    "cpu_temp_c": s.get("cput"),
                    "gpu_pct": s.get("gpu", 0),
                    "rx_MBs": s.get("rx", 0),
                    "tx_MBs": s.get("tx", 0),
                }
            except Exception:
                pass

        return ctx

    # ========================================== CHAMADAS AOS PROVEDORES =======
    def _call_gemini(self, system_prompt: str, user_prompt: str, timeout: float = 40.0) -> tuple[bool, str, str, str]:
        with self._lock:
            api_key = self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip()
            pref_model = self.gemini_model or DEFAULT_GEMINI_MODEL

        if not api_key:
            return False, "", "", "GEMINI_API_KEY nao configurada"

        candidates = [pref_model] + [m for m in GEMINI_FALLBACK_MODELS if m != pref_model]
        last_err = "Falha desconhecida na API Gemini"

        payload_obj = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 2048,
            },
        }
        payload_bytes = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")

        for model in candidates:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{urllib.parse.quote(model, safe='')}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
            )
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                cands = data.get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
                    if text:
                        return True, text, model, ""
                last_err = f"Resposta vazia do modelo {model}"
            except urllib.error.HTTPError as he:
                body_err = ""
                try:
                    body_err = he.read().decode("utf-8", errors="ignore")[:220]
                except Exception:
                    pass
                last_err = _sanitize_error(f"HTTP {he.code} ({model}): {body_err}")
                # Se 404 (modelo invalido/descontinuado), tenta proximo candidato; se 401/403 (chave invalida), para logo
                if he.code in (401, 403):
                    break
            except Exception as ex:
                last_err = _sanitize_error(f"Gemini erro ({model}): {ex}")
                break

        return False, "", pref_model, last_err

    def _call_local_ai(
        self,
        system_prompt: str,
        user_prompt: str,
        timeout: float = 180.0,
        max_tokens: int = 700,
    ) -> tuple[bool, str, str, str]:
        online, models, kind = self.list_local_models(timeout=2.5, force=True)
        with self._lock:
            url = self.local_ai_url
        if not online:
            return False, "", "", f"IA Local offline em {url}"

        model = self._pick_local_model(models)
        if not model:
            return False, "", "", f"Nenhum modelo instalado em {url}"

        if kind == "ollama":
            # Tenta /api/chat primeiro (com num_ctx=4096 e keep_alive=10m para acelerar inferencia local)
            chat_payload = {
                "model": model,
                "stream": False,
                "keep_alive": "10m",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "options": {
                    "temperature": 0.25,
                    "num_ctx": 4096,
                    "num_predict": int(max_tokens),
                },
            }
            req = urllib.request.Request(
                f"{url}/api/chat",
                data=json.dumps(chat_payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                txt = str(data.get("message", {}).get("content", "")).strip()
                if txt:
                    return True, txt, model, ""
                return False, "", model, "Resposta vazia do Ollama (/api/chat)"
            except urllib.error.HTTPError as he:
                if he.code not in (404, 405):
                    return False, "", model, _sanitize_error(f"Ollama HTTP {he.code}")
                # Fallback /api/generate apenas se /api/chat nao existir
                try:
                    gen_payload = {
                        "model": model,
                        "stream": False,
                        "keep_alive": "10m",
                        "system": system_prompt,
                        "prompt": user_prompt,
                        "options": {"temperature": 0.25, "num_ctx": 4096, "num_predict": int(max_tokens)},
                    }
                    req2 = urllib.request.Request(
                        f"{url}/api/generate",
                        data=json.dumps(gen_payload, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                        data2 = json.loads(resp2.read().decode("utf-8", errors="ignore"))
                    txt2 = str(data2.get("response", "")).strip()
                    if txt2:
                        return True, txt2, model, ""
                    return False, "", model, "Resposta vazia do Ollama (/api/generate)"
                except Exception as ex_gen:
                    return False, "", model, _sanitize_error(f"Ollama /api/generate erro: {ex_gen}")
            except Exception as ex_chat:
                return False, "", model, _sanitize_error(f"Ollama erro: {ex_chat}")

        # OpenAI-compatible (/v1/chat/completions)
        base_v1 = url if url.endswith("/v1") else f"{url}/v1"
        oai_payload = {
            "model": model,
            "temperature": 0.25,
            "max_tokens": int(max_tokens),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        req = urllib.request.Request(
            f"{base_v1}/chat/completions",
            data=json.dumps(oai_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            choices = data.get("choices", [])
            if choices:
                txt = str(choices[0].get("message", {}).get("content", "")).strip()
                if txt:
                    return True, txt, model, ""
            return False, "", model, "Resposta vazia do servidor OpenAI local"
        except Exception as ex:
            return False, "", model, _sanitize_error(f"Local OpenAI erro: {ex}")

    # ========================================== FALLBACK HEURISTICO ===========
    def _build_heuristic_report(self, ctx: dict, mode: str, question: str, err_reason: str) -> tuple[list[str], str]:
        rf = ctx.get("rf_radar", {}) or {}
        net = ctx.get("network", {}) or {}
        audit = rf.get("audit", {}) or {}

        gw_up = bool(net.get("gw_up", False))
        wan_up = bool(net.get("wan_up", False))
        gw_ms = float(net.get("gw_ms", 0.0) or 0.0)
        wan_ms = float(net.get("wan_ms", 0.0) or 0.0)
        dns_ms = float(net.get("dns_ms", 0.0) or 0.0)
        gw_loss = int(net.get("gw_loss_pct", 0) or 0)
        wan_loss = int(net.get("wan_loss_pct", 0) or 0)
        lan_cnt = int(net.get("lan_count", 0) or 0)
        plan = int(net.get("plan_mbps", 700) or 700)

        rf_on = bool(rf.get("online", False))
        aps = int(rf.get("total_aps", 0) or 0)
        best_ch = int(rf.get("recommended_ch", 1) or 1)
        busy_ch = int(rf.get("busiest_ch", 0) or 0)
        open_cnt = int(audit.get("open_count", 0) or 0)

        # Score heuristico 0..100
        score = 100
        if not gw_up:
            score -= 35
        elif gw_ms > 10 or gw_loss > 0:
            score -= 12
        if not wan_up:
            score -= 30
        elif wan_ms > 45 or wan_loss > 0:
            score -= 15
        if dns_ms > 60:
            score -= 8
        if open_cnt > 0:
            score -= 8
        if aps >= 20:
            score -= 6
        score = max(0, min(100, score))

        tag = "[OK]" if score >= 80 else ("[WARN]" if score >= 55 else "[ERR]")
        cyd_lines = [
            f"{tag} IA HEURISTICA | Score: {score}/100",
            f"GW:{net.get('gateway_ip','--')} {gw_ms:.1f}ms | WAN:{wan_ms:.0f}ms DNS:{dns_ms:.0f}ms",
            f"[WIFI] 32U:{'ON' if rf_on else 'OFF'} APs:{aps} Livre:CH{best_ch} Cheio:CH{busy_ch}",
            f"LAN:{lan_cnt} hosts | Plano:{plan}M | Open:{open_cnt}",
            f"[WARN] Acao: Fixe Wi-Fi 2.4G no CH{best_ch} (20MHz)",
            f"[WARN] Motivo fallback: {_to_ascii_cyd(err_reason)[:24]}",
        ]

        md_lines = [
            f"# Relatorio de Rede CYD Cyber Deck (Modo Heuristico — {ctx.get('timestamp', '')})",
            "",
            f"> **Nota:** Os provedores de IA (Gemini / IA Local) nao responderam (`{err_reason}`). "
            "Este relatorio foi gerado pelo motor heuristico local a partir da telemetria real.",
            "",
            f"## Resumo Executivo — Score de Saude: **{score}/100**",
            f"- **Gateway / Roteador:** `{net.get('gateway_ip', '--')}` ({'ONLINE' if gw_up else 'OFFLINE'}) | Ping `{gw_ms:.1f} ms` | Perda `{gw_loss}%`",
            f"- **WAN / DNS:** `{'ONLINE' if wan_up else 'OFFLINE'}` | Ping `{wan_ms:.1f} ms` | DNS `{dns_ms:.1f} ms` | ISP `{net.get('isp', '--')}`",
            f"- **LAN & Plano:** `{lan_cnt}` vizinhos ARP ativos | Plano alvo `{plan} Mbps`",
            f"- **Radar RF 2.4 GHz (ESP32-WROOM-32U):** `{'ONLINE' if rf_on else 'OFFLINE'}` | `{aps}` APs | Canal recomendado: **CH{best_ch}** | Mais congestionado: **CH{busy_ch}**",
            "",
            "## Acoes Recomendadas",
            f"1. Configure o Wi-Fi 2.4 GHz do roteador em canal fixo **CH{best_ch}** com largura **20 MHz** para evitar interferencia co-canal.",
            "2. Para ativar relatorios completos com Gemini, rode: `cyd ai config --gemini-key SUA_CHAVE`.",
            "3. Para usar IA local offline, garanta que o Ollama esteja ativo em `http://127.0.0.1:11434`.",
        ]
        if question:
            md_lines.extend(["", f"## Pergunta Recebida", f"- `{question}`"])

        return [x[: self.TERM_COLS] for x in cyd_lines], "\n".join(md_lines)

    # ========================================== PARSING & FORMATACAO CYD ======
    def _extract_cyd_and_markdown(self, raw_text: str, provider_label: str, model_label: str, ctx: dict) -> tuple[list[str], str]:
        m = re.search(
            r"<<<CYD_SUMMARY>>>(.*?)<<<END_CYD_SUMMARY>>>",
            raw_text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        cyd_lines: list[str] = []
        if m:
            block = m.group(1).strip()
            for ln in block.splitlines():
                clean = _to_ascii_cyd(ln)
                if clean:
                    cyd_lines.append(clean[: self.TERM_COLS])
            markdown = (raw_text[: m.start()] + raw_text[m.end() :]).strip()
        else:
            markdown = raw_text.strip()

        # Se o modelo omitiu o bloco CYD ou trouxe poucas linhas, sintetiza de forma segura
        if len(cyd_lines) < 2:
            rf = ctx.get("rf_radar", {}) or {}
            net = ctx.get("network", {}) or {}
            cyd_lines = [
                f"[OK] IA {provider_label.upper()} ({model_label[:16]})",
                f"GW:{net.get('gateway_ip','--')} {float(net.get('gw_ms',0) or 0):.1f}ms WAN:{float(net.get('wan_ms',0) or 0):.0f}ms",
                f"[WIFI] 32U:{rf.get('total_aps',0)} APs | Melhor: CH{rf.get('recommended_ch',1)}",
            ]
            # Adiciona ate 4 bullets extraidos do Markdown
            for raw_ln in markdown.splitlines():
                st = raw_ln.strip()
                if st.startswith(("-", "*", "1.", "2.", "3.")):
                    clean = _to_ascii_cyd(re.sub(r"[#*_`]+", "", st))
                    if clean:
                        cyd_lines.append(clean[: self.TERM_COLS])
                if len(cyd_lines) >= 8:
                    break

        # Garante cabecalho com o provedor/modelo + limite estrito de 9 linhas x 48 cols
        hdr = _to_ascii_cyd(f"[OK] IA:{provider_label.upper()} ({model_label[:22]})")[: self.TERM_COLS]
        if cyd_lines and not cyd_lines[0].startswith("[OK] IA:"):
            cyd_lines = [hdr] + cyd_lines[:8]
        else:
            cyd_lines = cyd_lines[:9]

        if not markdown:
            markdown = "\n".join(cyd_lines)

        return cyd_lines, markdown

    def _save_markdown_report(self, mode: str, provider: str, model: str, markdown: str) -> str:
        rdir = _resolve_reports_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_mode = re.sub(r"[^a-z0-9_]+", "", mode.lower()) or "report"
        fname = f"ai_{safe_mode}_{ts}.md"
        fpath = os.path.join(rdir, fname)
        header = (
            f"<!-- CYD Cyber Deck AI Network Report | Provider: {provider} | Model: {model} | "
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n\n"
        )
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(header + markdown.strip() + "\n")
        return fpath

    # ========================================== API PRINCIPAL =================
    def generate_report(
        self,
        mode: str = "full",
        provider: str | None = None,
        question: str = "",
        save_file: bool = True,
    ) -> dict:
        """
        Gera analise/relatorio de rede + RF usando Gemini, IA Local ou modo hibrido 'auto'.
        mode: 'full' | 'rf' | 'ask'
        """
        t0 = time.perf_counter()
        mode_n = (mode or "full").strip().lower()
        if mode_n not in ("full", "rf", "ask"):
            mode_n = "full"

        with self._lock:
            if self._busy:
                return {
                    "ok": False,
                    "error": "Agente IA ja esta processando uma analise. Aguarde concluir.",
                    "cyd_lines": ["[WARN] IA ocupada gerando analise anterior..."],
                    "markdown": "",
                }
            self._busy = True
            req_provider = self._norm_provider(provider) if provider else self.ai_provider

        try:
            ctx = self.collect_network_context()
            ctx_json = json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))

            if mode_n == "rf":
                sys_prompt = SYSTEM_PROMPT_ANALYST
                user_prompt = (
                    "Gere um RELATORIO PROFUNDO DE ESPECTRO RF 2.4 GHz baseado nos dados reais da "
                    "ESP32-WROOM-32U com antena externa abaixo. Avalie:\n"
                    "1. Congestao nos canais 1..13 (co-canal e sobreposicao adjacente) e qual canal fixo (1, 6 ou 11) escolher.\n"
                    "2. Auditoria passiva: redes OPEN, WEP, ocultas, clusters Mesh multi-BSSID e fabricantes OUI relevantes.\n"
                    "3. Qualidade do sinal RSSI e interferencias potenciais.\n"
                    "4. Plano de acao objetivo em passos curtos.\n\n"
                    f"TELEMETRIA JSON:\n```json\n{ctx_json}\n```"
                )
            elif mode_n == "ask":
                sys_prompt = SYSTEM_PROMPT_ASK
                q_clean = (question or "Como esta a saude geral da minha rede agora?").strip()
                user_prompt = (
                    f"PERGUNTA DO USUARIO:\n{q_clean}\n\n"
                    f"TELEMETRIA ATUAL DA REDE E RF (JSON):\n```json\n{ctx_json}\n```"
                )
            else:
                sys_prompt = SYSTEM_PROMPT_ANALYST
                user_prompt = (
                    "Gere um RELATORIO COMPLETO E OTIMIZADO DE SAUDE DA REDE + ESPECTRO RF baseado na "
                    "telemetria real abaixo. Inclua:\n"
                    "1. Resumo Executivo com Nota de Saude da Rede (0 a 100).\n"
                    "2. Diagnostico do Gateway/Roteador, WAN, DNS, Jitter/Perda e aderencia ao plano contratado (Mbps).\n"
                    "3. Inventario LAN (dispositivos ARP e fabricantes OUI) + observacoes defensivas.\n"
                    "4. Analise do Espectro Wi-Fi 2.4 GHz (ESP32-WROOM-32U): melhor canal (1/6/11), canais congestionados e auditoria passiva.\n"
                    "5. Top 5 Recomendacoes Praticas Priorizadas (Alto/Medio/Baixo impacto).\n\n"
                    f"TELEMETRIA JSON:\n```json\n{ctx_json}\n```"
                )

            # Ordem de tentativa conforme ai_provider
            plan_order: list[str]
            if req_provider == "gemini":
                plan_order = ["gemini"]
            elif req_provider == "local":
                plan_order = ["local"]
            else:
                # Modo auto: Gemini se chave configurada, senao Local primeiro; com failover cruzado
                has_key = bool(self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip())
                plan_order = ["gemini", "local"] if has_key else ["local", "gemini"]

            ok_ai = False
            raw_text = ""
            used_provider = ""
            used_model = ""
            errors: list[str] = []

            for prov in plan_order:
                if prov == "gemini":
                    self._log("🤖 Agente IA: consultando Google Gemini...")
                    ok_g, txt_g, mod_g, err_g = self._call_gemini(sys_prompt, user_prompt)
                    if ok_g:
                        ok_ai, raw_text, used_provider, used_model = True, txt_g, "gemini", mod_g
                        break
                    errors.append(f"Gemini: {err_g}")
                elif prov == "local":
                    self._log("🤖 Agente IA: consultando IA Local (Ollama/OpenAI)...")
                    local_toks = 420 if mode_n == "ask" else 720
                    ok_l, txt_l, mod_l, err_l = self._call_local_ai(sys_prompt, user_prompt, max_tokens=local_toks)
                    if ok_l:
                        ok_ai, raw_text, used_provider, used_model = True, txt_l, "local", mod_l
                        break
                    errors.append(f"Local: {err_l}")

            if ok_ai:
                cyd_lines, markdown = self._extract_cyd_and_markdown(raw_text, used_provider, used_model, ctx)
            else:
                used_provider = "heuristic"
                used_model = "rule-engine-v1"
                err_joined = " | ".join(errors) or "Nenhum provedor disponivel"
                cyd_lines, markdown = self._build_heuristic_report(ctx, mode_n, question, err_joined)

            report_path = ""
            if save_file and mode_n in ("full", "rf"):
                try:
                    report_path = self._save_markdown_report(mode_n, used_provider, used_model, markdown)
                    cyd_lines.append(f"[OK] Salvo: reports/{os.path.basename(report_path)}"[: self.TERM_COLS])
                except Exception:
                    pass

            elapsed = round(time.perf_counter() - t0, 2)
            now_str = datetime.now().strftime("%H:%M:%S")
            with self._lock:
                self._last_report_path = report_path or self._last_report_path
                self._last_report_time = now_str
                self._last_provider_used = used_provider
                self._last_model_used = used_model
                self._last_mode = mode_n
                self._last_cyd_lines = list(cyd_lines)
                self._last_markdown = markdown
                self._last_error = "" if ok_ai else " | ".join(errors)

            self._log(
                f"🤖 Agente IA concluiu ({mode_n}) via {used_provider}/{used_model} em {elapsed:.1f}s"
                + (f" -> {os.path.basename(report_path)}" if report_path else "")
            )
            return {
                "ok": True,
                "fallback": not ok_ai,
                "mode": mode_n,
                "provider_used": used_provider,
                "model_used": used_model,
                "elapsed_s": elapsed,
                "report_path": report_path,
                "cyd_lines": cyd_lines,
                "markdown": markdown,
                "errors": errors,
            }
        finally:
            with self._lock:
                self._busy = False
