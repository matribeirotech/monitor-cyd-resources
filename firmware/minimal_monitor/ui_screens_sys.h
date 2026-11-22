// ui_screens_sys.h - CYD OS v5.0 System & Hardware Telemetry Screens (Telas 0..5)
// Target: ESP32-2432S028R (320x240 ST7789 TFT_eSPI)
// Safe content area: y = 26..220 (HDR_H = 24, TICKER_Y = 222)
#pragma once

// Helper interno para desenhar mini card termico com ponto semantico e barra slim (Tela 0)
static inline void drawSysThermalTile(int x, int y, int w, int h, const char *label, float tempC) {
  bool valid = (tempC > 0.0f);
  uint16_t col = valid ? levelColor(tempC, T_TEMP_HOT, T_TEMP_MAX) : C_MUTED;
  uint16_t brd = valid ? blend565(C_CARD_HI, col, 90) : C_CARD_HI;

  tft.fillRoundRect(x, y, w, h, PILL_R, C_CARD_ELEV);
  tft.drawRoundRect(x, y, w, h, PILL_R, brd);

  // Ponto luminoso semantico + label
  tft.fillCircle(x + 8, y + 8, 2, col);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD_ELEV);
  tft.drawString(label, x + 14, y + 4, 1);

  // Leitura principal em destaque (Font 2)
  char tBuf[16];
  if (valid) snprintf(tBuf, sizeof(tBuf), "%.0f C", tempC);
  else       snprintf(tBuf, sizeof(tBuf), "-- C");

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(w - 12);
  tft.setTextColor(valid ? C_TEXT : C_DIM, C_CARD_ELEV);
  tft.drawString(tBuf, x + 7, y + 14, 2);
  tft.setTextPadding(0);

  // Mini barra termica (0..100C)
  float pct = valid ? constrain(tempC, 0.0f, 100.0f) : 0.0f;
  drawSlimBar(x + 6, y + h - 7, w - 12, 3, pct, col, C_TRACK);
}

// =========================================== TELA 0: RESUMO (CPU + RAM) ====
// Executive Hardware Overview:
// - Top row (y=27..125, h=98): CPU hero card (C_COOL) + RAM hero card (C_PURPLE)
// - Bottom row (y=129..219, h=90): STORAGE & THERMALS + NETWORK & HOST
void screenResumoStatic() {
  renderBackground();
  drawHeader();

  // Top Row: Hero Gauges & Pills (y=27..124)
  drawModernCard(6,   27, 151, 98, "CPU", C_COOL);
  drawModernCard(163, 27, 151, 98, "RAM", C_PURPLE);

  // Bottom Row: Storage/Thermals & Network/Host (y=129..218)
  drawModernCard(6,   129, 151, 90, "STORAGE & THERMALS", C_OK);
  drawModernCard(163, 129, 151, 90, "NETWORK & HOST",     C_COOL);
}

