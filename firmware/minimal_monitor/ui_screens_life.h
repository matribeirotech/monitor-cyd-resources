// ui_screens_life.h - CYD OS v5.0 Finance, Productivity, Media, Weather & News Screens (Telas 6..10)
#pragma once

// ======================================= TELA 6: MERCADO FINANCEIRO & CRIPTO =
// Modern Dark Finance Terminal (TradingView / Bloomberg style):
//   - Top (3 KPI Cards, y=27..79): USD/BRL, EUR/BRL, IBOVESPA with Delta Badges
//   - Bottom-Left (x=6 y=83 w=162 h=136): CRYPTO 24H Watchlist (ETH, SOL, BNB, XRP, S&P500)
//   - Bottom-Right (x=172 y=83 w=142 h=136): BITCOIN Hero + 24h Area Sparkline

static void drawWatchlistRow(int y, const char* sym, float price, float chgPct, bool isIndex = false) {
  uint16_t trendCol = (chgPct >= 0.0f) ? C_OK : C_HOT;

  // Vertical trend indicator bar
  tft.fillRoundRect(12, y + 2, 3, 15, 1, trendCol);

  // Ticker symbol
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(isIndex ? C_PURPLE : C_ACCENT, C_CARD);
  tft.setTextPadding(32);
  tft.drawString(sym, 18, y + 9, 2);

  // Price readout (crisp off-white)
  char pBuf[20];
  if (isIndex) {
    if (price > 0.0f) snprintf(pBuf, sizeof(pBuf), "%.0f", price);
    else              snprintf(pBuf, sizeof(pBuf), "----");
  } else {
    if (price >= 1000.0f)     snprintf(pBuf, sizeof(pBuf), "$%.0f", price);
    else if (price >= 10.0f)  snprintf(pBuf, sizeof(pBuf), "$%.2f", price);
    else if (price > 0.0f)    snprintf(pBuf, sizeof(pBuf), "$%.3f", price);
    else                      snprintf(pBuf, sizeof(pBuf), "$---");
  }

  tft.setTextColor(C_TEXT, C_CARD);
  tft.setTextPadding(58);
  tft.drawString(pBuf, 52, y + 9, 2);
  tft.setTextPadding(0);

  // 24h change pill
  drawDeltaBadge(114, y + 2, 48, 15, chgPct);
}

void plotBtcSparkline(int x, int y, int w, int h) {
  tft.fillRect(x, y, w, h, C_CARD);
  uint16_t col     = (mkt.btcc >= 0.0f) ? C_OK : C_HOT;
  uint16_t areaTop = blend565(C_CARD, col, 64);
  uint16_t areaBot = blend565(C_CARD, col, 24);

  // Subtle horizontal dotted gridlines
  for (int i = 1; i < 4; i++) {
    int gy = y + (h * i) / 4;
    for (int gx = x; gx < x + w; gx += 6) {
      tft.drawPixel(gx, gy, C_TRACK);
    }
  }

  int n = mkt.hBtcCount;
  if (n >= 2) {
    int prevX = -1, prevY = -1;
    int lastX = x,  lastY = y + h / 2;
    int midY  = y + h / 2;

    for (int i = 0; i < n; i++) {
      int px = x + (i * (w - 4)) / (n - 1);
      int v  = constrain((int)mkt.hBtc[i], 0, 100);
      int py = y + h - 3 - ((h - 6) * v) / 100;

      if (prevX >= 0) {
        int span = max(1, px - prevX);
        for (int fx = prevX; fx <= px; fx++) {
          int fy = prevY + ((py - prevY) * (fx - prevX)) / span;
          int splitY = max(fy, midY);
          if (splitY > fy) {
            tft.drawFastVLine(fx, fy, splitY - fy, areaTop);
          }
          if (y + h > splitY) {
            tft.drawFastVLine(fx, splitY, y + h - splitY, areaBot);
          }
        }
        tft.drawLine(prevX, prevY, px, py, col);
        if (py + 1 < y + h) {
          tft.drawLine(prevX, prevY + 1, px, py + 1, col);
        }
      }
      prevX = px;
      prevY = py;
      lastX = px;
      lastY = py;
    }

    // Glowing current-price indicator dot at latest sample
    tft.fillCircle(lastX, lastY, 3, blend565(C_CARD, col, 110));
    tft.fillCircle(lastX, lastY, 2, col);
    tft.drawPixel(lastX, lastY, C_TEXT);
  } else {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString("Aguardando dados BTC...", x + w / 2, y + h / 2, 1);
  }
}

void screenMarketStatic() {
  renderBackground();
  drawHeader();

  // Top 3 KPI Cards (y=27..79, h=52)
  drawModernCard(6,   27, 100, 52, "USD / BRL", C_OK);
  drawModernCard(110, 27, 100, 52, "EUR / BRL", C_COOL);
  drawModernCard(214, 27, 100, 52, "IBOVESPA",  C_PURPLE);

  // Bottom-Left: Crypto & Index 24h Watchlist (x=6, y=83, w=162, h=136)
  drawModernCard(6, 83, 162, 136, "CRYPTO 24H", C_COOL);
  for (int i = 1; i < 5; i++) {
    int divY = 100 + i * 23 - 2;
    tft.drawFastHLine(12, divY, 150, C_TRACK);
  }

  // Bottom-Right: Bitcoin Hero + 24h Sparkline (x=172, y=83, w=142, h=136)
  drawModernCard(172, 83, 142, 136, "BITCOIN", C_WARN);
}

