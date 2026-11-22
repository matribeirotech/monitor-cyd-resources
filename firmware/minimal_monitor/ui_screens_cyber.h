// ui_screens_cyber.h - CYD OS v5.0 Cyber Deck Console, RF Radar, Fiber Analyzer & IDS Security (Telas 11..14)
#pragma once

// ======================================= Modulo 2: SCR_TERMINAL (Tela 11) ===
static void appendRawTerminalLine(const char* s) {
  if (termSt.count < TERM_MAX_LINES) {
    strlcpy(termSt.lines[termSt.count], s, sizeof(termSt.lines[0]));
    termSt.count++;
  } else {
    // Scroll vertical: desloca todas as linhas para cima e escreve na ultima
    for (int i = 1; i < TERM_MAX_LINES; i++) {
      strlcpy(termSt.lines[i - 1], termSt.lines[i], sizeof(termSt.lines[0]));
    }
    strlcpy(termSt.lines[TERM_MAX_LINES - 1], s, sizeof(termSt.lines[0]));
  }
  termSt.totalLogged++;
  termSt.dirty = true;
}

// Funcao publica pedida na especificacao: faz o texto rolar para cima conforme novas linhas chegam
void log_to_terminal(String text) {
  isMatrixRain = false;
  char cleanBuf[512];
  sanitizeAscii(cleanBuf, text.c_str(), sizeof(cleanBuf));
  if (!cleanBuf[0]) return;

  int len = (int)strlen(cleanBuf);
  int pos = 0;
  while (pos < len) {
    while (pos < len && (cleanBuf[pos] == '\r')) pos++;
    if (pos >= len) break;
    if (cleanBuf[pos] == '\n') {
      pos++;
      continue;
    }

    // Encontra o proximo '\n' ou quebra em TERM_COLS (48 colunas monospace)
    int lineEnd = pos;
    while (lineEnd < len && cleanBuf[lineEnd] != '\n' && cleanBuf[lineEnd] != '\r' && (lineEnd - pos) < TERM_COLS) {
      lineEnd++;
    }

    char chunk[TERM_COLS + 4];
    int copyLen = lineEnd - pos;
    memcpy(chunk, cleanBuf + pos, copyLen);
    chunk[copyLen] = '\0';
    appendRawTerminalLine(chunk);

    pos = lineEnd;
    if (pos < len && cleanBuf[pos] == '\n') pos++;
  }
}

void clearTerminal() {
  isMatrixRain = false;
  termSt.count = 0;
  termSt.totalLogged = 0;
  log_to_terminal("CYD CYBER DECK OS v5.0 [ESP32-2432S028R]");
  log_to_terminal("Console pronto. Comandos: help | ping | docker | esp info");
  termSt.dirty = true;
}

static void drawTerminalToolbarChrome(const char* titlePrompt, uint16_t promptCol) {
  const int tx = 4, ty = 26, tw = 312, th = 193;
  // Janela moderna estilo macOS / Cyber Deck Obsidian
  tft.fillRoundRect(tx, ty, tw, th, CARD_R, C_BG);
  tft.drawRoundRect(tx, ty, tw, th, CARD_R, C_CARD_HI);

  // Barra de ferramentas superior (y = 27..41)
  tft.fillRoundRect(tx + 1, ty + 1, tw - 2, 15, CARD_R - 1, C_CARD);
  tft.fillRect(tx + 1, ty + 9, tw - 2, 7, C_CARD);
  tft.drawFastHLine(tx + 1, ty + 16, tw - 2, C_CARD_HI);

  // 3 dots estilo janela moderna (vermelho / ambar / esmeralda)
  tft.fillCircle(tx + 10, ty + 8, 2, C_HOT);
  tft.fillCircle(tx + 18, ty + 8, 2, C_WARN);
  tft.fillCircle(tx + 26, ty + 8, 2, C_OK);

  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(promptCol, C_CARD);
  tft.drawString(titlePrompt, tx + 35, ty + 8, 1);
  tft.setTextPadding(0);
}

void screenTerminalStatic() {
  isMatrixRain = false;
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  tft.fillScreen(C_BG);
  drawHeader();
  drawClock();

  const int tx = 4, ty = 26, tw = 312, th = 193;
  drawTerminalToolbarChrome("root@cyd:~$ ttyUSB0/UDP", C_ACCENT);

  // Barra inferior de prompt interativo (y = 204..218)
  tft.drawFastHLine(tx + 1, ty + th - 15, tw - 2, C_CARD_HI);
  tft.fillRoundRect(tx + 1, ty + th - 14, tw - 2, 13, CARD_R - 1, C_CARD);
  tft.fillRect(tx + 1, ty + th - 14, tw - 2, 6, C_CARD);

  if (termSt.count == 0) {
    clearTerminal();
  }
  termSt.dirty = true;
}

// ======================================= Easter Egg: Matrix Rain (SCR_TERMINAL) ===
static uint32_t lastMatrixTick = 0;
#define MATRIX_COLS 25
static int16_t matrixHeadY[MATRIX_COLS];
static uint8_t matrixSpeed[MATRIX_COLS];
static uint8_t matrixLen[MATRIX_COLS];
static uint8_t matrixTickCount[MATRIX_COLS];

void initMatrixRain() {
  isMatrixRain = true;
  strlcpy(termSt.lastCmd, "cmatrix", sizeof(termSt.lastCmd));
  drawTerminalToolbarChrome("root@cyd:~$ cmatrix [MATRIX RAIN]", C_OK);
  drawPillBadge(254, 28, 58, 12, "RAIN ON", C_OK, blend565(C_CARD, C_OK, 40), C_OK, 1);

  for (int i = 0; i < MATRIX_COLS; i++) {
    matrixHeadY[i]     = random(44, 120);
    matrixSpeed[i]     = random(1, 4);
    matrixLen[i]       = random(5, 13);
    matrixTickCount[i] = 0;
  }
  Serial.println("TERM_LOG:[MATRIX] Easter egg Matrix Rain iniciado na CYD!");
}