void screenResumoDynamic() {
  char buf[40];

  // ---- Top-Left Card: CPU (x=6..156, y=27..124) ----
  // Gauge ring occupies x=13..75, y=47..109
  drawGauge(44, 78, 31, st.cpu, "LOAD", linked, 65.0f, 85.0f, 0);

  // Right column inside CPU card (x=82..149, w=67)
  if (st.cput > 0.0f) {
    uint16_t tCol = levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX);
    snprintf(buf, sizeof(buf), "%.0f C", st.cput);
    drawPillBadge(82, 43, 67, 20, buf, tCol, blend565(C_CARD, tCol, 40), tCol, 2);
  } else {
    drawPillBadge(82, 43, 67, 20, "-- C", C_DIM, C_CARD_ELEV, C_CARD_HI, 2);
  }

  if (st.cpuf > 0.0f) {
    snprintf(buf, sizeof(buf), "%.1fGHz", st.cpuf / 1000.0f);
    drawPillBadge(82, 67, 67, 20, buf, C_TEXT, C_CARD_ELEV, C_CARD_HI, 2);
  } else {
    snprintf(buf, sizeof(buf), "%d CORES", st.cores > 0 ? st.cores : 1);
    drawPillBadge(82, 67, 67, 20, buf, C_TEXT, C_CARD_ELEV, C_CARD_HI, 1);
  }

  if (st.cores > 0) snprintf(buf, sizeof(buf), "%d CORES", st.cores);
  else              snprintf(buf, sizeof(buf), "SYS CPU");
  drawPillBadge(82, 91, 67, 18, buf, C_COOL, blend565(C_CARD, C_COOL, 32), 0, 1);

  // ---- Top-Right Card: RAM (x=163..313, y=27..124) ----
  // Gauge ring occupies x=170..232, y=47..109
  drawGauge(201, 78, 31, st.ram, "MEM", linked, 75.0f, 90.0f, 1);

  // Right column inside RAM card (x=239..306, w=67)
  if (st.ramt > 0.0f) {
    snprintf(buf, sizeof(buf), "%.1f/%.0fG", st.ramu, st.ramt);
  } else {
    snprintf(buf, sizeof(buf), "%.0f%% USE", st.ram);
  }
  drawPillBadge(239, 43, 67, 20, buf, C_TEXT, blend565(C_CARD, C_PURPLE, 42), C_PURPLE, 1);

  if (st.ramt > st.ramu && st.ramt > 0.0f) {
    snprintf(buf, sizeof(buf), "%.1fG FREE", st.ramt - st.ramu);
  } else {
    snprintf(buf, sizeof(buf), "RAM OK");
  }
  drawPillBadge(239, 67, 67, 19, buf, C_DIM, C_CARD_ELEV, C_CARD_HI, 1);

  // Mini SWAP readout + slim progress bar (y=91..113)
  uint16_t swpCol = levelColor(st.swap, 60.0f, 85.0f);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("SWAP", 239, 91, 1);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(36);
  tft.setTextColor(swpCol, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.swap);
  tft.drawString(buf, 306, 91, 1);
  tft.setTextPadding(0);

  drawSlimBar(239, 102, 67, 5, st.swap, swpCol, C_TRACK);

  // ---- Bottom-Left Card: STORAGE & THERMALS (x=6..156, y=129..218) ----
  snprintf(buf, sizeof(buf), "%.0fG FREE", st.dskf);
  drawModernBar(14, 144, 135, 19, "DISK", st.dsk, buf, 80.0f, 92.0f);

  // Dual thermal comparison tiles (CPU C & GPU C) at y=169..211
  drawSysThermalTile(14, 169, 65, 42, "CPU", st.cput);
  drawSysThermalTile(84, 169, 65, 42, "GPU", st.gput);

  // ---- Bottom-Right Card: NETWORK & HOST (x=163..313, y=129..218) ----
  // RX Row (Cyan downward arrow + throughput + activity slim bar)
  tft.fillTriangle(171, 146, 177, 146, 174, 152, C_COOL);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_COOL, C_CARD);
  tft.drawString("RX", 181, 145, 1);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(92);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.2f MB/s", st.rx);
  tft.drawString(buf, 306, 143, 2);
  tft.setTextPadding(0);

  float rxPct = constrain((st.rx / T_NET_HEAVY) * 100.0f, 0.0f, 100.0f);
  drawSlimBar(171, 159, 135, 4, rxPct, C_COOL, C_TRACK);

  // TX Row (Rose upward arrow + throughput + activity slim bar)
  tft.fillTriangle(174, 168, 171, 174, 177, 174, C_PINK);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_PINK, C_CARD);
  tft.drawString("TX", 181, 168, 1);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(92);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.2f MB/s", st.tx);
  tft.drawString(buf, 306, 166, 2);
  tft.setTextPadding(0);

  float txPct = constrain((st.tx / T_NET_HEAVY) * 100.0f, 0.0f, 100.0f);
  drawSlimBar(171, 182, 135, 4, txPct, C_PINK, C_TRACK);

  // Host & Uptime badge at bottom (y=192..210)
  char upStr[16];
  fmtUptime(st.up, upStr, sizeof(upStr));
  snprintf(buf, sizeof(buf), "%.9s | UP %s", st.host[0] ? st.host : "PC-HOST", upStr);
  drawPillBadge(171, 192, 135, 18, buf, C_TEXT, C_CARD_ELEV, C_CARD_HI, 1);
}