void screenMarketDynamic() {
  char buf[32];

  // ---- Card 1: USD/BRL ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(84);
  tft.setTextColor(C_TEXT, C_CARD);
  if (mkt.usd > 0.0f) snprintf(buf, sizeof(buf), "R$ %.2f", mkt.usd);
  else                snprintf(buf, sizeof(buf), "R$ --.--");
  tft.drawString(buf, 14, 43, 2);
  tft.setTextPadding(0);
  drawDeltaBadge(14, 61, 84, 14, mkt.usdc);

  // ---- Card 2: EUR/BRL ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(84);
  tft.setTextColor(C_TEXT, C_CARD);
  if (mkt.eur > 0.0f) snprintf(buf, sizeof(buf), "R$ %.2f", mkt.eur);
  else                snprintf(buf, sizeof(buf), "R$ --.--");
  tft.drawString(buf, 118, 43, 2);
  tft.setTextPadding(0);
  drawDeltaBadge(118, 61, 84, 14, mkt.eurc);

  // ---- Card 3: IBOVESPA ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(84);
  tft.setTextColor(C_TEXT, C_CARD);
  if (mkt.ibov > 0.0f) snprintf(buf, sizeof(buf), "%.1fk pts", mkt.ibov / 1000.0f);
  else                 snprintf(buf, sizeof(buf), "---k pts");
  tft.drawString(buf, 222, 43, 2);
  tft.setTextPadding(0);
  drawDeltaBadge(222, 61, 84, 14, mkt.ibovc);

  // ---- Bottom-Left: Watchlist Rows (ETH, SOL, BNB, XRP, S&P500) ----
  const int baseY = 100;
  drawWatchlistRow(baseY + 0,  "ETH", mkt.eth,   mkt.ethc,   false);
  drawWatchlistRow(baseY + 23, "SOL", mkt.sol,   mkt.solc,   false);
  drawWatchlistRow(baseY + 46, "BNB", mkt.bnb,   mkt.bnbc,   false);
  drawWatchlistRow(baseY + 69, "XRP", mkt.xrp,   mkt.xrpc,   false);
  drawWatchlistRow(baseY + 92, "S&P", mkt.sp500, mkt.sp500c, true);

  // ---- Bottom-Right: BITCOIN Hero Card ----
  drawDeltaBadge(254, 86, 54, 13, mkt.btcc);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(126);
  tft.setTextColor(C_TEXT, C_CARD);
  if (mkt.btc >= 1000.0f) {
    int k   = (int)(mkt.btc / 1000.0f);
    int rem = (int)(mkt.btc) % 1000;
    snprintf(buf, sizeof(buf), "$%d,%03d", k, rem);
  } else if (mkt.btc > 0.0f) {
    snprintf(buf, sizeof(buf), "$%.0f", mkt.btc);
  } else {
    snprintf(buf, sizeof(buf), "$--,---");
  }
  tft.drawString(buf, 180, 101, 4);

  tft.setTextColor(C_DIM, C_CARD);
  tft.setTextPadding(126);
  if (mkt.btc_brl > 0.0f) snprintf(buf, sizeof(buf), "BRL: R$ %.1f mil", mkt.btc_brl / 1000.0f);
  else                    snprintf(buf, sizeof(buf), "BRL: R$ --- mil");
  tft.drawString(buf, 180, 126, 2);
  tft.setTextPadding(0);

  plotBtcSparkline(180, 145, 126, 68);
}

// ======================================= TELA 7: PORTFOLIO PESSOAL ===========
// Modern Fintech Wealth Card:
//   - Left Hero Card (x=6 y=27 w=182 h=192): Total Balance, PnL Hero Pill, 24h Pill, Allocation Strip
//   - Right Card (x=192 y=27 w=122 h=192): TOP 3 ATIVOS nested elevated tiles + slim bars + delta pills

void screenPortfolioStatic() {
  renderBackground();
  drawHeader();

  // Left Hero Card: Patrimonio Consolidado
  drawModernCard(6, 27, 182, 192, "PATRIMONIO", C_ACCENT);

  // Right Card: Top 3 Ativos
  drawModernCard(192, 27, 122, 192, "TOP 3 ATIVOS", C_PURPLE);
  for (int i = 0; i < 3; i++) {
    int ry = 45 + i * 57;
    tft.fillRoundRect(198, ry, 110, 52, 5, C_CARD_ELEV);
    tft.drawRoundRect(198, ry, 110, 52, 5, C_CARD_HI);
  }
}