static void updateMatrixRain() {
  if (!isMatrixRain) return;
  uint32_t now = millis();
  if (now - lastMatrixTick < 40) return;
  lastMatrixTick = now;

  const int topY = 44;
  const int botY = 203;
  const int tx   = 8;
  const int colW = 12;

  uint16_t headGlow = 0xFFFF;
  uint16_t bodyHi   = C_OK;
  uint16_t bodyMid  = blend565(C_BG, C_OK, 150);
  uint16_t bodyDim  = blend565(C_BG, C_OK, 70);

  for (int i = 0; i < MATRIX_COLS; i++) {
    matrixTickCount[i]++;
    if (matrixTickCount[i] < matrixSpeed[i]) continue;
    matrixTickCount[i] = 0;

    int x = tx + i * colW;
    int y = matrixHeadY[i];

    // Ponta brilhante com glow branco
    if (y >= topY && y < botY) {
      char ch = (char)random(33, 126);
      tft.setTextColor(headGlow, C_BG);
      tft.drawChar(ch, x, y, 1);
    }

    // Corpo esmeralda vibrante
    int prevY1 = y - 8;
    if (prevY1 >= topY && prevY1 < botY) {
      char prevCh = (char)random(33, 126);
      tft.setTextColor(bodyHi, C_BG);
      tft.drawChar(prevCh, x, prevY1, 1);
    }

    // Fade intermediario
    int prevY2 = y - 16;
    if (prevY2 >= topY && prevY2 < botY) {
      char midCh = (char)random(33, 126);
      tft.setTextColor(bodyMid, C_BG);
      tft.drawChar(midCh, x, prevY2, 1);
    }

    // Cauda obsidiana suave
    int prevY3 = y - 24;
    if (prevY3 >= topY && prevY3 < botY) {
      char dimCh = (char)random(33, 126);
      tft.setTextColor(bodyDim, C_BG);
      tft.drawChar(dimCh, x, prevY3, 1);
    }

    // Apaga cauda anterior em C_BG
    int tailY = y - (matrixLen[i] * 8);
    if (tailY >= topY && tailY < botY) {
      tft.fillRect(x, tailY, 7, 8, C_BG);
    }

    matrixHeadY[i] += 8;
    if (matrixHeadY[i] > botY + (matrixLen[i] * 8)) {
      matrixHeadY[i] = topY;
      matrixSpeed[i] = random(1, 4);
      matrixLen[i]   = random(5, 13);
    }
  }
}

void screenTerminalDynamic() {
  if (isMatrixRain) {
    updateMatrixRain();
    return;
  }
  const int tx = 4, ty = 26, tw = 312, th = 193;
  static uint8_t lastCursorState = 255;
  bool forcePrompt = termSt.dirty;

  // Redesenha o buffer de linhas rolantes apenas quando novas linhas chegam
  if (termSt.dirty) {
    termSt.dirty = false;

    // Pill da ultima comando + contador de linhas no topo da janela
    char cmdBadge[20];
    snprintf(cmdBadge, sizeof(cmdBadge), "%.11s", termSt.lastCmd[0] ? termSt.lastCmd : "ready");
    drawPillBadge(tx + 178, ty + 3, 66, 11, cmdBadge, C_ACCENT, C_ACCENT_SOFT, 0, 1);

    char lnBuf[18];
    snprintf(lnBuf, sizeof(lnBuf), "LN:%lu", (unsigned long)termSt.totalLogged);
    drawPillBadge(tx + tw - 64, ty + 3, 58, 11, lnBuf, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);

    // Area util das 14 linhas: y = 44..198 (11 px por linha, Fonte 1 6x8 monospace)
    tft.fillRect(tx + 2, ty + 18, tw - 4, th - 34, C_BG);
    tft.setTextDatum(TL_DATUM);

    for (uint8_t i = 0; i < termSt.count; i++) {
      const char* ln = termSt.lines[i];
      uint16_t fg = C_TEXT; // Texto principal off-white ultra-legivel
      if (ln[0] == '$' || (ln[0] == '>' && ln[1] == ' ')) {
        fg = C_ACCENT; // Comandos digitados
      } else if (strstr(ln, "[ERR]") || strstr(ln, "FAIL") || strstr(ln, "OFFLINE") || strstr(ln, "ERRO")) {
        fg = C_HOT; // Erros/falhas em coral
      } else if (strstr(ln, "[WARN]") || strstr(ln, "WARN")) {
        fg = C_WARN; // Avisos em ambar
      } else if (strstr(ln, "[OK]") || strstr(ln, "200 OK") || strstr(ln, "ONLINE")) {
        fg = C_OK; // Sucesso em esmeralda
      } else if (strstr(ln, "[WIFI]") || strstr(ln, "[ESP32]") || strstr(ln, "[UDP]") ||
                 strstr(ln, "[HEAP]") || strstr(ln, "CYD CYBER DECK")) {
        fg = C_COOL; // Tags de sistema/hardware em sky cyan
      }
      tft.setTextColor(fg, C_BG);
      tft.drawString(ln, tx + 6, ty + 18 + i * 11, 1);
    }
  }

  // Prompt inferior com cursor piscante
  uint8_t cursorOn = (uint8_t)(((millis() / 450) % 2) == 0);
  if (forcePrompt || cursorOn != lastCursorState) {
    lastCursorState = cursorOn;
    tft.fillRect(tx + 4, ty + th - 13, tw - 8, 11, C_CARD);
    tft.setTextDatum(ML_DATUM);
    tft.setTextColor(C_OK, C_CARD);
    tft.drawString("root@cyd:~$", tx + 6, ty + th - 8, 1);

    char cmdLine[40];
    snprintf(cmdLine, sizeof(cmdLine), "%.28s%s",
             termSt.lastCmd, cursorOn ? "_" : " ");
    tft.setTextColor(C_ACCENT, C_CARD);
    tft.drawString(cmdLine, tx + 78, ty + th - 8, 1);
    tft.setTextPadding(0);
  }
}

// Executa Wi-Fi Scan nativo no ESP32 e imprime os resultados (SSID e RSSI) direto na SCR_TERMINAL
void runWifiScanOnTerminal() {
  strlcpy(termSt.lastCmd, "wifi scan", sizeof(termSt.lastCmd));
  if (currentScreen != SCR_TERMINAL) {
    currentScreen = SCR_TERMINAL;
    prefs.putUChar("screen", currentScreen);
    resetDrawCache();
    screenTerminalStatic();
    needFullDraw = false;
  }

  log_to_terminal("$ wifi scan");
  log_to_terminal("[WIFI] Escaneando redes 2.4GHz no ESP32...");
  screenTerminalDynamic(); // Exibe mensagem imediatamente antes do bloqueio do radio
  sendReplyLine("TERM_LOG:[WIFI] Escaneando redes 2.4GHz no hardware ESP32...");

  WiFi.mode(WIFI_STA);
  delay(20);

  int n = WiFi.scanNetworks(false, false);
  if (n <= 0) {
    log_to_terminal("[WIFI] Nenhuma rede Wi-Fi encontrada (0 APs).");
    sendReplyLine("TERM_LOG:[WIFI] Nenhuma rede Wi-Fi encontrada (0 APs).");
  } else {
    char hdr[48];
    snprintf(hdr, sizeof(hdr), "[WIFI] %d redes encontradas (SSID / RSSI):", n);
    log_to_terminal(hdr);
    char lHdr[64];
    snprintf(lHdr, sizeof(lHdr), "TERM_LOG:%s", hdr);
    sendReplyLine(lHdr);

    int maxShow = min(n, 11);
    for (int i = 0; i < maxShow; i++) {
      String ssidStr = WiFi.SSID(i);
      char cleanSsid[24];
      sanitizeAscii(cleanSsid, ssidStr.c_str(), sizeof(cleanSsid));
      if (!cleanSsid[0]) strlcpy(cleanSsid, "<OCULTA>", sizeof(cleanSsid));

      int32_t rssi = WiFi.RSSI(i);
      int32_t ch   = WiFi.channel(i);
      bool openNet = (WiFi.encryptionType(i) == WIFI_AUTH_OPEN);

      char row[52];
      snprintf(row, sizeof(row), "%02d) %-18.18s %4lddBm CH%02ld %s",
               i + 1, cleanSsid, (long)rssi, (long)ch, openNet ? "OPEN" : "WPA");
      log_to_terminal(row);
      char lRow[68];
      snprintf(lRow, sizeof(lRow), "TERM_LOG:%s", row);
      sendReplyLine(lRow);
    }
    if (n > maxShow) {
      char more[44];
      snprintf(more, sizeof(more), "... +%d redes adicionais omitidas", n - maxShow);
      log_to_terminal(more);
      char lMore[60];
      snprintf(lMore, sizeof(lMore), "TERM_LOG:%s", more);
      sendReplyLine(lMore);
    }
  }

  WiFi.scanDelete();
  // Mantem Wi-Fi STA conectado para Telemetria UDP (nao desliga o radio!)
  if (WiFi.status() != WL_CONNECTED && wifiSsid[0] != '\0' && strcmp(wifiSsid, "SUA_REDE_WIFI") != 0) {
    WiFi.begin(wifiSsid, wifiPass);
  }
  screenTerminalDynamic();
}

