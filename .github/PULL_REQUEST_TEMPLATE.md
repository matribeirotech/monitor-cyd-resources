## 📌 Tipo de Alteração
Selecione o tipo de contribuição que este Pull Request introduz:

- [ ] 🎨 **Nova Tela / Layout na CYD** (Adiciona uma nova tela ao firmware)
- [ ] 📈 **Mercado Financeiro / Cripto** (Novos ativos, tickers ou provedores de cotação)
- [ ] 💻 **Melhoria no Agente PC** (Interface Flet, novos sensores, otimizações)
- [ ] 🐛 **Correção de Bug** (Fix de travamento, renderização ou serial)
- [ ] 📝 **Documentação** (README, guias, pinagem ou arquitetura)
- [ ] ⚙️ **Refatoração / Infraestrutura** (CI/CD, PlatformIO, dependências)

---

## 📝 Descrição do que foi feito
Explique brevemente as mudanças implementadas, motivação e como a funcionalidade deve operar.

---

## 📸 Demonstração Visual (OBRIGATÓRIO para novas telas ou mudanças visuais)
> [!IMPORTANT]
> Se o seu PR adiciona uma nova tela (`SCR_X`), altera o layout da CYD ou modifica a interface do Agente PC, **anexe uma foto ou vídeo/GIF demonstrando o resultado real**.
> Isso garante a qualidade visual do projeto e a ausência de *flickering* no display.

- **Foto da tela física na placa CYD (320×240):**
  <!-- Arraste sua foto ou GIF aqui -->

- **Screenshot do Painel Flet no PC (se aplicável):**
  <!-- Arraste sua imagem aqui -->

---

## 📋 Checklist do Contribuidor
Antes de submeter o PR, certifique-se de que cumpriu os seguintes passos:

- [ ] Meu código segue as diretrizes do [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] **Firmware ESP32:** O código compila sem erros via `pio run -e cyd`.
- [ ] **Agente PC:** O script foi testado via `python agent/agent.py` sem erros de sintaxe ou dependências não declaradas no `requirements.txt`.
- [ ] **Nova Tela:** Se criei uma nova tela:
  - [ ] Adicionei o enum correspondente em `firmware/minimal_monitor/ui_theme.h`.
  - [ ] Implementei a função de renderização em `firmware/minimal_monitor/minimal_monitor.ino`.
  - [ ] Adicionei o botão de ação correspondente no painel Flet (`agent/agent.py`).
- [ ] O display não apresenta travamentos de watchdog nem *flickering* durante as atualizações.

---

## 🔗 Issues Relacionadas
Closes # (insira o número da issue relacionada, se houver).