void screenPortfolioDynamic() {
  char buf[48];

  // Active asset count badge in top-right of left card
  uint8_t nAssets = portf.count > 0 ? portf.count : portf.topCount;
  snprintf(buf, sizeof(buf), "%u ATIVOS", (unsigned)nAssets);
  drawPillBadge(122, 30, 58, 13, buf, C_ACCENT, C_ACCENT_SOFT, C_CARD_HI, 1);

  // ---- 1) Total Consolidated Balance (Font 4) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("SALDO TOTAL CONSOLIDADO", 14, 46, 1);

  tft.setTextPadding(166);
  tft.setTextColor(C_TEXT, C_CARD);
  if (!portf.valid) {
    snprintf(buf, sizeof(buf), "R$ 0.00");
  } else if (portf.tot >= 1000000.0f) {
    snprintf(buf, sizeof(buf), "R$ %.2fM", portf.tot / 1000000.0f);
  } else if (portf.tot >= 100000.0f) {
    snprintf(buf, sizeof(buf), "R$ %.0f", portf.tot);
  } else {
    snprintf(buf, sizeof(buf), "R$ %.2f", portf.tot);
  }
  tft.drawString(buf, 14, 57, 4);
  tft.setTextPadding(0);

  // ---- 2) Prominent Emerald/Coral PnL Hero Pill ----
  int8_t curSign = (portf.pnl_val >= 0.0f) ? 1 : -1;
  uint16_t pnlFg = (curSign >= 0) ? C_OK : C_HOT;
  uint16_t pnlBg = blend565(C_CARD, pnlFg, 36);
  uint16_t pnlBd = blend565(C_CARD_HI, pnlFg, 110);
  const int boxX = 14, boxY = 86, boxW = 166, boxH = 40;

  if (curSign != gLastPortfSign) {
    tft.fillRoundRect(boxX, boxY, boxW, boxH, 5, pnlBg);
    tft.drawRoundRect(boxX, boxY, boxW, boxH, 5, pnlBd);
    gLastPortfSign = curSign;
  }

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(150);
  tft.setTextColor(pnlFg, pnlBg);
  tft.drawString(curSign >= 0 ? "RESULTADO: LUCRO (PnL)" : "RESULTADO: PREJUIZO (PnL)", boxX + 8, boxY + 5, 1);

  tft.setTextPadding(90);
  tft.setTextColor(C_TEXT, pnlBg);
  float absPnl = fabsf(portf.pnl_val);
  if (absPnl >= 100000.0f) {
    snprintf(buf, sizeof(buf), "%sR$ %.1fk", curSign >= 0 ? "+" : "-", absPnl / 1000.0f);
  } else {
    snprintf(buf, sizeof(buf), "%sR$ %.2f", curSign >= 0 ? "+" : "-", absPnl);
  }
  tft.drawString(buf, boxX + 8, boxY + 18, 2);
  tft.setTextPadding(0);

  drawDeltaBadge(boxX + 104, boxY + 18, 56, 16, portf.pnl_pct);

  // ---- 3) 24H Daily Change Pill + USD Reference Pill ----
  uint16_t dayCol = (portf.day_pct >= 0.0f) ? C_OK : C_HOT;
  snprintf(buf, sizeof(buf), "24H: %s%.2f%%", portf.day_pct >= 0.0f ? "+" : "", portf.day_pct);
  drawPillBadge(14, 131, 96, 15, buf, dayCol, C_CARD_ELEV, blend565(C_CARD_HI, dayCol, 80), 1);

  if (mkt.usd > 0.0f) snprintf(buf, sizeof(buf), "USD %.2f", mkt.usd);
  else                snprintf(buf, sizeof(buf), "USD --.--");
  drawPillBadge(114, 131, 66, 15, buf, C_COOL, C_CARD_ELEV, C_CARD_HI, 1);

  // ---- 4) Mini Allocation Segmented Strip (Top 3 Weights) ----
  const uint16_t rankCols[3] = {C_ACCENT, C_COOL, C_PURPLE};
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("ALOCACAO TOP 3", 14, 153, 1);

  const int barX = 14, barY = 165, barW = 166, barH = 10;
  tft.fillRoundRect(barX, barY, barW, barH, 3, C_TRACK);
  if (portf.valid && portf.topCount > 0) {
    int curX = barX + 1;
    int maxRight = barX + barW - 1;
    for (int i = 0; i < portf.topCount && i < 3; i++) {
      float wPct = portf.top3w[i];
      if (wPct <= 0.0f) wPct = 100.0f / (float)portf.topCount;
      int segW = (int)(((barW - 2) * constrain(wPct, 0.0f, 100.0f)) / 100.0f);
      if (curX + segW > maxRight) segW = maxRight - curX;
      if (segW > 2) {
        tft.fillRect(curX, barY + 1, segW - 1, barH - 2, rankCols[i]);
        curX += segW;
      }
    }
  }
  tft.drawRoundRect(barX, barY, barW, barH, 3, C_CARD_HI);

  // Legend row & sync status at bottom of left card
  for (int i = 0; i < 3; i++) {
    int lx = 14 + i * 56;
    bool hasItem = (portf.valid && i < portf.topCount && strcmp(portf.top3[i], "---") != 0);
    tft.fillCircle(lx + 3, 185, 2, hasItem ? rankCols[i] : C_MUTED);
    tft.setTextDatum(ML_DATUM);
    tft.setTextPadding(46);
    tft.setTextColor(hasItem ? C_TEXT : C_DIM, C_CARD);
    snprintf(buf, sizeof(buf), "%.6s", hasItem ? portf.top3[i] : "---");
    tft.drawString(buf, lx + 8, 185, 1);
  }
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(166);
  tft.setTextColor(C_MUTED, C_CARD);
  tft.drawString(portf.valid ? "Carteira sincronizada em tempo real" : "Cadastre ativos no Agente PC", 14, 199, 1);
  tft.setTextPadding(0);

  // ---- 5) Right Card: 3 Nested Elevated Asset Tiles ----
  for (int i = 0; i < 3; i++) {
    int ry = 45 + i * 57;
    bool hasItem = (portf.valid && i < portf.topCount && strcmp(portf.top3[i], "---") != 0);
    float chg  = hasItem ? lookupPortfolioAssetChange(i) : 0.0f;
    float wPct = (hasItem && portf.top3w[i] > 0.0f) ? constrain(portf.top3w[i], 0.0f, 100.0f)
                                                    : (hasItem && portf.topCount > 0 ? (100.0f / (float)portf.topCount) : 0.0f);

    // Left vertical rank accent bar inside tile
    tft.fillRoundRect(201, ry + 5, 3, 42, 1, hasItem ? rankCols[i] : C_MUTED);

    // Ticker symbol badge
    tft.setTextDatum(TL_DATUM);
    tft.setTextPadding(64);
    tft.setTextColor(hasItem ? C_TEXT : C_DIM, C_CARD_ELEV);
    if (hasItem) snprintf(buf, sizeof(buf), "%d.%s", i + 1, portf.top3[i]);
    else         snprintf(buf, sizeof(buf), "%d.---", i + 1);
    tft.drawString(buf, 208, ry + 4, 2);
    tft.setTextPadding(0);

    // Weight % on top-right of tile
    tft.setTextDatum(TR_DATUM);
    tft.setTextPadding(30);
    tft.setTextColor(hasItem ? rankCols[i] : C_DIM, C_CARD_ELEV);
    if (hasItem) snprintf(buf, sizeof(buf), "%.0f%%", wPct);
    else         snprintf(buf, sizeof(buf), "--%%");
    tft.drawString(buf, 303, ry + 7, 1);
    tft.setTextPadding(0);

    // Slim weight bar
    drawSlimBar(208, ry + 22, 95, 5, wPct, hasItem ? rankCols[i] : C_MUTED, C_TRACK);

    // Live 24h delta badge
    if (hasItem) {
      drawDeltaBadge(208, ry + 31, 95, 16, chg);
    } else {
      drawPillBadge(208, ry + 31, 95, 16, "SEM ATIVO", C_DIM, C_TRACK, 0, 1);
    }
  }
}

// ======================================= TELA 8: POMODORO FOCUS STUDIO =======
// Minimalist Focus Studio:
//   - Left Hero Card (x=6 y=27 w=166 h=192): Smooth circular progress arc (r=62), MM:SS, state pill
//   - Right Card (x=176 y=27 w=138 h=192): Cycle counter pill, glowing cycle dots, progress bar, focus status tile

void screenPomodoroStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   27, 166, 192, "FOCUS STUDIO",    C_ACCENT);
  drawModernCard(176, 27, 138, 192, "SESSAO & CICLOS", C_PURPLE);
  tft.drawFastHLine(184, 96,  122, C_TRACK);
  tft.drawFastHLine(184, 150, 122, C_TRACK);
}