// ======================================= Modulo 3: SCR_WIFI_RADAR (Tela 12) =
static uint16_t rssiBarColor(int16_t rssi) {
  if (rssi >= -62) return C_OK;   // Esmeralda forte
  if (rssi >= -74) return C_COOL; // Sky cyan bom
  if (rssi >= -83) return C_WARN; // Ambar medio/fraco
  return C_HOT;                   // Coral muito fraco
}

void resetFlowPackets() {
  for (int i = 0; i < NETFLOW_MAX_PKTS; i++) {
    flowPkts[i].active = false;
  }
  // Semeia pacotes iniciais para animacao fluida imediata
  flowPkts[0] = { 188.0f, 2.2f, -1, 0, 0, true }; // RX WAN->ROUTER->HOST
  flowPkts[1] = { 104.0f, 2.0f, -1, 0, 0, true };
  flowPkts[2] = {  38.0f, 1.8f, +1, 1, 1, true }; // TX HOST->ROUTER->WAN
  flowPkts[3] = { 262.0f, 1.6f, -1, 2, 2, true }; // RF/BLE 32U->WAN
}

// Ilustracao Animada do Transito de Dados & Pacotes na Rede (HOST <-> ROUTER <-> WAN <-> 32U/BLE)
// NOTA 8-bit Sprite (RGB332): cores escolhidas com bits superiores limpos (R3:15..13, G3:10..8, B2:4..3)
void updateNetFlowAnimation() {
  if (!netFlowSprReady || currentScreen != SCR_WIFI_RADAR) return;
  flowAnimTick++;

  // Velocidade real de trafego (usa neta se disponivel, senao st.rx/st.tx * 8)
  float rxM = (neta.valid && (neta.rxMbps > 0.05f || neta.txMbps > 0.05f)) ? neta.rxMbps : (st.rx * 8.0f);
  float txM = (neta.valid && (neta.rxMbps > 0.05f || neta.txMbps > 0.05f)) ? neta.txMbps : (st.tx * 8.0f);
  if (rxM < 0.0f) rxM = 0.0f;
  if (txM < 0.0f) txM = 0.0f;

  // Coordenadas X dos 4 nos no sprite 304x48
  const int16_t xPC  = 24;
  const int16_t xGW  = 112;
  const int16_t xWAN = 198;
  const int16_t xRF  = 278;
  const int16_t yRx  = 18; // Trilha superior: Download (WAN -> ROUTER -> HOST)
  const int16_t yTx  = 28; // Trilha inferior: Upload   (HOST -> ROUTER -> WAN)
  const int16_t yRf  = 23; // Enlace sem fio RF/BLE     (32U/BLE <-> WAN)

  // Paleta otimizada para quantizacao RGB332 limpa no sprite 8-bit
  const uint16_t S_BG      = 0x0842; // Fundo dark slate
  const uint16_t S_GRID    = 0x0108; // Grade sutil RGB332
  const uint16_t S_NODE    = 0x2108; // Chip elevado escuro
  const uint16_t S_CYAN    = 0x07FF; // RX / Sky Cyan
  const uint16_t S_CYAN_TL = 0x0310; // Cauda RX
  const uint16_t S_AMB     = 0xFE00; // TX / Amber
  const uint16_t S_AMB_TL  = 0x6200; // Cauda TX
  const uint16_t S_VIO     = 0xC11F; // RF/BLE / Violet
  const uint16_t S_VIO_TL  = 0x4010; // Cauda RF/BLE
  const uint16_t S_RED     = 0xF800; // IDS Alert Coral Red
  const uint16_t S_RED_TL  = 0x6000; // Cauda IDS
  const uint16_t S_OK      = 0x07E0; // Emerald OK
  const uint16_t S_WHITE   = 0xFFFF; // Texto / nucleo brilhante
  const uint16_t S_DIM     = 0x9492; // Slate claro

  // Limpa fundo do sprite
  netFlowSpr.fillSprite(S_BG);

  // Grade pontilhada sutil ao fundo
  for (int gx = 16; gx < NETFLOW_W; gx += 24) {
    for (int gy = 10; gy < NETFLOW_H - 8; gy += 4) {
      netFlowSpr.drawPixel(gx, gy, S_GRID);
    }
  }

  // ---- Trilhas / Barramentos de dados ----
  netFlowSpr.drawFastHLine(xPC + 14, yRx, xWAN - xPC - 28, 0x0210); // trilha RX
  netFlowSpr.drawFastHLine(xPC + 14, yTx, xWAN - xPC - 28, 0x4100); // trilha TX

  // Enlace Wireless tracejado entre WAN e 32U/BLE
  uint16_t linkCol = wrad.bleConn ? S_CYAN : (wrad.online ? S_VIO : S_DIM);
  for (int wx = xWAN + 15; wx < xRF - 15; wx += 6) {
    netFlowSpr.drawFastHLine(wx, yRf, 3, linkCol);
  }

  // ---- Spawn dinamico de novos pacotes conforme trafego real ----
  uint16_t rxInterval = (rxM > 50.0f) ? 3 : ((rxM > 5.0f) ? 6 : ((rxM > 0.3f) ? 10 : 16));
  uint16_t txInterval = (txM > 20.0f) ? 4 : ((txM > 2.0f) ? 8 : ((txM > 0.2f) ? 13 : 22));
  uint16_t rfInterval = wrad.bleConn ? 7 : (wrad.online ? 14 : 32);

  float rxSpd = 1.8f + min(rxM * 0.04f, 3.6f);
  float txSpd = 1.6f + min(txM * 0.06f, 3.2f);

  auto spawnPkt = [&](float startX, float spd, int8_t dir, uint8_t lane, uint8_t type) {
    for (int i = 0; i < NETFLOW_MAX_PKTS; i++) {
      if (!flowPkts[i].active) {
        flowPkts[i] = { startX, spd, dir, lane, type, true };
        return;
      }
    }
  };

  if (flowAnimTick % rxInterval == 0) {
    uint8_t pType = (sec.level >= 2 && (flowAnimTick % 2 == 0)) ? 3 : 0;
    spawnPkt((float)(xWAN - 14), rxSpd, -1, 0, pType);
  }
  if (flowAnimTick % txInterval == 0) {
    spawnPkt((float)(xPC + 14), txSpd, +1, 1, 1);
  }
  if (flowAnimTick % rfInterval == 0 && (wrad.online || wrad.bleConn)) {
    spawnPkt((float)(xRF - 15), 1.8f, -1, 2, 2);
  }

  // ---- Atualiza e desenha os pacotes transitando com rastro luminoso ----
  for (int i = 0; i < NETFLOW_MAX_PKTS; i++) {
    if (!flowPkts[i].active) continue;
    FlowPacket& p = flowPkts[i];
    p.x += p.speed * (float)p.dir;

    if (p.lane == 0 && p.x < (xPC + 13))  { p.active = false; continue; }
    if (p.lane == 1 && p.x > (xWAN - 13)) { p.active = false; continue; }
    if (p.lane == 2 && p.x < (xWAN + 15)) { p.active = false; continue; }

    int16_t px = (int16_t)p.x;
    int16_t py = (p.lane == 0) ? yRx : ((p.lane == 1) ? yTx : yRf);
    uint16_t headCol = S_CYAN;
    uint16_t tailCol = S_CYAN_TL;
    if (p.type == 1)      { headCol = S_AMB; tailCol = S_AMB_TL; }
    else if (p.type == 2) { headCol = S_VIO; tailCol = S_VIO_TL; }
    else if (p.type == 3) { headCol = S_RED; tailCol = S_RED_TL; }

    // Rastro do pacote (streak + pixels de cauda)
    int16_t tx1 = px - p.dir * 6;
    int16_t tx2 = px - p.dir * 10;
    int16_t tx3 = px - p.dir * 13;
    netFlowSpr.drawFastHLine(min(px, tx1), py, abs(px - tx1) + 1, tailCol);
    netFlowSpr.drawPixel(tx2, py, tailCol);
    netFlowSpr.drawPixel(tx3, py, S_GRID);

    // Capsula luminosa do pacote
    netFlowSpr.fillRoundRect(px - 2, py - 2, 5, 5, 1, headCol);
    netFlowSpr.drawPixel(px, py, S_WHITE);
  }

  // ---- 4 Node Chips Modernos: HOST, ROUTER, WAN, 32U/BLE ----
  // 1) HOST (PC)
  uint16_t hostBd = linked ? S_CYAN : S_RED;
  netFlowSpr.fillRoundRect(xPC - 13, 10, 26, 24, 4, S_NODE);
  netFlowSpr.drawRoundRect(xPC - 13, 10, 26, 24, 4, hostBd);
  netFlowSpr.drawRect(xPC - 8, 14, 16, 10, S_WHITE);
  netFlowSpr.drawFastHLine(xPC - 4, 27, 9, hostBd);
  netFlowSpr.drawFastVLine(xPC, 24, 3, hostBd);
  netFlowSpr.setTextDatum(MC_DATUM);
  netFlowSpr.setTextColor(S_WHITE, S_BG);
  netFlowSpr.drawString("HOST", xPC, 42, 1);

  // 2) ROUTER (Gateway)
  uint16_t gwBd = neta.gwUp ? S_CYAN : S_AMB;
  netFlowSpr.fillRoundRect(xGW - 14, 10, 28, 24, 4, S_NODE);
  netFlowSpr.drawRoundRect(xGW - 14, 10, 28, 24, 4, gwBd);
  netFlowSpr.drawFastVLine(xGW - 7, 13, 7, gwBd);
  netFlowSpr.drawFastVLine(xGW + 7, 13, 7, gwBd);
  netFlowSpr.fillRect(xGW - 9, 20, 19, 8, S_BG);
  netFlowSpr.drawPixel(xGW - 5, 24, (flowAnimTick & 2) ? S_OK   : S_GRID);
  netFlowSpr.drawPixel(xGW,     24, (flowAnimTick & 4) ? S_CYAN : S_GRID);
  netFlowSpr.drawPixel(xGW + 5, 24, (flowAnimTick & 8) ? S_AMB  : S_GRID);
  netFlowSpr.setTextColor(S_CYAN, S_BG);
  netFlowSpr.drawString("ROUTER", xGW, 42, 1);

  // 3) WAN (Fibra / Internet)
  uint16_t wanBd = neta.wanUp ? S_OK : S_RED;
  netFlowSpr.fillRoundRect(xWAN - 13, 10, 26, 24, 4, S_NODE);
  netFlowSpr.drawRoundRect(xWAN - 13, 10, 26, 24, 4, wanBd);
  netFlowSpr.drawCircle(xWAN, 22, 6, wanBd);
  netFlowSpr.drawFastHLine(xWAN - 5, 22, 11, wanBd);
  netFlowSpr.drawFastVLine(xWAN, 16, 13, wanBd);
  netFlowSpr.setTextColor(wanBd, S_BG);
  netFlowSpr.drawString("WAN", xWAN, 42, 1);

  // 4) 32U/BLE (Modulo RF + Antena com ondas animadas)
  uint16_t rfBd = wrad.bleConn ? S_CYAN : (wrad.online ? S_VIO : S_DIM);
  netFlowSpr.fillRoundRect(xRF - 14, 10, 28, 24, 4, S_NODE);
  netFlowSpr.drawRoundRect(xRF - 14, 10, 28, 24, 4, rfBd);
  int waveR = 4 + ((flowAnimTick / 2) % 7);
  if (wrad.online || wrad.bleConn) {
    netFlowSpr.drawCircle(xRF, 20, waveR, rfBd);
  }
  netFlowSpr.fillCircle(xRF, 20, 2, S_WHITE);
  netFlowSpr.drawFastVLine(xRF, 22, 8, rfBd);
  netFlowSpr.setTextColor(rfBd, S_BG);
  netFlowSpr.drawString("32U/BLE", xRF, 42, 1);

  // ---- Barra de throughput ao vivo no topo do sprite (y = 0..8) ----
  char rxLbl[20], txLbl[20];
  snprintf(rxLbl, sizeof(rxLbl), "RX %.1fMbps", rxM);
  snprintf(txLbl, sizeof(txLbl), "TX %.1fMbps", txM);
  netFlowSpr.setTextDatum(TL_DATUM);
  netFlowSpr.setTextColor(S_CYAN, S_BG);
  netFlowSpr.drawString(rxLbl, 4, 0, 1);

  netFlowSpr.setTextColor(S_AMB, S_BG);
  netFlowSpr.drawString(txLbl, 96, 0, 1);

  char rfTop[20];
  if (wrad.bleConn) {
    snprintf(rfTop, sizeof(rfTop), "BLE %+ddBm", (int)wrad.blePwr);
    netFlowSpr.setTextColor(S_OK, S_BG);
  } else if (wrad.online) {
    snprintf(rfTop, sizeof(rfTop), "RF #%u", (unsigned)wrad.scanCount);
    netFlowSpr.setTextColor(S_VIO, S_BG);
  } else {
    snprintf(rfTop, sizeof(rfTop), "32U STBY");
    netFlowSpr.setTextColor(S_DIM, S_BG);
  }
  netFlowSpr.setTextDatum(TR_DATUM);
  netFlowSpr.drawString(rfTop, NETFLOW_W - 4, 0, 1);

  // Push dentro do Card Central (x=4 y=75 w=312 h=68 -> interior y=91..138)
  netFlowSpr.pushSprite(8, 91);
}

