# SYS.MONITOR_ (Minimal CYD Hardware Monitor)

Um monitor de hardware minimalista e com temática hacker (estilo terminal/Matrix) desenvolvido para o **Cheap Yellow Display (ESP32-2432S028R)**. 

Este projeto é um *fork* focado em estética cyberpunk, baixo uso de recursos e design de interface limpo. Ele se comunica com o seu PC via USB e exibe métricas em tempo real de CPU, GPU, RAM, Rede e Temperaturas.

## 🌟 Funcionalidades
- **Telas de Monitoramento Focadas:** Tela Principal (com chuva Matrix no fundo), Gráficos de Histórico e Temperaturas.
- **Temas Dinâmicos:** 
  - `TERMINAL`: Chuva matrix clássica com tons de verde neon e preto.
  - `Z1P0`: Chuva de folhas canábicas em pixel-art alternando nas cores verde, amarelo e vermelho.
- **Controle Integrado:** Ajuste o brilho da tela diretamente pelo display (salvo automaticamente na memória flash da placa) clicando na engrenagem no cabeçalho.
- **Zero Impacto:** O agente rodando no PC foi otimizado e compilado para consumir virtualmente 0% do seu processamento.

---

## 🛠️ Requisitos para Instalação

Para que qualquer pessoa consiga rodar esse projeto do zero, você vai precisar de algumas ferramentas básicas:

### 1. Preparando o Computador (Host)
Os dados (como a temperatura e o uso de CPU/GPU) são lidos por um servidor local leve antes de serem enviados para a telinha.
*   Baixe e instale o **[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)**.
*   Abra o LibreHardwareMonitor, vá em `Options` e ative o **Run Web Server**. Mude a porta para `8085`. (É dali que o nosso script vai puxar as temperaturas com segurança).
*   **Driver CH340:** O Windows precisa de um driver para reconhecer o ESP32 quando você plugar no USB. Baixe o driver CH340 da fabricante da placa e instale caso o seu PC não reconheça a plaquinha quando conectada.

### 2. Rodando o Agente (O Executável)
Você não precisa saber programar em Python! O script que coleta as informações do seu PC e manda para o USB já foi empacotado num executável leve.
*   Dentro da pasta `agent/dist/`, você vai encontrar o arquivo **`agent.exe`**.
*   Basta dar um duplo clique nele (com o LibreHardwareMonitor aberto e a placa plugada no USB) e ele começará a enviar os dados para a placa em segundo plano silenciosamente.
*   *Dica: Você pode colocar um atalho desse `agent.exe` na pasta `Inicializar` do Windows (tecle `Win + R` e digite `shell:startup`) para ele abrir sozinho quando o PC ligar.*

### 3. Instalando o Firmware na Placa (Para Desenvolvedores / Primeira Vez)
Se você quiser modificar o código da tela ou fazer o upload do firmware pela primeira vez:
1.  Instale o **VS Code**.
2.  Vá nas extensões e instale o **PlatformIO**.
3.  Abra a pasta `minimal-monitor` no VS Code. O PlatformIO vai baixar todas as bibliotecas necessárias automaticamente (`TFT_eSPI`, `ArduinoJson`).
4.  Plugue a sua tela CYD no cabo USB e clique no botão **Upload** (a setinha para a direita `→` na barra inferior do VS Code).

---
*Projeto arquitetado e escalado por Matheus Augusto & Z1P0.*