void screenPomodoroDynamic() {
  char buf[52];

  // Local 1-second countdown interpolation between packets
  int32_t effRem = pomo.rem;
  if (pomo.running && pomo.syncMs > 0) {
    uint32_t elap = (millis() - pomo.syncMs) / 1000;
    effRem = (int32_t)pomo.rem - (int32_t)elap;
    if (effRem < 0) effRem = 0;
  }

  // Trigger physical buzzer automatically at 00:00 transition
  if (pomo.running && effRem == 0 && pomo.rem > 0 && !pomo.chimeGuard) {
    pomo.chimeGuard = true;
    bool wasBreak = (strcasecmp(pomo.state, "WORK") != 0);
    triggerAlert(true, wasBreak ? C_OK : C_COOL, 3);
  }

  int32_t totSec = (pomo.tot > 0) ? pomo.tot : 1500;
  float pctDone  = constrain(100.0f * (float)(totSec - effRem) / (float)totSec, 0.0f, 100.0f);

  bool isLong  = (strcasecmp(pomo.state, "LONG") == 0);
  bool isBreak = isLong || (strcasecmp(pomo.state, "BREAK") == 0);
  int8_t phaseCode = !pomo.running ? 0 : (isLong ? 3 : (isBreak ? 2 : 1));

  uint16_t ringCol = C_OK;
  if (!pomo.running) ringCol = C_WARN;
  else if (isLong)   ringCol = C_PURPLE;
  else if (isBreak)  ringCol = C_COOL;

  // ---- Left Card: Large Anti-Aliased Circular Progress Ring (Slot 0 cache) ----
  const int cx = 89, cy = 113, r = 62, ir = 52;
  const int A0 = 30, A1 = 330;
  int aEnd = A0 + (int)((A1 - A0) * pctDone / 100.0f);

  if (gGaugeEnd[0] != aEnd || gGaugeCol[0] != ringCol) {
    if (aEnd > A0 + 1) tft.drawSmoothArc(cx, cy, r, ir, A0, aEnd, ringCol, C_CARD, true);
    if (aEnd < A1 - 1) tft.drawSmoothArc(cx, cy, r, ir, aEnd, A1, C_TRACK, C_CARD, true);
    gGaugeEnd[0] = aEnd;
    gGaugeCol[0] = ringCol;
  }

  // Crisp large MM:SS countdown centered inside ring
  int mm = effRem / 60;
  int ss = effRem % 60;
  snprintf(buf, sizeof(buf), "%02d:%02d", mm, ss);
  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(82);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(buf, cx, cy - 5, 4);

  snprintf(buf, sizeof(buf), "%.0f%% CONCLUIDO", pctDone);
  tft.setTextPadding(84);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(buf, cx, cy + 17, 1);
  tft.setTextPadding(0);

  // State pill below ring + right card header update on phase change
  if (phaseCode != gLastPomoPhase) {
    const char* stPillTxt = !pomo.running ? "PAUSADO" : (isLong ? "PAUSA LONGA" : (isBreak ? "PAUSA" : "EM FOCO"));
    drawPillBadge(39, 193, 100, 17, stPillTxt, ringCol,
                  blend565(C_CARD, ringCol, 38), blend565(C_CARD_HI, ringCol, 110), 1);
    gLastPomoPhase = phaseCode;
    drawClock();
  }

  // ---- Right Card Section 1: Cycle Counter Badge & Visual Cycle Dots ----
  snprintf(buf, sizeof(buf), "CICLOS: #%u", (unsigned)pomo.cycles);
  drawPillBadge(184, 45, 122, 20, buf, C_TEXT, C_CARD_ELEV, C_CARD_HI, 2);

  uint8_t modCyc = pomo.cycles % 4;
  if (pomo.cycles > 0 && modCyc == 0 && isLong) modCyc = 4;
  for (int i = 0; i < 4; i++) {
    int dx = 200 + i * 30;
    int dy = 79;
    tft.fillRect(dx - 9, dy - 9, 19, 19, C_CARD);
    if (i < modCyc) {
      tft.drawCircle(dx, dy, 8, blend565(C_CARD, C_OK, 90));
      tft.fillCircle(dx, dy, 6, C_OK);
      tft.fillCircle(dx - 2, dy - 2, 1, C_TEXT);
    } else if (i == modCyc && !isBreak && pomo.running) {
      tft.fillCircle(dx, dy, 6, ringCol);
      tft.fillCircle(dx, dy, 3, C_CARD);
      tft.drawPixel(dx, dy, C_TEXT);
    } else {
      tft.fillCircle(dx, dy, 6, C_CARD_ELEV);
      tft.drawCircle(dx, dy, 6, C_MUTED);
    }
  }

  // ---- Right Card Section 2: Session Duration & Progress Bar ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("SESSAO", 184, 102, 1);

  snprintf(buf, sizeof(buf), "%ldm | %.0f%%", (long)(totSec / 60), pctDone);
  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(buf, 306, 102, 1);
  tft.setTextPadding(0);

  drawSlimBar(184, 114, 122, 8, pctDone, ringCol, C_TRACK);

  int32_t elapSec = max((int32_t)0, totSec - effRem);
  snprintf(buf, sizeof(buf), "DECORRIDO %02d:%02d", (int)(elapSec / 60), (int)(elapSec % 60));
  drawPillBadge(184, 127, 122, 16, buf, C_DIM, C_CARD_ELEV, 0, 1);

  // ---- Right Card Section 3: Motivational Focus / Active Media Badge ----
  tft.fillRoundRect(184, 156, 122, 36, 5, C_CARD_ELEV);
  tft.drawRoundRect(184, 156, 122, 36, 5, blend565(C_CARD_HI, ringCol, 70));

  if (mediaSt.valid && strcasecmp(mediaSt.source, "NONE") != 0) {
    uint16_t mCol = getMediaAccentColor();
    tft.setTextDatum(TL_DATUM);
    tft.setTextPadding(110);
    tft.setTextColor(mCol, C_CARD_ELEV);
    snprintf(buf, sizeof(buf), "%s %s", mediaSt.playing ? "|>" : "||", mediaSt.source);
    tft.drawString(buf, 190, 161, 1);

    tft.setTextColor(C_TEXT, C_CARD_ELEV);
    snprintf(buf, sizeof(buf), "%.18s", mediaSt.title);
    tft.drawString(buf, 190, 175, 1);
    tft.setTextPadding(0);
  } else {
    tft.setTextDatum(MC_DATUM);
    tft.setTextPadding(112);
    tft.setTextColor(ringCol, C_CARD_ELEV);
    const char* fTitle = !pomo.running ? "PRONTO P/ FOCO" : (isBreak ? "PAUSA ATIVA" : "DEEP WORK MODE");
    tft.drawString(fTitle, 245, 166, 1);

    tft.setTextColor(C_DIM, C_CARD_ELEV);
    tft.drawString(isBreak ? "Respire e descanse" : "Foco total na tarefa", 245, 180, 1);
    tft.setTextPadding(0);
  }

  // Subtle PC health footer line
  snprintf(buf, sizeof(buf), "CPU %.0f%%   |   RAM %.0f%%", st.cpu, st.ram);
  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(122);
  tft.setTextColor(C_MUTED, C_CARD);
  tft.drawString(buf, 245, 204, 1);
  tft.setTextPadding(0);
}

// ======================================= TELA 9: HUB MULTIMIDIA (NOW PLAYING) =
// Modern Now Playing (Spotify / Apple Music Dark UI):
//   - SD Cover Art backdrop with real-time smoked glass overlay (or geometric vinyl studio emblem)
//   - Floating Dark Glass Card (x=8 y=136 w=304 h=82): Source pill, track title, artist/album,
//     slim playback progress bar with glowing playhead dot, timestamps, and animated 4-bar equalizer