void screenWifiRadarStatic() {
  isMatrixRain = false;
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  tft.fillScreen(C_BG);
  drawHeader();
  drawClock();

  // 1) Top-left card (x=4 y=26 w=154 h=46, accent C_PURPLE): ESP32-32U RF
  drawModernCard(4, 26, 154, 46, "ESP32-32U RF", C_PURPLE);

  // 2) Top-right card (x=162 y=26 w=154 h=46, accent C_COOL): 2.4GHz SPECTRUM
  drawModernCard(162, 26, 154, 46, "2.4GHz SPECTRUM", C_COOL);

  // 3) Middle card (x=4 y=75 w=312 h=68, accent C_ACCENT): LIVE PACKET FLOW
  drawModernCard(4, 75, 312, 68, "LIVE PACKET FLOW", C_ACCENT);

  // 4) Bottom card (x=4 y=146 w=312 h=73): NEARBY ACCESS POINTS
  drawModernCard(4, 146, 312, 73, "NEARBY ACCESS POINTS", C_ACCENT);

  resetFlowPackets();
  wrad.dirty = true;
}

static void drawMiniSignalBars(int16_t x, int16_t y, int16_t rssi, uint16_t activeCol) {
  uint8_t bars = 1;
  if (rssi >= -60)      bars = 4;
  else if (rssi >= -70) bars = 3;
  else if (rssi >= -82) bars = 2;

  for (uint8_t b = 0; b < 4; b++) {
    int16_t bh = 3 + b * 2; // alturas: 3, 5, 7, 9 px
    int16_t bx = x + b * 3;
    int16_t by = y + (9 - bh);
    tft.fillRect(bx, by, 2, bh, (b < bars) ? activeCol : C_TRACK);
  }
}