// =========================================== TELA 1: PAINEL CPU + RAM ======
// Split Performance Studio:
// - 2-column vertical dashboard (x=6 w=151 CPU in C_COOL, x=163 w=151 RAM in C_PURPLE, y=27..175)
// - Bottom full-width 4-column mini KPI strip (x=6 y=179 w=308 h=40)
void screenCpuRamStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   27, 151, 148, "CPU STUDIO", C_COOL);
  drawModernCard(163, 27, 151, 148, "RAM STUDIO", C_PURPLE);

  drawModernCard(6,   179, 308, 40, nullptr, C_ACCENT);
}

void screenCpuRamDynamic() {
  char buf[48];

  // ---- Left Column: CPU Studio (x=6..156, y=27..174) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.cpu);
  tft.drawString(buf, 14, 42, 4);
  tft.setTextPadding(0);

  // CPU Status Pills (Temp & Clock) on right of hero %
  if (st.cput > 0.0f) {
    uint16_t tCol = levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX);
    snprintf(buf, sizeof(buf), "%.0f C", st.cput);
    drawPillBadge(82, 41, 67, 13, buf, tCol, blend565(C_CARD, tCol, 36), tCol, 1);
  } else {
    drawPillBadge(82, 41, 67, 13, "-- C", C_DIM, C_CARD_ELEV, 0, 1);
  }

  if (st.cpuf > 0.0f) snprintf(buf, sizeof(buf), "%.2fGHz", st.cpuf / 1000.0f);
  else                snprintf(buf, sizeof(buf), "%d CORES", st.cores > 0 ? st.cores : 1);
  drawPillBadge(82, 56, 67, 13, buf, C_COOL, C_CARD_ELEV, 0, 1);

  drawSegmentedBar(14, 73, 135, 11, st.cpu, 65.0f, 85.0f);

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_MUTED, C_CARD);
  tft.drawString("HISTORY", 14, 87, 1);
  plotGraph(14, 98, 135, 69, hCpu, C_COOL, "%");

  // ---- Right Column: RAM Studio (x=163..313, y=27..174) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.ram);
  tft.drawString(buf, 171, 42, 4);
  tft.setTextPadding(0);

  // RAM Status Pills (GB Used/Total & Swap) on right of hero %
  if (st.ramt > 0.0f) snprintf(buf, sizeof(buf), "%.1f/%.0fG", st.ramu, st.ramt);
  else                snprintf(buf, sizeof(buf), "RAM USE");
  drawPillBadge(239, 41, 67, 13, buf, C_PURPLE, blend565(C_CARD, C_PURPLE, 36), C_PURPLE, 1);

  snprintf(buf, sizeof(buf), "SWP %.0f%%", st.swap);
  drawPillBadge(239, 56, 67, 13, buf, levelColor(st.swap, 60.0f, 85.0f), C_CARD_ELEV, 0, 1);

  drawSegmentedBar(171, 73, 135, 11, st.ram, 75.0f, 90.0f);

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_MUTED, C_CARD);
  tft.drawString("HISTORY", 171, 87, 1);
  plotGraph(171, 98, 135, 69, hRam, C_PURPLE, "%");

  // ---- Bottom 4-Column Telemetry Strip (x=6..313, y=179..218) ----
  // Subtle vertical hairlines separating the 4 columns
  tft.drawFastVLine(83,  185, 28, C_MUTED);
  tft.drawFastVLine(160, 185, 28, C_MUTED);
  tft.drawFastVLine(237, 185, 28, C_MUTED);

  // Col 1: GPU (x=12..77)
  float gpuVal = (st.gpu >= 0.0f) ? st.gpu : 0.0f;
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("GPU", 12, 184, 1);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(36);
  if (st.gput > 0.0f) {
    tft.setTextColor(levelColor(st.gput, T_TEMP_HOT, T_TEMP_MAX), C_CARD);
    snprintf(buf, sizeof(buf), "%.0fC", st.gput);
  } else {
    tft.setTextColor(C_MUTED, C_CARD);
    snprintf(buf, sizeof(buf), "--C");
  }
  tft.drawString(buf, 77, 184, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(st.gpu >= 0.0f ? C_TEXT : C_DIM, C_CARD);
  if (st.gpu >= 0.0f) snprintf(buf, sizeof(buf), "%.0f%%", gpuVal);
  else                snprintf(buf, sizeof(buf), "N/A");
  tft.drawString(buf, 12, 194, 2);
  tft.setTextPadding(0);
  drawSlimBar(12, 211, 65, 3, gpuVal, C_OK, C_TRACK);

  // Col 2: DISK (x=89..154)
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("DISK", 89, 184, 1);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(38);
  tft.setTextColor(C_COOL, C_CARD);
  snprintf(buf, sizeof(buf), "%.0fG", st.dskf);
  tft.drawString(buf, 154, 184, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.dsk);
  tft.drawString(buf, 89, 194, 2);
  tft.setTextPadding(0);
  drawSlimBar(89, 211, 65, 3, st.dsk, levelColor(st.dsk, 80.0f, 92.0f), C_TRACK);

  // Col 3: NET RX/TX (x=166..231)
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("NET", 166, 184, 1);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(42);
  tft.setTextColor(C_COOL, C_CARD);
  snprintf(buf, sizeof(buf), "%.1fM", st.rx + st.tx);
  tft.drawString(buf, 231, 184, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(65);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "v%.1f ^%.1f", st.rx, st.tx);
  tft.drawString(buf, 166, 195, 1);
  tft.setTextPadding(0);

  float netPct = constrain(((st.rx + st.tx) / T_NET_HEAVY) * 100.0f, 0.0f, 100.0f);
  drawSlimBar(166, 211, 65, 3, netPct, C_COOL, C_TRACK);

  // Col 4: UPTIME (x=243..307)
  char upStr[16];
  fmtUptime(st.up, upStr, sizeof(upStr));

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("UPTIME", 243, 184, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(64);
  tft.setTextColor(C_TEXT, C_CARD);
  tft.drawString(upStr, 243, 194, 2);
  tft.setTextPadding(0);
  drawSlimBar(243, 211, 64, 3, linked ? 100.0f : 0.0f, linked ? C_OK : C_WARN, C_TRACK);
}

// =========================================== TELA 2: GRAFICO DUPLO CPU+RAM =
// Dual Telemetry Analytics:
// - Top 2 compact KPI cards (y=27..79, h=52): CPU hero + RAM hero
// - Main full-width chart card (x=6 y=83 w=308 h=136): plotDualCpuRamGraph
void screenCpuRamDualStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   27, 151, 52, "CPU TELEMETRY", C_COOL);
  drawModernCard(163, 27, 151, 52, "RAM TELEMETRY", C_PURPLE);
  drawModernCard(6,   83, 308, 136, "DUAL STREAM: CPU vs RAM", C_ACCENT);
}