void drawMediaBackdropAndOverlay() {
  bool coverDrawn = false;
  if (initOrVerifySD() && mediaSt.coverFile[0]) {
    String cPath = resolveSdPath(mediaSt.coverFile);
    if (cPath.length() > 0 && SD.exists(cPath)) {
      gMediaOverlayMode = true;
      uint16_t res = TJpgDec.drawSdJpg(0, 0, cPath.c_str());
      gMediaOverlayMode = false;
      if (res == 0) {
        coverDrawn = true;
      }
    }
  }

  uint16_t mCol = getMediaAccentColor();

  if (!coverDrawn) {
    // Sleek Obsidian Studio Stage with Framed Album Art & Geometric Vinyl Emblem
    tft.fillRect(0, HDR_H, SCR_W, TICKER_Y - HDR_H, C_BG);

    // Subtle ambient side soundwave bars
    uint16_t waveCol = blend565(C_BG, mCol, 45);
    for (int i = 0; i < 6; i++) {
      int wh = 10 + (i % 3) * 12;
      tft.fillRoundRect(46 + i * 9, 80 - wh / 2, 4, wh, 2, waveCol);
      tft.fillRoundRect(226 + i * 9, 80 - wh / 2, 4, wh, 2, waveCol);
    }

    // Framed Album Art Box (x=112, y=30, w=96, h=96)
    tft.fillRoundRect(112, 30, 96, 96, 8, C_CARD);
    tft.drawRoundRect(112, 30, 96, 96, 8, blend565(C_CARD_HI, mCol, 85));

    // Vinyl disc grooves & glowing center label
    const int vcx = 160, vcy = 78;
    tft.fillCircle(vcx, vcy, 38, C_CARD_ELEV);
    tft.drawCircle(vcx, vcy, 38, C_CARD_HI);
    tft.drawCircle(vcx, vcy, 31, blend565(C_CARD_ELEV, mCol, 35));
    tft.drawCircle(vcx, vcy, 24, blend565(C_CARD_ELEV, mCol, 55));
    tft.fillCircle(vcx, vcy, 14, mCol);
    tft.drawCircle(vcx, vcy, 10, blend565(mCol, C_TEXT, 90));
    tft.fillCircle(vcx, vcy, 3, C_BG);

    // Floating dark glass card surface
    tft.fillRoundRect(8, 136, SCR_W - 16, 82, 7, C_CARD);
  }

  drawHeader();
  drawClock();

  // Luminous glass border over smoked overlay (x=8, y=136, w=304, h=82)
  tft.drawRoundRect(8, 136, SCR_W - 16, 82, 7, blend565(C_CARD_HI, mCol, 110));
  tft.drawFastHLine(20, 136, SCR_W - 40, mCol);

  // Source Platform Pill (SPOTIFY green / YT MUSIC red / MEDIA)
  const char* srcTxt = (strcasecmp(mediaSt.source, "NONE") == 0 || !mediaSt.source[0])
                         ? "WINDOWS MEDIA" : mediaSt.source;
  int pillW = max(64, (int)strlen(srcTxt) * 6 + 16);
  uint16_t pillFg = (strcasecmp(mediaSt.source, "YT MUSIC") == 0) ? C_TEXT : 0x0000;
  drawPillBadge(16, 142, pillW, 14, srcTxt, pillFg, mCol, 0, 1);

  // Track Title & Artist+Album drawn with transparent background over glass
  char cleanTitle[48], cleanArtist[40], cleanAlbum[36];
  sanitizeAscii(cleanTitle,  mediaSt.title,  sizeof(cleanTitle));
  sanitizeAscii(cleanArtist, mediaSt.artist, sizeof(cleanArtist));
  sanitizeAscii(cleanAlbum,  mediaSt.album,  sizeof(cleanAlbum));

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_TEXT);
  char line1[40];
  snprintf(line1, sizeof(line1), "%.33s", cleanTitle[0] ? cleanTitle : "Nenhuma midia ativa");
  tft.drawString(line1, 16, 160, 2);

  tft.setTextColor(C_DIM);
  char line2[46];
  if (cleanAlbum[0]) {
    snprintf(line2, sizeof(line2), "%.20s  -  %.16s", cleanArtist, cleanAlbum);
  } else {
    snprintf(line2, sizeof(line2), "%.36s", cleanArtist[0] ? cleanArtist : "Spotify / YouTube Music");
  }
  tft.drawString(line2, 16, 179, 2);

  gLastMediaFillW = -1;
}

void screenMediaStatic() {
  if (isGifPlaying) {
    gif.close();
    isGifPlaying = false;
  }
  snprintf(gLastMediaSig, sizeof(gLastMediaSig), "%s|%s|%s|%s",
           mediaSt.source, mediaSt.coverId, mediaSt.title, mediaSt.artist);
  gLastMediaPlay = !mediaSt.playing;
  drawMediaBackdropAndOverlay();
}

void screenMediaDynamic() {
  char curSig[128];
  snprintf(curSig, sizeof(curSig), "%s|%s|%s|%s",
           mediaSt.source, mediaSt.coverId, mediaSt.title, mediaSt.artist);

  if (strcmp(curSig, gLastMediaSig) != 0) {
    strlcpy(gLastMediaSig, curSig, sizeof(gLastMediaSig));
    drawMediaBackdropAndOverlay();
    gLastMediaPlay = !mediaSt.playing;
  }

  uint16_t mCol = getMediaAccentColor();

  // Play / Pause status pill
  if (mediaSt.playing != gLastMediaPlay || gLastMediaFillW < 0) {
    gLastMediaPlay = mediaSt.playing;
    uint16_t stFg = mediaSt.playing ? mCol : C_WARN;
    uint16_t stBg = blend565(C_CARD, stFg, 35);
    drawPillBadge(214, 142, 62, 14, mediaSt.playing ? "|> PLAY" : "|| PAUSE",
                  stFg, stBg, blend565(C_CARD_HI, stFg, 90), 1);
  }

  // Animated 4-bar mini equalizer on top-right of glass card (x=280, y=142, w=24, h=14)
  tft.fillRoundRect(280, 142, 24, 14, 3, C_CARD_ELEV);
  uint32_t eqTick = millis() / 130;
  for (int i = 0; i < 4; i++) {
    int bx = 283 + i * 5;
    int bh = 2;
    if (mediaSt.playing) {
      uint32_t phase = (eqTick + (uint32_t)(i * 3)) % 6;
      const int eqLut[6] = {3, 8, 10, 6, 11, 5};
      bh = eqLut[phase];
    }
    int by = 154 - bh;
    tft.fillRect(bx, by, 3, bh, mediaSt.playing ? mCol : C_MUTED);
    if (mediaSt.playing && bh >= 6) {
      tft.drawFastHLine(bx, by, 3, C_TEXT);
    }
  }

  // Smooth playback position interpolation
  int32_t effPos = mediaSt.pos;
  if (mediaSt.playing && mediaSt.syncMs > 0) {
    effPos += (int32_t)((millis() - mediaSt.syncMs) / 1000);
  }
  if (mediaSt.dur > 0 && effPos > mediaSt.dur) effPos = mediaSt.dur;
  if (effPos < 0) effPos = 0;

  // Sleek playback progress bar with glowing playhead dot
  const int barX = 16, barY = 203, barW = 192, barH = 6;
  float pct = (mediaSt.dur > 0) ? constrain((float)effPos / (float)mediaSt.dur, 0.0f, 1.0f) : 0.0f;
  int fillW = (int)((barW - 2) * pct);
  if (fillW != gLastMediaFillW) {
    tft.fillRoundRect(barX - 3, barY - 3, barW + 7, barH + 6, 4, C_CARD);
    drawSlimBar(barX, barY, barW, barH, pct * 100.0f, mCol, C_TRACK);
    int dotX = barX + constrain(fillW, 3, barW - 3);
    int dotY = barY + barH / 2;
    tft.fillCircle(dotX, dotY, 4, mCol);
    tft.fillCircle(dotX, dotY, 2, C_TEXT);
    gLastMediaFillW = fillW;
  }

  // MM:SS / MM:SS timestamp pill
  char tBuf[28];
  if (mediaSt.dur > 0) {
    snprintf(tBuf, sizeof(tBuf), "%02d:%02d / %02d:%02d",
             (int)(effPos / 60), (int)(effPos % 60),
             (int)(mediaSt.dur / 60), (int)(mediaSt.dur % 60));
  } else {
    snprintf(tBuf, sizeof(tBuf), "%02d:%02d / LIVE", (int)(effPos / 60), (int)(effPos % 60));
  }
  drawPillBadge(216, 199, 88, 14, tBuf, C_TEXT, C_CARD_ELEV, C_CARD_HI, 1);
}