void screenWifiRadarDynamic() {
  if (!wrad.dirty) return;
  wrad.dirty = false;

  // --- 1) Top-left card: ESP32-32U RF (x=4 y=26 w=154 h=46) ---
  // Pill Online/Offline no canto superior direito do card 1
  if (wrad.online) {
    drawPillBadge(108, 28, 46, 11, wrad.scanning ? "SCAN" : "ONLINE",
                  C_OK, blend565(C_CARD, C_OK, 40), C_OK, 1);
  } else {
    drawPillBadge(104, 28, 50, 11, "OFFLINE",
                  C_HOT, blend565(C_CARD, C_HOT, 40), C_HOT, 1);
  }

  tft.fillRect(8, 40, 146, 29, C_CARD);

  // Hero AP count a esquerda
  char apHero[16];
  snprintf(apHero, sizeof(apHero), "%u APs", (unsigned)wrad.total);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(wrad.online ? C_TEXT : C_DIM, C_CARD);
  tft.drawString(apHero, 10, 48, 2);

  // BLE status pill + tx dBm a direita
  char bleTxt[16];
  if (wrad.bleConn) {
    snprintf(bleTxt, sizeof(bleTxt), "BLE ON %+d", (int)wrad.blePwr);
    drawPillBadge(80, 41, 72, 13, bleTxt, C_OK, blend565(C_CARD, C_OK, 40), C_OK, 1);
  } else {
    snprintf(bleTxt, sizeof(bleTxt), "BLE OFF %+d", (int)wrad.blePwr);
    drawPillBadge(80, 41, 72, 13, bleTxt, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);
  }

  // Subtitulo RF na base do card 1
  char rfSub[32];
  if (wrad.online && wrad.total > 0) {
    snprintf(rfSub, sizeof(rfSub), "BEST %ddBm | SCAN #%u", (int)wrad.bestRssi, (unsigned)wrad.scanCount);
  } else if (wrad.online) {
    snprintf(rfSub, sizeof(rfSub), "Varrendo espectro 2.4GHz...");
  } else {
    snprintf(rfSub, sizeof(rfSub), "ESP32-32U externo aguardando");
  }
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(rfSub, 10, 63, 1);

  // --- 2) Top-right card: 2.4GHz SPECTRUM (x=162 y=26 w=154 h=46) ---
  char freePill[12];
  snprintf(freePill, sizeof(freePill), "CH%u", (unsigned)constrain(wrad.freeCh, 1, 13));
  drawPillBadge(280, 28, 32, 11, freePill, C_OK, blend565(C_CARD, C_OK, 40), C_OK, 1);

  tft.fillRect(166, 40, 146, 29, C_CARD);

  uint8_t maxChVal = 1;
  for (int i = 0; i < 13; i++) {
    if (wrad.chCounts[i] > maxChVal) maxChVal = wrad.chCounts[i];
  }

  const int barBaseY = 59;
  const int barMaxH  = 17;
  for (int i = 0; i < 13; i++) {
    int bx = 170 + i * 11;
    uint8_t cnt = wrad.chCounts[i];
    // Track de fundo do equalizador
    tft.fillRect(bx, barBaseY - barMaxH, 8, barMaxH, C_TRACK);

    int bh = (cnt > 0) ? max(3, (int)((cnt * barMaxH) / maxChVal)) : 2;
    uint16_t bCol = C_MUTED;
    if (cnt >= 4)      bCol = C_HOT;
    else if (cnt >= 2) bCol = C_WARN;
    else if (cnt == 1) bCol = C_OK;
    else if ((i + 1) == wrad.freeCh && wrad.online) bCol = C_COOL;
    tft.fillRect(bx, barBaseY - bh, 8, bh, bCol);
  }

  // Marcadores dos canais 1, 6, 11, 13
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("1",  174, 65, 1);
  tft.drawString("6",  229, 65, 1);
  tft.drawString("11", 284, 65, 1);
  tft.drawString("13", 306, 65, 1);

  // --- 4) Bottom card: NEARBY ACCESS POINTS (x=4 y=146 w=312 h=73) ---
  // Badge de contagem no topo direito do card 4
  char apCntPill[16];
  snprintf(apCntPill, sizeof(apCntPill), "TOP %u/%u",
           (unsigned)min((uint8_t)4, wrad.apCount), (unsigned)wrad.total);
  drawPillBadge(254, 148, 58, 11, apCntPill, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);

  tft.fillRect(7, 160, 306, 56, C_CARD);

  if (!wrad.online) {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_WARN, C_CARD);
    tft.drawString("Aguardando Radar RF ESP32-WROOM-32U", SCR_W / 2, 181, 2);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString("Telemetria RF 2.4GHz + BLE Long-Range", SCR_W / 2, 200, 1);
    tft.setTextPadding(0);
    return;
  }

  if (wrad.apCount == 0) {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_COOL, C_CARD);
    tft.drawString("Escaneando pontos de acesso...", SCR_W / 2, 188, 2);
    tft.setTextPadding(0);
    return;
  }

  const int rowH = 14;
  const uint8_t showMax = min((uint8_t)4, wrad.apCount);
  for (uint8_t i = 0; i < showMax; i++) {
    int ry = 160 + i * rowH;
    const WifiRadarAp& ap = wrad.aps[i];
    uint16_t sCol = rssiBarColor(ap.rssi);
    uint16_t rowBg = (i % 2 == 1) ? C_CARD_ELEV : C_CARD;

    if (i % 2 == 1) {
      tft.fillRoundRect(8, ry, 304, rowH - 1, 2, rowBg);
    }

    // Icone 4-barras de sinal a esquerda
    drawMiniSignalBars(11, ry + 2, ap.rssi, sCol);

    // SSID crisp C_TEXT
    char ssidShort[19];
    snprintf(ssidShort, sizeof(ssidShort), "%.18s", ap.ssid);
    tft.setTextDatum(ML_DATUM);
    tft.setTextColor(C_TEXT, rowBg);
    tft.drawString(ssidShort, 26, ry + 6, 1);

    // Channel pill
    char chBuf[8];
    snprintf(chBuf, sizeof(chBuf), "CH%02u", (unsigned)ap.ch);
    drawPillBadge(140, ry + 1, 30, 11, chBuf, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);

    // Visual RSSI mini signal bar (drawSlimBar)
    float pct = constrain((float)((ap.rssi + 96) * 100) / 52.0f, 5.0f, 100.0f);
    drawSlimBar(176, ry + 4, 84, 5, pct, sCol, C_TRACK);

    // dBm readout
    char rBuf[12];
    snprintf(rBuf, sizeof(rBuf), "%ddBm", (int)ap.rssi);
    tft.setTextDatum(MR_DATUM);
    tft.setTextColor(sCol, rowBg);
    tft.drawString(rBuf, 308, ry + 6, 1);
  }
  tft.setTextPadding(0);
}

