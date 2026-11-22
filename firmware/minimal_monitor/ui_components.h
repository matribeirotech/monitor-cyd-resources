// ui_components.h - CYD OS v5.0 Obsidian Dark Core UI Component Kit
// Included in minimal_monitor.ino AFTER state structs, tft, tickerSpr, and gGaugeEnd/gGaugeCol.
#pragma once
#include <Arduino.h>
#include "ui_theme.h"

// ======================================= Dynamic Theme Engine (v5.0) =======
void applyColor565(uint16_t c) {
  if (c == 0) c = 0x07E0; // Prevent invisible black-on-black accent
  currentColor565 = c;

  // Obsidian Dark Surface Hierarchy
  C_BG          = 0x0842; // Deep obsidian #070B14
  C_CARD        = 0x08A5; // Elevated dark slate #0F172A
  C_CARD_ELEV   = 0x1106; // Nested pill/badge slate #162033
  C_TRACK       = 0x1926; // Recessed progress track #1A2436

  // Typography Hierarchy
  C_TEXT        = 0xF7BE; // Crisp off-white #F1F5F9
  C_DIM         = 0x8CD6; // Cool slate #8A9BB5
  C_MUTED       = 0x4AF0; // Subtle slate #4D5E78

  // Dynamic Accent & Harmonized Surfaces
  C_ACCENT      = c;
  C_CARD_HI     = blend565(0x2189, C_ACCENT, 45);
  C_ACCENT_SOFT = blend565(C_CARD, C_ACCENT, 48);
  C_ACCENT_DK   = blend565(0x0842, C_ACCENT, 30);

  // Semantic Palette (Vibrant & Distinct)
  C_OK          = 0x262B; // Emerald #22C55E
  C_WARN        = 0xF4E1; // Amber #F59E0B
  C_HOT         = 0xEA28; // Coral Red #EF4444
  C_COOL        = 0x3DFF; // Sky Cyan #38BDF8
  C_PURPLE      = 0xAAAE; // Violet #A855F7
  C_PINK        = 0xEA53; // Rose #EC4899
}

// ======================================= Core Badges & Cards ===============
// Rounded pill badge with centered text
void drawPillBadge(int x, int y, int w, int h, const char *text,
                   uint16_t fg, uint16_t bg, uint16_t border = 0, uint8_t font = 1) {
  int r = min((int)PILL_R, min(w, h) / 2);
  tft.fillRoundRect(x, y, w, h, r, bg);
  if (border != 0) {
    tft.drawRoundRect(x, y, w, h, r, border);
  }
  if (text && text[0]) {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(fg, bg);
    tft.drawString(text, x + w / 2, y + h / 2, font);
  }
}

// Financial percentage change pill with vector ▲/▼ triangle and semantic emerald/coral tint
void drawDeltaBadge(int x, int y, int w, int h, float pct) {
  bool up = (pct >= 0.0f);
  uint16_t fg = up ? C_OK : C_HOT;
  uint16_t bg = blend565(C_CARD, fg, 42);
  uint16_t bd = blend565(C_CARD, fg, 96);

  int r = min((int)PILL_R, min(w, h) / 2);
  tft.fillRoundRect(x, y, w, h, r, bg);
  tft.drawRoundRect(x, y, w, h, r, bd);

  char buf[16];
  snprintf(buf, sizeof(buf), "%s%.2f%%", up ? "+" : "", pct);

  if (w >= 42) {
    int tx = x + 6;
    int cy = y + h / 2;
    if (up) {
      tft.fillTriangle(tx, cy - 2, tx - 3, cy + 2, tx + 3, cy + 2, fg);
    } else {
      tft.fillTriangle(tx, cy + 2, tx - 3, cy - 2, tx + 3, cy - 2, fg);
    }
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(fg, bg);
    tft.drawString(buf, x + 6 + (w - 6) / 2, y + h / 2, 1);
  } else {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(fg, bg);
    tft.drawString(buf, x + w / 2, y + h / 2, 1);
  }
}

// Elevated Obsidian Card with refined 1px border, subtle top highlight, and left vertical accent bar
void drawModernCard(int x, int y, int w, int h, const char *title, uint16_t accentCol = 0) {
  uint16_t acc = accentCol ? accentCol : C_ACCENT;
  uint16_t borderCol = accentCol ? blend565(C_CARD_HI, acc, 55) : C_CARD_HI;

  tft.fillRoundRect(x, y, w, h, CARD_R, C_CARD);
  tft.drawRoundRect(x, y, w, h, CARD_R, borderCol);

  // Subtle top specular hairline
  if (w > CARD_R * 2 + 4) {
    tft.drawFastHLine(x + CARD_R, y + 1, w - CARD_R * 2, blend565(C_CARD, acc, 38));
  }

  if (title && title[0]) {
    tft.fillRoundRect(x + 6, y + 4, 3, 9, 1, acc);
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(title, x + 13, y + 5, 1);
  }
}