// ======================================= TELA 10: CLIMA & NEWS DESK ==========
// Modern Weather + News Desk:
//   - Top Card (x=6 y=27 w=308 h=74): Vector weather icon, bold white temp hero, condition + feels/min-max pill,
//     date/weekday badge + humidity & rain-prob pills
//   - Bottom Card (x=6 y=105 w=308 h=114): Category topic pill, source + timestamp, queue index pill (1/5),
//     smooth-scrolling newsSpr (C_CARD_ELEV + crisp white text), 3-line summary, rotation progress slim bar

void drawWeatherIcon(int cx, int cy, uint8_t iconType, bool isAlert) {
  tft.fillRoundRect(cx - 23, cy - 21, 46, 42, 6, C_CARD_ELEV);
  tft.drawRoundRect(cx - 23, cy - 21, 46, 42, 6, C_CARD_HI);

  if (isAlert || iconType == 3) {
    // Storm cloud + bright lightning bolt + cyan raindrops
    uint16_t cld = 0x7BEF;
    tft.fillCircle(cx - 8, cy - 5, 8, cld);
    tft.fillCircle(cx + 2, cy - 9, 10, cld);
    tft.fillCircle(cx + 11, cy - 4, 7, cld);
    tft.fillRoundRect(cx - 15, cy - 5, 32, 9, 4, cld);
    // Lightning bolt
    tft.fillTriangle(cx + 2, cy + 1, cx - 5, cy + 10, cx + 1, cy + 10, C_WARN);
    tft.fillTriangle(cx - 1, cy + 9, cx + 5, cy + 9, cx - 3, cy + 18, 0xFFE0);
    // Raindrops
    tft.drawLine(cx - 11, cy + 7, cx - 14, cy + 14, C_COOL);
    tft.drawLine(cx + 11, cy + 7, cx + 8,  cy + 14, C_COOL);
  } else if (iconType == 2) {
    // Cloud + angled cyan rain streaks
    uint16_t cld = 0xAD55;
    tft.fillCircle(cx - 8, cy - 6, 8, cld);
    tft.fillCircle(cx + 2, cy - 10, 10, cld);
    tft.fillCircle(cx + 11, cy - 5, 7, cld);
    tft.fillRoundRect(cx - 15, cy - 6, 32, 9, 4, cld);
    for (int i = -9; i <= 9; i += 9) {
      tft.drawLine(cx + i,     cy + 6, cx + i - 3, cy + 15, C_COOL);
      tft.drawLine(cx + i + 1, cy + 6, cx + i - 2, cy + 15, C_COOL);
    }
  } else if (iconType == 1) {
    // Sun behind layered cloud (partly cloudy)
    tft.fillCircle(cx - 8, cy - 9, 7, 0xFFE0);
    tft.drawCircle(cx - 8, cy - 9, 8, C_WARN);
    uint16_t cld = 0xDEFB;
    tft.fillCircle(cx - 5, cy - 2, 8, cld);
    tft.fillCircle(cx + 4, cy - 5, 10, cld);
    tft.fillCircle(cx + 12, cy - 1, 7, cld);
    tft.fillRoundRect(cx - 13, cy - 2, 31, 9, 4, cld);
  } else {
    // Radiant Sun (clear sky)
    tft.fillCircle(cx, cy, 10, 0xFFE0);
    tft.drawCircle(cx, cy, 12, C_WARN);
    for (int a = 0; a < 360; a += 45) {
      float rad = a * 0.0174532925f;
      int x0 = cx + (int)(cosf(rad) * 14.0f);
      int y0 = cy + (int)(sinf(rad) * 14.0f);
      int x1 = cx + (int)(cosf(rad) * 18.0f);
      int y1 = cy + (int)(sinf(rad) * 18.0f);
      tft.drawLine(x0, y0, x1, y1, 0xFFE0);
    }
  }
}

// Wraps headline/summary text into clean lines up to `maxChars` without splitting words
static int wrapGemLines(const char* txt, char lines[][40], int maxLines, int maxChars) {
  if (!txt || !txt[0]) return 0;
  int lineCount = 0;
  int len = strlen(txt);
  int pos = 0;

  while (pos < len && lineCount < maxLines) {
    while (pos < len && (txt[pos] == ' ' || txt[pos] == '\n' || txt[pos] == '\r')) {
      pos++;
    }
    if (pos >= len) break;

    int nlPos = -1;
    for (int k = pos; k < len && (k - pos) <= maxChars; k++) {
      if (txt[k] == '\n' || txt[k] == '|') {
        nlPos = k;
        break;
      }
    }

    int endPos = pos + maxChars;
    if (nlPos >= 0) {
      endPos = nlPos;
    } else if (endPos < len) {
      int lastSpace = -1;
      for (int k = pos; k < endPos; k++) {
        if (txt[k] == ' ') lastSpace = k;
      }
      if (lastSpace > pos + 10) endPos = lastSpace;
    } else {
      endPos = len;
    }

    int copyLen = endPos - pos;
    if (copyLen > maxChars) copyLen = maxChars;
    memcpy(lines[lineCount], txt + pos, copyLen);
    lines[lineCount][copyLen] = '\0';
    lineCount++;
    pos = endPos;
    if (pos < len && (txt[pos] == '\n' || txt[pos] == '|')) pos++;
  }
  return lineCount;
}

