# -*- coding: utf-8 -*-
"""
mobile_web.py - Interface Web Mobile (PWA) de Alta Performance para o CYD Hardware Monitor.
Fornece controle 100% equivalente ao aplicativo Desktop diretamente de qualquer smartphone
(Android ou iOS) conectado a mesma rede Wi-Fi local, com zero instalacao.
"""

HTML_MOBILE_APP = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="theme-color" content="#07090E">
  <title>CYD Mobile Controller</title>
  <style>
    :root {
      --accent: #00FF00;
      --accent-glow: rgba(0, 255, 0, 0.28);
      --bg: #07090E;
      --card-bg: #0F141F;
      --card-active: #162032;
      --card-border: #1E2738;
      --text: #F1F5F9;
      --text-dim: #94A3B8;
      --text-muted: #64748B;
      --danger: #EF4444;
      --success: #22C55E;
      --warning: #F59E0B;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
      user-select: none;
    }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      padding: 14px 14px 85px 14px;
      min-height: 100vh;
      overflow-x: hidden;
      overflow-y: auto;
    }
    /* Top Bar */
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--card-border);
    }
    .topbar-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .topbar-icon {
      font-size: 22px;
      line-height: 1;
    }
    .topbar-title {
      font-size: 16px;
      font-weight: 800;
      letter-spacing: 0.5px;
      color: var(--accent);
      transition: color 0.3s;
    }
    .topbar-sub {
      font-size: 11px;
      color: var(--text-dim);
    }
    .status-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      background: #111622;
      border: 1px solid var(--card-border);
      padding: 5px 10px;
      border-radius: 20px;
      font-size: 11px;
      font-family: monospace;
      font-weight: 600;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--warning);
      box-shadow: 0 0 8px var(--warning);
      transition: background 0.3s, box-shadow 0.3s;
    }
    .status-dot.online {
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
    }

    /* Tabs Container */
    .tab-content {
      display: none;
      animation: fadeIn 0.25s ease-out;
    }
    .tab-content.active {
      display: block;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Section Title */
    .sec-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin: 12px 0 10px 0;
    }
    .sec-title {
      font-size: 12px;
      font-weight: 800;
      color: var(--text-dim);
      letter-spacing: 0.8px;
      text-transform: uppercase;
    }

    /* Screen Selector Grid */
    .screen-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }
    .screen-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 14px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      position: relative;
      overflow: hidden;
    }
    .screen-card:active {
      transform: scale(0.98);
    }
    .screen-card.active {
      background: var(--card-active);
      border: 2px solid var(--accent);
      box-shadow: 0 0 16px var(--accent-glow);
    }
    .sc-info {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .sc-icon {
      font-size: 26px;
      line-height: 1;
      width: 38px;
      text-align: center;
    }
    .sc-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 2px;
    }
    .screen-card.active .sc-title {
      color: var(--accent);
    }
    .sc-desc {
      font-size: 11px;
      color: var(--text-dim);
      line-height: 1.3;
      max-width: 220px;
    }
    .sc-badge {
      font-size: 10px;
      font-weight: 800;
      padding: 4px 8px;
      border-radius: 8px;
      background: #1A2234;
      color: var(--text-dim);
      font-family: monospace;
      letter-spacing: 0.5px;
    }
    .screen-card.active .sc-badge {
      background: var(--accent);
      color: #05070A;
      box-shadow: 0 0 10px var(--accent);
    }

    /* Cores / RGB Studio */
    .color-preview-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;
    }
    .cp-swatch {
      width: 54px;
      height: 54px;
      border-radius: 12px;
      border: 2px solid #FFFFFF33;
      box-shadow: 0 0 16px var(--accent-glow);
      transition: all 0.3s;
    }
    .cp-info {
      flex: 1;
      margin-left: 14px;
    }
    .cp-hex {
      font-size: 18px;
      font-weight: 800;
      font-family: monospace;
      color: var(--text);
    }
    .cp-rgb565 {
      font-size: 12px;
      color: var(--text-dim);
      font-family: monospace;
    }
    .color-presets-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-bottom: 16px;
    }
    .preset-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 10px 4px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .preset-btn:active {
      transform: scale(0.95);
    }
    .preset-dot {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      border: 1px solid #FFFFFF44;
    }
    .preset-label {
      font-size: 10px;
      font-weight: 600;
      color: var(--text-dim);
    }
    .slider-group {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 12px;
    }
    .slider-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin: 8px 0;
    }
    .slider-label {
      width: 20px;
      font-size: 12px;
      font-weight: 800;
      font-family: monospace;
    }
    .slider-val {
      width: 32px;
      font-size: 11px;
      font-family: monospace;
      color: var(--text-dim);
      text-align: right;
    }
    input[type=range] {
      flex: 1;
      height: 8px;
      border-radius: 4px;
      outline: none;
      -webkit-appearance: none;
      background: #1A2234;
    }
    input[type=range]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: var(--accent);
      cursor: pointer;
      box-shadow: 0 0 8px var(--accent);
    }

    /* Metricas e Mercado */
    .metrics-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 12px;
    }
    .metric-title {
      font-size: 11px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }
    .metric-value {
      font-size: 20px;
      font-weight: 900;
      color: var(--accent);
      font-family: monospace;
    }
    .metric-sub {
      font-size: 11px;
      color: var(--text-dim);
      margin-top: 2px;
    }
    .bar-bg {
      width: 100%;
      height: 4px;
      background: #1A2234;
      border-radius: 2px;
      margin-top: 8px;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      background: var(--accent);
      width: 0%;
      transition: width 0.4s ease;
    }

    /* Mercado Financeiro */
    .market-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 12px;
    }
    .market-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 10px;
    }
    .fin-pill {
      background: #07090E;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 8px 10px;
    }
    .fin-sym {
      font-size: 10px;
      font-weight: 800;
      color: var(--text-muted);
    }
    .fin-price {
      font-size: 13px;
      font-weight: 800;
      font-family: monospace;
      color: var(--text);
      margin: 2px 0;
    }
    .fin-chg {
      font-size: 10px;
      font-weight: 700;
      font-family: monospace;
    }
    .chg-pos { color: var(--success); }
    .chg-neg { color: var(--danger); }

    /* SD Card & Brilho */
    .action-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 14px;
    }
    .select-dropdown {
      width: 100%;
      background: #07090E;
      color: var(--text);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 12px;
      font-size: 13px;
      outline: none;
      margin-bottom: 10px;
      font-family: monospace;
    }
    .btn-row {
      display: flex;
      gap: 8px;
    }
    .btn {
      flex: 1;
      background: var(--accent);
      color: #05070A;
      font-weight: 800;
      font-size: 12px;
      padding: 12px;
      border-radius: 10px;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn:active {
      transform: scale(0.97);
    }
    .btn-secondary {
      background: #1A2234;
      color: var(--text);
      border: 1px solid var(--card-border);
    }
    .upload-box {
      border: 2px dashed #1E2738;
      border-radius: 12px;
      padding: 16px;
      text-align: center;
      margin-top: 10px;
      cursor: pointer;
      background: #07090E;
    }
    .upload-icon {
      font-size: 28px;
      margin-bottom: 6px;
    }
    .upload-text {
      font-size: 12px;
      font-weight: 700;
      color: var(--text-dim);
    }
    .upload-sub {
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 2px;
    }
    #fileInput {
      display: none;
    }
    .progress-bar-wrap {
      margin-top: 10px;
      display: none;
    }
    .progress-status {
      font-size: 11px;
      color: var(--text-dim);
      margin-bottom: 4px;
      display: flex;
      justify-content: space-between;
    }

    /* Brilho Quick Presets */
    .brt-presets {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 6px;
      margin-top: 10px;
    }
    .brt-btn {
      background: #1A2234;
      border: 1px solid var(--card-border);
      color: var(--text-dim);
      padding: 8px;
      border-radius: 8px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      text-align: center;
    }
    .brt-btn:active {
      background: var(--accent);
      color: #000;
    }

    /* Bottom Navigation */
    .bottom-nav {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      height: 64px;
      background: rgba(10, 14, 22, 0.95);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-top: 1px solid var(--card-border);
      display: flex;
      z-index: 1000;
      padding-bottom: env(safe-area-inset-bottom);
    }
    .nav-item {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
      color: var(--text-muted);
      cursor: pointer;
      transition: color 0.2s;
    }
    .nav-item.active {
      color: var(--accent);
    }
    .nav-icon {
      font-size: 20px;
      line-height: 1;
    }
    .nav-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.3px;
    }

    /* Toast Notification */
    .toast {
      position: fixed;
      top: 18px;
      left: 50%;
      transform: translateX(-50%) translateY(-60px);
      background: #162032;
      border: 1px solid var(--accent);
      box-shadow: 0 4px 20px rgba(0,0,0,0.5);
      color: var(--text);
      padding: 10px 18px;
      border-radius: 25px;
      font-size: 12px;
      font-weight: 700;
      z-index: 2000;
      opacity: 0;
      pointer-events: none;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .toast.show {
      transform: translateX(-50%) translateY(0);
      opacity: 1;
    }
  </style>
</head>
<body>

  <!-- Top Bar -->
  <div class="topbar">
    <div class="topbar-left">
      <div class="topbar-icon">⚡</div>
      <div>
        <div class="topbar-title" id="txtTitle">CYD CONTROLLER</div>
        <div class="topbar-sub">ESP32-2432S028R &bull; Wi-Fi Remote</div>
      </div>
    </div>
    <div class="status-badge">
      <div class="status-dot online" id="statusDot"></div>
      <span id="statusTxt">CONECTADO</span>
    </div>
  </div>

  <!-- Toast -->
  <div class="toast" id="toastBox">
    <span id="toastIcon">✔</span>
    <span id="toastMsg">Tela alterada com sucesso!</span>
  </div>

  <!-- ================= TAB 1: TELAS ================= -->
  <div class="tab-content active" id="tab-screens">
    <div class="sec-header">
      <div class="sec-title">SELECIONE A TELA DA CYD (0 a 6)</div>
    </div>
    <div class="screen-grid">
      <div class="screen-card active" data-screen="0" onclick="selectScreen(0)">
        <div class="sc-info">
          <div class="sc-icon">⚡</div>
          <div>
            <div class="sc-title">Tela 0: Resumo Gauges</div>
            <div class="sc-desc">Gauges circulares de CPU & RAM + Disco/Rede + Letreiro da Bolsa</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-0">ATIVO</div>
      </div>

      <div class="screen-card" data-screen="1" onclick="selectScreen(1)">
        <div class="sc-info">
          <div class="sc-icon">🖥️</div>
          <div>
            <div class="sc-title">Tela 1: CPU + RAM Principal</div>
            <div class="sc-desc">Barras duplas + Gráficos de histórico lado a lado + Letreiro</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-1">ATIVAR</div>
      </div>

      <div class="screen-card" data-screen="2" onclick="selectScreen(2)">
        <div class="sc-info">
          <div class="sc-icon">📈</div>
          <div>
            <div class="sc-title">Tela 2: Gráfico Duplo</div>
            <div class="sc-desc">Curvas de Uso de CPU % e RAM % sobrepostas + Letreiro</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-2">ATIVAR</div>
      </div>

      <div class="screen-card" data-screen="3" onclick="selectScreen(3)">
        <div class="sc-info">
          <div class="sc-icon">🎮</div>
          <div>
            <div class="sc-title">Tela 3: GPU Focus</div>
            <div class="sc-desc">Gauge grande de GPU + VRAM + Watts/FPS + Letreiro da Bolsa</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-3">ATIVAR</div>
      </div>

      <div class="screen-card" data-screen="4" onclick="selectScreen(4)">
        <div class="sc-info">
          <div class="sc-icon">📊</div>
          <div>
            <div class="sc-title">Tela 4: 4x Gráficos</div>
            <div class="sc-desc">Grid em tempo real: CPU %, RAM %, GPU % e TEMP °C</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-4">ATIVAR</div>
      </div>

      <div class="screen-card" data-screen="5" onclick="selectScreen(5)">
        <div class="sc-info">
          <div class="sc-icon">🖼️</div>
          <div>
            <div class="sc-title">Tela 5: Wallpaper HUD</div>
            <div class="sc-desc">Destaque total para imagem do Cartão SD + Dock CPU/RAM</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-5">ATIVAR</div>
      </div>

      <div class="screen-card" data-screen="6" onclick="selectScreen(6)">
        <div class="sc-info">
          <div class="sc-icon">💰</div>
          <div>
            <div class="sc-title">Tela 6: Mercado Financeiro</div>
            <div class="sc-desc">Dólar, Euro, B3, Top 5 Criptos + Gráfico Bitcoin 24h</div>
          </div>
        </div>
        <div class="sc-badge" id="badge-6">ATIVAR</div>
      </div>
    </div>
  </div>

  <!-- ================= TAB 2: CORES RGB565 ================= -->
  <div class="tab-content" id="tab-colors">
    <div class="sec-header">
      <div class="sec-title">ESTÚDIO DE CORES EM TEMPO REAL</div>
    </div>

    <div class="color-preview-box">
      <div class="cp-swatch" id="colorSwatch"></div>
      <div class="cp-info">
        <div class="cp-hex" id="txtHex">#00FF00</div>
        <div class="cp-rgb565" id="txtRgb565">RGB565: 0x07E0</div>
      </div>
      <input type="color" id="nativeColorPicker" value="#00FF00" onchange="applyHex(this.value)" style="width:40px; height:40px; border:none; background:none; cursor:pointer;">
    </div>

    <div class="sec-header">
      <div class="sec-title">PALETAS PRONTAS (1-TOQUE)</div>
    </div>
    <div class="color-presets-grid">
      <div class="preset-btn" onclick="applyHex('#00FF00')">
        <div class="preset-dot" style="background:#00FF00; box-shadow:0 0 6px #00FF00;"></div>
        <div class="preset-label">Matrix</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#00F0FF')">
        <div class="preset-dot" style="background:#00F0FF; box-shadow:0 0 6px #00F0FF;"></div>
        <div class="preset-label">Neon</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#FF5500')">
        <div class="preset-dot" style="background:#FF5500; box-shadow:0 0 6px #FF5500;"></div>
        <div class="preset-label">Chama</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#FF007F')">
        <div class="preset-dot" style="background:#FF007F; box-shadow:0 0 6px #FF007F;"></div>
        <div class="preset-label">Cyber</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#9D00FF')">
        <div class="preset-dot" style="background:#9D00FF; box-shadow:0 0 6px #9D00FF;"></div>
        <div class="preset-label">Synth</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#0088FF')">
        <div class="preset-dot" style="background:#0088FF; box-shadow:0 0 6px #0088FF;"></div>
        <div class="preset-label">Elétrico</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#FFD700')">
        <div class="preset-dot" style="background:#FFD700; box-shadow:0 0 6px #FFD700;"></div>
        <div class="preset-label">Ouro</div>
      </div>
      <div class="preset-btn" onclick="applyHex('#FFFFFF')">
        <div class="preset-dot" style="background:#FFFFFF; box-shadow:0 0 6px #FFFFFF;"></div>
        <div class="preset-label">Neve</div>
      </div>
    </div>

    <div class="sec-header">
      <div class="sec-title">AJUSTE FINO (R / G / B)</div>
    </div>
    <div class="slider-group">
      <div class="slider-row">
        <span class="slider-label" style="color:#EF4444;">R</span>
        <input type="range" id="sliderR" min="0" max="255" value="0" oninput="onRgbSlider()">
        <span class="slider-val" id="valR">0</span>
      </div>
      <div class="slider-row">
        <span class="slider-label" style="color:#22C55E;">G</span>
        <input type="range" id="sliderG" min="0" max="255" value="255" oninput="onRgbSlider()">
        <span class="slider-val" id="valG">255</span>
      </div>
      <div class="slider-row">
        <span class="slider-label" style="color:#3B82F6;">B</span>
        <input type="range" id="sliderB" min="0" max="255" value="0" oninput="onRgbSlider()">
        <span class="slider-val" id="valB">0</span>
      </div>
    </div>
  </div>

  <!-- ================= TAB 3: MÉTRICAS & MERCADO ================= -->
  <div class="tab-content" id="tab-metrics">
    <div class="sec-header">
      <div class="sec-title">TELEMETRIA DO COMPUTADOR AO VIVO</div>
    </div>
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-title">CPU</div>
        <div class="metric-value" id="mCpuVal">0%</div>
        <div class="metric-sub" id="mCpuSub">-- °C</div>
        <div class="bar-bg"><div class="bar-fill" id="mCpuBar"></div></div>
      </div>
      <div class="metric-card">
        <div class="metric-title">MEMÓRIA RAM</div>
        <div class="metric-value" id="mRamVal">0%</div>
        <div class="metric-sub" id="mRamSub">-- / -- GB</div>
        <div class="bar-bg"><div class="bar-fill" id="mRamBar"></div></div>
      </div>
      <div class="metric-card">
        <div class="metric-title">GPU</div>
        <div class="metric-value" id="mGpuVal">0%</div>
        <div class="metric-sub" id="mGpuSub">-- °C</div>
        <div class="bar-bg"><div class="bar-fill" id="mGpuBar"></div></div>
      </div>
      <div class="metric-card">
        <div class="metric-title">DISCO & REDE</div>
        <div class="metric-value" id="mDskVal">0%</div>
        <div class="metric-sub" id="mNetSub">↓0.0 ↑0.0 MB/s</div>
        <div class="bar-bg"><div class="bar-fill" id="mDskBar"></div></div>
      </div>
    </div>

    <div class="sec-header">
      <div class="sec-title">MERCADO FINANCEIRO & CRIPTO</div>
    </div>
    <div class="market-card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:11px; color:var(--text-dim);" id="mMktStatus">Cripto: Ao Vivo (Coinbase / 3s)</span>
        <span style="font-size:10px; font-family:monospace; color:var(--text-muted);" id="mMktTime">--:--:--</span>
      </div>

      <div class="market-grid">
        <div class="fin-pill">
          <div class="fin-sym">USD / BRL</div>
          <div class="fin-price" id="fUsd">R$ --</div>
          <div class="fin-chg" id="fUsdC">--%</div>
        </div>
        <div class="fin-pill">
          <div class="fin-sym">EUR / BRL</div>
          <div class="fin-price" id="fEur">R$ --</div>
          <div class="fin-chg" id="fEurC">--%</div>
        </div>
        <div class="fin-pill">
          <div class="fin-sym">IBOVESPA</div>
          <div class="fin-price" id="fIbov">-- pts</div>
          <div class="fin-chg" id="fIbovC">--%</div>
        </div>
        <div class="fin-pill">
          <div class="fin-sym">BITCOIN (BTC)</div>
          <div class="fin-price" id="fBtc">$ --</div>
          <div class="fin-chg" id="fBtcC">--%</div>
        </div>
        <div class="fin-pill">
          <div class="fin-sym">ETHEREUM (ETH)</div>
          <div class="fin-price" id="fEth">$ --</div>
          <div class="fin-chg" id="fEthC">--%</div>
        </div>
        <div class="fin-pill">
          <div class="fin-sym">SOLANA (SOL)</div>
          <div class="fin-price" id="fSol">$ --</div>
          <div class="fin-chg" id="fSolC">--%</div>
        </div>
      </div>

      <div style="margin-top:14px; display:flex; gap:8px;">
        <button class="btn btn-secondary" id="btnToggleTicker" onclick="toggleTicker()" style="font-size:11px;">
          Ticker na CYD: LIGADO
        </button>
      </div>
    </div>
  </div>

  <!-- ================= TAB 4: SD CARD & BRILHO ================= -->
  <div class="tab-content" id="tab-sd">
    <div class="sec-header">
      <div class="sec-title">FUNDO DE TELA (CARTÃO MICROSD)</div>
    </div>
    <div class="action-card">
      <select class="select-dropdown" id="selBg">
        <option value="none">none (Fundo Preto Padrão)</option>
        <option value="terminal">terminal (Estilo Hacker)</option>
        <option value="z1p0">z1p0 (Mascote)</option>
      </select>

      <div class="btn-row">
        <button class="btn" onclick="applySelectedBg()">⚡ Aplicar Fundo</button>
        <button class="btn btn-secondary" onclick="refreshSdFiles()">🔄 Ler SD</button>
      </div>

      <div class="sec-header" style="margin-top:16px;">
        <div class="sec-title">ENVIAR FOTO DO CELULAR P/ CYD</div>
      </div>

      <div class="upload-box" onclick="document.getElementById('fileInput').click()">
        <div class="upload-icon">📸</div>
        <div class="upload-text">Tirar Foto ou Escolher da Galeria</div>
        <div class="upload-sub">Redimensionamento automático 320x240 otimizado</div>
      </div>
      <input type="file" id="fileInput" accept="image/*" onchange="onFileSelected(this)">

      <div class="progress-bar-wrap" id="progWrap">
        <div class="progress-status">
          <span id="progLabel">Enviando imagem...</span>
          <span id="progPct">0%</span>
        </div>
        <div class="bar-bg"><div class="bar-fill" id="progFill"></div></div>
      </div>
    </div>

    <div class="sec-header">
      <div class="sec-title">BRILHO DO DISPLAY (PWM - PINO 21)</div>
    </div>
    <div class="action-card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:12px; color:var(--text-dim);">Ajuste Backlight:</span>
        <span style="font-size:14px; font-weight:800; font-family:monospace; color:var(--accent);" id="lblBrtVal">78% (200/255)</span>
      </div>
      <input type="range" id="sliderBrt" min="10" max="255" value="200" oninput="onBrtSlider(this.value)">

      <div class="brt-presets">
        <div class="brt-btn" onclick="setBrt(64)">25%</div>
        <div class="brt-btn" onclick="setBrt(128)">50%</div>
        <div class="brt-btn" onclick="setBrt(204)">80%</div>
        <div class="brt-btn" onclick="setBrt(255)">100%</div>
      </div>
    </div>
  </div>

  <!-- ================= BOTTOM NAVIGATION ================= -->
  <div class="bottom-nav">
    <div class="nav-item active" onclick="switchTab('screens', this)">
      <div class="nav-icon">📺</div>
      <div class="nav-label">Telas</div>
    </div>
    <div class="nav-item" onclick="switchTab('colors', this)">
      <div class="nav-icon">🎨</div>
      <div class="nav-label">Cores</div>
    </div>
    <div class="nav-item" onclick="switchTab('metrics', this)">
      <div class="nav-icon">📊</div>
      <div class="nav-label">Métricas</div>
    </div>
    <div class="nav-item" onclick="switchTab('sd', this)">
      <div class="nav-icon">🖼️</div>
      <div class="nav-label">SD & Brilho</div>
    </div>
  </div>

  <script>
    let appState = {
      screen: 1,
      hex_color: "#00FF00",
      color: "0x07E0",
      bg: "none",
      brt: 200,
      ticker: true,
      sd_files: ["none", "terminal", "z1p0"]
    };

    function vibrate(ms = 18) {
      if (window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(ms);
      }
    }

    function showToast(msg, icon = "✔") {
      const box = document.getElementById("toastBox");
      document.getElementById("toastMsg").innerText = msg;
      document.getElementById("toastIcon").innerText = icon;
      box.classList.add("show");
      setTimeout(() => box.classList.remove("show"), 2200);
    }

    function switchTab(tabId, el) {
      vibrate(12);
      document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
      const target = document.getElementById("tab-" + tabId);
      if (target) target.classList.add("active");
      if (el) el.classList.add("active");
    }

    function setAccentColor(hex) {
      document.documentElement.style.setProperty("--accent", hex);
      const r = parseInt(hex.slice(1,3), 16) || 0;
      const g = parseInt(hex.slice(3,5), 16) || 0;
      const b = parseInt(hex.slice(5,7), 16) || 0;
      document.documentElement.style.setProperty("--accent-glow", `rgba(${r}, ${g}, ${b}, 0.35)`);
      document.getElementById("colorSwatch").style.backgroundColor = hex;
      document.getElementById("txtHex").innerText = hex.toUpperCase();
      document.getElementById("nativeColorPicker").value = hex;
      document.getElementById("sliderR").value = r;
      document.getElementById("sliderG").value = g;
      document.getElementById("sliderB").value = b;
      document.getElementById("valR").innerText = r;
      document.getElementById("valG").innerText = g;
      document.getElementById("valB").innerText = b;
    }

    async function selectScreen(scrIdx) {
      vibrate(22);
      appState.screen = scrIdx;
      updateScreenCardsUI(scrIdx);
      showToast("Mudando para Tela " + scrIdx + "...");
      try {
        await fetch("/api/screen", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({screen: scrIdx})
        });
      } catch (err) {
        console.error(err);
      }
    }

    function updateScreenCardsUI(scrIdx) {
      document.querySelectorAll(".screen-card").forEach(card => {
        const idx = parseInt(card.getAttribute("data-screen"));
        const badge = document.getElementById("badge-" + idx);
        if (idx === scrIdx) {
          card.classList.add("active");
          if (badge) badge.innerText = "ATIVO";
        } else {
          card.classList.remove("active");
          if (badge) badge.innerText = "ATIVAR";
        }
      });
    }

    async function applyHex(hex) {
      vibrate(15);
      setAccentColor(hex);
      showToast("Cor " + hex.toUpperCase() + " aplicada!");
      try {
        await fetch("/api/color", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({hex: hex})
        });
      } catch (err) {
        console.error(err);
      }
    }

    let rgbDebounce = null;
    function onRgbSlider() {
      const r = parseInt(document.getElementById("sliderR").value);
      const g = parseInt(document.getElementById("sliderG").value);
      const b = parseInt(document.getElementById("sliderB").value);
      document.getElementById("valR").innerText = r;
      document.getElementById("valG").innerText = g;
      document.getElementById("valB").innerText = b;
      const hex = "#" + [r, g, b].map(x => x.toString(16).padStart(2, "0")).join("").toUpperCase();
      document.documentElement.style.setProperty("--accent", hex);
      document.getElementById("colorSwatch").style.backgroundColor = hex;
      document.getElementById("txtHex").innerText = hex;
      document.getElementById("nativeColorPicker").value = hex;

      clearTimeout(rgbDebounce);
      rgbDebounce = setTimeout(() => {
        applyHex(hex);
      }, 150);
    }

    let brtDebounce = null;
    function onBrtSlider(val) {
      const num = parseInt(val);
      const pct = Math.round(num / 255 * 100);
      document.getElementById("lblBrtVal").innerText = `${pct}% (${num}/255)`;
      clearTimeout(brtDebounce);
      brtDebounce = setTimeout(() => {
        setBrt(num);
      }, 120);
    }

    async function setBrt(num) {
      vibrate(10);
      document.getElementById("sliderBrt").value = num;
      const pct = Math.round(num / 255 * 100);
      document.getElementById("lblBrtVal").innerText = `${pct}% (${num}/255)`;
      try {
        await fetch("/api/brightness", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({brt: num})
        });
      } catch (err) {
        console.error(err);
      }
    }

    async function toggleTicker() {
      vibrate(15);
      appState.ticker = !appState.ticker;
      const btn = document.getElementById("btnToggleTicker");
      btn.innerText = `Ticker na CYD: ${appState.ticker ? "LIGADO" : "DESLIGADO"}`;
      showToast(`Ticker ${appState.ticker ? "LIGADO" : "DESLIGADO"}`);
      try {
        await fetch("/api/ticker", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ticker: appState.ticker})
        });
      } catch (err) {
        console.error(err);
      }
    }

    async function applySelectedBg() {
      vibrate(15);
      const bg = document.getElementById("selBg").value;
      showToast("Fundo '" + bg + "' aplicado!");
      try {
        await fetch("/api/bg", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({bg: bg})
        });
      } catch (err) {
        console.error(err);
      }
    }

    async function refreshSdFiles() {
      vibrate(15);
      showToast("Solicitando lista do Cartão SD...");
      try {
        await fetch("/api/refresh_sd", {method: "POST"});
      } catch (err) {
        console.error(err);
      }
    }

    function onFileSelected(input) {
      if (!input.files || !input.files[0]) return;
      const file = input.files[0];
      const wrap = document.getElementById("progWrap");
      const fill = document.getElementById("progFill");
      const lbl = document.getElementById("progLabel");
      const pct = document.getElementById("progPct");

      wrap.style.display = "block";
      fill.style.width = "10%";
      lbl.innerText = "Lendo foto '" + file.name + "'...";
      pct.innerText = "10%";
      vibrate(20);

      const reader = new FileReader();
      reader.onload = async () => {
        try {
          fill.style.width = "40%";
          lbl.innerText = "Enviando para PC & Redimensionando...";
          pct.innerText = "40%";
          const b64 = reader.result.split(",")[1];
          const resp = await fetch("/api/upload", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({filename: file.name, data: b64})
          });
          const res = await resp.json();
          if (res.ok) {
            fill.style.width = "100%";
            lbl.innerText = "Imagem gravada no MicroSD da CYD!";
            pct.innerText = "100%";
            showToast("Foto gravada no SD da CYD com sucesso!", "📸");
            setTimeout(() => { wrap.style.display = "none"; }, 3500);
          } else {
            lbl.innerText = "Erro: " + (res.error || "Falha no envio");
            showToast("Falha no upload da foto", "❌");
          }
        } catch (err) {
          lbl.innerText = "Erro de conexão ao enviar";
          showToast("Erro ao conectar", "❌");
        }
      };
      reader.readAsDataURL(file);
    }

    function updateState(data) {
      if (!data) return;
      if (data.screen !== undefined && data.screen !== appState.screen) {
        appState.screen = data.screen;
        updateScreenCardsUI(data.screen);
      }
      if (data.hex_color && data.hex_color !== appState.hex_color) {
        appState.hex_color = data.hex_color;
        setAccentColor(data.hex_color);
      }
      if (data.color) {
        document.getElementById("txtRgb565").innerText = "RGB565: " + data.color;
      }
      if (data.brt !== undefined) {
        appState.brt = data.brt;
        document.getElementById("sliderBrt").value = data.brt;
        const pct = Math.round(data.brt / 255 * 100);
        document.getElementById("lblBrtVal").innerText = `${pct}% (${data.brt}/255)`;
      }
      if (data.ticker !== undefined) {
        appState.ticker = data.ticker;
        document.getElementById("btnToggleTicker").innerText = `Ticker na CYD: ${data.ticker ? "LIGADO" : "DESLIGADO"}`;
      }
      if (Array.isArray(data.sd_files)) {
        const sel = document.getElementById("selBg");
        const curVal = sel.value;
        const opts = data.sd_files;
        let html = "";
        opts.forEach(f => {
          html += `<option value="${f}">${f}</option>`;
        });
        sel.innerHTML = html;
        if (data.bg && opts.includes(data.bg)) {
          sel.value = data.bg;
        } else if (opts.includes(curVal)) {
          sel.value = curVal;
        }
      }

      // Telemetria
      if (data.sys) {
        const s = data.sys;
        const cpu = s.cpu || 0;
        document.getElementById("mCpuVal").innerText = cpu.toFixed(1) + "%";
        document.getElementById("mCpuSub").innerText = (s.cput !== null && s.cput !== undefined) ? `${s.cput.toFixed(0)} °C` : `${s.cpuf || 0} MHz`;
        document.getElementById("mCpuBar").style.width = Math.min(Math.max(cpu, 0), 100) + "%";

        const ram = s.ram || 0;
        document.getElementById("mRamVal").innerText = ram.toFixed(1) + "%";
        document.getElementById("mRamSub").innerText = `${(s.ramu || 0).toFixed(1)} / ${(s.ramt || 0).toFixed(0)} GB`;
        document.getElementById("mRamBar").style.width = Math.min(Math.max(ram, 0), 100) + "%";

        const gpu = s.gpu || 0;
        document.getElementById("mGpuVal").innerText = gpu.toFixed(1) + "%";
        document.getElementById("mGpuSub").innerText = (s.gput !== null && s.gput !== undefined) ? `${s.gput.toFixed(0)} °C` : (s.gpuname || "GPU");
        document.getElementById("mGpuBar").style.width = Math.min(Math.max(gpu, 0), 100) + "%";

        const dsk = s.dsk || 0;
        document.getElementById("mDskVal").innerText = dsk.toFixed(0) + "%";
        document.getElementById("mNetSub").innerText = `↓${(s.rx || 0).toFixed(1)} ↑${(s.tx || 0).toFixed(1)} MB/s`;
        document.getElementById("mDskBar").style.width = Math.min(Math.max(dsk, 0), 100) + "%";
      }

      // Mercado Financeiro
      if (data.mkt) {
        const m = data.mkt;
        if (m.usd) {
          document.getElementById("fUsd").innerText = "R$ " + m.usd.toFixed(2);
          formatChg("fUsdC", m.usdc);
        }
        if (m.eur) {
          document.getElementById("fEur").innerText = "R$ " + m.eur.toFixed(2);
          formatChg("fEurC", m.eurc);
        }
        if (m.ibov) {
          document.getElementById("fIbov").innerText = (m.ibov / 1000).toFixed(1) + "k pts";
          formatChg("fIbovC", m.ibovc);
        }
        if (m.btc) {
          document.getElementById("fBtc").innerText = "$ " + Number(m.btc).toLocaleString("en-US");
          formatChg("fBtcC", m.btcc);
        }
        if (m.eth) {
          document.getElementById("fEth").innerText = "$ " + Number(m.eth).toLocaleString("en-US");
          formatChg("fEthC", m.ethc);
        }
        if (m.sol) {
          document.getElementById("fSol").innerText = "$ " + Number(m.sol).toFixed(2);
          formatChg("fSolC", m.solc);
        }
        if (m.last_str && m.last_str !== "--:--:--") {
          document.getElementById("mMktTime").innerText = m.last_str;
        }
      }

      // Upload State
      if (data.upload && data.upload.active) {
        const wrap = document.getElementById("progWrap");
        const fill = document.getElementById("progFill");
        const lbl = document.getElementById("progLabel");
        const pct = document.getElementById("progPct");
        wrap.style.display = "block";
        const p = Math.round((data.upload.pct || 0) * 100);
        fill.style.width = p + "%";
        pct.innerText = p + "%";
        lbl.innerText = data.upload.status || "Gravando...";
      }
    }

    function formatChg(id, val) {
      const el = document.getElementById(id);
      if (!el || val === undefined) return;
      const sign = val >= 0 ? "+" : "";
      el.innerText = `${sign}${Number(val).toFixed(2)}%`;
      el.className = "fin-chg " + (val >= 0 ? "chg-pos" : "chg-neg");
    }

    // Server-Sent Events (SSE) Real-Time Stream
    function connectSSE() {
      const dot = document.getElementById("statusDot");
      const txt = document.getElementById("statusTxt");
      const es = new EventSource("/api/stream");

      es.onopen = () => {
        dot.className = "status-dot online";
        txt.innerText = "CONECTADO";
      };

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          updateState(data);
        } catch (err) {
          console.error(err);
        }
      };

      es.onerror = () => {
        dot.className = "status-dot";
        txt.innerText = "RECONECTANDO";
        es.close();
        setTimeout(connectSSE, 2000);
      };
    }

    // Inicializacao
    window.addEventListener("DOMContentLoaded", () => {
      connectSSE();
      // Fetch inicial caso SSE demore
      fetch("/api/status")
        .then(r => r.json())
        .then(updateState)
        .catch(console.error);
    });
  </script>
</body>
</html>
"""
