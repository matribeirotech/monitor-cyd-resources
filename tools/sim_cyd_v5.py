#!/usr/bin/env python3
"""
sim_cyd_v5.py - Exact 320x240 Pixel-Accurate Simulator & Preview Generator for CYD OS v5.0 (Obsidian Dark UI).

Simulates the exact RGB565 color math (applyColor565, blend565, levelColor) and
320x240 layout geometry across all 4 screen groups of the CYD ESP32-2432S028R firmware:
  1. Boot Splash (v5.0 Hybrid Telemetry)
  2. Tela 0: Resumo Geral (CPU & RAM Gauges + Storage/Thermals + Network/Host)
  3. Tela 1: CPU / RAM Studio (Segmented Bars + Real-Time Area Charts + 4-Col KPI Strip)
  4. Tela 3: GPU Focus (Large Gauge + VRAM Segmented Bar + Thermal Bar + GPU History)
  5. Tela 6: Mercado Financeiro & Cripto (USD, EUR, IBOV, Watchlist + BTC 24h Sparkline)
  6. Tela 7: Portfolio Pessoal (Patrimonio Consolidado, PnL Hero, Allocation + Top 3 Ativos)
  7. Tela 8: Pomodoro Focus Studio (Smooth Circular Arc + Cycle Dots + Deep Work Status)
  8. Tela 9: Media Hub Now Playing (Studio Vinyl Stage + Smoked Glass Overlay + Equalizer)
  9. Tela 10: Clima Regional & News Desk (Vector Weather + Scrolling Headline Sprite + Summary)
 10. Tela 12: RF Radar & Live Packet Flow (ESP32-32U RF + 2.4GHz Spectrum + Animated Packet Flow + APs)
 11. Tela 13: Net / WAN Fiber Analyzer (Router/Gateway + WAN/DNS/ISP + Realtime Link + Speedtest)
 12. Tela 14: SOC / IDS Security Monitor (Vector Tactical Shield + 2x2 IDS KPIs + Event Log Stream)

Outputs 2x-upscaled crisp PNG previews (640x480) + a 3x4 full-screen showcase grid.
"""
import math
import os
import random
import shutil
from PIL import Image, ImageDraw, ImageFont

# ---- Display Geometry Constants (from ui_theme.h) ----
SCR_W = 320
SCR_H = 240
HDR_H = 24
TICKER_H = 18
TICKER_Y = SCR_H - TICKER_H  # 222
CONTENT_Y = HDR_H + 2        # 26
CONTENT_H = TICKER_Y - CONTENT_Y - 2  # 194 (y = 26..220)
CARD_R = 7
PILL_R = 4

# ---- Fonts approximating TFT_eSPI built-in Fonts 1 (6x8), 2 (~16px), 4 (~26px) ----
def _load_font(candidates: list[str], size: int):
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