// ======================================= Top Bar: Header & Clock ===========
void drawHeader() {
  tft.fillRect(0, 0, SCR_W, HDR_H - 1, C_ACCENT_DK);
  tft.drawFastHLine(0, HDR_H - 1, SCR_W, C_CARD_HI);
  tft.drawFastHLine(0, HDR_H - 1, 88, C_ACCENT);

  // Sleek geometric icon badge (x=4..18, y=4..18)
  tft.fillRoundRect(4, 4, 14, 15, 3, C_ACCENT_SOFT);
  tft.drawRoundRect(4, 4, 14, 15, 3, C_ACCENT);
  tft.drawLine(7, 8, 10, 11, C_ACCENT);
  tft.drawLine(7, 14, 10, 11, C_ACCENT);
  tft.drawFastHLine(11, 14, 3, C_TEXT);

  // Crisp screen title on the left (x = 22..100)
  const char* scrTitle = "RESUMO";
  if      (currentScreen == SCR_CPU_RAM)      scrTitle = "CPU / RAM";
  else if (currentScreen == SCR_CPU_RAM_DUAL) scrTitle = "DUAL GRAPH";
  else if (currentScreen == SCR_GPU_FOCUS)    scrTitle = "GPU FOCUS";
  else if (currentScreen == SCR_GRAPH)        scrTitle = "4x TELEM";
  else if (currentScreen == SCR_WALLPAPER)    scrTitle = "WALLPAPER";
  else if (currentScreen == SCR_MARKET)       scrTitle = "MERCADO";
  else if (currentScreen == SCR_PORTFOLIO)    scrTitle = "PORTFOLIO";
  else if (currentScreen == SCR_POMODORO)     scrTitle = "POMODORO";
  else if (currentScreen == SCR_MEDIA)        scrTitle = "MEDIA HUB";
  else if (currentScreen == SCR_NEWS)         scrTitle = "CLIMA/NEWS";
  else if (currentScreen == SCR_TERMINAL)     scrTitle = "CYBER TERM";
  else if (currentScreen == SCR_WIFI_RADAR)   scrTitle = "RF RADAR";
  else if (currentScreen == SCR_NET_ANALYZER) scrTitle = "NET / WAN";
  else if (currentScreen == SCR_SECURITY)     scrTitle = "SOC / IDS";

  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_ACCENT_DK);
  tft.drawString(scrTitle, 22, 11, 2);
}