// ======================================= Modulo 4: SCR_NET_ANALYZER (Tela 13) =
void screenNetAnalyzerStatic() {
  isMatrixRain = false;
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  tft.fillScreen(C_BG);
  drawHeader();
  drawClock();

  // 1) Top-left card (x=4 y=26 w=154 h=66, accent C_COOL): ROUTER / GATEWAY
  drawModernCard(4, 26, 154, 66, "ROUTER / GATEWAY", C_COOL);

  // 2) Top-right card (x=162 y=26 w=154 h=66, accent C_OK): WAN / DNS / ISP
  drawModernCard(162, 26, 154, 66, "WAN / DNS / ISP", C_OK);

  // 3) Middle card (x=4 y=96 w=312 h=60, accent C_ACCENT): REALTIME LINK (Mbps)
  drawModernCard(4, 96, 312, 60, "REALTIME LINK (Mbps)", C_ACCENT);

  // 4) Bottom card (x=4 y=160 w=312 h=59, accent C_PURPLE): FIBER SPEEDTEST
  drawModernCard(4, 160, 312, 59, "FIBER SPEEDTEST", C_PURPLE);

  neta.dirty = true;
}

void screenNetAnalyzerDynamic() {
  if (!neta.dirty) return;
  neta.dirty = false;

  // --- 1) Top-left card: ROUTER / GATEWAY (x=4 y=26 w=154 h=66) ---
  drawPillBadge(122, 28, 32, 11, neta.gwUp ? "UP" : "DOWN",
                neta.gwUp ? C_OK : C_HOT,
                blend565(C_CARD, neta.gwUp ? C_OK : C_HOT, 40),
                neta.gwUp ? C_OK : C_HOT, 1);

  tft.fillRect(8, 40, 146, 49, C_CARD);

  // Gateway IP hero
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(neta.gw, 10, 48, 2);

  if (neta.gwHttp > 0) {
    drawPillBadge(122, 42, 30, 12, "WEB", C_COOL, C_CARD_ELEV, C_CARD_HI, 1);
  }

  // 3 mini metric tiles: LATENCY, JITTER, LOSS
  auto drawMiniMetric = [&](int16_t bx, int16_t by, int16_t bw, const char* lbl, const char* val, uint16_t vCol) {
    tft.fillRoundRect(bx, by, bw, 27, 3, C_CARD_ELEV);
    tft.setTextDatum(TC_DATUM);
    tft.setTextColor(C_DIM, C_CARD_ELEV);
    tft.drawString(lbl, bx + bw / 2, by + 3, 1);
    tft.setTextDatum(BC_DATUM);
    tft.setTextColor(vCol, C_CARD_ELEV);
    tft.drawString(val, bx + bw / 2, by + 25, 1);
  };

  char latStr[12], jitStr[12], lossStr[12];
  snprintf(latStr,  sizeof(latStr),  "%.1fms", neta.gwMs);
  snprintf(jitStr,  sizeof(jitStr),  "%.1fms", neta.gwJit);
  snprintf(lossStr, sizeof(lossStr), "%u%%",   (unsigned)neta.loss);

  drawMiniMetric(8,   61, 46, "PING",   latStr,  levelColor(neta.gwMs, 8.0f, 25.0f));
  drawMiniMetric(58,  61, 46, "JITTER", jitStr,  levelColor(neta.gwJit, 5.0f, 15.0f));
  drawMiniMetric(108, 61, 46, "LOSS",   lossStr, (neta.loss == 0) ? C_OK : C_HOT);

  // --- 2) Top-right card: WAN / DNS / ISP (x=162 y=26 w=154 h=66) ---
  drawPillBadge(268, 28, 44, 11, neta.wanUp ? "WAN UP" : "WAN DN",
                neta.wanUp ? C_OK : C_HOT,
                blend565(C_CARD, neta.wanUp ? C_OK : C_HOT, 40),
                neta.wanUp ? C_OK : C_HOT, 1);

  tft.fillRect(166, 40, 146, 49, C_CARD);

  // ISP name em C_TEXT + interface pill
  char ispUp[16];
  snprintf(ispUp, sizeof(ispUp), "%.12s", neta.isp[0] ? neta.isp : "FIBER ISP");
  for (int i = 0; ispUp[i]; i++) ispUp[i] = toupper((unsigned char)ispUp[i]);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(ispUp, 168, 48, 2);

  // Mini metrics: WAN ping + DNS ms + LAN host count pill
  char wanMsStr[12], dnsMsStr[12], hostsStr[14];
  snprintf(wanMsStr, sizeof(wanMsStr), "%.0fms", neta.wanMs);
  snprintf(dnsMsStr, sizeof(dnsMsStr), "%dms",   (int)neta.dnsMs);
  snprintf(hostsStr, sizeof(hostsStr), "%u HOSTS", (unsigned)neta.lanCount);

  drawMiniMetric(166, 61, 44, "WAN", wanMsStr, neta.wanUp ? levelColor(neta.wanMs, 35.0f, 80.0f) : C_HOT);
  drawMiniMetric(213, 61, 44, "DNS", dnsMsStr, levelColor((float)neta.dnsMs, 40.0f, 90.0f));
  drawPillBadge(260, 61, 52, 27, hostsStr, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);

  // --- 3) Middle card: REALTIME LINK (Mbps) (x=4 y=96 w=312 h=60) ---
  uint16_t plan = max((uint16_t)10, neta.planMbps);
  char planPill[18];
  snprintf(planPill, sizeof(planPill), "PLAN %uM", (unsigned)plan);
  drawPillBadge(252, 98, 60, 11, planPill, C_ACCENT, C_ACCENT_SOFT, 0, 1);

  tft.fillRect(8, 111, 304, 42, C_CARD);

  float rxPct = constrain((neta.rxMbps * 100.0f) / (float)plan, 0.0f, 100.0f);
  float txPct = constrain((neta.txMbps * 100.0f) / (float)plan, 0.0f, 100.0f);

  // Linha RX (Cyan)
  drawPillBadge(8, 113, 24, 14, "RX", C_COOL, blend565(C_CARD, C_COOL, 45), C_COOL, 1);
  char rxVal[20];
  snprintf(rxVal, sizeof(rxVal), "%.1f Mbps", neta.rxMbps);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(rxVal, 36, 120, 2);
  drawSlimBar(132, 117, 142, 6, rxPct, C_COOL, C_TRACK);
  char rxPctStr[10];
  snprintf(rxPctStr, sizeof(rxPctStr), "%d%%", (int)(rxPct + 0.5f));
  tft.setTextDatum(MR_DATUM);
  tft.setTextColor(C_COOL, C_CARD);
  tft.drawString(rxPctStr, 308, 120, 1);

  // Linha TX (Rose/Amber)
  drawPillBadge(8, 134, 24, 14, "TX", C_PINK, blend565(C_CARD, C_PINK, 45), C_PINK, 1);
  char txVal[20];
  snprintf(txVal, sizeof(txVal), "%.1f Mbps", neta.txMbps);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(txVal, 36, 141, 2);
  drawSlimBar(132, 138, 142, 6, txPct, C_PINK, C_TRACK);
  char txPctStr[10];
  snprintf(txPctStr, sizeof(txPctStr), "%d%%", (int)(txPct + 0.5f));
  tft.setTextDatum(MR_DATUM);
  tft.setTextColor(C_PINK, C_CARD);
  tft.drawString(txPctStr, 308, 141, 1);

  // --- 4) Bottom card: FIBER SPEEDTEST (x=4 y=160 w=312 h=59) ---
  if (neta.spdRun) {
    drawPillBadge(238, 162, 74, 11, "TESTANDO...", C_WARN, blend565(C_CARD, C_WARN, 50), C_WARN, 1);
  } else {
    char tmPill[18];
    snprintf(tmPill, sizeof(tmPill), "LAST %s", neta.spdTm[0] ? neta.spdTm : "--:--");
    drawPillBadge(242, 162, 70, 11, tmPill, C_DIM, C_CARD_ELEV, C_CARD_HI, 1);
  }

  tft.fillRect(8, 175, 304, 41, C_CARD);

  if (neta.spdRun) {
    drawPillBadge(10, 180, 108, 28, "TESTANDO...", C_WARN, blend565(C_CARD, C_WARN, 45), C_WARN, 2);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_TEXT, C_CARD);
    tft.drawString("Cloudflare Multi-Stream Fiber", 126, 181, 1);
    drawSlimBar(126, 196, 180, 7, 68.0f, C_PURPLE, C_TRACK);
  } else if (neta.spdDl > 0.0f || neta.spdUl > 0.0f) {
    char dlPill[20], ulPill[20];
    snprintf(dlPill, sizeof(dlPill), "DL %.1fM", neta.spdDl);
    snprintf(ulPill, sizeof(ulPill), "UL %.1fM", neta.spdUl);

    drawPillBadge(8,   178, 116, 34, dlPill, C_OK,   blend565(C_CARD, C_OK, 35),   C_OK,   2);
    drawPillBadge(128, 178, 112, 34, ulPill, C_COOL, blend565(C_CARD, C_COOL, 35), C_COOL, 2);

    int spdPct = constrain((int)((neta.spdDl * 100.0f) / (float)plan), 0, 150);
    uint16_t qCol = (spdPct >= 80) ? C_OK : ((spdPct >= 50) ? C_WARN : C_HOT);
    char effBuf[16];
    snprintf(effBuf, sizeof(effBuf), "%d%% PLAN", spdPct);
    drawPillBadge(244, 178, 68, 16, effBuf, qCol, C_CARD_ELEV, qCol, 1);
    drawPillBadge(244, 196, 68, 16, neta.spdTm, C_DIM, C_CARD_ELEV, C_CARD_HI, 1);
  } else {
    drawPillBadge(8,   178, 106, 34, "DL -- M",   C_OK,     C_CARD_ELEV,   C_CARD_HI, 2);
    drawPillBadge(118, 178, 106, 34, "UL -- M",   C_COOL,   C_CARD_ELEV,   C_CARD_HI, 2);
    drawPillBadge(228, 178, 84,  34, "cyd speed", C_PURPLE, C_ACCENT_SOFT, C_PURPLE,  1);
  }
  tft.setTextPadding(0);
}