MONO_CANDIDATES = [
    "/usr/share/fonts/adwaita-mono-fonts/AdwaitaMono-Regular.ttf",
    "/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-Medium.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
SANS_BOLD_CANDIDATES = [
    "/usr/share/fonts/google-carlito-fonts/Carlito-Bold.ttf",
    "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Bold.otf",
    "/usr/share/fonts/adwaita-mono-fonts/AdwaitaMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

F1 = _load_font(MONO_CANDIDATES, 8)
F2 = _load_font(SANS_BOLD_CANDIDATES, 11)
F4 = _load_font(SANS_BOLD_CANDIDATES, 20)


# ---- RGB565 Color Engine (exact match with ui_theme.h & ui_components.h) ----
def rgb888_to_565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def rgb565_to_888(c: int) -> tuple[int, int, int]:
    r5 = (c >> 11) & 0x1F
    g6 = (c >> 5) & 0x3F
    b5 = c & 0x1F
    r = (r5 << 3) | (r5 >> 2)
    g = (g6 << 2) | (g6 >> 4)
    b = (b5 << 3) | (b5 >> 2)
    return (r, g, b)


def blend565(bg: int, fg: int, alpha: int) -> int:
    inv = 255 - alpha
    r = (((bg >> 11) & 0x1F) * inv + ((fg >> 11) & 0x1F) * alpha) // 255
    g = (((bg >> 5) & 0x3F) * inv + ((fg >> 5) & 0x3F) * alpha) // 255
    b = ((bg & 0x1F) * inv + (fg & 0x1F) * alpha) // 255
    return ((r & 0x1F) << 11) | ((g & 0x3F) << 5) | (b & 0x1F)


# Default dynamic accent: Sky/Emerald Cyber Cyan-Teal (0x3DFF or 0x07E0)
C_BG_565          = 0x0842  # Deep obsidian #070B14
C_CARD_565        = 0x08A5  # Elevated dark slate #0F172A
C_CARD_ELEV_565   = 0x1106  # Nested pill/badge slate #162033
C_TRACK_565       = 0x1926  # Recessed progress track #1A2436
C_TEXT_565        = 0xF7BE  # Crisp off-white #F1F5F9
C_DIM_565         = 0x8CD6  # Cool slate #8A9BB5
C_MUTED_565       = 0x4AF0  # Subtle slate #4D5E78
C_ACCENT_565      = 0x3DFF  # Dynamic accent (Sky Cyan #38BDF8)
C_CARD_HI_565     = blend565(0x2189, C_ACCENT_565, 45)
C_ACCENT_SOFT_565 = blend565(C_CARD_565, C_ACCENT_565, 48)
C_ACCENT_DK_565   = blend565(0x0842, C_ACCENT_565, 30)

C_OK_565     = 0x262B  # Emerald #22C55E
C_WARN_565   = 0xF4E1  # Amber #F59E0B
C_HOT_565    = 0xEA28  # Coral Red #EF4444
C_COOL_565   = 0x3DFF  # Sky Cyan #38BDF8
C_PURPLE_565 = 0xAAAE  # Violet #A855F7
C_PINK_565   = 0xEA53  # Rose #EC4899

C_BG          = rgb565_to_888(C_BG_565)
C_CARD        = rgb565_to_888(C_CARD_565)
C_CARD_ELEV   = rgb565_to_888(C_CARD_ELEV_565)
C_CARD_HI     = rgb565_to_888(C_CARD_HI_565)
C_TRACK       = rgb565_to_888(C_TRACK_565)
C_TEXT        = rgb565_to_888(C_TEXT_565)
C_DIM         = rgb565_to_888(C_DIM_565)
C_MUTED       = rgb565_to_888(C_MUTED_565)
C_ACCENT      = rgb565_to_888(C_ACCENT_565)
C_ACCENT_SOFT = rgb565_to_888(C_ACCENT_SOFT_565)
C_ACCENT_DK   = rgb565_to_888(C_ACCENT_DK_565)
C_OK          = rgb565_to_888(C_OK_565)
C_WARN        = rgb565_to_888(C_WARN_565)
C_HOT         = rgb565_to_888(C_HOT_565)
C_COOL        = rgb565_to_888(C_COOL_565)
C_PURPLE      = rgb565_to_888(C_PURPLE_565)
C_PINK        = rgb565_to_888(C_PINK_565)


def b565(bg565: int, fg565: int, alpha: int) -> tuple[int, int, int]:
    return rgb565_to_888(blend565(bg565, fg565, alpha))


def level_color565(v: float, warn: float, hot: float) -> int:
    if v >= hot:
        return C_HOT_565
    if v >= warn:
        return C_WARN_565
    return C_OK_565


def level_color(v: float, warn: float, hot: float) -> tuple[int, int, int]:
    return rgb565_to_888(level_color565(v, warn, hot))


# ---- Core Drawing Primitives (ui_components.h) ----
def font_for(idx: int):
    if idx == 1:
        return F1
    if idx == 2:
        return F2
    return F4


def draw_str(d: ImageDraw.ImageDraw, text: str, x: int, y: int, font_idx: int,
             fg: tuple[int, int, int], datum: str = "TL") -> int:
    f = font_for(font_idx)
    anchor_map = {
        "TL": "lt", "TC": "mt", "TR": "rt",
        "ML": "lm", "MC": "mm", "MR": "rm",
        "BL": "lb", "BC": "mb", "BR": "rb",
    }
    anc = anchor_map.get(datum, "lt")
    d.text((x, y), text, font=f, fill=fg, anchor=anc)
    bbox = d.textbbox((x, y), text, font=f, anchor=anc)
    return bbox[2] - bbox[0]


def fill_round_rect(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, r: int,
                    fill=None, outline=None):
    if w <= 0 or h <= 0:
        return
    r = max(0, min(r, w // 2, h // 2))
    d.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=r, fill=fill, outline=outline)


def draw_pill_badge(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, text: str,
                    fg: tuple[int, int, int], bg: tuple[int, int, int],
                    border: tuple[int, int, int] | None = None, font_idx: int = 1):
    r = min(PILL_R, min(w, h) // 2)
    fill_round_rect(d, x, y, w, h, r, fill=bg, outline=border)
    if text:
        draw_str(d, text, x + w // 2, y + h // 2, font_idx, fg, "MC")


def draw_delta_badge(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, pct: float):
    up = pct >= 0.0
    fg565 = C_OK_565 if up else C_HOT_565
    fg = rgb565_to_888(fg565)
    bg = b565(C_CARD_565, fg565, 42)
    bd = b565(C_CARD_565, fg565, 96)
    r = min(PILL_R, min(w, h) // 2)
    fill_round_rect(d, x, y, w, h, r, fill=bg, outline=bd)
    buf = f"{'+' if up else ''}{pct:.2f}%"
    if w >= 42:
        tx = x + 6
        cy = y + h // 2
        if up:
            d.polygon([(tx, cy - 2), (tx - 3, cy + 2), (tx + 3, cy + 2)], fill=fg)
        else:
            d.polygon([(tx, cy + 2), (tx - 3, cy - 2), (tx + 3, cy - 2)], fill=fg)
        draw_str(d, buf, x + 6 + (w - 6) // 2, y + h // 2, 1, fg, "MC")
    else:
        draw_str(d, buf, x + w // 2, y + h // 2, 1, fg, "MC")


def draw_modern_card(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                     title: str | None = None, accent565: int = 0):
    acc565 = accent565 if accent565 else C_ACCENT_565
    acc = rgb565_to_888(acc565)
    border = b565(C_CARD_HI_565, acc565, 55) if accent565 else C_CARD_HI
    fill_round_rect(d, x, y, w, h, CARD_R, fill=C_CARD, outline=border)
    if w > CARD_R * 2 + 4:
        spec = b565(C_CARD_565, acc565, 38)
        d.line([(x + CARD_R, y + 1), (x + w - CARD_R - 1, y + 1)], fill=spec)
    if title:
        fill_round_rect(d, x + 6, y + 4, 3, 9, 1, fill=acc)
        draw_str(d, title, x + 13, y + 5, 1, C_DIM, "TL")


def draw_header_and_clock(d: ImageDraw.ImageDraw, scr_title: str,
                          right_badge_text: str = "SAO PAULO",
                          right_badge_col565: int = 0,
                          temp_c: float = 26.0,
                          hh: int = 14, mm: int = 32, date_short: str = "22/11"):
    # Header Bar (y=0..23)
    d.rectangle([0, 0, SCR_W - 1, HDR_H - 2], fill=C_ACCENT_DK)
    d.line([(0, HDR_H - 1), (SCR_W - 1, HDR_H - 1)], fill=C_CARD_HI)
    d.line([(0, HDR_H - 1), (87, HDR_H - 1)], fill=C_ACCENT)

    # Geometric icon badge (x=4..18, y=4..18)
    fill_round_rect(d, 4, 4, 14, 15, 3, fill=C_ACCENT_SOFT, outline=C_ACCENT)
    d.line([(7, 8), (10, 11)], fill=C_ACCENT)
    d.line([(7, 14), (10, 11)], fill=C_ACCENT)
    d.line([(11, 14), (13, 14)], fill=C_TEXT)

    draw_str(d, scr_title, 22, 11, 2, C_TEXT, "ML")

    # Right cluster (x=102..319)
    d.line([(102, 5), (102, 17)], fill=C_CARD_HI)
    d.ellipse([106, 8, 112, 14], fill=b565(C_ACCENT_DK_565, C_OK_565, 85))
    d.ellipse([107, 9, 111, 13], fill=C_OK)

    w_time = draw_str(d, f"{hh:02d}:{mm:02d}", 116, 11, 2, C_TEXT, "ML")
    draw_str(d, date_short, 116 + w_time + 4, 12, 1, C_DIM, "ML")

    # Weather pill (x=190, y=3, w=40, h=16)
    t_col565 = C_OK_565 if 20 <= temp_c < 30 else (C_WARN_565 if temp_c >= 30 else C_COOL_565)
    p_bg = b565(C_ACCENT_DK_565, t_col565, 45)
    p_bd = b565(C_CARD_HI_565, t_col565, 130)
    fill_round_rect(d, 190, 3, 40, 16, PILL_R, fill=p_bg, outline=p_bd)
    draw_str(d, f"{temp_c:.0f}C", 210, 11, 2, C_TEXT, "MC")

    # Right status / city badge (x=234, y=3, w=82, h=16)
    if right_badge_col565:
        fg = rgb565_to_888(right_badge_col565)
        bg = b565(C_ACCENT_DK_565, right_badge_col565, 42)
        bd = b565(C_CARD_HI_565, right_badge_col565, 110)
        draw_pill_badge(d, 234, 3, 82, 16, right_badge_text, fg, bg, bd, 1)
    else:
        draw_pill_badge(d, 234, 3, 82, 16, right_badge_text, C_ACCENT, C_ACCENT_SOFT, C_CARD_HI, 1)


def draw_ticker_tape(d: ImageDraw.ImageDraw):
    y0 = TICKER_Y
    d.rectangle([0, y0, SCR_W - 1, SCR_H - 1], fill=C_CARD)
    d.line([(0, y0), (SCR_W - 1, y0)], fill=C_CARD_HI)

    segments = [
        ("USD", "R$5.78", +0.42),
        ("BTC", "$94,250", +3.85),
        ("ETH", "$3,140", +2.15),
        ("IBOV", "129.4k", -0.18),
    ]
    x = 44
    for sym, price, chg in segments:
        up = chg >= 0
        ccol = C_OK if up else C_HOT
        x += draw_str(d, sym, x, y0 + 10, 2, C_ACCENT, "ML") + 4
        x += draw_str(d, price, x, y0 + 10, 2, C_TEXT, "ML") + 5
        if up:
            d.polygon([(x + 3, y0 + 6), (x, y0 + 12), (x + 6, y0 + 12)], fill=ccol)
        else:
            d.polygon([(x + 3, y0 + 12), (x, y0 + 6), (x + 6, y0 + 6)], fill=ccol)
        x += 9
        x += draw_str(d, f"{'+' if up else ''}{chg:.2f}%", x, y0 + 10, 2, ccol, "ML") + 8
        d.ellipse([x - 1, y0 + 8, x + 1, y0 + 10], fill=C_MUTED)
        x += 8

    # Left fixed MKT badge
    d.rectangle([0, y0 + 1, 40, SCR_H - 1], fill=C_CARD)
    d.line([(39, y0 + 2), (39, SCR_H - 2)], fill=C_CARD_HI)
    fill_round_rect(d, 3, y0 + 3, 33, TICKER_H - 5, 3, fill=C_ACCENT_SOFT, outline=C_ACCENT)
    draw_str(d, "MKT", 19, y0 + 9, 1, C_ACCENT, "MC")


def draw_slim_bar(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                  pct: float, fill_col565: int, track_col: tuple[int, int, int] = C_TRACK):
    v = max(0.0, min(100.0, pct))
    radius = min(3, max(1, h // 2))
    fill_round_rect(d, x, y, w, h, radius, fill=track_col)
    fill_w = int((w * v) / 100.0 + 0.5)
    if fill_w > 0:
        fill_w = min(w, max(fill_w, radius * 2))
        fill_col = rgb565_to_888(fill_col565)
        fill_round_rect(d, x, y, fill_w, h, radius, fill=fill_col)
        if h >= 5 and fill_w > 4:
            hi = b565(fill_col565, 0xFFFF, 75)
            d.line([(x + 2, y + 1), (x + fill_w - 3, y + 1)], fill=hi)


def draw_modern_bar(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                    label: str, pct: float, right_text: str, warn: float, hot: float):
    v = max(0.0, min(100.0, pct))
    col565 = level_color565(v, warn, hot)
    if label:
        draw_str(d, label, x, y, 1, C_DIM, "TL")
    if right_text:
        draw_str(d, right_text, x + w, y, 1, C_TEXT, "TR")
    bar_y = y + 9
    bar_h = max(5, h - 9)
    draw_slim_bar(d, x, bar_y, w, bar_h, v, col565, C_TRACK)


def draw_segmented_bar(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                       pct: float, warn: float, hot: float):
    v = max(0.0, min(100.0, pct))
    act565 = level_color565(v, warn, hot)
    fill_round_rect(d, x, y, w, h, 3, fill=C_CARD_ELEV, outline=C_CARD_HI)
    segments = 16
    inner_w = w - 6
    gap = 2
    seg_w = max(2, (inner_w - (segments - 1) * gap) // segments)
    total_w = segments * seg_w + (segments - 1) * gap
    start_x = x + (w - total_w) // 2
    active_segs = int((v / 100.0) * segments + 0.5)
    for i in range(segments):
        sx = start_x + i * (seg_w + gap)
        sc = C_TRACK
        if i < active_segs:
            seg_pct = ((i + 1) * 100.0) / segments
            sc = b565(act565, level_color565(seg_pct, warn, hot), 110)
        fill_round_rect(d, sx, y + 2, seg_w, max(2, h - 4), 1, fill=sc)


def draw_smooth_arc_pil(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, ir: int,
                        a_start_deg: float, a_end_deg: float, col: tuple[int, int, int]):
    # TFT_eSPI drawSmoothArc: 0 deg = 6 o'clock (bottom), clockwise
    # PIL arc: 0 deg = 3 o'clock (right), clockwise -> pil_angle = tft_angle + 90
    width = max(1, r - ir)
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, start=a_start_deg + 90, end=a_end_deg + 90, fill=col, width=width)


def draw_gauge(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, value: float,
               label: str, valid: bool, warn: float, hot: float):
    ir = max(4, r - 6)
    a0, a1 = 38, 322
    v = max(0.0, min(100.0, value)) if valid else 0.0
    a_end = a0 + int((a1 - a0) * v / 100.0)
    col565 = level_color565(v, warn, hot) if valid else C_TRACK_565
    col = rgb565_to_888(col565)

    if ir > 6:
        ring_r = ir - 3
        d.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                  outline=b565(C_CARD_565, col565, 32))
    if a_end > a0 + 1:
        draw_smooth_arc_pil(d, cx, cy, r, ir, a0, a_end, col)
    if a_end < a1 - 1:
        draw_smooth_arc_pil(d, cx, cy, r, ir, max(a0, a_end), a1, C_TRACK)

    val_font = 4 if r >= 36 else 2
    buf = f"{int(v + 0.5)}%" if valid else "--"
    draw_str(d, buf, cx, cy - 2, val_font, C_TEXT if valid else C_DIM, "MC")
    if label:
        draw_str(d, label, cx, cy + (14 if r >= 36 else 10), 1, C_DIM, "MC")


def plot_graph(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
               data: list[int], col565: int, unit: str):
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=C_CARD)
    d.line([(x, y + h - 1), (x + w - 1, y + h - 1)], fill=C_CARD_HI)
    col = rgb565_to_888(col565)
    area = b565(C_CARD_565, col565, 45)
    sub_col = b565(C_CARD_565, col565, 175)

    for i in range(1, 4):
        gy = y + (h * i) // 4
        for gx in range(x + 2, x + w - 2, 6):
            d.point((gx, gy), fill=C_TRACK)
    step_x = max(12, w // 4)
    for gx in range(x + w // 4, x + w - 4, step_x):
        for gy in range(y + 2, y + h - 2, 6):
            d.point((gx, gy), fill=C_TRACK)

    plot_w = w - 3
    n = min(len(data), plot_w)
    prev_y = -1
    latest_px, latest_py = -1, -1
    for i in range(n):
        v = max(0, min(100, int(data[-1 - i])))
        px = x + plot_w - 1 - i
        py = y + h - 2 - ((h - 5) * v) // 100
        if y + h - 1 > py:
            d.line([(px, py), (px, y + h - 2)], fill=area)
        if prev_y >= 0:
            d.line([(px + 1, prev_y), (px, py)], fill=col)
            if prev_y + 1 < y + h - 1 and py + 1 < y + h - 1:
                d.line([(px + 1, prev_y + 1), (px, py + 1)], fill=sub_col)
        d.point((px, py), fill=col)
        if i == 0:
            latest_px, latest_py = px, py
        prev_y = py

    if latest_px >= x + 3 and y + 3 <= latest_py < y + h - 3:
        d.ellipse([latest_px - 3, latest_py - 3, latest_px + 3, latest_py + 3],
                  fill=b565(C_CARD_565, col565, 90))
        d.ellipse([latest_px - 2, latest_py - 2, latest_px + 2, latest_py + 2], fill=col)
        d.point((latest_px, latest_py), fill=C_TEXT)

    if unit and len(data) > 0 and y >= 13:
        buf = f"{int(data[-1])}{unit}"
        draw_pill_badge(d, x + w - 36, y - 13, 36, 11, buf,
                        C_TEXT, b565(C_CARD_565, col565, 48), b565(C_CARD_565, col565, 110), 1)


# ==============================================================================
# 12 REPRESENTATIVE KEY SCREENS
# ==============================================================================

def render_boot_splash() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_modern_card(d, 16, 18, SCR_W - 32, SCR_H - 36, "SYSTEM BOOT // HYBRID TELEMETRY", C_ACCENT_565)
    draw_pill_badge(d, SCR_W - 76, 23, 52, 13, "OS v5.0", C_ACCENT, C_ACCENT_SOFT, C_ACCENT, 1)
    draw_str(d, "CYD CYBER DECK", SCR_W // 2, 68, 4, C_TEXT, "MC")
    draw_str(d, "OBSIDIAN TELEMETRY & RF COMMAND CENTER", SCR_W // 2, 92, 1, C_DIM, "MC")

    draw_pill_badge(d, 32, 112, 122, 18, "SD CARD: READY",
                    C_OK, b565(C_CARD_565, C_OK_565, 40), b565(C_CARD_HI_565, C_OK_565, 110), 1)
    draw_pill_badge(d, 166, 112, 122, 18, "USB 115200: LINK",
                    C_COOL, b565(C_CARD_565, C_COOL_565, 40), b565(C_CARD_HI_565, C_COOL_565, 110), 1)
    draw_pill_badge(d, 32, 138, SCR_W - 64, 20, "WI-FI UDP ATIVO -> 192.168.1.42:8888",
                    C_OK, b565(C_CARD_565, C_OK_565, 42), b565(C_CARD_HI_565, C_OK_565, 120), 1)
    draw_slim_bar(d, 32, 174, SCR_W - 64, 6, 100.0, C_OK_565, C_TRACK)
    return img


def render_tela0_resumo() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "RESUMO")
    draw_ticker_tape(d)

    draw_modern_card(d, 6,   27, 151, 98, "CPU", C_COOL_565)
    draw_modern_card(d, 163, 27, 151, 98, "RAM", C_PURPLE_565)
    draw_modern_card(d, 6,   129, 151, 90, "STORAGE & THERMALS", C_OK_565)
    draw_modern_card(d, 163, 129, 151, 90, "NETWORK & HOST", C_COOL_565)

    # Top-Left: CPU
    draw_gauge(d, 44, 78, 31, 42.0, "LOAD", True, 65.0, 85.0)
    t_col565 = level_color565(58.0, 75.0, 85.0)
    draw_pill_badge(d, 82, 43, 67, 20, "58 C", rgb565_to_888(t_col565),
                    b565(C_CARD_565, t_col565, 40), rgb565_to_888(t_col565), 2)
    draw_pill_badge(d, 82, 67, 67, 20, "4.6GHz", C_TEXT, C_CARD_ELEV, C_CARD_HI, 2)
    draw_pill_badge(d, 82, 91, 67, 18, "16 CORES", C_COOL, b565(C_CARD_565, C_COOL_565, 32), None, 1)

    # Top-Right: RAM
    draw_gauge(d, 201, 78, 31, 64.0, "MEM", True, 75.0, 90.0)
    draw_pill_badge(d, 239, 43, 67, 20, "20.5/32G", C_TEXT, b565(C_CARD_565, C_PURPLE_565, 42), C_PURPLE, 1)
    draw_pill_badge(d, 239, 67, 67, 19, "11.5G FREE", C_DIM, C_CARD_ELEV, C_CARD_HI, 1)
    draw_str(d, "SWAP", 239, 91, 1, C_DIM, "TL")
    draw_str(d, "12%", 306, 91, 1, C_OK, "TR")
    draw_slim_bar(d, 239, 102, 67, 5, 12.0, C_OK_565, C_TRACK)

    # Bottom-Left: Storage & Thermals
    draw_modern_bar(d, 14, 144, 135, 19, "DISK", 68.0, "312G FREE", 80.0, 92.0)
    for tx, lbl, tmp in ((14, "CPU", 58.0), (84, "GPU", 62.0)):
        c565 = level_color565(tmp, 75.0, 85.0)
        fill_round_rect(d, tx, 169, 65, 42, PILL_R, fill=C_CARD_ELEV, outline=b565(C_CARD_HI_565, c565, 90))
        d.ellipse([tx + 6, 175, tx + 10, 179], fill=rgb565_to_888(c565))
        draw_str(d, lbl, tx + 14, 173, 1, C_DIM, "TL")
        draw_str(d, f"{tmp:.0f} C", tx + 7, 183, 2, C_TEXT, "TL")
        draw_slim_bar(d, tx + 6, 204, 53, 3, tmp, c565, C_TRACK)

    # Bottom-Right: Network & Host
    d.polygon([(171, 146), (177, 146), (174, 152)], fill=C_COOL)
    draw_str(d, "RX", 181, 145, 1, C_COOL, "TL")
    draw_str(d, "14.80 MB/s", 306, 143, 2, C_TEXT, "TR")
    draw_slim_bar(d, 171, 159, 135, 4, (14.8 / 25.0) * 100.0, C_COOL_565, C_TRACK)

    d.polygon([(174, 168), (171, 174), (177, 174)], fill=C_PINK)
    draw_str(d, "TX", 181, 168, 1, C_PINK, "TL")
    draw_str(d, "3.45 MB/s", 306, 166, 2, C_TEXT, "TR")
    draw_slim_bar(d, 171, 182, 135, 4, (3.45 / 25.0) * 100.0, C_PINK_565, C_TRACK)

    draw_pill_badge(d, 171, 192, 135, 18, "ZIPO-WORK | UP 14h22m", C_TEXT, C_CARD_ELEV, C_CARD_HI, 1)
    return img


def render_tela1_cpu_ram(h_cpu: list[int], h_ram: list[int]) -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "CPU / RAM")
    draw_ticker_tape(d)

    draw_modern_card(d, 6,   27, 151, 148, "CPU STUDIO", C_COOL_565)
    draw_modern_card(d, 163, 27, 151, 148, "RAM STUDIO", C_PURPLE_565)
    draw_modern_card(d, 6,   179, 308, 40, None, C_ACCENT_565)

    # Left: CPU Studio
    draw_str(d, f"{h_cpu[-1]}%", 14, 42, 4, C_TEXT, "TL")
    draw_pill_badge(d, 82, 41, 67, 13, "58 C", C_OK, b565(C_CARD_565, C_OK_565, 36), C_OK, 1)
    draw_pill_badge(d, 82, 56, 67, 13, "4.65GHz", C_COOL, C_CARD_ELEV, None, 1)
    draw_segmented_bar(d, 14, 73, 135, 11, float(h_cpu[-1]), 65.0, 85.0)
    draw_str(d, "HISTORY", 14, 87, 1, C_MUTED, "TL")
    plot_graph(d, 14, 98, 135, 69, h_cpu, C_COOL_565, "%")

    # Right: RAM Studio
    draw_str(d, f"{h_ram[-1]}%", 171, 42, 4, C_TEXT, "TL")
    draw_pill_badge(d, 239, 41, 67, 13, "20.5/32G", C_PURPLE, b565(C_CARD_565, C_PURPLE_565, 36), C_PURPLE, 1)
    draw_pill_badge(d, 239, 56, 67, 13, "SWP 12%", C_OK, C_CARD_ELEV, None, 1)
    draw_segmented_bar(d, 171, 73, 135, 11, float(h_ram[-1]), 75.0, 90.0)
    draw_str(d, "HISTORY", 171, 87, 1, C_MUTED, "TL")
    plot_graph(d, 171, 98, 135, 69, h_ram, C_PURPLE_565, "%")

    # Bottom 4-col KPI Strip
    for vx in (83, 160, 237):
        d.line([(vx, 185), (vx, 212)], fill=C_MUTED)

    draw_str(d, "GPU", 12, 184, 1, C_DIM, "TL")
    draw_str(d, "62C", 77, 184, 1, C_OK, "TR")
    draw_str(d, "76%", 12, 194, 2, C_TEXT, "TL")
    draw_slim_bar(d, 12, 211, 65, 3, 76.0, C_OK_565, C_TRACK)

    draw_str(d, "DISK", 89, 184, 1, C_DIM, "TL")
    draw_str(d, "312G", 154, 184, 1, C_COOL, "TR")
    draw_str(d, "68%", 89, 194, 2, C_TEXT, "TL")
    draw_slim_bar(d, 89, 211, 65, 3, 68.0, C_OK_565, C_TRACK)

    draw_str(d, "NET", 166, 184, 1, C_DIM, "TL")
    draw_str(d, "18.2M", 231, 184, 1, C_COOL, "TR")
    draw_str(d, "v14.8 ^3.4", 166, 195, 1, C_TEXT, "TL")
    draw_slim_bar(d, 166, 211, 65, 3, 72.0, C_COOL_565, C_TRACK)

    draw_str(d, "UPTIME", 243, 184, 1, C_DIM, "TL")
    draw_str(d, "14h22m", 243, 194, 2, C_TEXT, "TL")
    draw_slim_bar(d, 243, 211, 64, 3, 100.0, C_OK_565, C_TRACK)
    return img


def render_tela3_gpu_focus(h_gpu: list[int]) -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "GPU FOCUS")
    draw_ticker_tape(d)

    draw_modern_card(d, 6,   27,  142, 192, "GPU CORE",       C_OK_565)
    draw_modern_card(d, 154, 27,  160, 84,  "VRAM & THERMAL", C_PURPLE_565)
    draw_modern_card(d, 154, 115, 160, 104, "GPU HISTORY",    C_OK_565)

    draw_pill_badge(d, 14, 41, 126, 15, "RTX 4070 SUPER", C_TEXT, C_CARD_ELEV, C_CARD_HI, 1)
    draw_gauge(d, 77, 99, 38, float(h_gpu[-1]), "GPU LOAD", True, 70.0, 90.0)

    # TEMP + POWER tiles
    fill_round_rect(d, 14, 143, 60, 30, PILL_R, fill=C_CARD_ELEV, outline=C_CARD_HI)
    draw_str(d, "TEMP", 20, 146, 1, C_DIM, "TL")
    draw_str(d, "64 C", 44, 163, 2, C_OK, "MC")

    fill_round_rect(d, 80, 143, 60, 30, PILL_R, fill=C_CARD_ELEV, outline=C_CARD_HI)
    draw_str(d, "POWER", 86, 146, 1, C_DIM, "TL")
    draw_str(d, "185 W", 110, 163, 2, C_WARN, "MC")

    draw_pill_badge(d, 14, 179, 126, 28, "GAME: 144 FPS", C_TEXT,
                    b565(C_CARD_565, C_OK_565, 34), C_OK, 2)

    # Top-Right: VRAM & Thermal
    draw_str(d, "8.4 / 12 GB", 162, 41, 2, C_TEXT, "TL")
    draw_pill_badge(d, 260, 41, 46, 16, "70%", C_OK, b565(C_CARD_565, C_OK_565, 38), C_OK, 1)
    draw_segmented_bar(d, 162, 62, 144, 11, 70.0, 75.0, 90.0)
    draw_modern_bar(d, 162, 80, 144, 19, "GPU TEMP", 64.0, "64.0 C", 75.0, 85.0)

    # Bottom-Right: GPU History
    plot_graph(d, 162, 134, 144, 77, h_gpu, C_OK_565, "%")
    return img


def render_tela6_market(btc_curve: list[int]) -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "MERCADO")
    draw_ticker_tape(d)

    draw_modern_card(d, 6,   27, 100, 52, "USD / BRL", C_OK_565)
    draw_modern_card(d, 110, 27, 100, 52, "EUR / BRL", C_COOL_565)
    draw_modern_card(d, 214, 27, 100, 52, "IBOVESPA",  C_PURPLE_565)
    draw_modern_card(d, 6,   83, 162, 136, "CRYPTO 24H", C_COOL_565)
    for i in range(1, 5):
        div_y = 100 + i * 23 - 2
        d.line([(12, div_y), (161, div_y)], fill=C_TRACK)
    draw_modern_card(d, 172, 83, 142, 136, "BITCOIN", C_WARN_565)

    # Top 3 KPI Cards
    draw_str(d, "R$ 5.78", 14, 43, 2, C_TEXT, "TL")
    draw_delta_badge(d, 14, 61, 84, 14, +0.42)

    draw_str(d, "R$ 6.12", 118, 43, 2, C_TEXT, "TL")
    draw_delta_badge(d, 118, 61, 84, 14, -0.24)

    draw_str(d, "129.4k pts", 222, 43, 2, C_TEXT, "TL")
    draw_delta_badge(d, 222, 61, 84, 14, +1.15)

    # Watchlist Rows
    rows = [
        ("ETH", "$3140", +2.15, False),
        ("SOL", "$214.80", +5.40, False),
        ("BNB", "$642.50", -0.65, False),
        ("XRP", "$1.482", +8.90, False),
        ("S&P", "5985", +0.58, True),
    ]
    for idx, (sym, p_str, chg, is_idx) in enumerate(rows):
        ry = 100 + idx * 23
        tcol = C_OK if chg >= 0 else C_HOT
        fill_round_rect(d, 12, ry + 2, 3, 15, 1, fill=tcol)
        draw_str(d, sym, 18, ry + 9, 2, C_PURPLE if is_idx else C_ACCENT, "ML")
        draw_str(d, p_str, 52, ry + 9, 2, C_TEXT, "ML")
        draw_delta_badge(d, 114, ry + 2, 48, 15, chg)

    # Bitcoin Hero + Sparkline
    draw_delta_badge(d, 254, 86, 54, 13, +3.85)
    draw_str(d, "$94,250", 180, 101, 4, C_TEXT, "TL")
    draw_str(d, "BRL: R$ 544.8 mil", 180, 126, 2, C_DIM, "TL")

    # Sparkline (180, 145, 126, 68)
    sx, sy, sw, sh = 180, 145, 126, 68
    d.rectangle([sx, sy, sx + sw - 1, sy + sh - 1], fill=C_CARD)
    for i in range(1, 4):
        gy = sy + (sh * i) // 4
        for gx in range(sx, sx + sw, 6):
            d.point((gx, gy), fill=C_TRACK)
    area_top = b565(C_CARD_565, C_OK_565, 64)
    area_bot = b565(C_CARD_565, C_OK_565, 24)
    mid_y = sy + sh // 2
    n = len(btc_curve)
    prev_x, prev_y = -1, -1
    last_x, last_y = sx, mid_y
    for i, val in enumerate(btc_curve):
        px = sx + (i * (sw - 4)) // (n - 1)
        py = sy + sh - 3 - ((sh - 6) * val) // 100
        if prev_x >= 0:
            span = max(1, px - prev_x)
            for fx in range(prev_x, px + 1):
                fy = prev_y + ((py - prev_y) * (fx - prev_x)) // span
                split_y = max(fy, mid_y)
                if split_y > fy:
                    d.line([(fx, fy), (fx, split_y)], fill=area_top)
                if sy + sh > split_y:
                    d.line([(fx, split_y), (fx, sy + sh - 1)], fill=area_bot)
            d.line([(prev_x, prev_y), (px, py)], fill=C_OK)
            d.line([(prev_x, prev_y + 1), (px, py + 1)], fill=C_OK)
        prev_x, prev_y = px, py
        last_x, last_y = px, py
    d.ellipse([last_x - 3, last_y - 3, last_x + 3, last_y + 3], fill=b565(C_CARD_565, C_OK_565, 110))
    d.ellipse([last_x - 2, last_y - 2, last_x + 2, last_y + 2], fill=C_OK)
    d.point((last_x, last_y), fill=C_TEXT)
    return img


def render_tela7_portfolio() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "PORTFOLIO")
    draw_ticker_tape(d)

    draw_modern_card(d, 6, 27, 182, 192, "PATRIMONIO", C_ACCENT_565)
    draw_modern_card(d, 192, 27, 122, 192, "TOP 3 ATIVOS", C_PURPLE_565)
    for i in range(3):
        ry = 45 + i * 57
        fill_round_rect(d, 198, ry, 110, 52, 5, fill=C_CARD_ELEV, outline=C_CARD_HI)

    draw_pill_badge(d, 122, 30, 58, 13, "6 ATIVOS", C_ACCENT, C_ACCENT_SOFT, C_CARD_HI, 1)
    draw_str(d, "SALDO TOTAL CONSOLIDADO", 14, 46, 1, C_DIM, "TL")
    draw_str(d, "R$ 148,520", 14, 57, 4, C_TEXT, "TL")

    # PnL Hero Box
    pnl_bg = b565(C_CARD_565, C_OK_565, 36)
    pnl_bd = b565(C_CARD_HI_565, C_OK_565, 110)
    fill_round_rect(d, 14, 86, 166, 40, 5, fill=pnl_bg, outline=pnl_bd)
    draw_str(d, "RESULTADO: LUCRO (PnL)", 22, 91, 1, C_OK, "TL")
    draw_str(d, "+R$ 24.8k", 22, 104, 2, C_TEXT, "TL")
    draw_delta_badge(d, 118, 104, 56, 16, +20.05)

    draw_pill_badge(d, 14, 131, 96, 15, "24H: +3.18%", C_OK, C_CARD_ELEV, b565(C_CARD_HI_565, C_OK_565, 80), 1)
    draw_pill_badge(d, 114, 131, 66, 15, "USD 5.78", C_COOL, C_CARD_ELEV, C_CARD_HI, 1)

    draw_str(d, "ALOCACAO TOP 3", 14, 153, 1, C_DIM, "TL")
    fill_round_rect(d, 14, 165, 166, 10, 3, fill=C_TRACK, outline=C_CARD_HI)
    weights = [("BTC", 52, C_ACCENT, C_ACCENT_565, +3.85),
               ("SOL", 28, C_COOL, C_COOL_565, +5.40),
               ("ETH", 20, C_PURPLE, C_PURPLE_565, +2.15)]
    cur_x = 15
    for idx, (sym, w_pct, col, col565, chg) in enumerate(weights):
        seg_w = int((164 * w_pct) / 100.0)
        d.rectangle([cur_x, 166, cur_x + seg_w - 2, 173], fill=col)
        cur_x += seg_w
        lx = 14 + idx * 56
        d.ellipse([lx + 1, 183, lx + 5, 187], fill=col)
        draw_str(d, sym, lx + 8, 185, 1, C_TEXT, "ML")

        # Right card tile
        ry = 45 + idx * 57
        fill_round_rect(d, 201, ry + 5, 3, 42, 1, fill=col)
        draw_str(d, f"{idx + 1}.{sym}", 208, ry + 4, 2, C_TEXT, "TL")
        draw_str(d, f"{w_pct}%", 303, ry + 7, 1, col, "TR")
        draw_slim_bar(d, 208, ry + 22, 95, 5, float(w_pct), col565, C_TRACK)
        draw_delta_badge(d, 208, ry + 31, 95, 16, chg)

    draw_str(d, "Carteira sincronizada em tempo real", 14, 199, 1, C_MUTED, "TL")
    return img


def render_tela8_pomodoro() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "POMODORO", "EM FOCO", C_OK_565)
    draw_ticker_tape(d)

    draw_modern_card(d, 6,   27, 166, 192, "FOCUS STUDIO",    C_ACCENT_565)
    draw_modern_card(d, 176, 27, 138, 192, "SESSAO & CICLOS", C_PURPLE_565)
    d.line([(184, 96),  (305, 96)],  fill=C_TRACK)
    d.line([(184, 150), (305, 150)], fill=C_TRACK)

    # Left circular progress ring (cx=89, cy=113, r=62, ir=52)
    cx, cy, r, ir = 89, 113, 62, 52
    a0, a1 = 30, 330
    pct_done = 68.0
    a_end = a0 + int((a1 - a0) * pct_done / 100.0)
    draw_smooth_arc_pil(d, cx, cy, r, ir, a0, a_end, C_OK)
    draw_smooth_arc_pil(d, cx, cy, r, ir, a_end, a1, C_TRACK)
    draw_str(d, "08:00", cx, cy - 5, 4, C_TEXT, "MC")
    draw_str(d, "68% CONCLUIDO", cx, cy + 17, 1, C_DIM, "MC")
    draw_pill_badge(d, 39, 193, 100, 17, "EM FOCO", C_OK,
                    b565(C_CARD_565, C_OK_565, 38), b565(C_CARD_HI_565, C_OK_565, 110), 1)

    # Right card section 1: cycles
    draw_pill_badge(d, 184, 45, 122, 20, "CICLOS: #3", C_TEXT, C_CARD_ELEV, C_CARD_HI, 2)
    for i in range(4):
        dx, dy = 200 + i * 30, 79
        if i < 2:
            d.ellipse([dx - 8, dy - 8, dx + 8, dy + 8], outline=b565(C_CARD_565, C_OK_565, 90))
            d.ellipse([dx - 6, dy - 6, dx + 6, dy + 6], fill=C_OK)
            d.ellipse([dx - 3, dy - 3, dx - 1, dy - 1], fill=C_TEXT)
        elif i == 2:
            d.ellipse([dx - 6, dy - 6, dx + 6, dy + 6], fill=C_OK)
            d.ellipse([dx - 3, dy - 3, dx + 3, dy + 3], fill=C_CARD)
            d.point((dx, dy), fill=C_TEXT)
        else:
            d.ellipse([dx - 6, dy - 6, dx + 6, dy + 6], fill=C_CARD_ELEV, outline=C_MUTED)

    # Right card section 2: session bar
    draw_str(d, "SESSAO", 184, 102, 1, C_DIM, "TL")
    draw_str(d, "25m | 68%", 306, 102, 1, C_TEXT, "TR")
    draw_slim_bar(d, 184, 114, 122, 8, pct_done, C_OK_565, C_TRACK)
    draw_pill_badge(d, 184, 127, 122, 16, "DECORRIDO 17:00", C_DIM, C_CARD_ELEV, None, 1)

    # Right card section 3: deep work tile
    fill_round_rect(d, 184, 156, 122, 36, 5, fill=C_CARD_ELEV, outline=b565(C_CARD_HI_565, C_OK_565, 70))
    draw_str(d, "DEEP WORK MODE", 245, 166, 1, C_OK, "MC")
    draw_str(d, "Foco total na tarefa", 245, 180, 1, C_DIM, "MC")
    draw_str(d, "CPU 42%   |   RAM 64%", 245, 204, 1, C_MUTED, "MC")
    return img


def render_tela9_media() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    m_col565 = C_OK_565  # Spotify Emerald
    m_col = C_OK

    # Ambient side soundwave bars
    wave_col = b565(C_BG_565, m_col565, 45)
    for i in range(6):
        wh = 10 + (i % 3) * 12
        fill_round_rect(d, 46 + i * 9, 80 - wh // 2, 4, wh, 2, fill=wave_col)
        fill_round_rect(d, 226 + i * 9, 80 - wh // 2, 4, wh, 2, fill=wave_col)

    # Framed Album Art Box (x=112, y=30, w=96, h=96)
    fill_round_rect(d, 112, 30, 96, 96, 8, fill=C_CARD, outline=b565(C_CARD_HI_565, m_col565, 85))
    vcx, vcy = 160, 78
    d.ellipse([vcx - 38, vcy - 38, vcx + 38, vcy + 38], fill=C_CARD_ELEV, outline=C_CARD_HI)
    d.ellipse([vcx - 31, vcy - 31, vcx + 31, vcy + 31], outline=b565(C_CARD_ELEV_565, m_col565, 35))
    d.ellipse([vcx - 24, vcy - 24, vcx + 24, vcy + 24], outline=b565(C_CARD_ELEV_565, m_col565, 55))
    d.ellipse([vcx - 14, vcy - 14, vcx + 14, vcy + 14], fill=m_col)
    d.ellipse([vcx - 10, vcy - 10, vcx + 10, vcy + 10], outline=b565(m_col565, C_TEXT_565, 90))
    d.ellipse([vcx - 3, vcy - 3, vcx + 3, vcy + 3], fill=C_BG)

    draw_header_and_clock(d, "MEDIA HUB", "SPOTIFY", m_col565)
    draw_ticker_tape(d)

    # Floating Dark Glass Card (x=8, y=136, w=304, h=82)
    fill_round_rect(d, 8, 136, 304, 82, 7, fill=C_CARD, outline=b565(C_CARD_HI_565, m_col565, 110))
    d.line([(20, 136), (300, 136)], fill=m_col)

    draw_pill_badge(d, 16, 142, 64, 14, "SPOTIFY", (0, 0, 0), m_col, None, 1)
    draw_pill_badge(d, 214, 142, 62, 14, "|> PLAY", m_col, b565(C_CARD_565, m_col565, 35),
                    b565(C_CARD_HI_565, m_col565, 90), 1)

    # 4-bar equalizer
    fill_round_rect(d, 280, 142, 24, 14, 3, fill=C_CARD_ELEV)
    for i, bh in enumerate((8, 11, 6, 10)):
        bx = 283 + i * 5
        by = 154 - bh
        d.rectangle([bx, by, bx + 2, 153], fill=m_col)
        d.line([(bx, by), (bx + 2, by)], fill=C_TEXT)

    draw_str(d, "Midnight City (Cyberpunk Mix)", 16, 160, 2, C_TEXT, "TL")
    draw_str(d, "M83  -  Hurry Up, We're Dreaming", 16, 179, 2, C_DIM, "TL")

    # Progress bar + playhead dot
    bar_x, bar_y, bar_w, bar_h = 16, 203, 192, 6
    pct = 0.62
    draw_slim_bar(d, bar_x, bar_y, bar_w, bar_h, pct * 100.0, m_col565, C_TRACK)
    dot_x = bar_x + int((bar_w - 2) * pct)
    dot_y = bar_y + bar_h // 2
    d.ellipse([dot_x - 4, dot_y - 4, dot_x + 4, dot_y + 4], fill=m_col)
    d.ellipse([dot_x - 2, dot_y - 2, dot_x + 2, dot_y + 2], fill=C_TEXT)

    draw_pill_badge(d, 216, 199, 88, 14, "02:31 / 04:03", C_TEXT, C_CARD_ELEV, C_CARD_HI, 1)
    return img


def render_tela10_weather_news() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "CLIMA/NEWS")
    draw_ticker_tape(d)

    draw_modern_card(d, 6, 27, 308, 74, "CLIMA REGIONAL", C_COOL_565)
    draw_modern_card(d, 6, 105, 308, 114, "", C_ACCENT_565)

    draw_pill_badge(d, 108, 29, 88, 13, "SAO PAULO", C_COOL, C_CARD_ELEV, None, 1)
    draw_pill_badge(d, 200, 29, 108, 13, "DOM 22/11/2026", C_TEXT, C_ACCENT_SOFT, C_CARD_HI, 1)

    # Weather icon box (cx=35, cy=69)
    cx, cy = 35, 69
    fill_round_rect(d, cx - 23, cy - 21, 46, 42, 6, fill=C_CARD_ELEV, outline=C_CARD_HI)
    d.ellipse([cx - 15, cy - 16, cx - 1, cy - 2], fill=(255, 255, 0), outline=C_WARN)
    cld = rgb565_to_888(0xDEFB)
    d.ellipse([cx - 13, cy - 10, cx + 3, cy + 6], fill=cld)
    d.ellipse([cx - 6, cy - 15, cx + 14, cy + 5], fill=cld)
    d.ellipse([cx + 5, cy - 8, cx + 19, cy + 6], fill=cld)
    fill_round_rect(d, cx - 13, cy - 2, 31, 9, 4, fill=cld)

    w_t = draw_str(d, "26.4", 64, 45, 4, C_TEXT, "TL")
    d.ellipse([64 + w_t + 2, 47, 64 + w_t + 6, 51], outline=C_OK)
    draw_str(d, "C", 64 + w_t + 9, 46, 2, C_OK, "TL")
    draw_str(d, "Sol entre nuvens", 64, 71, 1, C_COOL, "TL")
    draw_pill_badge(d, 64, 82, 132, 15, "SENS 28C | 19/29C", C_DIM, C_CARD_ELEV, None, 1)

    draw_pill_badge(d, 202, 46, 106, 15, "UMIDADE: 58%", C_COOL, C_CARD_ELEV, None, 1)
    draw_pill_badge(d, 202, 64, 106, 15, "CHUVA: 15%", C_TEXT, C_CARD_ELEV, None, 1)
    draw_pill_badge(d, 202, 82, 106, 15, "VENTO: 14 km/h", C_DIM, C_CARD_ELEV, None, 1)

    # Bottom Card: News Desk
    draw_pill_badge(d, 12, 109, 84, 15, "TECNOLOGIA", C_ACCENT, C_ACCENT_SOFT, C_CARD_HI, 1)
    draw_str(d, "TechCrunch  |  14:20", 102, 116, 1, C_DIM, "ML")
    draw_pill_badge(d, 266, 109, 42, 15, "1/5", C_TEXT, C_CARD_ELEV, C_CARD_HI, 1)

    # Scrolling newsSpr (x=12, y=128, w=296, h=26)
    d.rectangle([12, 128, 307, 153], fill=C_CARD_ELEV, outline=C_CARD_HI)
    d.rectangle([12, 128, 14, 153], fill=C_ACCENT)
    draw_str(d, "ESP32 Cyber Deck OS v5.0 traz UI", 20, 141, 4, C_TEXT, "ML")

    # 3-line summary
    lines = [
        "ESP32 Cyber Deck OS v5.0 traz nova",
        "arquitetura visual Obsidian Dark com",
        "telemetria hibrida USB + Wi-Fi UDP.",
    ]
    for r_idx, line in enumerate(lines):
        draw_str(d, line, 14, 158 + r_idx * 15, 2, C_TEXT if r_idx == 0 else C_DIM, "TL")

    draw_slim_bar(d, 12, 209, 262, 5, 60.0, C_ACCENT_565, C_TRACK)
    draw_str(d, "06s", 306, 211, 1, C_DIM, "MR")
    return img


def render_tela12_wifi_radar() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "RF RADAR")
    draw_ticker_tape(d)

    draw_modern_card(d, 4,   26, 154, 46, "ESP32-32U RF", C_PURPLE_565)
    draw_modern_card(d, 162, 26, 154, 46, "2.4GHz SPECTRUM", C_COOL_565)
    draw_modern_card(d, 4,   75, 312, 68, "LIVE PACKET FLOW", C_ACCENT_565)
    draw_modern_card(d, 4,   146, 312, 73, "NEARBY ACCESS POINTS", C_ACCENT_565)

    # Top-left: ESP32-32U RF
    draw_pill_badge(d, 108, 28, 46, 11, "ONLINE", C_OK, b565(C_CARD_565, C_OK_565, 40), C_OK, 1)
    draw_str(d, "14 APs", 10, 48, 2, C_TEXT, "ML")
    draw_pill_badge(d, 80, 41, 72, 13, "BLE ON +9", C_OK, b565(C_CARD_565, C_OK_565, 40), C_OK, 1)
    draw_str(d, "BEST -42dBm | SCAN #128", 10, 63, 1, C_DIM, "ML")

    # Top-right: 2.4GHz Spectrum
    draw_pill_badge(d, 280, 28, 32, 11, "CH13", C_OK, b565(C_CARD_565, C_OK_565, 40), C_OK, 1)
    ch_counts = [3, 1, 0, 1, 2, 5, 1, 0, 1, 2, 4, 1, 0]
    max_ch = max(ch_counts)
    bar_base_y, bar_max_h = 59, 17
    for i, cnt in enumerate(ch_counts):
        bx = 170 + i * 11
        d.rectangle([bx, bar_base_y - bar_max_h, bx + 7, bar_base_y - 1], fill=C_TRACK)
        bh = max(3, (cnt * bar_max_h) // max_ch) if cnt > 0 else 2
        bcol = C_HOT if cnt >= 4 else (C_WARN if cnt >= 2 else (C_OK if cnt == 1 else (C_COOL if i == 12 else C_MUTED)))
        d.rectangle([bx, bar_base_y - bh, bx + 7, bar_base_y - 1], fill=bcol)
    for lbl, lx in (("1", 174), ("6", 229), ("11", 284), ("13", 306)):
        draw_str(d, lbl, lx, 65, 1, C_DIM, "MC")

    # Middle: Live Packet Flow Sprite (pushed at x=8, y=91, w=304, h=48)
    sx, sy, sw, sh = 8, 91, 304, 48
    d.rectangle([sx, sy, sx + sw - 1, sy + sh - 1], fill=C_BG)
    for gx in range(sx + 16, sx + sw, 24):
        for gy in range(sy + 10, sy + sh - 8, 4):
            d.point((gx, gy), fill=C_TRACK)
    x_pc, x_gw, x_wan, x_rf = sx + 24, sx + 112, sx + 198, sx + 278
    y_rx, y_tx, y_rf = sy + 18, sy + 28, sy + 23
    d.line([(x_pc + 14, y_rx), (x_wan - 14, y_rx)], fill=b565(C_BG_565, C_COOL_565, 70))
    d.line([(x_pc + 14, y_tx), (x_wan - 14, y_tx)], fill=b565(C_BG_565, C_WARN_565, 70))
    for wx in range(x_wan + 15, x_rf - 15, 6):
        d.line([(wx, y_rf), (wx + 2, y_rf)], fill=C_COOL)

    # Animated packets
    for px, py, col in ((sx + 68, y_rx, C_COOL), (sx + 156, y_rx, C_COOL),
                        (sx + 84, y_tx, C_WARN), (sx + 238, y_rf, C_PURPLE)):
        fill_round_rect(d, px - 2, py - 2, 5, 5, 1, fill=col)
        d.point((px, py), fill=C_TEXT)

    # 4 Node Chips: HOST, ROUTER, WAN, 32U/BLE (with internal vector icons matching ui_screens_cyber.h)
    for nx, nw, lbl, bd in ((x_pc, 26, "HOST", C_COOL), (x_gw, 28, "ROUTER", C_COOL),
                            (x_wan, 26, "WAN", C_OK), (x_rf, 28, "32U/BLE", C_COOL)):
        fill_round_rect(d, nx - nw // 2, sy + 10, nw, 24, 4, fill=C_CARD_ELEV, outline=bd)
        draw_str(d, lbl, nx, sy + 42, 1, bd if lbl != "HOST" else C_TEXT, "MC")

    # HOST monitor vector icon
    d.rectangle([x_pc - 8, sy + 14, x_pc + 7, sy + 23], outline=C_TEXT)
    d.line([(x_pc - 4, sy + 27), (x_pc + 4, sy + 27)], fill=C_COOL)
    d.line([(x_pc, sy + 24), (x_pc, sy + 26)], fill=C_COOL)

    # ROUTER antennas + LED indicators
    d.line([(x_gw - 7, sy + 13), (x_gw - 7, sy + 19)], fill=C_COOL)
    d.line([(x_gw + 7, sy + 13), (x_gw + 7, sy + 19)], fill=C_COOL)
    d.rectangle([x_gw - 9, sy + 20, x_gw + 9, sy + 27], fill=C_BG)
    d.point((x_gw - 5, sy + 24), fill=C_OK)
    d.point((x_gw,     sy + 24), fill=C_COOL)
    d.point((x_gw + 5, sy + 24), fill=C_WARN)

    # WAN globe vector icon
    d.ellipse([x_wan - 6, sy + 16, x_wan + 6, sy + 28], outline=C_OK)
    d.line([(x_wan - 5, sy + 22), (x_wan + 5, sy + 22)], fill=C_OK)
    d.line([(x_wan, sy + 16), (x_wan, sy + 28)], fill=C_OK)

    # 32U/BLE antenna + RF wave
    d.ellipse([x_rf - 7, sy + 13, x_rf + 7, sy + 27], outline=C_COOL)
    d.ellipse([x_rf - 2, sy + 18, x_rf + 2, sy + 22], fill=C_TEXT)
    d.line([(x_rf, sy + 22), (x_rf, sy + 29)], fill=C_COOL)

    draw_str(d, "RX 118.4Mbps", sx + 4, sy, 1, C_COOL, "TL")
    draw_str(d, "TX 27.6Mbps", sx + 96, sy, 1, C_WARN, "TL")
    draw_str(d, "BLE +9dBm", sx + sw - 4, sy, 1, C_OK, "TR")

    # Bottom: Nearby Access Points
    draw_pill_badge(d, 254, 148, 58, 11, "TOP 4/14", C_COOL, C_CARD_ELEV, C_CARD_HI, 1)
    aps = [
        ("ZIPO-FIBER-5G", 6, -42, C_OK, C_OK_565),
        ("CYBER-LAB-IOT", 1, -58, C_OK, C_OK_565),
        ("VIVO-FIBRA-89A", 11, -71, C_COOL, C_COOL_565),
        ("CLARO-WIFI-EXT", 6, -81, C_WARN, C_WARN_565),
    ]
    for i, (ssid, ch, rssi, scol, scol565) in enumerate(aps):
        ry = 160 + i * 14
        if i % 2 == 1:
            fill_round_rect(d, 8, ry, 304, 13, 2, fill=C_CARD_ELEV)
        bars = 4 if rssi >= -60 else (3 if rssi >= -72 else 2)
        for b in range(4):
            bh = 3 + b * 2
            bx = 11 + b * 3
            by = ry + 2 + (9 - bh)
            d.rectangle([bx, by, bx + 1, by + bh - 1], fill=scol if b < bars else C_TRACK)
        draw_str(d, ssid, 26, ry + 6, 1, C_TEXT, "ML")
        draw_pill_badge(d, 140, ry + 1, 30, 11, f"CH{ch:02d}", C_COOL, C_CARD_ELEV, C_CARD_HI, 1)
        pct = max(5.0, min(100.0, ((rssi + 96) * 100.0) / 52.0))
        draw_slim_bar(d, 176, ry + 4, 84, 5, pct, scol565, C_TRACK)
        draw_str(d, f"{rssi}dBm", 308, ry + 6, 1, scol, "MR")
    return img


def render_tela13_net_analyzer() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "NET / WAN")
    draw_ticker_tape(d)

    draw_modern_card(d, 4,   26, 154, 66, "ROUTER / GATEWAY", C_COOL_565)
    draw_modern_card(d, 162, 26, 154, 66, "WAN / DNS / ISP", C_OK_565)
    draw_modern_card(d, 4,   96, 312, 60, "REALTIME LINK (Mbps)", C_ACCENT_565)
    draw_modern_card(d, 4,   160, 312, 59, "FIBER SPEEDTEST", C_PURPLE_565)

    # Top-left: Router / Gateway
    draw_pill_badge(d, 122, 28, 32, 11, "UP", C_OK, b565(C_CARD_565, C_OK_565, 40), C_OK, 1)
    draw_str(d, "192.168.1.1", 10, 48, 2, C_TEXT, "ML")
    draw_pill_badge(d, 122, 42, 30, 12, "WEB", C_COOL, C_CARD_ELEV, C_CARD_HI, 1)

    for bx, bw, lbl, val in ((8, 46, "PING", "1.4ms"), (58, 46, "JITTER", "0.3ms"), (108, 46, "LOSS", "0%")):
        fill_round_rect(d, bx, 61, bw, 27, 3, fill=C_CARD_ELEV)
        draw_str(d, lbl, bx + bw // 2, 64, 1, C_DIM, "TC")
        draw_str(d, val, bx + bw // 2, 86, 1, C_OK, "BC")

    # Top-right: WAN / DNS / ISP
    draw_pill_badge(d, 268, 28, 44, 11, "WAN UP", C_OK, b565(C_CARD_565, C_OK_565, 40), C_OK, 1)
    draw_str(d, "VIVO FIBRA", 168, 48, 2, C_TEXT, "ML")
    for bx, bw, lbl, val in ((166, 44, "WAN", "7ms"), (213, 44, "DNS", "11ms")):
        fill_round_rect(d, bx, 61, bw, 27, 3, fill=C_CARD_ELEV)
        draw_str(d, lbl, bx + bw // 2, 64, 1, C_DIM, "TC")
        draw_str(d, val, bx + bw // 2, 86, 1, C_OK, "BC")
    draw_pill_badge(d, 260, 61, 52, 27, "18 HOSTS", C_COOL, C_CARD_ELEV, C_CARD_HI, 1)

    # Middle: Realtime Link (Mbps)
    draw_pill_badge(d, 252, 98, 60, 11, "PLAN 600M", C_ACCENT, C_ACCENT_SOFT, None, 1)
    draw_pill_badge(d, 8, 113, 24, 14, "RX", C_COOL, b565(C_CARD_565, C_COOL_565, 45), C_COOL, 1)
    draw_str(d, "412.8 Mbps", 36, 120, 2, C_TEXT, "ML")
    draw_slim_bar(d, 132, 117, 142, 6, 69.0, C_COOL_565, C_TRACK)
    draw_str(d, "69%", 308, 120, 1, C_COOL, "MR")

    draw_pill_badge(d, 8, 134, 24, 14, "TX", C_PINK, b565(C_CARD_565, C_PINK_565, 45), C_PINK, 1)
    draw_str(d, "194.2 Mbps", 36, 141, 2, C_TEXT, "ML")
    draw_slim_bar(d, 132, 138, 142, 6, 32.0, C_PINK_565, C_TRACK)
    draw_str(d, "32%", 308, 141, 1, C_PINK, "MR")

    # Bottom: Fiber Speedtest
    draw_pill_badge(d, 242, 162, 70, 11, "LAST 14:15", C_DIM, C_CARD_ELEV, C_CARD_HI, 1)
    draw_pill_badge(d, 8,   178, 116, 34, "DL 586.4M", C_OK,   b565(C_CARD_565, C_OK_565, 35),   C_OK,   2)
    draw_pill_badge(d, 128, 178, 112, 34, "UL 312.0M", C_COOL, b565(C_CARD_565, C_COOL_565, 35), C_COOL, 2)
    draw_pill_badge(d, 244, 178, 68,  16, "98% PLAN",  C_OK,   C_CARD_ELEV, C_OK, 1)
    draw_pill_badge(d, 244, 196, 68,  16, "14:15",     C_DIM,  C_CARD_ELEV, C_CARD_HI, 1)
    return img


def render_tela14_ids_security() -> Image.Image:
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    draw_header_and_clock(d, "SOC / IDS")
    draw_ticker_tape(d)

    draw_modern_card(d, 4,   26, 154, 60, "SOC / IDS SHIELD", C_ACCENT_565)
    draw_modern_card(d, 162, 26, 154, 60, "IDS TELEMETRY", C_PURPLE_565)
    draw_modern_card(d, 4,   90, 312, 129, "SECURITY & SYSTEM EVENTS", C_ACCENT_565)

    # Top-left: Shield icon + status + IP
    cx, cy = 22, 60
    soft_fill = b565(C_CARD_565, C_OK_565, 45)
    fill_round_rect(d, cx - 11, cy - 12, 22, 14, 3, fill=C_OK)
    d.polygon([(cx - 11, cy + 1), (cx + 10, cy + 1), (cx, cy + 13)], fill=C_OK)
    fill_round_rect(d, cx - 9, cy - 10, 18, 11, 2, fill=C_CARD)
    d.polygon([(cx - 9, cy), (cx + 8, cy), (cx, cy + 10)], fill=C_CARD)
    fill_round_rect(d, cx - 7, cy - 8, 14, 9, 2, fill=soft_fill)
    d.polygon([(cx - 7, cy), (cx + 6, cy), (cx, cy + 8)], fill=soft_fill)
    d.line([(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)], fill=C_OK, width=2)

    draw_pill_badge(d, 40, 41, 112, 20, "SEGURO", C_OK, b565(C_CARD_565, C_OK_565, 45), C_OK, 2)
    draw_pill_badge(d, 40, 65, 112, 16, "SYNC 14:32", C_DIM, C_CARD_ELEV, C_CARD_HI, 1)

    # Top-right: 2x2 KPI Grid
    draw_pill_badge(d, 167, 41, 70, 18, "AUTH 0", C_OK, C_CARD_ELEV, C_CARD_HI, 1)
    draw_pill_badge(d, 241, 41, 70, 18, "ERRS 1", C_WARN, b565(C_CARD_565, C_WARN_565, 45), C_WARN, 1)
    draw_pill_badge(d, 167, 63, 70, 18, "SCAN 0", C_OK, C_CARD_ELEV, C_CARD_HI, 1)
    draw_pill_badge(d, 241, 63, 70, 18, "LAN/PORT 0/4", C_OK, C_CARD_ELEV, C_CARD_HI, 1)

    # Bottom: Event Log Stream
    draw_pill_badge(d, 262, 92, 50, 11, "EXT:12", C_COOL, C_CARD_ELEV, C_CARD_HI, 1)
    events = [
        (0, "14:31", "UFW Firewall ativo: 4 portas locais"),
        (0, "14:28", "SSH daemon: 0 falhas de autenticacao"),
        (1, "14:19", "docker0: latencia elevada no container"),
        (0, "14:10", "ARP watch: 18 hosts conhecidos na LAN"),
        (0, "13:55", "IDS Kernel: integridade verificada OK"),
        (0, "13:40", "Agent Telemetry: link UDP :8888 estavel"),
    ]
    for i, (sev, hm, msg) in enumerate(events):
        ry = 106 + i * 18
        if sev == 1:
            draw_pill_badge(d, 9, ry + 2, 30, 13, "WARN", C_WARN, b565(C_CARD_565, C_WARN_565, 45), C_WARN, 1)
        else:
            draw_pill_badge(d, 9, ry + 2, 30, 13, "INFO", C_COOL, b565(C_CARD_565, C_COOL_565, 35), None, 1)
        draw_str(d, hm, 43, ry + 8, 1, C_DIM, "ML")
        draw_str(d, msg[:38], 77, ry + 8, 1, C_TEXT, "ML")
        if i + 1 < len(events):
            d.line([(10, ry + 17), (309, ry + 17)], fill=C_CARD_ELEV)
    return img


def main():
    random.seed(42)

    def gen_series(n: int, start: float, lo: float, hi: float, step: float) -> list[int]:
        out = []
        v = start
        for _ in range(n):
            v = max(lo, min(hi, v + random.uniform(-step, step)))
            out.append(int(v + 0.5))
        return out

    h_cpu = gen_series(140, 38, 12, 85, 8)
    h_cpu[-1] = 42
    h_ram = gen_series(140, 60, 45, 78, 3)
    h_ram[-1] = 64
    h_gpu = gen_series(140, 68, 25, 94, 9)
    h_gpu[-1] = 76
    btc_curve = [35, 38, 34, 42, 47, 44, 52, 58, 54, 63, 61, 69, 74, 71, 79, 85, 82, 88, 92]

    screens = [
        ("boot_splash",         "BOOT SPLASH v5.0",        render_boot_splash()),
        ("tela00_resumo",       "TELA 0: RESUMO GERAL",    render_tela0_resumo()),
        ("tela01_cpu_ram",      "TELA 1: CPU/RAM STUDIO",  render_tela1_cpu_ram(h_cpu, h_ram)),
        ("tela03_gpu_focus",    "TELA 3: GPU FOCUS",       render_tela3_gpu_focus(h_gpu)),
        ("tela06_market",       "TELA 6: MERCADO & BTC",   render_tela6_market(btc_curve)),
        ("tela07_portfolio",    "TELA 7: PORTFOLIO",       render_tela7_portfolio()),
        ("tela08_pomodoro",     "TELA 8: POMODORO STUDIO", render_tela8_pomodoro()),
        ("tela09_media",        "TELA 9: MEDIA HUB",       render_tela9_media()),
        ("tela10_weather_news", "TELA 10: CLIMA & NEWS",   render_tela10_weather_news()),
        ("tela12_wifi_radar",   "TELA 12: RF RADAR & FLOW",render_tela12_wifi_radar()),
        ("tela13_net_analyzer", "TELA 13: NET / FIBER WAN",render_tela13_net_analyzer()),
        ("tela14_ids_security", "TELA 14: SOC / IDS",      render_tela14_ids_security()),
    ]

    repo_preview_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "preview", "v5"))
    brain_dir = "/home/zipo/.gemini/antigravity-cli/brain/c2bc3932-2755-4b21-ba76-05898fae46e9"
    os.makedirs(repo_preview_dir, exist_ok=True)
    os.makedirs(brain_dir, exist_ok=True)

    # Save 2x-upscaled individual PNGs (640x480) to both destinations
    for slug, _caption, im in screens:
        up = im.resize((SCR_W * 2, SCR_H * 2), Image.NEAREST)
        p_repo = os.path.join(repo_preview_dir, f"{slug}.png")
        p_brain = os.path.join(brain_dir, f"{slug}.png")
        up.save(p_repo)
        shutil.copy2(p_repo, p_brain)

    # Build 3x4 full-screen showcase grid (using 2x-upscaled 640x480 tiles with clean dark frame)
    cols, rows = 3, 4
    tile_w, tile_h = SCR_W * 2, SCR_H * 2
    pad = 16
    hdr_band = 26
    grid_w = cols * tile_w + (cols + 1) * pad
    grid_h = rows * (tile_h + hdr_band) + (rows + 1) * pad
    grid = Image.new("RGB", (grid_w, grid_h), (5, 8, 15))
    gd = ImageDraw.Draw(grid)

    for idx, (_slug, caption, im) in enumerate(screens):
        c = idx % cols
        r = idx // cols
        tx = pad + c * (tile_w + pad)
        ty = pad + r * (tile_h + hdr_band + pad)
        draw_str(gd, caption, tx + 6, ty + 4, 2, C_COOL, "TL")
        up = im.resize((tile_w, tile_h), Image.NEAREST)
        grid.paste(up, (tx, ty + hdr_band))
        gd.rectangle([tx - 1, ty + hdr_band - 1, tx + tile_w, ty + hdr_band + tile_h],
                     outline=C_CARD_HI, width=1)

    grid_repo = os.path.join(repo_preview_dir, "cyd_os_v5_showcase_grid.png")
    grid_brain = os.path.join(brain_dir, "cyd_os_v5_showcase_grid.png")
    grid.save(grid_repo)
    shutil.copy2(grid_repo, grid_brain)
    print(f"Generated {len(screens)} 2x-upscaled previews + 3x4 showcase grid in:\n  - {repo_preview_dir}\n  - {brain_dir}")


if __name__ == "__main__":
    main()