// Flicker-free right cluster (x=104..319): Status Dot + HH:MM + DD/MM + Weather Pill + Status/City Badge
void drawClock() {
  tft.fillRect(102, 0, SCR_W - 102, HDR_H - 1, C_ACCENT_DK);
  tft.drawFastVLine(102, 5, 13, C_CARD_HI);

  // 1) Live connection status dot (x = 109, y = 11)
  uint16_t dotCol = linked ? C_OK : C_WARN;
  tft.fillCircle(109, 11, 3, blend565(C_ACCENT_DK, dotCol, 85));
  tft.fillCircle(109, 11, 2, dotCol);

  // 2) Crisp HH:MM (C_TEXT, Font 2) + DD/MM (C_DIM, Font 1)
  char hmBuf[10];
  bool hasTime = (linked && st.hh >= 0 && st.mm >= 0);
  bool hasDate = (wth.dateShort[0] != '\0' && wth.dateShort[0] != '-');

  if (hasTime) {
    snprintf(hmBuf, sizeof(hmBuf), "%02d:%02d", st.hh, st.mm);
  } else {
    snprintf(hmBuf, sizeof(hmBuf), "--:--");
  }

  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(C_TEXT, C_ACCENT_DK);
  int wTime = tft.drawString(hmBuf, 116, 11, 2);

  const char* dateStr = hasDate ? wth.dateShort : "--/--";
  tft.setTextColor(C_DIM, C_ACCENT_DK);
  tft.drawString(dateStr, 116 + wTime + 4, 12, 1);

  // 3) Thermal-tinted Weather Pill (x = 190..230, w = 40, h = 16)
  const int pillX = 190;
  const int pillW = 40;
  uint16_t tCol = C_COOL;
  if (wth.valid) {
    if      (wth.alert || wth.temp >= 35.0f) tCol = C_HOT;
    else if (wth.temp >= 30.0f)              tCol = C_WARN;
    else if (wth.temp >= 20.0f)              tCol = C_OK;
    else                                     tCol = C_COOL;
  } else {
    tCol = C_DIM;
  }

  uint16_t pillBg = blend565(C_ACCENT_DK, tCol, 45);
  uint16_t pillBd = blend565(C_CARD_HI, tCol, 130);
  tft.fillRoundRect(pillX, 3, pillW, 16, PILL_R, pillBg);
  tft.drawRoundRect(pillX, 3, pillW, 16, PILL_R, pillBd);

  char tBuf[10];
  if (wth.valid) {
    snprintf(tBuf, sizeof(tBuf), "%.0fC", wth.temp);
  } else {
    snprintf(tBuf, sizeof(tBuf), "--C");
  }
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(wth.valid ? C_TEXT : C_DIM, pillBg);
  tft.drawString(tBuf, pillX + pillW / 2, 11, 2);

  // 4) Right-aligned Status / City / Page Badge (x = 234..316, w = 82, zero overlap!)
  const int rX = 234;
  const int rW = 82;
  if (wth.alert) {
    bool flashOn = ((millis() / 450) % 2 == 0);
    uint16_t aBg = flashOn ? C_HOT : C_WARN;
    uint16_t aFg = flashOn ? C_TEXT : C_BG;
    drawPillBadge(rX, 3, rW, 16, "! ALERTA !", aFg, aBg, aFg, 1);
  } else if (currentScreen == SCR_POMODORO) {
    bool isBrk = (strcasecmp(pomo.state, "WORK") != 0);
    uint16_t pCol = !pomo.running ? C_WARN : (isBrk ? C_COOL : C_OK);
    const char* pTxt = !pomo.running ? "PAUSADO" : (isBrk ? "PAUSA" : "EM FOCO");
    drawPillBadge(rX, 3, rW, 16, pTxt, pCol, blend565(C_ACCENT_DK, pCol, 42), blend565(C_CARD_HI, pCol, 110), 1);
  } else if (currentScreen == SCR_MEDIA) {
    uint16_t mCol = getMediaAccentColor();
    const char* sLbl = (strcasecmp(mediaSt.source, "NONE") == 0) ? "PLAYER" : mediaSt.source;
    drawPillBadge(rX, 3, rW, 16, sLbl, mCol, blend565(C_ACCENT_DK, mCol, 42), blend565(C_CARD_HI, mCol, 110), 1);
  } else if (wth.valid && wth.city[0]) {
    char cityShort[14];
    snprintf(cityShort, sizeof(cityShort), "%.11s", wth.city);
    for (int i = 0; cityShort[i]; i++) cityShort[i] = (char)toupper((unsigned char)cityShort[i]);
    drawPillBadge(rX, 3, rW, 16, cityShort, C_ACCENT, C_ACCENT_SOFT, C_CARD_HI, 1);
  } else {
    char hostShort[14];
    snprintf(hostShort, sizeof(hostShort), "%.11s", linked ? st.host : "OFFLINE");
    uint16_t hCol = linked ? C_TEXT : C_WARN;
    drawPillBadge(rX, 3, rW, 16, hostShort, hCol, C_CARD_ELEV, C_CARD_HI, 1);
  }
}

// ======================================= Alert Ribbons =====================
void drawStormAlertBanner() {
  if (!wth.alert) {
    if (gLastStormAlert) {
      gLastStormAlert = false;
      gLastStormFlash = 255;
      needFullDraw = true;
    }
    return;
  }
  gLastStormAlert = true;
  uint8_t flashPhase = (uint8_t)((millis() / 500) % 2);
  if (flashPhase == gLastStormFlash && !needFullDraw) return;
  gLastStormFlash = flashPhase;

  uint16_t bgCol = flashPhase ? C_HOT : C_WARN;
  uint16_t fgCol = flashPhase ? C_TEXT : C_BG;
  uint16_t bdCol = flashPhase ? C_WARN : C_HOT;

  const int by = HDR_H;
  const int bh = 18;
  tft.fillRect(0, by, SCR_W, bh, bgCol);
  tft.drawRect(0, by, SCR_W, bh, bdCol);

  // Crisp lightning vector icon
  tft.fillTriangle(12, by + 2, 7, by + 9, 12, by + 9, fgCol);
  tft.fillTriangle(10, by + 9, 15, by + 9, 9, by + 16, fgCol);

  char bannerTxt[58];
  snprintf(bannerTxt, sizeof(bannerTxt), "AVISO %s: %.34s", wth.city, wth.alertMsg);
  for (int i = 0; bannerTxt[i]; i++) bannerTxt[i] = (char)toupper((unsigned char)bannerTxt[i]);

  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(fgCol, bgCol);
  tft.drawString(bannerTxt, SCR_W / 2 + 4, by + bh / 2, 1);
}