void screenCpuRamDualDynamic() {
  char buf[40];

  // ---- Top-Left KPI Card: CPU (x=6..156, y=27..78) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(62);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.cpu);
  tft.drawString(buf, 14, 42, 4);
  tft.setTextPadding(0);

  if (st.cput > 0.0f) {
    uint16_t tCol = levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX);
    snprintf(buf, sizeof(buf), "%.0f C", st.cput);
    drawPillBadge(82, 40, 67, 13, buf, tCol, blend565(C_CARD, tCol, 36), tCol, 1);
  } else {
    drawPillBadge(82, 40, 67, 13, "-- C", C_DIM, C_CARD_ELEV, 0, 1);
  }

  if (st.cpuf > 0.0f && st.cores > 0) {
    snprintf(buf, sizeof(buf), "%.1fG %dC", st.cpuf / 1000.0f, st.cores);
  } else if (st.cpuf > 0.0f) {
    snprintf(buf, sizeof(buf), "%.0fMHz", st.cpuf);
  } else {
    snprintf(buf, sizeof(buf), "%d CORES", st.cores > 0 ? st.cores : 1);
  }
  drawPillBadge(82, 56, 67, 13, buf, C_COOL, C_CARD_ELEV, 0, 1);
  drawSlimBar(14, 72, 135, 3, st.cpu, C_COOL, C_TRACK);

  // ---- Top-Right KPI Card: RAM (x=163..313, y=27..78) ----
  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(62);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.ram);
  tft.drawString(buf, 171, 42, 4);
  tft.setTextPadding(0);

  if (st.ramt > 0.0f) snprintf(buf, sizeof(buf), "%.1f/%.0fG", st.ramu, st.ramt);
  else                snprintf(buf, sizeof(buf), "RAM %.0f%%", st.ram);
  drawPillBadge(239, 40, 67, 13, buf, C_PURPLE, blend565(C_CARD, C_PURPLE, 36), C_PURPLE, 1);

  snprintf(buf, sizeof(buf), "SWP %.0f%%", st.swap);
  drawPillBadge(239, 56, 67, 13, buf, levelColor(st.swap, 60.0f, 85.0f), C_CARD_ELEV, 0, 1);
  drawSlimBar(171, 72, 135, 3, st.ram, C_PURPLE, C_TRACK);

  // ---- Bottom Full-Width Dual Chart Card (x=6..313, y=83..218) ----
  plotDualCpuRamGraph(14, 100, 292, 111);
}

