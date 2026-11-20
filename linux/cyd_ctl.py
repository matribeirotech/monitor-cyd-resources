#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cyd_ctl.py - CLI nativo Linux para controlar a placa CYD (Cyber Deck) direto do terminal.

Exemplos:
  cyd 12                  # Troca para Tela 12 (Radar Wi-Fi)
  cyd 13                  # Troca para Tela 13 (Analise de Rede & Roteador)
  cyd screen net          # Troca usando apelido (resumo, cpu, gpu, market, media, news, term, radar, net)
  cyd next / cyd prev     # Avanca ou volta tela
  cyd list                # Lista todas as 14 telas (0..13)
  cyd status              # Mostra resumo completo (hardware, Wi-Fi Radar e Rede/Roteador)
  cyd router [--open]     # Diagnostico do roteador/gateway (e abre painel admin no navegador)
  cyd lan                 # Lista dispositivos ativos na LAN (tabela ARP local)
  cyd speed               # Dispara Speedtest Fibra na Tela 13 e exibe o resultado
  cyd radar [--scan]      # Mostra redes detectadas pela ESP32-WROOM-32U
  cyd rf [acao]           # Analise RF no Terminal CYD (scan|spectrum|audit|diff|status|export|track <alvo>)
  cyd diag                # Executa bateria completa netcheck (GW + Jitter + WAN + DNS + LAN + 32U)
  cyd jitter [alvo]       # Teste de estabilidade ICMP / jitter (padrao 1.1.1.1 ou gw)
  cyd mtu [alvo]          # Descoberta de Path MTU (PPPoE 1492 vs Ethernet 1500)
  cyd tls <host>          # Inspecao passiva de certificado TLS/SSL (:443)
  cyd ai status|models    # Status do Agente IA (Google Gemini + Ollama/Local)
  cyd ai report           # Relatorio completo da rede + RF com IA (salva em reports/*.md)
  cyd ai rf               # Analise profunda do espectro 2.4GHz (ESP32-WROOM-32U)
  cyd ai ask "<pergunta>" # Pergunta livre ao Agente IA usando telemetria atual
  cyd ai config [...]     # Configura provedor (auto/gemini/local), chave Gemini ou modelo local
  cyd plan 700            # Define plano de internet contratado (ex: 700 Mbps Vivo Fibra)
  cyd brt 200             # Ajusta brilho PWM (0..255)
  cyd color "#00FFFF"     # Altera cor tema em tempo real
  cyd cmd "rf spectrum"   # Executa comando no Terminal CYD (Tela 11) e imprime a saida no Linux
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser

API_BASE = os.environ.get("CYD_API_URL", "http://127.0.0.1:8088").rstrip("/")

SCREENS = [
    (0,  "Resumo Gauges",       ("resumo", "home", "gauges")),
    (1,  "CPU + RAM",           ("cpu", "ram", "cpuram")),
    (2,  "Grafico Duplo",       ("dual", "duplo")),
    (3,  "GPU Focus",           ("gpu", "video")),
    (4,  "4x Graficos",         ("graph", "graficos", "4x")),
    (5,  "Wallpaper HUD",       ("wall", "wallpaper", "fundo")),
    (6,  "Mercado & Cripto",    ("market", "mercado", "btc", "bolsa")),
    (7,  "Meu Portfolio",       ("portfolio", "carteira")),
    (8,  "Pomodoro Focus",      ("pomo", "pomodoro", "foco")),
    (9,  "Spotify & YT Music",  ("media", "midia", "spotify", "music")),
    (10, "Clima & News Feed",   ("news", "clima", "weather", "noticias")),
    (11, "Terminal CYD",        ("term", "terminal", "shell", "cmd")),
    (12, "Radar Wi-Fi RF",      ("radar", "wifi", "rf", "scan")),
    (13, "Rede & Roteador",     ("net", "rede", "router", "roteador", "vivo", "speed")),
]

SCREEN_COUNT = len(SCREENS)