void drawSecurityAlertBanner() {
  if (sec.level < 2) {
    if (gLastSecAlert) {
      gLastSecAlert = false;
      gLastSecFlash = 255;
      needFullDraw = true;
    }
    return;
  }
  if (currentScreen == SCR_SECURITY) {
    gLastSecAlert = false;
    return;
  }
  gLastSecAlert = true;
  uint8_t flashPhase = (uint8_t)((millis() / 420) % 2);
  if (flashPhase == gLastSecFlash && !needFullDraw) return;
  gLastSecFlash = flashPhase;

  uint16_t bgCol = flashPhase ? C_HOT : blend565(C_BG, C_HOT, 95);
  uint16_t fgCol = flashPhase ? C_TEXT : C_WARN;
  uint16_t bdCol = flashPhase ? C_WARN : C_HOT;

  const int by = HDR_H;
  const int bh = 18;
  tft.fillRect(0, by, SCR_W, bh, bgCol);
  tft.drawRect(0, by, SCR_W, bh, bdCol);

  // Warning triangle vector icon
  tft.fillTriangle(11, by + 3, 5, by + 15, 17, by + 15, fgCol);
  tft.drawFastVLine(11, by + 7, 4, bgCol);
  tft.drawPixel(11, by + 13, bgCol);

  char bannerTxt[56];
  if (sec.lastAlert[0]) {
    snprintf(bannerTxt, sizeof(bannerTxt), "IDS INVASAO: %.36s", sec.lastAlert);
  } else {
    snprintf(bannerTxt, sizeof(bannerTxt), "ALERTA IDS: VERIFIQUE TELA 14 (%s)", sec.lastIp);
  }
  for (int i = 0; bannerTxt[i]; i++) bannerTxt[i] = (char)toupper((unsigned char)bannerTxt[i]);

  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(fgCol, bgCol);
  tft.drawString(bannerTxt, SCR_W / 2 + 4, by + bh / 2, 1);
}

// ======================================= Letreiro Infinito (Ticker Tape) ===
int drawTickerSegment(int x, const char* sym, const char* priceStr, float chgPct) {
  int startX = x;
  bool up = (chgPct >= 0.0f);
  uint16_t chgCol = up ? C_OK : C_HOT;

  char chgBuf[16];
  snprintf(chgBuf, sizeof(chgBuf), "%s%.2f%%", up ? "+" : "", chgPct);

  tickerSpr.setTextDatum(ML_DATUM);

  // Symbol in dynamic accent
  tickerSpr.setTextColor(C_ACCENT, C_CARD);
  int wSym = tickerSpr.drawString(sym, x, 10, 2);
  x += wSym + 4;

  // Price in crisp off-white
  tickerSpr.setTextColor(C_TEXT, C_CARD);
  int wPrc = tickerSpr.drawString(priceStr, x, 10, 2);
  x += wPrc + 5;

  // Vector ▲/▼ trend triangle
  if (up) {
    tickerSpr.fillTriangle(x + 3, 6, x, 12, x + 6, 12, chgCol);
  } else {
    tickerSpr.fillTriangle(x + 3, 12, x, 6, x + 6, 6, chgCol);
  }
  x += 9;

  // Percentage change
  tickerSpr.setTextColor(chgCol, C_CARD);
  int wChg = tickerSpr.drawString(chgBuf, x, 10, 2);
  x += wChg + 9;

  // Subtle muted divider dot
  tickerSpr.fillCircle(x, 9, 1, C_MUTED);
  x += 10;

  return x - startX;
}

