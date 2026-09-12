# CYD HARDWARE MONITOR

Um monitor de hardware moderno e customizável desenvolvido para o **Cheap Yellow Display (ESP32-2432S028R)**. 

Este projeto exibe métricas em tempo real de CPU, GPU, RAM, Disco e Temperaturas na telinha, conectado via USB. O projeto conta também com uma Interface de Controle no PC (Python GUI) que opera na bandeja do sistema (system tray).

## 🌟 Funcionalidades
- **Painel de Controle no PC:** Interface gráfica em Python para gerenciar a tela em tempo real, sem precisar mexer nela fisicamente.
- **Segundo Plano Otimizado:** O programa roda oculto na bandeja de ícones (system tray) do Windows, enviando telemetria em tempo real com uso quase zero de CPU.
- **Temas Dinâmicos e Animados:** 
  - `TERMINAL`: Visual minimalista estilo prompt de comando hacker.
  - `Z1P0`: Chuva estática de folhas canábicas em pixel-art.
  - `SD GIF`: Reproduz um GIF animado (background.gif) hospedado direto do seu Cartão SD ao fundo dos dados.
  - `HEAVY METAL`: Um slideshow super estilizado com imagens pré-configuradas carregado do SD card.
- **Cores Customizáveis:** Escolha a cor principal pelo Painel de Controle (Verde, Ciano, Laranja, Magenta, Vermelho) e todo o sistema será repintado instantaneamente!
- **Transferência de GIFs In-App:** Selecione qualquer GIF no seu computador e envie diretamente para o Cartão SD da placa através do cabo USB, direto pelo nosso Painel!
- **Controle Integrado Remoto:** Ajuste o brilho e mude telas ou temas na plaquinha tanto pela própria tela touch quanto pelo Painel no PC.

---

## 🛠️ Requisitos para Instalação

Para que qualquer pessoa consiga rodar esse projeto do zero, você vai precisar de algumas ferramentas básicas:

### 1. Preparando o Computador (Host)
Os dados (como a temperatura e o uso de CPU/GPU) são lidos por um servidor local leve antes de serem enviados para a telinha.
*   Baixe e instale o **[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)**.
*   Abra o LibreHardwareMonitor, vá em `Options` e ative o **Run Web Server**. Mude a porta para `8085`. (É dali que o nosso script vai puxar as temperaturas com segurança).
*   **Driver CH340:** O Windows precisa de um driver para reconhecer o ESP32 quando você plugar no USB. Baixe e instale caso o seu PC não reconheça a plaquinha.

### 2. Rodando o Painel de Controle (O Agente)
Você não precisa saber programar em Python! O script que coleta as informações do seu PC e manda para o USB já foi empacotado num executável leve.
*   Dentro da pasta `agent/dist/`, você vai encontrar o arquivo **`CYD-Hardware-Monitor.exe`**.
*   Basta dar um duplo clique nele (com o LibreHardwareMonitor aberto e a placa plugada no USB) e o Painel de Controle se abrirá.
*   Quando você fechar no X, ele apenas se minimizará para a bandeja do sistema perto do relógio (ícone verde), onde continuará enviando a telemetria silenciosamente!
*   (Use o botão direito no ícone para reabrir o painel ou sair de vez).

*(Alternativa para desenvolvedores: Instale `pyserial requests psutil pystray pillow` e rode `python agent.py`)*

### 3. Instalando o Firmware na Placa (Para Desenvolvedores / Primeira Vez)
Se você quiser modificar o código da tela ou fazer o upload do firmware pela primeira vez:
1.  Instale o **VS Code**.
2.  Vá nas extensões e instale o **PlatformIO**.
3.  Abra a pasta do projeto no VS Code. O PlatformIO vai baixar todas as bibliotecas necessárias automaticamente (`TFT_eSPI`, `ArduinoJson`, `AnimatedGIF`, etc.).
4.  Plugue a sua tela CYD no cabo USB (lembre-se de inserir um Cartão SD formatado em FAT32 caso queira usar os temas de GIF).
5.  Clique no botão **Upload** (a setinha para a direita `→` na barra inferior do VS Code).

---
*Projeto arquitetado e escalado por Matheus Augusto & Z1P0.*