// =========================================== TELA 3: GPU FOCUS =============
// GPU Command Center:
// - Left hero card (x=6 y=27 w=142 h=192): GPU model badge, drawGauge(r=38), TEMP + POWER grid, FPS/FAN pill
// - Top-right card (x=154 y=27 w=160 h=84): VRAM hero + % badge + drawSegmentedBar + thermal status bar
// - Bottom-right card (x=154 y=115 w=160 h=104): Live GPU Load plotGraph
void screenGpuFocusStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   27,  142, 192, "GPU CORE",       C_OK);
  drawModernCard(154, 27,  160, 84,  "VRAM & THERMAL", C_PURPLE);
  drawModernCard(154, 115, 160, 104, "GPU HISTORY",    C_OK);
}

void screenGpuFocusDynamic() {
  char buf[40];
  bool hasGpu = (st.gpu >= 0.0f);
  float gpuVal = hasGpu ? st.gpu : 0.0f;

  // ---- Left Hero Card (x=6..147, y=27..218) ----
  // 1) GPU Model Badge at top (y=41..56)
  const char *gName = (st.gpuname[0]) ? st.gpuname : (hasGpu ? "GPU ENGINE" : "NO DEDICATED GPU");
  drawPillBadge(14, 41, 126, 15, gName, hasGpu ? C_TEXT : C_DIM, C_CARD_ELEV, C_CARD_HI, 1);

  // 2) Large Anti-Aliased Gauge (slot 0, r=38) at cx=77, cy=99 (y=61..137)
  drawGauge(77, 99, 38, gpuVal, hasGpu ? "GPU LOAD" : "OFFLINE", linked && hasGpu, 70.0f, 90.0f, 0);

  // 3) 2-Pill Metric Grid below gauge: TEMP (left) + POWER (right) at y=143..173
  // Left Tile: TEMP
  tft.fillRoundRect(14, 143, 60, 30, PILL_R, C_CARD_ELEV);
  tft.drawRoundRect(14, 143, 60, 30, PILL_R, C_CARD_HI);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD_ELEV);
  tft.drawString("TEMP", 20, 146, 1);

  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(50);
  if (st.gput > 0.0f) {
    snprintf(buf, sizeof(buf), "%.0f C", st.gput);
    tft.setTextColor(levelColor(st.gput, T_TEMP_HOT, T_TEMP_MAX), C_CARD_ELEV);
  } else {
    snprintf(buf, sizeof(buf), "-- C");
    tft.setTextColor(C_DIM, C_CARD_ELEV);
  }
  tft.drawString(buf, 44, 163, 2);
  tft.setTextPadding(0);

  // Right Tile: POWER
  tft.fillRoundRect(80, 143, 60, 30, PILL_R, C_CARD_ELEV);
  tft.drawRoundRect(80, 143, 60, 30, PILL_R, C_CARD_HI);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD_ELEV);
  tft.drawString("POWER", 86, 146, 1);

  tft.setTextDatum(MC_DATUM);
  tft.setTextPadding(50);
  if (st.gpuw > 0.0f) {
    snprintf(buf, sizeof(buf), "%.0f W", st.gpuw);
    tft.setTextColor(C_WARN, C_CARD_ELEV);
  } else {
    snprintf(buf, sizeof(buf), "-- W");
    tft.setTextColor(C_DIM, C_CARD_ELEV);
  }
  tft.drawString(buf, 110, 163, 2);
  tft.setTextPadding(0);

  // 4) Bottom Status Pill: FPS / FAN / Desktop Mode (y=179..207)
  uint16_t modeCol = C_COOL;
  if (st.fps >= 0) {
    snprintf(buf, sizeof(buf), "GAME: %d FPS", st.fps);
    modeCol = C_OK;
  } else if (st.gpufan >= 0) {
    snprintf(buf, sizeof(buf), "FAN: %d%%", st.gpufan);
    modeCol = C_COOL;
  } else if (!hasGpu) {
    snprintf(buf, sizeof(buf), "SHARED / IGPU");
    modeCol = C_MUTED;
  } else {
    snprintf(buf, sizeof(buf), "MODE: DESKTOP");
    modeCol = C_COOL;
  }
  drawPillBadge(14, 179, 126, 28, buf, hasGpu ? C_TEXT : C_DIM,
                blend565(C_CARD, modeCol, 34), modeCol, (strlen(buf) <= 13) ? 2 : 1);

  // ---- Top-Right Card: VRAM & THERMAL (x=154..313, y=27..110) ----
  float vramPct = (st.vram >= 0.0f) ? st.vram : st.ram;
  uint16_t vCol = levelColor(vramPct, 75.0f, 90.0f);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(94);
  tft.setTextColor(C_TEXT, C_CARD);
  if (st.vramu >= 0.0f && st.vramt > 0.0f) {
    snprintf(buf, sizeof(buf), "%.1f / %.0f GB", st.vramu, st.vramt);
  } else if (st.vram >= 0.0f) {
    snprintf(buf, sizeof(buf), "VRAM %.0f%%", st.vram);
  } else if (st.ramt > 0.0f) {
    snprintf(buf, sizeof(buf), "%.1f/%.0fG SHM", st.ramu, st.ramt);
  } else {
    snprintf(buf, sizeof(buf), "MEM %.0f%%", st.ram);
  }
  tft.drawString(buf, 162, 41, 2);
  tft.setTextPadding(0);

  snprintf(buf, sizeof(buf), "%.0f%%", vramPct);
  drawPillBadge(260, 41, 46, 16, buf, vCol, blend565(C_CARD, vCol, 38), vCol, 1);

  drawSegmentedBar(162, 62, 144, 11, vramPct, 75.0f, 90.0f);

  float gTemp = (st.gput > 0.0f) ? st.gput : ((st.cput > 0.0f) ? st.cput : 0.0f);
  const char *tLbl = (st.gput > 0.0f) ? "GPU TEMP" : "CORE TEMP";
  if (gTemp > 0.0f) snprintf(buf, sizeof(buf), "%.1f C", gTemp);
  else              snprintf(buf, sizeof(buf), "-- C");
  drawModernBar(162, 80, 144, 19, tLbl, gTemp, buf, T_TEMP_HOT, T_TEMP_MAX);

  // ---- Bottom-Right Card: GPU LOAD HISTORY (x=154..313, y=115..218) ----
  plotGraph(162, 134, 144, 77, hGpu, C_OK, "%");
}