// ======================================= Modulo 5: SCR_SECURITY (Tela 14) ===
void screenSecurityStatic() {
  isMatrixRain = false;
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  tft.fillScreen(C_BG);
  drawHeader();
  drawClock();

  // 1) Top-left card (x=4 y=26 w=154 h=60): SOC / IDS SHIELD
  drawModernCard(4, 26, 154, 60, "SOC / IDS SHIELD", C_ACCENT);

  // 2) Top-right card (x=162 y=26 w=154 h=60): IDS TELEMETRY
  drawModernCard(162, 26, 154, 60, "IDS TELEMETRY", C_PURPLE);

  // 3) Bottom card (x=4 y=90 w=312 h=129): SECURITY & SYSTEM EVENTS
  drawModernCard(4, 90, 312, 129, "SECURITY & SYSTEM EVENTS", C_ACCENT);

  sec.dirty = true;
}

static void drawShieldIcon(int16_t cx, int16_t cy, uint16_t col, uint16_t bg) {
  // Escudo tatico vetorial com contorno duplo (22x26)
  uint16_t softFill = blend565(bg, col, 45);
  // Contorno externo
  tft.fillRoundRect(cx - 11, cy - 12, 22, 14, 3, col);
  tft.fillTriangle(cx - 11, cy + 1, cx + 10, cy + 1, cx, cy + 13, col);
  // Miolo intermediario escuro
  tft.fillRoundRect(cx - 9, cy - 10, 18, 11, 2, bg);
  tft.fillTriangle(cx - 9, cy, cx + 8, cy, cx, cy + 10, bg);
  // Nucleo interno levemente tonalizado
  tft.fillRoundRect(cx - 7, cy - 8, 14, 9, 2, softFill);
  tft.fillTriangle(cx - 7, cy, cx + 6, cy, cx, cy + 8, softFill);

  if (sec.level == 0) {
    // Emblem Check (SEGURO)
    tft.drawLine(cx - 4, cy, cx - 1, cy + 3, col);
    tft.drawLine(cx - 1, cy + 3, cx + 4, cy - 3, col);
    tft.drawLine(cx - 4, cy + 1, cx - 1, cy + 4, col);
    tft.drawLine(cx - 1, cy + 4, cx + 4, cy - 2, col);
  } else if (sec.level == 1) {
    // Emblem Exclamacao (ATENCAO)
    tft.fillRect(cx - 1, cy - 6, 2, 6, col);
    tft.fillRect(cx - 1, cy + 2, 2, 2, col);
  } else {
    // Emblem X Critico (INVASAO!)
    tft.drawLine(cx - 4, cy - 4, cx + 4, cy + 4, col);
    tft.drawLine(cx - 3, cy - 4, cx + 4, cy + 3, col);
    tft.drawLine(cx + 4, cy - 4, cx - 4, cy + 4, col);
    tft.drawLine(cx + 3, cy - 4, cx - 4, cy + 3, col);
  }
}

