# CYD HARDWARE MONITOR

Um monitor de hardware moderno e customizável desenvolvido para o **Cheap Yellow Display (ESP32-2432S028R)**. 

Este projeto exibe métricas em tempo real de CPU, GPU, RAM, Disco e Temperaturas na telinha, conectado via USB. O projeto conta também com uma Interface de Controle no PC (Python GUI) que opera na bandeja do sistema (system tray).

## 🌟 Funcionalidades
- **Painel de Controle Total em Flet (Flutter):** Interface gráfica moderna no PC construída com **Flet**, permitindo gerenciar 100% da tela em tempo real sem depender de touch físico na placa.
- **Telas Dedicadas (Hardware + Mercado Financeiro):**
  - `Tela 0: Resumo Gauges` — Medidores circulares suaves de CPU & RAM + Disco e Rede.
  - `Tela 1: Painel CPU + RAM (Principal)` — Barras segmentadas + Gráficos de uso de CPU (%) e uso de RAM (%) lado a lado.
  - `Tela 2: Gráfico Duplo CPU vs RAM` — Curvas de uso de CPU (%) e uso de RAM (%) sobrepostas no mesmo gráfico grande.
  - `Tela 3: GPU Focus` — Carga da GPU, Temperatura, VRAM, Watts/FPS e Gráfico de GPU.
  - `Tela 4: 4x Gráficos` — Monitoramento simultâneo de CPU %, RAM %, GPU % e TEMP °C.
  - `Tela 5: Wallpaper HUD` — Destaque para a imagem de fundo do Cartão SD + Dock compacto.
  - `Tela 6: Mercado Financeiro & Bolsa (Cripto + Câmbio + B3)` — Terminal financeiro ininterrupto com **Dólar (USD/BRL)**, **Euro (EUR/BRL)**, **IBOVESPA (B3)**, **Top 5 Criptomoedas (`BTC`, `ETH`, `SOL`, `BNB`, `XRP`)** e **Gráfico Sparkline 24h do Bitcoin**.
- **Letreiro Infinito da Bolsa (Ticker Tape) nas Telas de Hardware:** Uma fita estilo painel de LED da Bolsa de Valores (`y=222..239`, renderizada via `TFT_eSprite` a ~28 FPS sem piscar) corre continuamente no rodapé das telas principais exibindo **USD/BRL**, **EUR/BRL**, **BTC ($ e R$)**, **ETH**, **SOL**, **BNB**, **XRP**, **IBOV** e **S&P 500** com variações em verde/vermelho enquanto você monitora o hardware.
- **Estúdio de Cores RGB565 em Tempo Real:** Escolha qualquer cor usando Swatches Neon, código HEX (`#RRGGBB`) ou Sliders RGB no painel Flet e repinte toda a interface da CYD instantaneamente.
- **Fundos Estáticos (JPG/BMP) e Animados (GIF) no Cartão SD:** Selecione qualquer imagem no seu PC e envie diretamente para o Cartão SD da CYD pelo cabo USB (com redimensionamento e conversão automática para `320x240` JPEG Baseline).
- **Controle de Brilho PWM Instantâneo:** Slider de brilho (`0-255`) com envio *event-driven* de baixa latência.

---

## 🛠️ Requisitos para Instalação

Para que qualquer pessoa consiga rodar esse projeto do zero, você vai precisar de algumas ferramentas básicas:

### 1. Preparando o Computador (Host)
Os dados (como a temperatura e o uso de CPU/GPU) são lidos por um servidor local leve antes de serem enviados para a telinha.
*   Baixe e instale o **[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)**.
*   Abra o LibreHardwareMonitor, vá em `Options` e ative o **Run Web Server**. Mude a porta para `8085`. (É dali que o nosso script vai puxar as temperaturas com segurança).
*   **Driver CH340:** O Windows precisa de um driver para reconhecer o ESP32 quando você plugar no USB. Baixe e instale caso o seu PC não reconheça a plaquinha.

### 2. Rodando o Painel de Controle em Flet (O Agente)
Com o ambiente virtual configurado na raiz do projeto (`.venv`):
```powershell
.\.venv\Scripts\python agent\agent.py
```
*(Ou instale as dependências de `agent/requirements.txt`: `flet pyserial psutil Pillow pystray`).*

### 3. Instalando o Firmware na Placa (PlatformIO)
Se você quiser modificar o código da tela ou fazer o upload do firmware:
1.  Instale o **VS Code** com a extensão **PlatformIO**.
2.  Abra a pasta do projeto no VS Code. O PlatformIO baixará automaticamente todas as bibliotecas (`TFT_eSPI`, `ArduinoJson`, `TJpg_Decoder`, `AnimatedGIF`).
3.  Plugue a sua tela CYD no cabo USB (insira um Cartão SD formatado em FAT32 para armazenar os wallpapers `.jpg` / `.bmp` / `.gif`).
4.  Clique em **Upload** (`pio run -t upload`).

---
*Projeto arquitetado e escalado por Matheus Augusto & Z1P0.*