int drawFullTickerCycle(int baseX) {
  int x = baseX;
  char pBuf[64];

  if (wth.alert) {
    tickerSpr.setTextDatum(ML_DATUM);
    tickerSpr.setTextColor(C_WARN, C_CARD);
    int wA = tickerSpr.drawString("[! ALERTA CLIMA !] ", x, 10, 2);
    x += wA;
    snprintf(pBuf, sizeof(pBuf), "%s: %s (%.0fC | Chuva %u%%)   ",
             wth.city, wth.alertMsg, wth.temp, (unsigned)wth.rainProb);
    tickerSpr.setTextColor(C_HOT, C_CARD);
    x += tickerSpr.drawString(pBuf, x, 10, 2) + 12;
  } else if (wth.valid) {
    tickerSpr.setTextDatum(ML_DATUM);
    tickerSpr.setTextColor(C_COOL, C_CARD);
    x += tickerSpr.drawString(wth.city, x, 10, 2) + 4;
    snprintf(pBuf, sizeof(pBuf), "%.1fC (%s)", wth.temp, wth.cond);
    tickerSpr.setTextColor(C_TEXT, C_CARD);
    x += tickerSpr.drawString(pBuf, x, 10, 2) + 9;
    tickerSpr.fillCircle(x, 9, 1, C_MUTED);
    x += 10;
  }

  if (!mkt.valid) {
    tickerSpr.setTextDatum(ML_DATUM);
    tickerSpr.setTextColor(C_DIM, C_CARD);
    int w = tickerSpr.drawString(
      "Sincronizando cotacoes em tempo real (USD/BRL, EUR/BRL, BTC, ETH, SOL, BNB, XRP, IBOV, S&P500)...   ",
      x, 10, 2);
    return max((x - baseX) + w, 320);
  }

  // 1) USD/BRL
  snprintf(pBuf, sizeof(pBuf), "R$%.2f", mkt.usd);
  x += drawTickerSegment(x, "USD", pBuf, mkt.usdc);

  // 2) EUR/BRL
  snprintf(pBuf, sizeof(pBuf), "R$%.2f", mkt.eur);
  x += drawTickerSegment(x, "EUR", pBuf, mkt.eurc);

  // 3) Bitcoin (USD + BRL)
  if (mkt.btc_brl > 0) snprintf(pBuf, sizeof(pBuf), "$%.0f (R$%.0fk)", mkt.btc, mkt.btc_brl / 1000.0f);
  else                 snprintf(pBuf, sizeof(pBuf), "$%.0f", mkt.btc);
  x += drawTickerSegment(x, "BTC", pBuf, mkt.btcc);

  // 4) Ethereum
  snprintf(pBuf, sizeof(pBuf), "$%.0f", mkt.eth);
  x += drawTickerSegment(x, "ETH", pBuf, mkt.ethc);

  // 5) Solana
  snprintf(pBuf, sizeof(pBuf), "$%.2f", mkt.sol);
  x += drawTickerSegment(x, "SOL", pBuf, mkt.solc);

  // 6) BNB
  snprintf(pBuf, sizeof(pBuf), "$%.1f", mkt.bnb);
  x += drawTickerSegment(x, "BNB", pBuf, mkt.bnbc);

  // 7) XRP
  snprintf(pBuf, sizeof(pBuf), "$%.2f", mkt.xrp);
  x += drawTickerSegment(x, "XRP", pBuf, mkt.xrpc);

  // 8) IBOVESPA
  if (mkt.ibov > 0) {
    snprintf(pBuf, sizeof(pBuf), "%.1fk pts", mkt.ibov / 1000.0f);
    x += drawTickerSegment(x, "IBOV", pBuf, mkt.ibovc);
  }

  // 9) S&P 500
  if (mkt.sp500 > 0) {
    snprintf(pBuf, sizeof(pBuf), "%.0f pts", mkt.sp500);
    x += drawTickerSegment(x, "S&P500", pBuf, mkt.sp500c);
  }

  // Hardware telemetry or Portfolio summary in ticker
  if ((currentScreen == SCR_MARKET || currentScreen == SCR_PORTFOLIO) && linked) {
    snprintf(pBuf, sizeof(pBuf), "CPU %.0f%% | RAM %.0f%%", st.cpu, st.ram);
    x += drawTickerSegment(x, "PC", pBuf, 0.0f);
  } else if (portf.valid && portf.tot > 0.0f) {
    snprintf(pBuf, sizeof(pBuf), "R$%.1fk", portf.tot / 1000.0f);
    x += drawTickerSegment(x, "CART", pBuf, portf.pnl_pct);
  }

  return x - baseX;
}

void updateTickerTape() {
  if (!showTickerBar || !tickerSprReady) return;

  tickerSpr.fillSprite(C_CARD);
  tickerSpr.drawFastHLine(0, 0, SCR_W, C_CARD_HI);

  const int badgeW = 38;
  int cycleW = drawFullTickerCycle(badgeW + 4 - tickerScrollX);
  if (cycleW < 100) cycleW = 320;

  if (badgeW + 4 - tickerScrollX + cycleW < SCR_W) {
    drawFullTickerCycle(badgeW + 4 - tickerScrollX + cycleW);
  }

  tickerScrollX += 2;
  if (tickerScrollX >= cycleW) {
    tickerScrollX = 0;
  }

  // Left fixed MKT pill badge
  tickerSpr.fillRect(0, 1, badgeW + 2, TICKER_H - 1, C_CARD);
  tickerSpr.drawFastVLine(badgeW + 1, 2, TICKER_H - 3, C_CARD_HI);
  tickerSpr.fillRoundRect(3, 3, badgeW - 5, TICKER_H - 5, 3, C_ACCENT_SOFT);
  tickerSpr.drawRoundRect(3, 3, badgeW - 5, TICKER_H - 5, 3, C_ACCENT);
  tickerSpr.setTextDatum(MC_DATUM);
  tickerSpr.setTextColor(C_ACCENT, C_ACCENT_SOFT);
  tickerSpr.drawString("MKT", 3 + (badgeW - 5) / 2, 9, 1);

  tickerSpr.pushSprite(0, TICKER_Y);
}