// =========================================== TELA 4: GRAFICOS (4x) =========
// 2x2 Quad Telemetry Matrix:
// - 4 symmetric modern cards (151x94 each, 6px gutters)
// - TL: CPU LOAD (C_COOL), TR: RAM USE (C_PURPLE), BL: GPU LOAD (C_OK), BR: THERMAL (C_HOT/C_WARN)
void screenGraphStatic() {
  renderBackground();
  drawHeader();

  drawModernCard(6,   27,  151, 94, "CPU LOAD", C_COOL);
  drawModernCard(163, 27,  151, 94, "RAM USE",  C_PURPLE);
  drawModernCard(6,   126, 151, 94, "GPU LOAD", C_OK);
  drawModernCard(163, 126, 151, 94, "THERMAL",  C_HOT);
}

void screenGraphDynamic() {
  float curTmp = maxTemp();
  uint16_t tmpCol = (curTmp >= T_TEMP_HOT) ? C_HOT : C_WARN;

  plotGraph(14,  45,  135, 69, hCpu, C_COOL,   "%");
  plotGraph(171, 45,  135, 69, hRam, C_PURPLE, "%");
  plotGraph(14,  144, 135, 69, hGpu, C_OK,     "%");
  plotGraph(171, 144, 135, 69, hTmp, tmpCol,   "C");
}

