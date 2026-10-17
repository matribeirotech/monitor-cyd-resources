# 🤝 Guia de Contribuição (Contributing Guide)

Obrigado pelo seu interesse em contribuir para o **CYD Hardware & Financial Market Monitor**! Este guia foi criado para ajudar qualquer desenvolvedor (C++/ESP32 ou Python/Flet) a configurar o ambiente rapidamente e enviar contribuições limpas.

---

## 🛠️ 1. Configurando o Ambiente de Desenvolvimento

### Agente PC (Python + Flet)
1. Clone o seu fork do repositório:
   ```bash
   git clone https://github.com/SEU-USUARIO/minimal-monitor.git
   cd minimal-monitor
   ```
2. Crie um ambiente virtual `.venv` na raiz do projeto e instale as dependências:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r agent\requirements.txt
   ```
3. Teste a coleta de telemetria + mercado financeiro via linha de comando:
   ```powershell
   .\.venv\Scripts\python agent\agent.py --stdout --once
   ```
4. Execute a interface gráfica Flet:
   ```powershell
   .\.venv\Scripts\python agent\agent.py
   ```

### Firmware ESP32 (PlatformIO)
1. Instale o **VS Code** + extensão **PlatformIO IDE**.
2. Compile o firmware para validar que não há erros de sintaxe ou estouro de memória:
   ```powershell
   pio run -e cyd
   ```

---

## 🎨 2. Como Criar uma Nova Tela (Layout) na Placa CYD

Adicionar uma nova tela ao projeto envolve apenas **3 passos simples**:

### Passo A: Definir a constante em `firmware/minimal_monitor/ui_theme.h`
1. Incremente o total de telas em `#define SCREENS`:
   ```cpp
   #define SCREENS          8
   // ...
   #define SCR_MINHA_TELA   7
   ```

### Passo B: Implementar o desenho em `firmware/minimal_monitor/minimal_monitor.ino`
Cada tela é dividida em duas funções para **evitar que a tela pisque (*anti-flicker*)**:
- `screenMinhaTelaStatic()`: Chamada **apenas uma vez** quando o usuário entra na tela ou muda a cor/wallpaper. Desenha o fundo (`renderBackground()`), o cabeçalho (`drawHeader()`) e as molduras dos cards (`drawModernCard(x, y, w, h, "TITULO")`).
- `screenMinhaTelaDynamic()`: Chamada a cada `250ms` para atualizar apenas os números, barras (`drawModernBar`) e gráficos (`plotGraph`).

> ⚠️ **Regra de Ouro das Coordenadas (320×240):**
> - O Cabeçalho ocupa `y = 0` até `y = 23` (`HDR_H = 24`).
> - O Letreiro Infinito da Bolsa (*Ticker Tape*) ocupa `y = 222` até `y = 239` (`TICKER_Y = 222`).
> - Portanto, desenhe os seus cards dentro da área útil vertical **`y = 26` até `y = 220`**.

Por fim, adicione sua tela nos `if/else` de `needFullDraw` e `lastRefresh` dentro da função `loop()`.

### Passo C: Adicionar o botão no Painel Flet (`agent/agent.py`)
Na lista `screen_defs` dentro de `launch_flet_gui()` em `agent/agent.py`, adicione a tupla da nova tela:
```python
(7, "Tela 7: Minha Nova Tela", "Descrição curta do que a tela exibe", "STAR"),
```

---

## 📈 3. Como Adicionar Novas Cotações ou Sensores

1. **No Agente Python (`agent/agent.py`):**
   - Para métricas de hardware (CPU/GPU/RAM/Disco/Rede), adicione o campo no método `Collector.sample_sys()`.
   - Para ativos do mercado financeiro (novas criptomoedas, ações da B3 ou moedas), adicione no método `MarketCollector.fetch_once()`.
2. **No Firmware ESP32 (`firmware/minimal_monitor/minimal_monitor.ino`):**
   - Adicione a variável correspondente em `struct Stats st` ou `struct MarketStats mkt`.
   - Leia a chave JSON dentro da função `applyJson(const char *json)`.

---

## 📦 4. Gerando o Executável Standalone (`.exe`)

Se você alterou o `agent/agent.py` e deseja atualizar o executável standalone do Windows:

```powershell
.\.venv\Scripts\flet.exe pack agent\agent.py -n CYD-Hardware-Monitor --distpath agent\dist --hidden-import serial --hidden-import serial.tools.list_ports --hidden-import psutil --hidden-import wmi --hidden-import win32com.client --hidden-import PIL --product-name "CYD Hardware Monitor" -y
```

---

## ✅ 5. Checklist antes de abrir um Pull Request

- [ ] O firmware compila sem erros (`pio run -e cyd`).
- [ ] O agente Python executa sem erros (`.\.venv\Scripts\python agent\agent.py --stdout --once`).
- [ ] Nenhum arquivo temporário de compilação (`.pio/`, `.venv/`, `build/`, `__pycache__/`) foi incluído no commit.
- [ ] A descrição do Pull Request explica claramente o que foi adicionado ou corrigido (se possível, inclua uma foto da tela CYD ou print do painel Flet!).