// ======================================= Progress Bars & Gauges ============
void drawSlimBar(int x, int y, int w, int h, float pct, uint16_t fillCol, uint16_t trackCol = 0) {
  float v = constrain(pct, 0.0f, 100.0f);
  uint16_t trk = trackCol ? trackCol : C_TRACK;
  int radius = min(3, max(1, h / 2));

  tft.fillRoundRect(x, y, w, h, radius, trk);

  int fillW = (int)((w * v) / 100.0f + 0.5f);
  if (fillW > 0) {
    fillW = min(w, max(fillW, radius * 2));
    tft.fillRoundRect(x, y, fillW, h, radius, fillCol);
    if (h >= 5 && fillW > 4) {
      tft.drawFastHLine(x + 2, y + 1, fillW - 4, blend565(fillCol, 0xFFFF, 75));
    }
  }
}

void drawModernBar(int x, int y, int w, int h, const char *label, float pct,
                   const char *rightText, float warn, float hot) {
  float v = constrain(pct, 0.0f, 100.0f);
  uint16_t col = levelColor(v, warn, hot);

  if (label && label[0]) {
    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(label, x, y, 1);
  }

  if (rightText) {
    tft.setTextDatum(TR_DATUM);
    tft.setTextColor(C_TEXT, C_CARD);
    tft.setTextPadding(min(w / 2 + 18, 84));
    tft.drawString(rightText, x + w, y, 1);
    tft.setTextPadding(0);
  }

  int barY = y + 9;
  int barH = max(5, h - 9);
  drawSlimBar(x, barY, w, barH, v, col, C_TRACK);
}

void drawSegmentedBar(int x, int y, int w, int h, float pct, float warn, float hot) {
  float v = constrain(pct, 0.0f, 100.0f);
  uint16_t activeCol = levelColor(v, warn, hot);

  tft.fillRoundRect(x, y, w, h, 3, C_CARD_ELEV);
  tft.drawRoundRect(x, y, w, h, 3, C_CARD_HI);

  const int segments = 16;
  int innerW = w - 6;
  int gap = 2;
  int segW = max(2, (innerW - (segments - 1) * gap) / segments);
  int totalW = segments * segW + (segments - 1) * gap;
  int startX = x + (w - totalW) / 2;
  int activeSegs = (int)((v / 100.0f) * segments + 0.5f);

  for (int i = 0; i < segments; i++) {
    int sx = startX + i * (segW + gap);
    uint16_t sc = C_TRACK;
    if (i < activeSegs) {
      float segPct = ((float)(i + 1) * 100.0f) / (float)segments;
      sc = blend565(activeCol, levelColor(segPct, warn, hot), 110);
    }
    tft.fillRoundRect(sx, y + 2, segW, max(2, h - 4), 1, sc);
  }
}

void drawGauge(int cx, int cy, int r, float value, const char *label,
               bool valid, float warn, float hot, int8_t slot) {
  const int ir = max(4, r - 6);
  const int A0 = 38, A1 = 322;
  float v = valid ? constrain(value, 0.0f, 100.0f) : 0.0f;
  int aEnd = A0 + (int)((A1 - A0) * v / 100.0f);
  uint16_t col = valid ? levelColor(v, warn, hot) : C_TRACK;

  bool useSlot = (slot >= 0 && slot < GAUGE_SLOTS);
  bool changed = !useSlot || (gGaugeEnd[slot] != aEnd) || (gGaugeCol[slot] != col);
  if (changed) {
    if (ir > 6) {
      tft.drawCircle(cx, cy, ir - 3, blend565(C_CARD, col, 32));
    }
    if (aEnd > A0 + 1) tft.drawSmoothArc(cx, cy, r, ir, A0, aEnd, col, C_CARD, true);
    if (aEnd < A1 - 1) tft.drawSmoothArc(cx, cy, r, ir, max(A0, aEnd), A1, C_TRACK, C_CARD, true);
    if (useSlot) {
      gGaugeEnd[slot] = aEnd;
      gGaugeCol[slot] = col;
    }
  }

  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(max(16, ir + 8));
  tft.setTextColor(valid ? C_TEXT : C_DIM, C_CARD);
  char buf[12];
  if (valid) snprintf(buf, sizeof(buf), "%d%%", (int)(v + 0.5f));
  else       snprintf(buf, sizeof(buf), "--");
  uint8_t valFont = (r >= 36) ? 4 : 2;
  tft.drawString(buf, cx, cy - 2, valFont);
  tft.setTextPadding(0);

  if (label && label[0]) {
    tft.setTextColor(C_DIM, C_CARD);
    tft.drawString(label, cx, cy + (r >= 36 ? 15 : 11), 1);
  }
}