def api_get(path: str, timeout: float = 4.0) -> dict:
    url = f"{API_BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.URLError as ex:
        sys.exit(f"Erro ao conectar no agente CYD ({API_BASE}): {ex.reason}\nVerifique: systemctl --user status cyd-cyber-deck.service")


def api_post(path: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.URLError as ex:
        sys.exit(f"Erro ao enviar comando para o agente CYD ({API_BASE}): {ex.reason}")
    except TimeoutError:
        sys.exit(f"Tempo limite excedido ({int(timeout)}s) aguardando resposta do agente CYD ({path}).")


def resolve_screen_arg(token: str) -> int:
    t = str(token).strip().lower()
    if t.isdigit():
        idx = int(t)
        if 0 <= idx < SCREEN_COUNT:
            return idx
        sys.exit(f"Tela invalida: {idx} (use 0..{SCREEN_COUNT - 1})")
    for idx, name, aliases in SCREENS:
        if t == name.lower() or t in aliases or t in name.lower():
            return idx
    sys.exit(f"Tela desconhecida: '{token}'. Rode 'cyd list' para ver as telas disponiveis.")


def cmd_list(_args):
    st = api_get("/api/status")
    cur = st.get("screen", -1)
    print(f"CYD Cyber Deck ({API_BASE}) — {SCREEN_COUNT} telas disponiveis:")
    for idx, name, aliases in SCREENS:
        mark = "◀ ATIVA" if idx == cur else ""
        al = ", ".join(aliases[:3])
        print(f"  [{idx:02d}] {name:<20} ({al})  {mark}")


def cmd_screen(target: str):
    idx = resolve_screen_arg(target)
    res = api_post("/api/screen", {"screen": idx})
    name = SCREENS[idx][1]
    if res.get("ok"):
        print(f"CYD -> Tela {idx} ({name})")
    else:
        sys.exit(f"Falha: {res.get('error', res)}")


def cmd_step(delta: int):
    st = api_get("/api/status")
    cur = int(st.get("screen", 0))
    nxt = (cur + delta) % SCREEN_COUNT
    cmd_screen(str(nxt))


def cmd_status(_args):
    st = api_get("/api/status")
    scr = int(st.get("screen", 0))
    scr_name = SCREENS[scr][1] if 0 <= scr < SCREEN_COUNT else str(scr)
    sys_m = st.get("sys", {})
    wrad = st.get("wifi_radar", {})
    neta = st.get("net_analyzer", {})

    print(f"Tela ativa : [{scr:02d}] {scr_name} | Cor: {st.get('hex_color')} | Brilho: {st.get('brt')}/255")
    print(
        f"Hardware   : CPU {sys_m.get('cpu', 0):.1f}% ({sys_m.get('cput', '--')}°C) | "
        f"RAM {sys_m.get('ram', 0):.1f}% | GPU {sys_m.get('gpu', 0):.1f}%"
    )
    if wrad:
        st_w = "ONLINE" if wrad.get("online") else "OFFLINE"
        print(
            f"Radar Wi-Fi: {st_w} ({wrad.get('port', '--')}) | {wrad.get('total', 0)} APs | "
            f"Melhor: {wrad.get('best_rssi', 0)} dBm | Livre: CH{wrad.get('free_ch', 1)} | Cheio: CH{wrad.get('busiest_ch', 0)}"
        )
    if neta:
        spd = neta.get("speedtest", {})
        print(
            f"Rede / GW  : {neta.get('gateway_ip', '--')} ({neta.get('gw_ms', 0):.1f}ms, loss {neta.get('gw_loss', 0)}%) | "
            f"WAN {neta.get('wan_ms', 0):.1f}ms | DNS {neta.get('dns_ms', 0)}ms | ISP: {neta.get('isp', '--')}"
        )
        print(
            f"Trafego    : ↓ {neta.get('rx_mbps', 0):.1f} Mbps | ↑ {neta.get('tx_mbps', 0):.1f} Mbps "
            f"(Plano: {neta.get('plan_mbps', 700)} Mbps | LAN: {neta.get('lan_count', 0)} hosts)"
        )
        if spd.get("dl_mbps", 0) > 0:
            print(
                f"Speedtest  : DL {spd['dl_mbps']:.1f} Mbps ({spd.get('plan_pct', 0)}%) | "
                f"UL {spd['ul_mbps']:.1f} Mbps | Ping {spd.get('ping_ms', 0):.1f}ms ({spd.get('time_str')})"
            )


def cmd_radar(args):
    if args.scan:
        api_post("/api/wifi_radar", {"action": "scan"})
        print("Varredura disparada na ESP32-WROOM-32U... aguardando 4s")
        time.sleep(4.0)
    st = api_get("/api/status")
    wr = st.get("wifi_radar", {})
    print(f"Status: {wr.get('status_msg', 'Indisponivel')}")
    print(
        f"Total: {wr.get('total', 0)} APs | Melhor: {wr.get('best_rssi', 0)} dBm | "
        f"Livre: CH{wr.get('free_ch', 1)} | Cheio: CH{wr.get('busiest_ch', 0)} | Ultimo: {wr.get('last_scan_str', '--')}"
    )
    print("-" * 68)
    print(f"{'SSID':<24} {'CH':>3}  {'RSSI':>8}  {'SEG':<5} {'BSSID':<17}")
    for n in wr.get("networks", [])[:15]:
        print(
            f"{str(n.get('ssid', '<OCULTA>'))[:24]:<24} "
            f"C{int(n.get('ch', 0)):02d}  "
            f"{int(n.get('rssi', -100)):>4d} dBm  "
            f"{str(n.get('enc', 'WPA')):<5} "
            f"{str(n.get('bssid', '')):<17}"
        )


def cmd_router(args):
    res = api_post("/api/net_analyzer", {"action": "router_diag"})
    diag = res.get("diag") or api_get("/api/status").get("net_analyzer", {})
    gw = diag.get("gateway_ip", "--")
    url = diag.get("admin_url", f"http://{gw}")
    print(f"Roteador / Gateway : {gw} (MAC: {diag.get('gateway_mac') or '--'})")
    print(f"Interface / IP PC  : {diag.get('interface', '--')} -> {diag.get('local_ip', '--')}")
    print(f"Latencia / Jitter  : {diag.get('ping_ms', diag.get('gw_ms', 0)):.1f} ms | jitter {diag.get('jitter_ms', diag.get('gw_jit', 0)):.1f} ms | perda {diag.get('loss_pct', diag.get('gw_loss', 0))}%")
    print(f"Painel Admin HTTP  : {url} (HTTP {diag.get('http_status', diag.get('gw_http', 0))} • {diag.get('http_hint', diag.get('gw_hint', ''))})")
    if "dns_forwarder_ok" in diag:
        print(f"DNS no Roteador    : {'OK' if diag['dns_forwarder_ok'] else 'Sem resposta'}")
    print(f"Hosts ativos LAN   : {diag.get('lan_count', 0)}")
    if args.open and gw and gw != "--":
        print(f"Abrindo painel do roteador em {url}...")
        webbrowser.open(url)


def cmd_lan(_args):
    st = api_get("/api/status")
    neta = st.get("net_analyzer", {})
    hosts = neta.get("lan_hosts", [])
    print(f"Dispositivos na LAN ({len(hosts)} encontrados via tabela ARP local):")
    print(f"{'IP':<16} {'MAC':<19} {'ESTADO':<10} {'TIPO'}")
    print("-" * 58)
    for h in hosts:
        print(f"{h.get('ip',''):<16} {h.get('mac',''):<19} {h.get('state',''):<10} {h.get('tag','')}")


def cmd_speed(args):
    if not args.no_switch:
        api_post("/api/screen", {"screen": 13})
    api_post("/api/net_analyzer", {"action": "speedtest"})
    print("Speedtest iniciado (acompanhe tambem na Tela 13 da CYD)...")
    t0 = time.time()
    while time.time() - t0 < 35:
        time.sleep(1.5)
        st = api_get("/api/status")
        spd = st.get("net_analyzer", {}).get("speedtest", {})
        if not spd.get("running"):
            if spd.get("error"):
                sys.exit(f"Erro no Speedtest: {spd['error']}")
            plan = st.get("net_analyzer", {}).get("plan_mbps", 700)
            print(
                f"Resultado ({spd.get('time_str')}): "
                f"Download {spd.get('dl_mbps', 0):.1f} Mbps ({spd.get('plan_pct', 0)}% de {plan} Mbps) | "
                f"Upload {spd.get('ul_mbps', 0):.1f} Mbps | Ping {spd.get('ping_ms', 0):.1f} ms"
            )
            return
    print("Speedtest ainda em andamento (confira na Tela 13 da CYD).")


def run_term_cmd(cmd_str: str, timeout: float = 15.0):
    """Envia comando ao Terminal CYD (Tela 11) com wait=True e imprime as linhas retornadas."""
    is_ai = cmd_str.strip().lower().startswith(("ai ", "ia ", "gemini ")) or cmd_str.strip().lower() in ("ai", "ia", "gemini")
    eff_to = max(timeout, 110.0) if is_ai else timeout
    st_before = None
    try:
        res = api_post("/api/terminal", {"cmd": cmd_str, "wait": True, "timeout": eff_to - 5.0}, timeout=eff_to)
    except Exception:
        res = api_post("/api/terminal", {"cmd": cmd_str}, timeout=eff_to)

    out_lines = res.get("output")
    if isinstance(out_lines, list) and out_lines:
        for ln in out_lines:
            print(ln)
        return

    # Fallback para daemons que ainda nao retornam "output" sincrono no POST /api/terminal
    seq_before = res.get("lines_before", res.get("seq"))
    t0 = time.time()
    while time.time() - t0 < 8.0:
        time.sleep(0.35)
        st_before = api_get("/api/status")
        term = st_before.get("terminal", {})
        if not term.get("busy", False):
            break
    if st_before is None:
        st_before = api_get("/api/status")
    all_lines = st_before.get("terminal", {}).get("lines", [])
    if isinstance(seq_before, int) and 0 <= seq_before < len(all_lines):
        sliced = all_lines[seq_before:]
    else:
        marker = f"$ {cmd_str}".strip()
        idx = -1
        for i in range(len(all_lines) - 1, -1, -1):
            if all_lines[i].strip() == marker:
                idx = i
                break
        sliced = all_lines[idx:] if idx >= 0 else all_lines[-12:]
    if sliced:
        for ln in sliced:
            print(ln)
    else:
        print(f"Comando enviado ao Terminal CYD: {cmd_str}")


def cmd_ai(args):
    """Comandos do Agente IA Hibrido (Google Gemini + IA Local Ollama/OpenAI-compat)."""
    sub_a = (args.ai_action or "status").lower().strip()
    extra = list(args.extra or [])

    if sub_a in ("status", "st"):
        res = api_post("/api/ai", {"action": "status"}, timeout=8.0)
        ai = res.get("ai", {})
        print(f"Agente IA CYD Cyber Deck ({API_BASE})")
        print(f"  Provedor ativo : {str(ai.get('ai_provider', 'auto')).upper()}")
        g_key = f"CONFIGURADA ({ai.get('gemini_key_masked', '***')})" if ai.get("gemini_key_set") else "NAO CONFIGURADA"
        print(f"  Google Gemini  : {g_key} | Modelo: {ai.get('gemini_model', 'gemini-2.5-flash')}")
        l_on = "ONLINE" if ai.get("local_online") else "OFFLINE"
        print(
            f"  IA Local       : {l_on} ({ai.get('local_kind', 'ollama')}) | "
            f"URL: {ai.get('local_ai_url', 'http://127.0.0.1:11434')} | "
            f"Modelo ativo: {ai.get('active_local_model') or '--'}"
        )
        mods = ai.get("local_models", [])
        if mods:
            print(f"  Modelos locais : {', '.join(mods)}")
        if ai.get("last_report_path"):
            print(
                f"  Ultimo relat.  : {ai['last_report_path']} "
                f"({ai.get('last_provider_used', '--')}/{ai.get('last_model_used', '--')} @ {ai.get('last_report_time', '--')})"
            )
        return

    if sub_a in ("models", "modelos", "list"):
        res = api_post("/api/ai", {"action": "models"}, timeout=8.0)
        ai = res.get("ai", {})
        print(f"Google Gemini : {ai.get('gemini_model', 'gemini-2.5-flash')} ({'CHAVE OK' if ai.get('gemini_key_set') else 'SEM CHAVE'})")
        print(f"IA Local      : {'ONLINE' if res.get('local_online') else 'OFFLINE'} ({res.get('local_kind', 'ollama')}) em {ai.get('local_ai_url', '')}")
        mods = res.get("local_models", [])
        if mods:
            active_m = ai.get("active_local_model", "")
            for m in mods:
                mark = " ◀ ATIVO" if m == active_m else ""
                print(f"  - {m}{mark}")
        else:
            print("  Nenhum modelo local encontrado.")
        return

    if sub_a in ("config", "cfg", "set"):
        payload = {"action": "config"}
        if args.provider:
            payload["ai_provider"] = args.provider
        if args.gemini_key is not None:
            payload["gemini_api_key"] = args.gemini_key
        if args.gemini_model:
            payload["gemini_model"] = args.gemini_model
        if args.local_url:
            payload["local_ai_url"] = args.local_url
        if args.local_model is not None:
            payload["local_ai_model"] = args.local_model
        if len(payload) == 1:
            print("Nenhuma opcao informada. Exemplo:")
            print("  cyd ai config --provider auto --gemini-key SUA_CHAVE --gemini-model gemini-2.5-flash")
            print("  cyd ai config --provider local --local-url http://127.0.0.1:11434 --local-model qwen2.5:7b")
            return
        res = api_post("/api/ai", payload, timeout=10.0)
        cfg_p = res.get("config", {})
        print("Configuracao do Agente IA salva com sucesso!")
        print(f"  Provedor     : {str(cfg_p.get('ai_provider', 'auto')).upper()}")
        print(f"  Gemini       : {'CHAVE OK (' + cfg_p.get('gemini_key_masked', '') + ')' if cfg_p.get('gemini_key_set') else 'SEM CHAVE'} | {cfg_p.get('gemini_model', '')}")
        print(f"  IA Local     : {cfg_p.get('local_ai_url', '')} | modelo: {cfg_p.get('local_ai_model') or 'auto'}")
        return

    if sub_a in ("report", "relatorio", "full", "rf", "spectrum", "ask", "perguntar"):
        if sub_a in ("rf", "spectrum"):
            act_api = "rf"
            q_str = ""
        elif sub_a in ("ask", "perguntar"):
            act_api = "ask"
            q_str = " ".join(extra).strip()
            if not q_str:
                sys.exit("Informe a pergunta. Ex: cyd ai ask \"Qual canal 2.4GHz devo usar no roteador?\"")
        else:
            act_api = "report"
            q_str = ""

        prov = args.provider
        if not prov and extra and act_api != "ask" and extra[0].lower() in ("auto", "gemini", "local"):
            prov = extra[0].lower()

        print(f"Consultando Agente IA ({act_api}, provedor={prov or 'padrao'})... aguarde...")
        res = api_post(
            "/api/ai",
            {
                "action": act_api,
                "provider": prov,
                "question": q_str,
                "push_cyd": not bool(args.no_cyd),
                "switch_screen": not bool(args.no_cyd),
            },
            timeout=210.0,
        )
        if not res.get("ok"):
            sys.exit(f"Erro no Agente IA: {res.get('error', 'desconhecido')}")

        prov_u = res.get("provider_used", "?")
        mod_u = res.get("model_used", "?")
        elap = res.get("elapsed_s", 0.0)
        print(f"\n=== AGENTE IA CYD ({prov_u.upper()} / {mod_u} — {elap:.1f}s) ===")
        if res.get("report_path"):
            print(f"Relatorio salvo em: {res['report_path']}")
        print("=" * 68)
        print(res.get("markdown") or "\n".join(res.get("cyd_lines", [])))
        print("=" * 68)
        if not args.no_cyd:
            print("Resumo tambem enviado para a Tela 11 (SCR_TERMINAL) da placa CYD.")
        return

    # Atalho: `cyd ai <pergunta livre>`
    q_free = " ".join([args.ai_action] + extra).strip()
    print(f"Consultando Agente IA (pergunta livre)... aguarde...")
    res = api_post(
        "/api/ai",
        {"action": "ask", "provider": args.provider, "question": q_free, "push_cyd": not bool(args.no_cyd)},
        timeout=125.0,
    )
    if not res.get("ok"):
        sys.exit(f"Erro no Agente IA: {res.get('error', 'desconhecido')}")
    print(f"\n=== AGENTE IA CYD ({res.get('provider_used','?').upper()} / {res.get('model_used','?')} — {res.get('elapsed_s',0):.1f}s) ===")
    print(res.get("markdown") or "\n".join(res.get("cyd_lines", [])))


def main():
    # Atalho super pratico: `cyd 12`, `cyd 13`, `cyd diag`
    if len(sys.argv) == 2 and (sys.argv[1].isdigit() or sys.argv[1].lower() in ("next", "prev", "list", "status", "lan", "diag")):
        tok = sys.argv[1].lower()
        if tok.isdigit():
            cmd_screen(tok)
            return
        if tok == "next":
            cmd_step(1)
            return
        if tok == "prev":
            cmd_step(-1)
            return
        if tok == "diag":
            run_term_cmd("netcheck")
            return

    ap = argparse.ArgumentParser(prog="cyd", description="CLI Linux do CYD Cyber Deck (troca de telas, Radar Wi-Fi RF, Terminal e Analise de Rede)")
    sub = ap.add_subparsers(dest="command")

    p_scr = sub.add_parser("screen", aliases=["s"], help="Muda a tela da CYD (numero 0..13 ou apelido)")
    p_scr.add_argument("target", help="Numero (0..13) ou nome (ex: radar, net, gpu, term, market)")

    sub.add_parser("next", aliases=["n"], help="Avanca para a proxima tela")
    sub.add_parser("prev", aliases=["p"], help="Volta para a tela anterior")
    sub.add_parser("list", aliases=["ls"], help="Lista todas as telas disponiveis")
    sub.add_parser("status", aliases=["st"], help="Mostra resumo do hardware, Radar Wi-Fi e Rede")

    p_rad = sub.add_parser("radar", help="Mostra redes do Radar Wi-Fi (ESP32-WROOM-32U)")
    p_rad.add_argument("--scan", action="store_true", help="Dispara nova varredura antes de exibir")

    p_rf = sub.add_parser("rf", help="Comandos de inteligencia RF no Terminal CYD (scan, spectrum, audit, diff, status, export, track)")
    p_rf.add_argument("args", nargs="*", help="Subcomando RF (ex: scan, spectrum, audit, diff, status, export, track <filtro>)")

    sub.add_parser("diag", aliases=["netcheck"], help="Executa bateria completa de diagnostico (GW + Jitter + WAN + DNS + LAN + 32U)")

    p_jit = sub.add_parser("jitter", help="Mede estabilidade ICMP e jitter (padrao 1.1.1.1 ou gw)")
    p_jit.add_argument("target", nargs="?", default="1.1.1.1", help="Host ou IP alvo (use 'gw' para testar o roteador)")

    p_mtu = sub.add_parser("mtu", help="Descobre o Path MTU (Don't Fragment) da rota")
    p_mtu.add_argument("target", nargs="?", default="1.1.1.1", help="Host ou IP alvo (padrao: 1.1.1.1)")

    p_tls = sub.add_parser("tls", aliases=["ssl"], help="Inspeciona certificado TLS/SSL de um dominio (:443)")
    p_tls.add_argument("host", help="Dominio ou host:porta (ex: github.com)")

    p_ai = sub.add_parser("ai", aliases=["ia"], help="Agente IA hibrido (Gemini + Ollama local) para analise de redes e RF")
    p_ai.add_argument("ai_action", nargs="?", default="status", help="status | models | report | rf | ask | config")
    p_ai.add_argument("extra", nargs="*", help="Pergunta para 'ask' ou provedor opcional")
    p_ai.add_argument("--provider", choices=["auto", "gemini", "local"], default=None, help="Forca provedor de IA")
    p_ai.add_argument("--gemini-key", default=None, help="Define chave GEMINI_API_KEY (use 'clear' para remover)")
    p_ai.add_argument("--gemini-model", default=None, help="Define modelo Gemini (ex: gemini-2.5-flash)")
    p_ai.add_argument("--local-url", default=None, help="URL da IA Local (padrao: http://127.0.0.1:11434)")
    p_ai.add_argument("--local-model", default=None, help="Modelo local (ex: qwen2.5:7b ou 'auto')")
    p_ai.add_argument("--no-cyd", action="store_true", help="Nao envia o resumo para a Tela 11 da CYD")

    p_rt = sub.add_parser("router", aliases=["gw"], help="Diagnostico do roteador/gateway")
    p_rt.add_argument("--open", action="store_true", help="Abre a pagina de admin do roteador no navegador")

    sub.add_parser("lan", aliases=["arp"], help="Lista dispositivos ativos na LAN")

    p_spd = sub.add_parser("speed", help="Dispara Speedtest do link de internet (Tela 13)")
    p_spd.add_argument("--no-switch", action="store_true", help="Nao troca a CYD para a Tela 13")

    p_plan = sub.add_parser("plan", help="Define a velocidade contratada do plano em Mbps (ex: 700)")
    p_plan.add_argument("mbps", type=int)

    p_brt = sub.add_parser("brt", help="Ajusta brilho da CYD (0..255)")
    p_brt.add_argument("value", type=int)

    p_col = sub.add_parser("color", help="Altera cor tema da CYD (ex: #00FFFF)")
    p_col.add_argument("hex_color")

    p_cmd = sub.add_parser("cmd", help="Executa comando no Terminal CYD (Tela 11) e exibe a saida")
    p_cmd.add_argument("text", nargs="+")

    args = ap.parse_args()
    c = args.command

    if c in ("screen", "s"):
        cmd_screen(args.target)
    elif c in ("next", "n"):
        cmd_step(1)
    elif c in ("prev", "p"):
        cmd_step(-1)
    elif c in ("list", "ls"):
        cmd_list(args)
    elif c in ("status", "st"):
        cmd_status(args)
    elif c == "radar":
        cmd_radar(args)
    elif c == "rf":
        sub_rf = " ".join(args.args).strip() if args.args else "status"
        run_term_cmd(f"rf {sub_rf}".strip())
    elif c in ("diag", "netcheck"):
        run_term_cmd("netcheck")
    elif c == "jitter":
        run_term_cmd(f"jitter {args.target}".strip())
    elif c == "mtu":
        run_term_cmd(f"mtu {args.target}".strip())
    elif c in ("tls", "ssl"):
        run_term_cmd(f"tls {args.host}".strip())
    elif c in ("ai", "ia"):
        cmd_ai(args)
    elif c in ("router", "gw"):
        cmd_router(args)
    elif c in ("lan", "arp"):
        cmd_lan(args)
    elif c == "speed":
        cmd_speed(args)
    elif c == "plan":
        api_post("/api/net_analyzer", {"action": "set_plan", "plan_mbps": args.mbps})
        print(f"Plano de internet ajustado para {args.mbps} Mbps.")
    elif c == "brt":
        v = max(0, min(255, args.value))
        api_post("/api/brightness", {"brt": v})
        print(f"Brilho CYD ajustado para {v}/255.")
    elif c == "color":
        api_post("/api/color", {"hex": args.hex_color})
        print(f"Cor CYD ajustada para {args.hex_color}.")
    elif c == "cmd":
        txt = " ".join(args.text)
        run_term_cmd(txt)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