// =========================================== TELA 5: WALLPAPER HUD =========
// Floating Minimalist HUD:
// - Preserves full SD wallpaper unobscured in upper/middle area
// - Sleek floating dark dock card at bottom (x=8 y=166 w=304 h=52) with 3 crisp columns
void screenWallpaperStatic() {
  renderBackground();
  drawHeader();
  drawModernCard(8, 166, 304, 52, nullptr, C_ACCENT);
}

void screenWallpaperDynamic() {
  char buf[32];

  // Vertical dividers inside floating dock (x=8..311, y=166..217)
  tft.drawFastVLine(109, 173, 38, C_MUTED);
  tft.drawFastVLine(210, 173, 38, C_MUTED);

  // ---- Column 1: CPU % + Temp (x=14..104, w=90) ----
  tft.fillCircle(18, 176, 2, C_COOL);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("CPU", 24, 172, 1);

  if (st.cput > 0.0f) {
    uint16_t tCol = levelColor(st.cput, T_TEMP_HOT, T_TEMP_MAX);
    snprintf(buf, sizeof(buf), "%.0fC", st.cput);
    drawPillBadge(64, 170, 40, 13, buf, tCol, C_CARD_ELEV, 0, 1);
  } else {
    drawPillBadge(64, 170, 40, 13, "--C", C_DIM, C_CARD_ELEV, 0, 1);
  }

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(48);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.cpu);
  tft.drawString(buf, 14, 186, 2);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(40);
  tft.setTextColor(C_COOL, C_CARD);
  if (st.cpuf > 0.0f) snprintf(buf, sizeof(buf), "%.1fG", st.cpuf / 1000.0f);
  else                snprintf(buf, sizeof(buf), "%dC", st.cores > 0 ? st.cores : 1);
  tft.drawString(buf, 104, 190, 1);
  tft.setTextPadding(0);

  drawSlimBar(14, 206, 90, 5, st.cpu, C_COOL, C_TRACK);

  // ---- Column 2: RAM % + GB (x=115..205, w=90) ----
  tft.fillCircle(119, 176, 2, C_PURPLE);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString("RAM", 125, 172, 1);

  if (st.ramt > 0.0f) snprintf(buf, sizeof(buf), "%.1fG", st.ramu);
  else                snprintf(buf, sizeof(buf), "MEM");
  drawPillBadge(161, 170, 44, 13, buf, C_PURPLE, C_CARD_ELEV, 0, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(48);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", st.ram);
  tft.drawString(buf, 115, 186, 2);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(40);
  tft.setTextColor(C_DIM, C_CARD);
  if (st.ramt > 0.0f) snprintf(buf, sizeof(buf), "/%.0fG", st.ramt);
  else                snprintf(buf, sizeof(buf), "S:%.0f%%", st.swap);
  tft.drawString(buf, 205, 190, 1);
  tft.setTextPadding(0);

  drawSlimBar(115, 206, 90, 5, st.ram, C_PURPLE, C_TRACK);

  // ---- Column 3: GPU/NET + Uptime (x=216..305, w=89) ----
  bool hasGpu = (st.gpu >= 0.0f);
  float col3Pct = hasGpu ? st.gpu : st.dsk;

  tft.fillCircle(220, 176, 2, C_OK);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_DIM, C_CARD);
  tft.drawString(hasGpu ? "GPU" : "DSK", 226, 172, 1);

  char upStr[16];
  fmtUptime(st.up, upStr, sizeof(upStr));
  drawPillBadge(255, 170, 50, 13, upStr, C_TEXT, C_CARD_ELEV, 0, 1);

  tft.setTextDatum(TL_DATUM);
  tft.setTextPadding(44);
  tft.setTextColor(C_TEXT, C_CARD);
  snprintf(buf, sizeof(buf), "%.0f%%", col3Pct);
  tft.drawString(buf, 216, 186, 2);

  tft.setTextDatum(TR_DATUM);
  tft.setTextPadding(44);
  tft.setTextColor(C_OK, C_CARD);
  snprintf(buf, sizeof(buf), "%.1fM/s", st.rx + st.tx);
  tft.drawString(buf, 305, 190, 1);
  tft.setTextPadding(0);

  drawSlimBar(216, 206, 89, 5, col3Pct, C_OK, C_TRACK);
}