// ======================================= Real-Time Area Charts =============
void plotGraph(int x, int y, int w, int h, uint8_t *data, uint16_t col, const char *unit) {
  tft.fillRect(x, y, w, h, C_CARD);
  tft.drawFastHLine(x, y + h - 1, w, C_CARD_HI);

  uint16_t area = blend565(C_CARD, col, 45);
  uint16_t subCol = blend565(C_CARD, col, 175);

  // Subtle dotted 25/50/75% grid
  for (int i = 1; i < 4; i++) {
    int gy = y + (h * i) / 4;
    for (int gx = x + 2; gx < x + w - 2; gx += 6) {
      tft.drawPixel(gx, gy, C_TRACK);
    }
  }
  for (int gx = x + w / 4; gx < x + w - 4; gx += max(12, w / 4)) {
    for (int gy = y + 2; gy < y + h - 2; gy += 6) {
      tft.drawPixel(gx, gy, C_TRACK);
    }
  }

  uint16_t n = hFilled ? HIST : hPos;
  int latestPx = -1, latestPy = -1;

  if (n >= 2) {
    int prevY = -1;
    int plotW = w - 3;
    for (int i = 0; i < plotW && i < (int)n; i++) {
      uint16_t idx = (hPos - 1 - i + HIST * 2) % HIST;
      int px = x + plotW - 1 - i;
      int v  = constrain((int)data[idx], 0, 100);
      int py = y + h - 2 - ((h - 5) * v) / 100;

      if (y + h - 1 > py) {
        tft.drawFastVLine(px, py, y + h - 1 - py, area);
      }
      if (prevY >= 0) {
        tft.drawLine(px + 1, prevY, px, py, col);
        if (prevY + 1 < y + h - 1 && py + 1 < y + h - 1) {
          tft.drawLine(px + 1, prevY + 1, px, py + 1, subCol);
        }
      }
      tft.drawPixel(px, py, col);
      if (i == 0) {
        latestPx = px;
        latestPy = py;
      }
      prevY = py;
    }
  }

  // Glowing circle at latest data point
  if (latestPx >= x + 3 && latestPy >= y + 3 && latestPy < y + h - 3) {
    tft.fillCircle(latestPx, latestPy, 3, blend565(C_CARD, col, 90));
    tft.fillCircle(latestPx, latestPy, 2, col);
    tft.drawPixel(latestPx, latestPy, C_TEXT);
  }

  // Clean top-right pill value in card header
  if (unit && n > 0 && y >= 13) {
    uint16_t last = (hPos - 1 + HIST) % HIST;
    char buf[14];
    snprintf(buf, sizeof(buf), "%d%s", data[last], unit);
    drawPillBadge(x + w - 36, y - 13, 36, 11, buf,
                  C_TEXT, blend565(C_CARD, col, 48), blend565(C_CARD, col, 110), 1);
  }
}

void plotDualCpuRamGraph(int x, int y, int w, int h) {
  tft.fillRect(x, y, w, h, C_CARD);
  tft.drawFastHLine(x, y + h - 1, w, C_CARD_HI);

  uint16_t colCpu  = C_COOL;   // Sky Cyan for CPU
  uint16_t colRam  = C_PURPLE; // Violet for RAM
  uint16_t areaCpu = blend565(C_CARD, colCpu, 42);
  uint16_t areaRam = blend565(C_CARD, colRam, 36);
  uint16_t areaMix = blend565(areaCpu, areaRam, 128);

  // Dotted 25/50/75% grid
  for (int i = 1; i < 4; i++) {
    int gy = y + (h * i) / 4;
    for (int gx = x + 2; gx < x + w - 2; gx += 6) tft.drawPixel(gx, gy, C_TRACK);
  }
  for (int i = 1; i < 6; i++) {
    int gx = x + (w * i) / 6;
    for (int gy = y + 2; gy < y + h - 2; gy += 6) tft.drawPixel(gx, gy, C_TRACK);
  }

  uint16_t n = hFilled ? HIST : hPos;
  int latestPx = -1, latestCpuY = -1, latestRamY = -1;

  if (n >= 2) {
    int prevCpuY = -1;
    int prevRamY = -1;
    int plotW = w - 3;
    for (int i = 0; i < plotW && i < (int)n; i++) {
      uint16_t idx = (hPos - 1 - i + HIST * 2) % HIST;
      int px = x + plotW - 1 - i;

      int vCpu = constrain((int)hCpu[idx], 0, 100);
      int vRam = constrain((int)hRam[idx], 0, 100);

      int pyCpu = y + h - 2 - ((h - 5) * vCpu) / 100;
      int pyRam = y + h - 2 - ((h - 5) * vRam) / 100;

      int topY = min(pyCpu, pyRam);
      int midY = max(pyCpu, pyRam);
      uint16_t topArea = (pyCpu < pyRam) ? areaCpu : areaRam;

      if (midY > topY) {
        tft.drawFastVLine(px, topY, midY - topY, topArea);
      }
      if (y + h - 1 > midY) {
        tft.drawFastVLine(px, midY, y + h - 1 - midY, areaMix);
      }

      if (prevRamY >= 0) {
        tft.drawLine(px + 1, prevRamY, px, pyRam, colRam);
      }
      tft.drawPixel(px, pyRam, colRam);
      if (pyRam + 1 < y + h - 1) tft.drawPixel(px, pyRam + 1, colRam);

      if (prevCpuY >= 0) {
        tft.drawLine(px + 1, prevCpuY, px, pyCpu, colCpu);
      }
      tft.drawPixel(px, pyCpu, colCpu);
      if (pyCpu + 1 < y + h - 1) tft.drawPixel(px, pyCpu + 1, colCpu);

      if (i == 0) {
        latestPx   = px;
        latestCpuY = pyCpu;
        latestRamY = pyRam;
      }
      prevCpuY = pyCpu;
      prevRamY = pyRam;
    }
  }

  if (latestPx >= x + 3) {
    if (latestRamY >= y + 3 && latestRamY < y + h - 3) {
      tft.fillCircle(latestPx, latestRamY, 2, colRam);
      tft.drawPixel(latestPx, latestRamY, C_TEXT);
    }
    if (latestCpuY >= y + 3 && latestCpuY < y + h - 3) {
      tft.fillCircle(latestPx, latestCpuY, 2, colCpu);
      tft.drawPixel(latestPx, latestCpuY, C_TEXT);
    }
  }

  // Clean pill legends in card header row
  if (y >= 13) {
    char buf[20];
    snprintf(buf, sizeof(buf), "CPU %.0f%%", st.cpu);
    drawPillBadge(x + w - 108, y - 13, 52, 11, buf,
                  colCpu, blend565(C_CARD, colCpu, 42), blend565(C_CARD, colCpu, 100), 1);

    snprintf(buf, sizeof(buf), "RAM %.0f%%", st.ram);
    drawPillBadge(x + w - 52, y - 13, 52, 11, buf,
                  colRam, blend565(C_CARD, colRam, 42), blend565(C_CARD, colRam, 100), 1);
  }
}