// Pushes or updates a headline in the local ESP32 queue (up to NEWS_QUEUE_MAX items)
static void pushNewsToQueue(const char* topic, const char* headline, const char* src, const char* tm, bool makeActive) {
  if (!headline || !headline[0]) return;

  char cleanTopic[28], cleanHead[220], cleanSrc[24], cleanTm[10];
  sanitizeAscii(cleanTopic, topic && topic[0] ? topic : "Noticias", sizeof(cleanTopic));
  sanitizeAscii(cleanHead,  headline, sizeof(cleanHead));
  sanitizeAscii(cleanSrc,   src && src[0] ? src : "RSS Live", sizeof(cleanSrc));
  sanitizeAscii(cleanTm,    tm && tm[0] ? tm : "--:--", sizeof(cleanTm));

  for (uint8_t i = 0; i < newsSt.count; i++) {
    if (strcmp(newsSt.queue[i].headline, cleanHead) == 0) {
      strlcpy(newsSt.queue[i].topic,  cleanTopic, sizeof(newsSt.queue[i].topic));
      strlcpy(newsSt.queue[i].source, cleanSrc,   sizeof(newsSt.queue[i].source));
      strlcpy(newsSt.queue[i].tm,     cleanTm,    sizeof(newsSt.queue[i].tm));
      if (makeActive && newsSt.activeIdx != i) {
        newsSt.activeIdx    = i;
        newsSt.lastRotateMs = millis();
        newsSt.scrollX      = -20;
      }
      newsSt.valid = true;
      return;
    }
  }

  uint8_t slot = 0;
  if (newsSt.count < NEWS_QUEUE_MAX) {
    slot = newsSt.count++;
  } else {
    for (uint8_t i = 1; i < NEWS_QUEUE_MAX; i++) {
      newsSt.queue[i - 1] = newsSt.queue[i];
    }
    slot = NEWS_QUEUE_MAX - 1;
  }

  strlcpy(newsSt.queue[slot].topic,    cleanTopic, sizeof(newsSt.queue[slot].topic));
  strlcpy(newsSt.queue[slot].headline, cleanHead,  sizeof(newsSt.queue[slot].headline));
  strlcpy(newsSt.queue[slot].source,   cleanSrc,   sizeof(newsSt.queue[slot].source));
  strlcpy(newsSt.queue[slot].tm,       cleanTm,    sizeof(newsSt.queue[slot].tm));

  if (makeActive || !newsSt.valid) {
    newsSt.activeIdx    = slot;
    newsSt.lastRotateMs = millis();
    newsSt.scrollX      = -20;
  }
  newsSt.valid = true;
}

static const NewsItem* getActiveNewsItem() {
  static const NewsItem defaultItem = {
    "TECNOLOGIA",
    "Sincronizando feed de manchetes em tempo real pelo Cyber Deck Agent...",
    "CYD RSS",
    "--:--"
  };
  if (!newsSt.valid || newsSt.count == 0) return &defaultItem;
  if (newsSt.activeIdx >= newsSt.count) newsSt.activeIdx = 0;
  return &newsSt.queue[newsSt.activeIdx];
}

// Smoothly scrolls active headline in `newsSpr` (296x26 16-bit) at 28 FPS and rotates every 15s
void updateNewsHeadlineSprite() {
  if (currentScreen != SCR_NEWS || !newsSprReady) return;

  uint32_t now = millis();
  if (newsSt.lastRotateMs == 0) newsSt.lastRotateMs = now;

  if (newsSt.count > 1 && (now - newsSt.lastRotateMs >= NEWS_ROTATE_MS)) {
    newsSt.activeIdx    = (newsSt.activeIdx + 1) % newsSt.count;
    newsSt.lastRotateMs = now;
    newsSt.scrollX      = -24;
    gLastNewsSig[0]     = '\0';
  }

  const NewsItem* item = getActiveNewsItem();

  newsSpr.fillSprite(C_CARD_ELEV);
  newsSpr.drawRect(0, 0, NEWS_SPR_W, NEWS_SPR_H, C_CARD_HI);
  newsSpr.fillRect(0, 0, 3, NEWS_SPR_H, C_ACCENT);

  newsSpr.setTextDatum(ML_DATUM);
  newsSpr.setTextColor(C_TEXT, C_CARD_ELEV);

  int drawX = 8 - max((int16_t)0, newsSt.scrollX);
  int pxW = newsSpr.drawString(item->headline, drawX, NEWS_SPR_H / 2 + 1, 4);
  newsSt.headlinePxW = pxW;

  int loopGap = 54;
  if (pxW > (NEWS_SPR_W - 16)) {
    int secondX = drawX + pxW + loopGap;
    newsSpr.setTextColor(C_ACCENT, C_CARD_ELEV);
    newsSpr.drawString("///", drawX + pxW + 16, NEWS_SPR_H / 2 + 1, 2);
    newsSpr.setTextColor(C_TEXT, C_CARD_ELEV);
    if (secondX < NEWS_SPR_W) {
      newsSpr.drawString(item->headline, secondX, NEWS_SPR_H / 2 + 1, 4);
    }
    newsSt.scrollX += 2;
    if (newsSt.scrollX >= (pxW + loopGap)) {
      newsSt.scrollX = 0;
    }
  } else {
    newsSt.scrollX = 0;
  }

  newsSpr.pushSprite(12, 128);
}

void screenNewsStatic() {
  renderBackground();
  drawHeader();
  drawClock();

  // Top Card: Regional Weather & Date (x=6, y=27, w=308, h=74)
  drawModernCard(6, 27, 308, 74, "CLIMA REGIONAL", C_COOL);

  // Bottom Card: Modern News Desk (x=6, y=105, w=308, h=114)
  drawModernCard(6, 105, 308, 114, "", C_ACCENT);

  gLastWthSig[0]   = '\0';
  gLastGemSig[0]   = '\0';
  gLastNewsSig[0]  = '\0';
  gLastGemPage     = -1;
  gLastNewsRemainS = -1;
}

