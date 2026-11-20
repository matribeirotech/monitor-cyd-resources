# ⚡ CYD Cyber Deck: Hardware, Clima Regional, News Feed, Terminal Administrativo, Radar Wi-Fi RF, Análise de Rede & Financial Market Monitor (v4.5 — Windows & Linux)

![Versão](https://img.shields.io/badge/vers%C3%A3o-4.5.0-00FF00?style=for-the-badge)
![OS](https://img.shields.io/badge/OS-Ubuntu%20%7C%20Linux%20%7C%20Windows-E95420?style=for-the-badge&logo=ubuntu)
![Plataforma](https://img.shields.io/badge/ESP32-2432S028R%20(CYD)-blue?style=for-the-badge&logo=espressif)
![Interface PC](https://img.shields.io/badge/GUI%20PC-Flet%20%2F%20Flutter-02569B?style=for-the-badge&logo=flutter)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?style=for-the-badge&logo=githubactions)
![Autor](https://img.shields.io/badge/Autor-Matheus%20Ribeiro%20(z1po)-FF5500?style=for-the-badge)
[![Maintained by LYPSYOS](https://img.shields.io/badge/Maintained%20by-LYPSYOS%20OSS%20Community-2457F5?style=for-the-badge)](https://lypsyos.com)
![Licença](https://img.shields.io/badge/Licen%C3%A7a-MIT-green?style=for-the-badge)

Um **Cyber Deck administrativo, monitor de hardware de alta performance, feed de notícias passivo, terminal interativo de rede/sistema e estação meteorológica regional** de código aberto para a placa **ESP32-2432S028R (*Cheap Yellow Display* / CYD 2.8" 320×240)**.

Controlado **100% pelo PC via USB Serial com I/O Assíncrono (`SerialManager` a 115200 bps sem delay de UI)**, interface desktop minimalista **Clean UI em 8 módulos com `NavigationRail` lateral expansível** construída em **Flet (Flutter para Python)**, nova identidade visual oficial, pipeline CI/CD automatizado no GitHub Actions e controle remoto pelo smartphone via **Wi-Fi local (PWA de 5 abas)**.

---

## 📸 Galeria do Projeto (v4.1 em Hardware Real na Placa CYD)

### 💻 1. Novo Painel de Controle Desktop v4.1 — Navegação em 7 Abas & Gestão de 11 Telas
<p align="center">
  <img src="preview/5.0/agent-novo.jpg" alt="Novo Painel de Controle Desktop v4.1 - 7 Abas, Header com Clima Regional de Votuporanga e Seletor das 11 Telas da CYD" width="98%" />
</p>

---

### 🖥️ 2. Fotos em Execução Real na Placa CYD (ESP32-2432S028R)

Todas as fotos abaixo foram capturadas diretamente da placa física em funcionamento, exibindo o **menu superior com Data e Temperatura de Votuporanga em tempo real** e as novas telas:

#### 🌦️🤖 Tela 10: Clima Regional (Votuporanga), Previsão & Gemini Gems IA
<p align="center">
  <img src="preview/5.0/IMG_20261107_150219_002.jpg" alt="Tela 10: Clima Regional de Votuporanga (35.1°C), Sensação, Vento, Chuva e Gemini Gems IA (Radar Embarcados)" width="85%" />
</p>

#### ⚡ Tela 0: Resumo Gauges & 🖥️ Tela 1: CPU + RAM Principal (`sys.mon_`)
<p align="center">
  <img src="preview/5.0/IMG_20261107_150101_946.jpg" alt="Tela 0: Resumo Gauges circulares com cabeçalho [35C] VOTUPORANGA" width="49%" />
  <img src="preview/5.0/IMG_20261107_150110_792.jpg" alt="Tela 1: CPU + RAM Principal sys.mon_ com barras e gráficos duplos" width="49%" />
</p>

#### 📈 Tela 2: Gráfico Duplo CPU vs RAM & 🎮 Tela 3: GPU Focus
<p align="center">
  <img src="preview/5.0/IMG_20261107_150122_079.jpg" alt="Tela 2: Gráfico Duplo CPU vs RAM sobrepostos" width="49%" />
  <img src="preview/5.0/IMG_20261107_150136_050.jpg" alt="Tela 3: GPU Focus - Medidor de carga, Watts e VRAM + Ticker Votuporanga" width="49%" />
</p>

#### 📊 Tela 4: 4x Gráficos em Tempo Real & 💰 Tela 6: Mercado Financeiro & Cripto
<p align="center">
  <img src="preview/5.0/IMG_20261107_150142_150.jpg" alt="Tela 4: 4x Gráficos em Tempo Real (CPU, RAM, GPU, Temp)" width="49%" />
  <img src="preview/5.0/IMG_20261107_150151_460.jpg" alt="Tela 6: Mercado Financeiro - Dólar, Euro, IBOVESPA e Curva Bitcoin 24h" width="49%" />
</p>

#### 💼 Tela 7: Meu Portfólio & 🍅 Tela 8: Pomodoro Focus Hub
<p align="center">
  <img src="preview/5.0/IMG_20261107_150158_685.jpg" alt="Tela 7: Portfólio de Investimentos Pessoal com PnL dinâmico" width="49%" />
  <img src="preview/5.0/IMG_20261107_150204_804.jpg" alt="Tela 8: Pomodoro Focus Hub - Cronômetro circular 25:00 e contador de ciclos" width="49%" />
</p>

#### 🎵 Tela 9: Player Spotify & YouTube Music
<p align="center">
  <img src="preview/5.0/IMG_20261107_150210_945.jpg" alt="Tela 9: Player Multimídia com disco holográfico e card translúcido de mídia" width="85%" />
</p>

---

### 💻 3. Abas do Painel de Controle Desktop v4.1 (Flet / Flutter)

<details>
<summary><b>Clique para ver as capturas individuais de cada aba do Desktop</b></summary>
<br/>

#### 📊 Aba 0: Painel Geral, Telemetria & Grade das Telas
<p align="center">
  <img src="preview/v4-aba0-painel-telas.png" alt="Aba 0: Painel Geral e Seletor de Telas" width="90%" />
</p>

#### 🍅🎵 Aba 1: Foco & Mídia — Pomodoro Focus Hub + Player Spotify / YouTube Music
<p align="center">
  <img src="preview/v4-aba1-foco-midia.png" alt="Aba 1: Pomodoro Timer e Player de Mídia" width="90%" />
</p>

#### 💼 Aba 2: Mercado Financeiro & Portfólio Pessoal de Investimentos
<p align="center">
  <img src="preview/v4-aba2-mercado-carteira.png" alt="Aba 2: Cotações ao Vivo e Gestão de Carteira" width="90%" />
</p>

#### 🎨☀️ Aba 3: Estúdio de Cores RGB565, Fundo SD, Brilho PWM & Modo Sleep/Noturno
<p align="center">
  <img src="preview/v4-aba3-estudio-energia.png" alt="Aba 3: Seletor de Cores e Energia" width="90%" />
</p>

#### 🔔 Aba 4: Sistema de Alertas Físicos Avançados (Buzzer & LED RGB)
<p align="center">
  <img src="preview/v4-aba4-alertas-fisicos.png" alt="Aba 4: Configuração de Gatilhos de Alerta Físico" width="90%" />
</p>

</details>

---

## 🎯 Destaques e Novidades da Versão 4.2 (Cyber Deck Edition)

* **⚡ Comunicação Serial 100% Assíncrona (`SerialManager` a 115200 bps):**
  * Toda a leitura/escrita de porta COM (`pyserial`) foi isolada em uma thread dedicada (`SerialManagerThread`). O loop do Flet **nunca mais espera resposta da CYD** e opera com fluidez absoluta.
  * **3 Canais de Prioridade:** `transfer_queue` (blocos de foto SD), `event_queue` (troca de tela e comandos imediatos `< 20ms`) e slot atômico `_latest_telemetry` que descarta frames velhos se a porta estiver ocupada, eliminando qualquer atraso acumulado (*buffer bloat*).
  * Card lateral de diagnóstico em tempo real no rodapé do menu (Porta, Baudrate, pacotes TX/RX, taxa B/s e botão de reconexão rápida).
* **🚀 Otimização de Coleta de Hardware (`Collector` em Background Worker):**
  * Eliminação do stall de 800ms/s do Windows TCP com backoff de 30s caso o LibreHardwareMonitor (`127.0.0.1:8085`) não esteja rodando.
  * Coleta em camadas: CPU/RAM/Disco/Rede (1.0s), GPU/WMI/Sensores (2.0s) e Processos/Jogos (6.0s). O método `sample_sys()` retorna a foto em cache instantaneamente em **`~0.028 ms` ($O(1)$)**.
* **🎨 Clean UI com `NavigationRail` Lateral Expansível:**
  * Substituição das antigas abas horizontais por uma barra lateral retrátil elegante (`NavigationRail`) com botão toggle de expansão/recolhimento.
  * **State Management Granular:** As atualizações periódicas afetam exclusivamente a aba visível (`active_tab`) e os chips do cabeçalho via `safe_update()`, reduzindo drasticamente o uso de CPU e memória RAM do agente no PC.
* **🛡️ Nova Identidade Visual Oficial:**
  * Novos ícones vetorizados de alta resolução (`icone-cyd-resource-monitor.ico` e `icone-cyd-resource-monitor.png`) embutidos na barra de títulos da janela, no topo do menu lateral, na bandeja do sistema Windows (`pystray`) e no binário compilado `.exe`.
* **📡 Telemetria Wi-Fi (UDP) & Modo Híbrido (USB + Sem Fio):**
  * **Zero Latência Sem Fio:** Transmissão contínua de telemetria e controle de telas através de datagramas UDP na porta `8888` via `<WiFiUdp.h>` nativo do ESP32.
  * **Modo Híbrido com Failover Inteligente:** O agente desktop detecta a saúde do link Wi-Fi via heartbeats periódicos (`udp_ping` / `udp_pong`). Se a rede oscilar, o sistema realiza fallback transparente e imediato para a porta USB Serial (115200 bps) sem perda de quadros.
  * **Fragmentação Segura (< 1400 bytes):** O Python divide payloads extensos em blocos de topo seguros, contornando limitações de reassembly do lwIP e garantindo recepção íntegra no ESP32.
  * **Provisionamento Remoto de Wi-Fi:** Configuração de SSID e senha direto pela interface Flet com gravação permanente na memória NVS (`Preferences`) do ESP32 via comando `wifi_cfg`.
  * **Loop Não-Bloqueante:** Processamento dreno de buffer assíncrono mantendo a taxa de renderização de ~28 FPS no display TFT.
* **📰 Feed de Notícias Customizável (Tela 10 / `SCR_NEWS`):**
  * Módulo passivo de notícias por tópicos customizáveis ("Política", "Tecnologia", "Mercado Financeiro", "Inteligência Artificial", etc.) via NewsAPI.org ou feeds RSS gratuitos (Google/Bing News RSS).
  * Fila inteligente com rotação automática a cada 15 segundos e letreiro deslizante suave na tela da CYD via `TFT_eSprite`.
* **💻 O Terminal CYD — Ferramentas de Rede, Homelab e Sistema (Tela 11 / `SCR_TERMINAL`):**
  * Prompt interativo estilo hacker retrô / terminal CRT verde com buffer de rolagem vertical (*scroll* suave linha por linha).
  * **UX Avançada no Flet:** Histórico com navegação por setas **Cima / Baixo** (estilo bash), rolagem automática inteligente e chips de acesso rápido com 1-toque.
  * **Comandos do Sistema (PC / Homelab):**
    * `whoami`: Exibe usuário ativo, máquina, SO e PID.
    * `neofetch`: Banner de hardware compacto com arte ASCII (OS, Host, Uptime, CPU, RAM e GPU).
    * `df -h`: Partições de disco ativas, espaço livre, ocupado e percentual de uso via `psutil`.
    * `free -m`: Memória RAM e Swap usada/livre em Megabytes.
    * `uptime`: Tempo contínuo de atividade do PC e timestamp de inicialização.
    * `top`: Ranking dos 5 principais processos por consumo de memória RAM.
  * **Rede & Infraestrutura:**
    * `ip addr` / `ifconfig`: Detecção automática das interfaces de rede ativas (Ethernet, Wi-Fi, Tailscale, etc.) e seus respectivos IPs locais.
    * `netstat -tuln`: Lista portas abertas em estado `LISTEN` e seus processos associados.
    * `ping [alvo]`: Teste ICMP de latência em tempo real transmitido linha a linha para a placa.
    * `fetch [url]`: Disparo de HTTP GET com aferição de tempo de resposta, headers e status code.
    * `ssh [user]@[host] [cmd]`: Execução remota rápida em servidores Linux / VPS / Homelab com suporte a `paramiko` e fallback para o cliente OpenSSH.
  * **Gerenciamento Docker:**
    * `docker ps`: Lista os containers ativos, status e portas mapeadas.
    * `docker stats`: Consumo instantâneo de CPU e memória RAM dos containers ativos.
    * `docker logs [container]`: Inspeção das últimas 10 linhas de log de um container específico.
  * **Comandos Nativos Executados em Hardware na CYD (ESP32):**
    * `wifi scan`: Dispara `WiFi.scanNetworks()` nativo do ESP32 e imprime os SSIDs e potências RSSI direto no terminal da placa.
    * `esp info`: Retorna IP local da placa, força do sinal Wi-Fi (dBm), MAC Address, versão do firmware e clock do chip.
    * `esp mem`: Diagnóstico detalhado de memória RAM (Heap livre, tamanho total, mínimo histórico, maior bloco contínuo e status de PSRAM).
    * `esp reboot`: Aciona remotamente o `ESP.restart()` na placa CYD com aviso prévio no display.
    * `cmatrix`: *Easter egg* visual que inicia uma chuva de código verde estilo Matrix Rain fosforescente na `SCR_TERMINAL`.
* **🍅 Módulo de Foco Pomodoro (Tela 8):** Máquina de estados completa no PC (Trabalho 25m, Pausa Curta 5m, Pausa Longa 15m), anel circular anti-flicker (`drawSmoothArc`) na CYD com interpolação de 1s, contador de ciclos diários e **bipes sonoros automáticos no Buzzer** ao concluir cada ciclo.
* **🎵 Hub Multimídia Spotify & YouTube Music (Tela 9):**
  * Integração nativa com Windows GSMTC (`winrt.windows.media.control`) identificando **Spotify** (Desktop/Store/Web) e **YouTube Music** (Chrome/Edge/Brave/Firefox/PWA/Desktop).
  * Redimensionamento inteligente da capa para **320×240 JPEG** (com remoção automática de faixas pretas em thumbnails 16:9) e transmissão em blocos Base64 para o MicroSD (`_media_cov.jpg`).
  * **Overlay Translúcido Real (*Alpha-Blending* RGB565 em Hardware):** Renderiza a capa do álbum com vidro fumê escuro mantendo a leitura nítida de Título, Artista, badge dinâmico da fonte e barra de progresso.
* **💼 Gestão de Portfólio de Investimentos (Tela 7):** Monitoramento de patrimônio pessoal em Reais (`R$`), cálculo de Lucro/Prejuízo (PnL) histórico ou diário (24h) com cor dinâmica (verde/vermelho) e ranking dos Top 3 ativos da carteira (Cripto, B3, Câmbio e EUA).
* **🔔 Sistema de Alertas Físicos Avançados:** Criação de gatilhos customizados (`CPU Temp > 85°C`, `GPU Uso > 95%`, `Bitcoin > $100k`, etc.) para disparar **bipes sonoros no Buzzer** e padrões visuais no **LED RGB traseiro** da CYD sem travar o processamento do ESP32.
* **🌙 Controle de Brilho Dinâmico & Modo Sleep:** Monitoramento de inatividade do mouse/teclado no PC para apagar a tela (`brt: 0`), Modo Noturno automático entre 22h e 06h e transição suave por PWM no Pino 21.
* **🌦️ Clima Regional & Temperatura no Topo (Todas as Telas):** Localidade configurável (padrão: `Votuporanga - SP`), exibindo permanentemente ao lado da Hora a Data Atual (`DD/MM`), a Temperatura Atual (`°C`) e a Cidade no menu superior da CYD e no cabeçalho do Desktop.
* **⛈️ Sistema de Alerta de Tempestade na Placa CYD:** Detecção automática de tempestades/raios via Open-Meteo com disparo de Banner de Emergência piscante vermelho/amarelo no topo de qualquer tela, alerta sonoro no Buzzer, LED RGB e aviso no Ticker Tape.
* **🚀 CI/CD Totalmente Automatizado (GitHub Actions):** Pipeline configurado em `.github/workflows/build-release.yml` para compilar o executável Windows (`CYD-Hardware-Monitor.exe`) e o firmware ESP32 (`cyd_firmware.bin`), publicando releases com os binários anexados a cada tag `v*`.

---

## 📍 Estágio Atual do Projeto & Roadmap

| Versão | Descrição | Status |
| :--- | :--- | :---: |
| **v1.0** | Telemetria básica de Hardware (CPU, GPU, RAM, Disco, Rede) via USB Serial | ✅ Concluído |
| **v2.0** | **Arquitetura *No-Touch***: Suporte a Wallpapers no MicroSD, Color Picker RGB565 e Brilho PWM | ✅ Concluído |
| **v3.0** | **Painel Desktop em Flet** + **Gráfico Duplo CPU vs RAM** + **Terminal Financeiro (Bolsa & Cripto)** + **Ticker Tape a ~28 FPS** | ✅ Concluído |
| **v3.1** | **Controle Remoto pelo Celular (Wi-Fi PWA com QR Code & App Flutter em `mobile/`)** + **Upload de fotos do smartphone p/ SD** | ✅ Concluído |
| **v4.0** | **Pomodoro (Tela 8) + Spotify & YouTube Music (Tela 9) + Portfólio Pessoal (Tela 7) + Alertas Físicos Buzzer/LED + Modo Sleep/Noturno + UI 6 Abas** | ✅ Concluído |
| **v4.1** | **Clima Regional (Votuporanga) no Topo + Tela 10 (Clima & Gemini Gems) + Alerta de Tempestade + CI/CD GitHub Actions** | ✅ Concluído |
| **v4.2** | **CYD Cyber Deck (12 Telas) + Feed de Notícias (Tela 10) + Terminal CYD (Tela 11) + Serial Assíncrona (115200 bps) + Clean UI (NavigationRail) + Nova Identidade Visual** | ✅ Concluído |
| **v4.3** | **Telemetria Wi-Fi (UDP Porta 8888) + Modo Híbrido (USB & Sem Fio) + Fragmentação MTU + Terminal Linux Expandido** | ✅ Concluído |
| **v4.5 (Atual)** | **Modo Headless (`systemd --user`) + Tela 12 (`SCR_WIFI_RADAR` via ESP32-WROOM-32U sem fio mDNS/UDP) + Tela 13 (`SCR_NET_ANALYZER` Roteador/LAN/Speedtest 700 Mbps) + CLI Linux (`cyd`)** | ✅ **Concluído (v4.5)** |

---

## 🖥️ As 14 Telas da CYD (320×240)

Todas as telas podem ser alternadas instantaneamente pelo painel Desktop, pelo aplicativo do celular (Wi-Fi), pelo **CLI Linux (`cyd`)** ou pelo botão físico `BOOT` traseiro:

1. **Tela 0 — `Resumo Gauges` (`SCR_RESUMO`):** Gauges circulares suaves de CPU % e RAM %, clock, temperatura, GPU, VRAM, Disco, Rede e Letreiro da Bolsa no rodapé.
2. **Tela 1 — `CPU + RAM Principal` (`SCR_CPU_RAM`):** Visual clássico *cyberpunk terminal* com barras duplas segmentadas, 2 gráficos dedicados de histórico lado a lado e Letreiro da Bolsa.
3. **Tela 2 — `Gráfico Duplo CPU vs RAM` (`SCR_CPU_RAM_DUAL`):** Osciloscópio de tela cheia sobrepondo curvas históricas de uso de CPU e RAM em tempo real.
4. **Tela 3 — `GPU Focus` (`SCR_GPU_FOCUS`):** Medidor grande de carga de GPU, temperatura, consumo em Watts (`W`), contador de FPS e barra de VRAM.
5. **Tela 4 — `4x Gráficos em Tempo Real` (`SCR_GRAPH`):** Grid 2×2 com gráficos simultâneos para `CPU %`, `RAM %`, `GPU %` e `TEMP °C`.
6. **Tela 5 — `Wallpaper HUD` (`SCR_WALLPAPER`):** Foco na imagem/arte do Cartão MicroSD com dock minimalista de hardware e Letreiro da Bolsa.
7. **Tela 6 — `Mercado Financeiro & Bolsa` (`SCR_MARKET`):** Terminal Bloomberg/B3 com Dólar, Euro, IBOVESPA, Top 5 Criptos e Gráfico Sparkline de Bitcoin 24h.
8. **💼 Tela 7 — `Portfólio de Investimentos` (`SCR_PORTFOLIO`):** Patrimônio total consolidado (`R$`), badge dinâmico de PnL (Lucro/Prejuízo) e Top 3 ativos da carteira.
9. **🍅 Tela 8 — `Pomodoro Focus Hub` (`SCR_POMODORO`):** Cronômetro circular anti-flicker (25m Trabalho / 5m Pausa / 15m Longa), contador de ciclos, mini-status da música atual e bipe no Buzzer ao finalizar.
10. **🎵 Tela 9 — `Player Spotify & YouTube Music` (`SCR_MEDIA`):** Capa do álbum em tela cheia do MicroSD com card de vidro fumê translúcido, Título, Artista, badge de fonte (`SPOTIFY` verde / `YT MUSIC` vermelho) e barra de progresso.
11. **📰 Tela 10 — `Feed de Notícias Customizável` (`SCR_NEWS`):** Manchetes rotativas dos tópicos escolhidos (Política, Tecnologia, Mercado, IA) com deslize horizontal suave (*ticker smooth scroll* via `TFT_eSprite`).
12. **💻 Tela 11 — `Terminal CYD & Rede` (`SCR_TERMINAL`):** Prompt estilo hacker CRT verde com buffer de rolagem vertical, logs em tempo real, comandos locais (`ping`, `fetch`, `docker`, `router`, `lan`, `dns`, `trace`, `speed`) e escaneamento nativo no ESP32 (`wifi scan`).
13. **📡 Tela 12 — `Radar Wi-Fi RF` (`SCR_WIFI_RADAR`):** Integrada via **Wi-Fi UDP + mDNS (`cyd-radar.local`)** com uma placa **ESP32-WROOM-32U** com antena externa (alimentada apenas por energia): exibe status RF, contagem de redes 2.4 GHz, gráfico de ocupação dos canais `1–13` (canal mais livre vs mais congestionado) e Top 6 redes mais fortes com barras de RSSI e dBm.
14. **🌐 Tela 13 — `Análise de Rede, Roteador & Fibra` (`SCR_NET_ANALYZER`):** Monitoramento do roteador/gateway padrão (latência, jitter, perda de pacotes e status HTTP do painel admin), latência WAN (`1.1.1.1`) + DNS + ISP, tráfego em tempo real (Mbps RX/TX vs plano configurável ex.: `700 Mbps`), contagem de vizinhos ativos na LAN (tabela ARP) e Speedtest Fibra sob demanda.

---

## 📱 Controle Remoto pelo Celular (Wi-Fi PWA & App Flutter Nativo)

Controle 100% da sua placa CYD à distância sem instalar nada no smartphone:

1. **Acesso Instantâneo via QR Code:**
   - Ao abrir o painel desktop, o servidor web local inicia na porta `8088` (com failover automático para portas seguintes caso ocupada).
   - Aponte a câmera do celular para o QR Code exibido na Aba **Remoto & Serial** ou no ícone do cabeçalho.
2. **5 Abas no Celular:**
   - 📺 **Telas:** Seletor em grade 2 colunas para as 10 telas (`0` a `9`).
   - 🎵 **Foco & Mídia:** Controles remotos completos do Pomodoro (`▶`, `↺`, `⏭`, seleção de fase) e do player Spotify / YouTube Music (`⏮`, `⏯`, `⏭`, reenviar capa ao SD).
   - 📊 **Métricas:** Telemetria ao vivo do PC, resumo do Portfólio Pessoal e cotações de mercado.
   - 🎨 **Cores:** Paletas de 1-toque, Color Picker RGB565 e disparador de teste do Buzzer/LED.
   - 🖼️ **SD & Energia:** Upload de fotos da câmera/galeria para o MicroSD, ajuste de brilho PWM e toggles de **Modo Sleep** e **Modo Noturno**.
3. **App Nativo Flutter:** O diretório [`mobile/`](mobile/) contém a codebase completa em Flutter pronta para compilação nativa em Android ou iOS.

---

## 📂 Estrutura do Repositório

```text
minimal-monitor/
├── firmware/                        # Firmwares C++ para ESP32 (CYD e Nó Radar Wi-Fi)
│   ├── minimal_monitor/
│   │   ├── minimal_monitor.ino      # Loop principal, decodificador JPEG com alpha-blending, 14 telas e parser JSON
│   │   └── ui_theme.h               # Definições das 14 telas (SCR_0..SCR_13), pinos Buzzer/LED e paletas RGB565
│   ├── wifi_scanner/                # Firmware sem fio para ESP32-WROOM-32U (Antena Externa)
│   │   ├── wifi_scanner.ino         # Scan 2.4 GHz + mDNS (cyd-radar.local) + UDP Unicast/Broadcast (:8888/:8889)
│   │   └── platformio.ini           # Projeto PlatformIO isolado para gravação da ESP32-WROOM-32U
│   └── User_Setup.h                 # Configurações de barramento SPI e pinagem TFT_eSPI
│
├── agent/                           # Agente Desktop (PC) em Flet (Flutter), Daemon Headless e Servidor Web Mobile
│   ├── agent.py                     # Coletor Hardware + Mercado + Pomodoro + Media + GUI Flet + modo --headless
│   ├── wifi_scanner.py              # Módulo Radar Wi-Fi RF (listener UDP :8889 / comando :8890 para ESP32-WROOM-32U)
│   ├── net_analyzer.py              # Módulo Análise de Rede, Roteador/Gateway, LAN ARP e Speedtest Fibra 700 Mbps
│   ├── mobile_web.py                # Interface Web Mobile (PWA) em tempo real (SSE)
│   ├── file_version_info.txt        # Metadados de versão Windows para o executável
│   ├── requirements.txt             # Dependências Python (Flet, WinRT, Pillow, psutil, pyserial, etc.)
│   ├── ui_config.json               # Configuração persistida de telas, cores, alertas e carteira (ignorado no Git)
│   ├── CYD-Hardware-Monitor.spec    # Especificação PyInstaller para build do executável
│   └── dist/
│       └── CYD-Hardware-Monitor.exe # Executável standalone Windows pronto para uso
│
│
├── linux/                           # 🐧 Suíte Nativa para Linux (Fedora / Ubuntu / Debian)
│   ├── cyd_ctl.py                   # CLI nativo Linux (`cyd`) para trocar telas, diagnóstico de rede e controle
│   ├── run_linux.sh                 # Launcher nativo Linux (GUI ou --headless)
│   ├── cyd-cyber-deck.service       # Serviço systemd de usuário para inicialização automática em segundo plano
│   └── ...                          # Scripts auxiliares, regras udev e atalho desktop
│
├── mobile/                          # Projeto Flutter nativo para Android e iOS
│   ├── README.md                    # Instruções de compilação do APK nativo
│   ├── pubspec.yaml                 # Dependências do app Flutter
│   └── lib/                         # Código Dart (telas, modelos e serviços SSE)
│
├── preview/                         # Capturas de tela reais do Painel Desktop e da placa CYD
├── imgs/                            # Ícone oficial da aplicação (imgsCYD.ico)
├── platformio.ini                   # Manifesto de compilação PlatformIO para ESP32 (CYD)
└── README.md                        # Documentação completa do projeto
```

---

## 🐧 Como Instalar e Rodar no Ubuntu / Linux (Nativo)

O projeto possui suporte **100% nativo ao Ubuntu (22.04 LTS / 24.04 LTS+) e Debian** dentro da pasta [`linux/`](linux/), com integração **MPRIS2 / D-Bus** (Spotify & YouTube Music com capa no SD), detecção de inatividade **GNOME Mutter (Wayland & X11)**, telemetria de GPU (`amdgpu`, `nvidia-smi`, `i915`/`xe`), correção automática do conflito `brltty` com o chip CH340 e atalho na Grade de Aplicativos do Ubuntu:

```bash
# 1. Instale tudo automaticamente no Ubuntu (pacotes APT, regras udev, .venv e atalho no Menu):
chmod +x linux/*.sh
./linux/install_ubuntu.sh

# 2. Inicie o Painel Desktop Flet no Linux (ou rode em segundo plano com --headless):
./linux/run_linux.sh
./linux/run_linux.sh --headless

# 3. (Opcional) Instale como serviço automático em segundo plano (systemd --user):
mkdir -p ~/.config/systemd/user
cp linux/cyd-cyber-deck.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cyd-cyber-deck.service
```

### ⌨️ Controle pelo CLI no Linux (`cyd`)

Instale o atalho executável `cyd` no seu `PATH` (sem dependências externas — comunica-se via API local `http://127.0.0.1:8088`, configurável pela variável `CYD_API_URL`):

```bash
chmod +x linux/cyd_ctl.py
mkdir -p ~/.local/bin
ln -sf "$(pwd)/linux/cyd_ctl.py" ~/.local/bin/cyd
```

#### Comandos disponíveis

| Comando | Descrição |
| :--- | :--- |
| `cyd <0..13>` | Troca diretamente para a tela pelo número (ex.: `cyd 12`, `cyd 13`) |
| `cyd screen <alvo>` / `cyd s <alvo>` | Troca de tela por número ou apelido (`resumo`, `cpu`, `dual`, `gpu`, `graph`, `wall`, `market`, `portfolio`, `pomo`, `media`, `news`, `term`, `radar`, `net`) |
| `cyd next` / `cyd prev` | Avança ou volta para a tela seguinte/anterior (`0..13`) |
| `cyd list` | Lista todas as 14 telas disponíveis indicando qual está ativa |
| `cyd status` | Exibe resumo de Hardware, Radar Wi-Fi (ESP32-WROOM-32U) e Análise de Rede/Roteador |
| `cyd router` | Executa diagnóstico completo do roteador/gateway (IP, MAC, ping, jitter, perda, HTTP admin e DNS) |
| `cyd router --open` | Além do diagnóstico, abre a página de administração do roteador no navegador |
| `cyd lan` | Lista os dispositivos ativos na LAN via tabela ARP/vizinhos local |
| `cyd speed` | Abre a Tela 13 e dispara o Speedtest Fibra multi-stream (Download/Upload Mbps + Ping) |
| `cyd radar [--scan]` | Exibe as redes 2.4 GHz detectadas pela ESP32-WROOM-32U (`--scan` força nova varredura sem fio) |
| `cyd rf [scan\|spectrum\|audit\|diff\|status\|export]` | Executa análise RF defensiva da ESP32-WROOM-32U no Terminal CYD (Tela 11) e imprime a saída no Linux |
| `cyd rf track <filtro>` | Rastreia um AP por SSID/BSSID (RSSI atual/min/méd/máx, estabilidade dB, fabricante OUI e distância indoor) |
| `cyd diag` | Executa bateria completa `netcheck` (Gateway + Jitter + WAN + DNS + HTTP + LAN ARP + ESP32-WROOM-32U) |
| `cyd jitter [alvo]` | Mede estabilidade ICMP (10 pacotes: perda, RTT min/méd/máx, jitter em ms e classificação; aceita `gw`) |
| `cyd mtu [alvo]` | Descobre o Path MTU com bit Don't Fragment (`1500` Ethernet vs `1492` PPPoE Vivo Fibra) |
| `cyd tls <dominio>` | Inspeciona passivamente o certificado TLS/SSL (`CN`, emissor, dias restantes, versão TLS e handshake ms) |
| `cyd plan <mbps>` | Configura a velocidade contratada do plano de internet (ex.: `cyd plan 700` para Vivo Fibra 700 Mb) |
| `cyd brt <0..255>` | Ajusta o brilho PWM do display da CYD |
| `cyd color "#00FFFF"` | Altera a cor tema RGB565 da CYD em tempo real |
| `cyd cmd "<comando>"` | Executa comando no Terminal CYD (Tela 11) com retorno síncrono no terminal Linux (ex.: `cyd cmd "rf spectrum"`, `cyd cmd "oui 30:DE:4B"`, `cyd cmd "route"`) |

#### Exemplos práticos
```bash
cyd 12                  # Abre o Radar Wi-Fi RF (ESP32-WROOM-32U)
cyd screen net          # Abre a Tela 13 (Análise de Rede & Roteador)
cyd rf spectrum         # Analisa ocupação dos canais 1..13 e recomenda melhor canal (1, 6 ou 11)
cyd rf audit            # Auditoria passiva: redes OPEN, ocultas, WEP, Mesh multi-BSSID e canais cheios
cyd rf track Vivo       # Rastreia estabilidade de sinal (dBm/dB), OUI e distância indoor aproximada
cyd diag                # Bateria completa GW + Jitter + WAN + DNS + LAN + ESP32-32U na Tela 11 e no Linux
cyd jitter gw           # Testa jitter e perda de pacotes para o próprio roteador/gateway
cyd mtu 1.1.1.1         # Descobre Path MTU (ex: 1492 PPPoE Vivo Fibra vs 1500 Ethernet)
cyd tls github.com      # Inspeciona certificado TLSv1.3, validade e tempo de handshake
cyd speed               # Mede velocidade da fibra ao vivo na Tela 13
cyd router --open       # Diagnostica o gateway e abre o painel do roteador
cyd radar --scan        # Dispara varredura remota sem fio na ESP32-WROOM-32U
```

> 📖 Consulte também o guia detalhado em [`linux/README_LINUX.md`](linux/README_LINUX.md).

---

## 🚀 Como Usar e Instalar no Windows

### Opção A: Executável Pronto para Windows (Sem instalar Python)
Basta executar o binário compilado:
```powershell
.\agent\dist\CYD-Hardware-Monitor.exe
```

### Opção B: Rodando a partir do Código-Fonte Python
1. Ative o ambiente virtual e instale as dependências:
   ```powershell
   .\.venv\Scripts\pip install -r agent\requirements.txt
   ```
2. Inicie o agente com a nova interface em abas:
   ```powershell
   .\.venv\Scripts\python agent\agent.py
   ```
3. Teste rápido de payload JSON no terminal:
   ```powershell
   .\.venv\Scripts\python agent\agent.py --stdout --once
   ```

### Gravando o Firmware Atualizado na CYD (PlatformIO)
Com o cabo USB conectado à placa CYD:
```powershell
& "C:\Users\Matheus Augusto\.platformio\penv\Scripts\pio.exe" run -e cyd -t upload
```

---

## 📡 Resumo do Protocolo Serial JSON (v4.0)

O Agente envia dados via Serial a `115200 bps` no formato JSON terminado em `\n`:

```json
{
  "sys": {"cpu": 14.2, "cput": 52.0, "ram": 68.4, "gpu": 19.0, "gput": 49.0},
  "mkt": {"usd": 4.97, "usdc": -1.72, "ibov": 205083, "btc": 80508, "btcc": 0.07},
  "portf": {"tot": 15200.50, "pnl_pct": 2.50, "pnl_val": 380.00, "top3": ["BTC", "ETH", "PETR4"]},
  "pomo": {"st": "WORK", "run": true, "rem": 1425, "tot": 1500, "cyc": 2},
  "media": {
    "src": "YT MUSIC",
    "play": true,
    "tit": "Starboy",
    "art": "The Weeknd",
    "alb": "Starboy",
    "pos": 84,
    "dur": 230,
    "cov": "_media_cov.jpg",
    "cid": "a91f4c02"
  },
  "alrt": {"bz": true, "led": "0x07FF", "p": 3},
  "ui": {"screen": 9, "color": "0x07E0", "bg": "none", "brt": 200, "ticker": true}
}
```

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja o arquivo [`LICENSE`](LICENSE) para mais detalhes.

---
*Projeto idealizado, arquitetado e desenvolvido por **Matheus Ribeiro -- z1po** (`@matribeirotech`) & **[LYPSYOS Open Source Lab & Community](https://lypsyos.com)**.*