// ======================================= Boot Splash v5.0 ==================
void drawBootSplash(bool sdOk) {
  tft.fillScreen(C_BG);
  drawModernCard(16, 18, SCR_W - 32, SCR_H - 36, "SYSTEM BOOT // HYBRID TELEMETRY", C_ACCENT);

  // Version pill badge in top-right of boot card
  drawPillBadge(SCR_W - 76, 23, 52, 13, "OS v5.0", C_ACCENT, C_ACCENT_SOFT, C_ACCENT, 1);

  // Main Hero Title
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString("CYD CYBER DECK", SCR_W / 2, 68, 4);

  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("OBSIDIAN TELEMETRY & RF COMMAND CENTER", SCR_W / 2, 92, 1);

  // Subsystem status pills
  drawPillBadge(32, 112, 122, 18,
                sdOk ? "SD CARD: READY" : "SD CARD: NO FAT32",
                sdOk ? C_OK : C_WARN,
                blend565(C_CARD, sdOk ? C_OK : C_WARN, 40),
                blend565(C_CARD_HI, sdOk ? C_OK : C_WARN, 110), 1);

  drawPillBadge(166, 112, 122, 18,
                "USB 115200: LINK",
                C_COOL,
                blend565(C_CARD, C_COOL, 40),
                blend565(C_CARD_HI, C_COOL, 110), 1);

  // Initial Wi-Fi status placeholder pill
  drawPillBadge(32, 138, SCR_W - 64, 20,
                "Iniciando Wi-Fi & Listener UDP :8888...",
                C_TEXT, C_CARD_ELEV, C_CARD_HI, 1);

  // Accent progress bar
  drawSlimBar(32, 174, SCR_W - 64, 6, 55.0f, C_ACCENT, C_TRACK);
}

void drawBootSplashWifiStatus(bool wifiOk, const char* ipStr) {
  char msg[56];
  if (wifiOk && ipStr && ipStr[0]) {
    snprintf(msg, sizeof(msg), "WI-FI UDP ATIVO -> %s:8888", ipStr);
    drawPillBadge(32, 138, SCR_W - 64, 20, msg,
                  C_OK, blend565(C_CARD, C_OK, 42), blend565(C_CARD_HI, C_OK, 120), 1);
    drawSlimBar(32, 174, SCR_W - 64, 6, 100.0f, C_OK, C_TRACK);
  } else {
    snprintf(msg, sizeof(msg), "USB SERIAL 115200 ATIVO (WI-FI STANDBY)");
    drawPillBadge(32, 138, SCR_W - 64, 20, msg,
                  C_DIM, C_CARD_ELEV, C_CARD_HI, 1);
    drawSlimBar(32, 174, SCR_W - 64, 6, 100.0f, C_ACCENT, C_TRACK);
  }
}