void screenSecurityDynamic() {
  static uint8_t lastCritFlash = 255;
  uint8_t critFlash = (sec.level >= 2) ? (uint8_t)((millis() / 400) % 2) : 0;
  if (!sec.dirty && (sec.level < 2 || critFlash == lastCritFlash)) return;
  sec.dirty = false;
  lastCritFlash = critFlash;

  // --- 1) Top-left card: SOC / IDS SHIELD (x=4 y=26 w=154 h=60) ---
  tft.fillRect(8, 39, 146, 44, C_CARD);

  uint16_t lvlCol   = C_OK;
  uint16_t pillBg   = blend565(C_CARD, C_OK, 45);
  uint16_t pillBd   = C_OK;
  const char* stTxt = sec.status[0] ? sec.status : "SEGURO";

  if (sec.level == 1) {
    lvlCol = C_WARN;
    pillBg = blend565(C_CARD, C_WARN, 45);
    pillBd = C_WARN;
    stTxt  = "ATENCAO";
  } else if (sec.level >= 2) {
    lvlCol = critFlash ? 0xFFFF : C_HOT;
    pillBg = critFlash ? C_HOT : blend565(C_CARD, C_HOT, 75);
    pillBd = 0xFFFF;
    stTxt  = "INVASAO!";
  }

  drawShieldIcon(22, 60, (sec.level >= 2) ? C_HOT : lvlCol, C_CARD);
  drawPillBadge(40, 41, 112, 20, stTxt, lvlCol, pillBg, pillBd, 2);

  // Last attacker IP highlighted cleanly
  char ipBadge[26];
  uint16_t ipFg = C_DIM;
  uint16_t ipBg = C_CARD_ELEV;
  uint16_t ipBd = C_CARD_HI;
  if (sec.lastIp[0] && strcmp(sec.lastIp, "---") != 0) {
    snprintf(ipBadge, sizeof(ipBadge), "IP %s", sec.lastIp);
    ipFg = (sec.level >= 2) ? C_HOT : ((sec.level == 1) ? C_WARN : C_COOL);
    ipBg = blend565(C_CARD, ipFg, 35);
    ipBd = ipFg;
  } else {
    snprintf(ipBadge, sizeof(ipBadge), "SYNC %s", sec.lastTime[0] ? sec.lastTime : "--:--");
  }
  drawPillBadge(40, 65, 112, 16, ipBadge, ipFg, ipBg, ipBd, 1);

  // --- 2) Top-right card: IDS TELEMETRY 2x2 KPI Grid (x=162 y=26 w=154 h=60) ---
  tft.fillRect(166, 39, 146, 44, C_CARD);

  auto drawIdsKpiPill = [&](int16_t x, int16_t y, int16_t w, int16_t h,
                            const char* label, const char* valStr, bool active, uint16_t alertCol) {
    uint16_t fg = active ? alertCol : C_OK;
    uint16_t bg = active ? blend565(C_CARD, alertCol, 45) : C_CARD_ELEV;
    uint16_t bd = active ? alertCol : C_CARD_HI;
    char cellTxt[20];
    snprintf(cellTxt, sizeof(cellTxt), "%s %s", label, valStr);
    drawPillBadge(x, y, w, h, cellTxt, fg, bg, bd, 1);
  };

  char vAuth[10], vErrs[10], vScan[10], vLanPort[12];
  snprintf(vAuth,    sizeof(vAuth),    "%u", (unsigned)sec.authFails);
  snprintf(vErrs,    sizeof(vErrs),    "%u", (unsigned)sec.sysErrors);
  snprintf(vScan,    sizeof(vScan),    "%u", (unsigned)sec.portScans);
  snprintf(vLanPort, sizeof(vLanPort), "%u/%u", (unsigned)sec.unknownLan, (unsigned)sec.openPorts);

  drawIdsKpiPill(167, 41, 70, 18, "AUTH",     vAuth,    sec.authFails > 0,  C_HOT);
  drawIdsKpiPill(241, 41, 70, 18, "ERRS",     vErrs,    sec.sysErrors > 0,  C_WARN);
  drawIdsKpiPill(167, 63, 70, 18, "SCAN",     vScan,    sec.portScans > 0,  C_HOT);
  drawIdsKpiPill(241, 63, 70, 18, "LAN/PORT", vLanPort, sec.unknownLan > 0, C_WARN);

  // --- 3) Bottom card: SECURITY & SYSTEM EVENTS (x=4 y=90 w=312 h=129) ---
  char connPill[20];
  snprintf(connPill, sizeof(connPill), "EXT:%u", (unsigned)sec.extConns);
  drawPillBadge(262, 92, 50, 11, connPill, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);

  tft.fillRect(7, 105, 306, 111, C_CARD);

  if (sec.logCount == 0) {
    drawPillBadge(88, 136, 144, 22, "PERIMETRO SEGURO", C_OK, blend565(C_CARD, C_OK, 35), C_OK, 2);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString("Monitorando SSH, Sudo, Firewall, ARP e Logs", SCR_W / 2, 174, 1);
    tft.setTextPadding(0);
    return;
  }

  const int rowH = 18;
  for (uint8_t i = 0; i < sec.logCount && i < SEC_MAX_LOGS; i++) {
    int ry = 106 + i * rowH;
    const SecLogEntry& e = sec.logs[i];

    const char* sevTxt = "INFO";
    uint16_t sevFg = C_COOL;
    uint16_t sevBg = blend565(C_CARD, C_COOL, 35);
    uint16_t sevBd = 0;
    uint16_t msgCol = C_TEXT;

    if (e.sev == 1) {
      sevTxt = "WARN";
      sevFg  = C_WARN;
      sevBg  = blend565(C_CARD, C_WARN, 45);
      sevBd  = C_WARN;
    } else if (e.sev >= 2) {
      sevTxt = "CRIT";
      sevFg  = 0xFFFF;
      sevBg  = C_HOT;
      sevBd  = C_HOT;
      msgCol = C_HOT;
    }

    // Pill de severidade (CRIT / WARN / INFO)
    drawPillBadge(9, ry + 2, 30, 13, sevTxt, sevFg, sevBg, sevBd, 1);

    // Timestamp HH:MM em C_DIM
    tft.setTextDatum(ML_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(e.hm, 43, ry + 8, 1);

    // Mensagem crisp C_TEXT (truncada para caber perfeitamente em 230px -> ~38 chars)
    char cleanMsg[39];
    snprintf(cleanMsg, sizeof(cleanMsg), "%.38s", e.msg);
    tft.setTextColor(msgCol, C_CARD);
    tft.drawString(cleanMsg, 77, ry + 8, 1);

    // Separador sutil entre linhas
    if (i + 1 < sec.logCount && i + 1 < SEC_MAX_LOGS) {
      tft.drawFastHLine(10, ry + rowH - 1, 300, C_CARD_ELEV);
    }
  }
  tft.setTextPadding(0);
}