void screenNewsDynamic() {
  // ---- 1) Top Card: Weather Desk ----
  char wSig[96];
  snprintf(wSig, sizeof(wSig), "%s|%s|%s|%.1f|%.1f|%u|%.0f|%u|%u|%d|%s",
           wth.city, wth.dateFull, wth.dow, wth.temp, wth.feels,
           (unsigned)wth.hum, wth.wind, (unsigned)wth.rainProb,
           (unsigned)wth.icon, wth.alert ? 1 : 0, wth.cond);

  if (strcmp(wSig, gLastWthSig) != 0) {
    strlcpy(gLastWthSig, wSig, sizeof(gLastWthSig));

    // City pill & Date/weekday badge in top header row of Weather Card
    char cityBadge[20];
    snprintf(cityBadge, sizeof(cityBadge), "%.12s", wth.city);
    for (int i = 0; cityBadge[i]; i++) cityBadge[i] = toupper((unsigned char)cityBadge[i]);
    drawPillBadge(108, 29, 88, 13, cityBadge, C_COOL, C_CARD_ELEV, 0, 1);

    char dtBadge[28];
    if (wth.dow[0] && wth.dow[0] != '-') {
      snprintf(dtBadge, sizeof(dtBadge), "%s %s", wth.dow, wth.dateFull);
    } else {
      snprintf(dtBadge, sizeof(dtBadge), "%s", wth.dateFull);
    }
    drawPillBadge(200, 29, 108, 13, dtBadge, C_TEXT, C_ACCENT_SOFT, C_CARD_HI, 1);

    // Left: Refined Vector Weather Icon
    drawWeatherIcon(35, 69, wth.icon, wth.alert);

    // Center: Bold White Temperature Hero + Condition + Feels/Min-Max Pill
    tft.fillRect(62, 44, 138, 54, C_CARD);

    uint16_t tCol = C_OK;
    if      (wth.alert || wth.temp >= 35.0f) tCol = C_HOT;
    else if (wth.temp >= 30.0f)              tCol = C_WARN;
    else if (wth.temp <  20.0f)              tCol = C_COOL;

    char tempBig[16];
    if (wth.valid) snprintf(tempBig, sizeof(tempBig), "%.1f", wth.temp);
    else           snprintf(tempBig, sizeof(tempBig), "--.-");
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_TEXT, C_CARD);
    int wT = tft.drawString(tempBig, 64, 45, 4);
    tft.drawCircle(64 + wT + 4, 49, 2, tCol);
    tft.setTextColor(tCol, C_CARD);
    tft.drawString("C", 64 + wT + 9, 46, 2);

    // Condition label right of temperature or on line below
    char condLine[24];
    snprintf(condLine, sizeof(condLine), "%.18s", wth.valid ? wth.cond : "Sincronizando...");
    tft.setTextColor(C_COOL, C_CARD);
    tft.drawString(condLine, 64, 71, 1);

    char rangePill[28];
    snprintf(rangePill, sizeof(rangePill), "SENS %.0fC | %.0f/%.0fC", wth.feels, wth.tmin, wth.tmax);
    drawPillBadge(64, 82, 132, 15, rangePill, C_DIM, C_CARD_ELEV, 0, 1);

    // Right Column: Humidity, Rain Prob & Wind/Alert Pills
    char pHum[22], pRain[22], pWind[22];
    snprintf(pHum,  sizeof(pHum),  "UMIDADE: %u%%", (unsigned)wth.hum);
    snprintf(pRain, sizeof(pRain), "CHUVA: %u%%",   (unsigned)wth.rainProb);
    if (wth.alert) {
      snprintf(pWind, sizeof(pWind), "! TEMPESTADE !");
    } else {
      snprintf(pWind, sizeof(pWind), "VENTO: %.0f km/h", wth.wind);
    }

    drawPillBadge(202, 46, 106, 15, pHum, C_COOL, C_CARD_ELEV, 0, 1);
    uint16_t rainCol = (wth.rainProb >= 60) ? C_WARN : C_TEXT;
    drawPillBadge(202, 64, 106, 15, pRain, rainCol, C_CARD_ELEV, 0, 1);
    uint16_t wBg = wth.alert ? C_HOT : C_CARD_ELEV;
    uint16_t wFg = wth.alert ? C_TEXT : C_DIM;
    drawPillBadge(202, 82, 106, 15, pWind, wFg, wBg, wth.alert ? C_WARN : 0, 1);
  }

  // ---- 2) Bottom Card: Modern News Desk ----
  const NewsItem* item = getActiveNewsItem();
  char nSig[240];
  snprintf(nSig, sizeof(nSig), "%u|%u|%s|%s|%s",
           (unsigned)newsSt.activeIdx, (unsigned)newsSt.count,
           item->topic, item->source, item->headline);

  uint32_t elapsed = (newsSt.lastRotateMs > 0) ? (millis() - newsSt.lastRotateMs) : 0;
  uint32_t clampedElapsed = (elapsed > (uint32_t)NEWS_ROTATE_MS) ? (uint32_t)NEWS_ROTATE_MS : elapsed;
  int8_t remSec = (int8_t)constrain((int)(((uint32_t)NEWS_ROTATE_MS - clampedElapsed) / 1000U), 0, 15);

  if (strcmp(nSig, gLastNewsSig) != 0) {
    strlcpy(gLastNewsSig, nSig, sizeof(gLastNewsSig));

    // Top row: Category Topic Pill + Source & Timestamp + Queue Index Pill (1/5)
    tft.fillRect(12, 109, 296, 16, C_CARD);

    char topPill[18];
    snprintf(topPill, sizeof(topPill), "%.12s", item->topic);
    for (int i = 0; topPill[i]; i++) topPill[i] = toupper((unsigned char)topPill[i]);
    drawPillBadge(12, 109, 84, 15, topPill, C_ACCENT, C_ACCENT_SOFT, C_CARD_HI, 1);

    char srcLine[36];
    snprintf(srcLine, sizeof(srcLine), "%.14s  |  %s", item->source, item->tm);
    tft.setTextDatum(ML_DATUM);
    tft.setTextPadding(150);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(srcLine, 102, 116, 1);
    tft.setTextPadding(0);

    uint8_t tot = max((uint8_t)1, newsSt.count);
    uint8_t cur = (newsSt.activeIdx % tot) + 1;
    char idxBuf[12];
    snprintf(idxBuf, sizeof(idxBuf), "%u/%u", (unsigned)cur, (unsigned)tot);
    drawPillBadge(266, 109, 42, 15, idxBuf, C_TEXT, C_CARD_ELEV, C_CARD_HI, 1);

    // Multi-line readable summary below scrolling sprite (y=157..203)
    char wrapped[4][40];
    int nLines = wrapGemLines(item->headline, wrapped, 4, 37);
    tft.fillRect(12, 157, 296, 47, C_CARD);
    tft.setTextDatum(TL_DATUM);
    for (int r = 0; r < min(nLines, 3); r++) {
      tft.setTextColor(r == 0 ? C_TEXT : C_DIM, C_CARD);
      tft.drawString(wrapped[r], 14, 158 + r * 15, 2);
    }
  }

  // Bottom subtle rotation progress slim bar + countdown seconds
  if (remSec != gLastNewsRemainS) {
    gLastNewsRemainS = remSec;
    float rotPct = constrain(100.0f * (float)(15 - remSec) / 15.0f, 0.0f, 100.0f);
    drawSlimBar(12, 209, 262, 5, rotPct, C_ACCENT, C_TRACK);

    char secBuf[10];
    snprintf(secBuf, sizeof(secBuf), "%02ds", (int)remSec);
    tft.setTextDatum(MR_DATUM);
    tft.setTextPadding(28);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(secBuf, 306, 211, 1);
    tft.setTextPadding(0);
  }
}
