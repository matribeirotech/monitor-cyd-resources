#!/usr/bin/env python3
"""
sim_screens.py - Simula as 5 telas do Mike Monitor em 320x240.

Reproduz as MESMAS coordenadas do firmware para conferir o layout sem precisar
gravar a placa. Gera preview/tela0.png, tela1.png, tela2.png e telas.png.
"""
import math, os, random
from PIL import Image, ImageDraw, ImageFont

SW, SH, HDR = 320, 240, 22
FDIR = "/usr/share/fonts/truetype/dejavu/"
F1 = ImageFont.truetype(FDIR + "DejaVuSans.ttf", 8)
F2 = ImageFont.truetype(FDIR + "DejaVuSans.ttf", 11)
F4 = ImageFont.truetype(FDIR + "DejaVuSans-Bold.ttf", 19)
F7 = ImageFont.truetype(FDIR + "DejaVuSansMono-Bold.ttf", 46)

BG        = (11, 14, 26)
CARD      = (26, 33, 48)
CARD_HI   = (42, 47, 53)
TRACK     = (33, 37, 41)
TEXT      = (255, 255, 255)
DIM       = (132, 132, 132)
ACCENT    = (245, 210, 31)
ACCENT_DK = (35, 43, 71)
OK        = (55, 252, 55)
WARN      = (255, 168, 0)
HOT       = (255, 60, 60)
COOL      = (111, 211, 255)
PINK      = (255, 154, 168)

SCREENS = 5
# tem que bater com MOODS/PHASES de tools/gen_mike.py
MOODS = ["sleep", "calm", "busy", "hot", "panic",
         "scared", "angry", "happy", "curious", "netheavy", "walk",
         "coffee", "smoke", "fish", "snack",
         "hacker", "biz", "focushappy", "high", "game", "gamehot",
         "stretch", "yawn", "groom", "peek"]
PHASES = {"sleep": 3, "calm": 4, "busy": 3, "hot": 3, "panic": 3,
          "scared": 3, "angry": 3, "happy": 3, "curious": 2, "netheavy": 4, "walk": 4,
          "coffee": 3, "smoke": 3, "fish": 3, "snack": 3,
          "hacker": 3, "biz": 3, "focushappy": 3, "high": 3,
          "game": 3, "gamehot": 3,
          "stretch": 3, "yawn": 3, "groom": 3, "peek": 3}
# gestos ociosos: sorteados por cima do humor calmo/dormindo (ver pumpGestures
# no .ino); nao sao humores "de verdade", entao herdam o titulo/cor do calm
GESTURES = ["stretch", "yawn", "groom", "peek"]
# variantes do foco do pomodoro: sorteadas ao clicar em "comecar" (ver
# POMO_FOCUS_MOODS no .ino); herdam titulo/cor do busy (o pomodoro manda no
# texto de qualquer forma, ver moodTitle no .ino)
POMO_FOCUS_VARIANTS = ["hacker", "biz", "focushappy"]
MOOD_TITLE = {
    "sleep": "zZz... de boa", "calm": "tudo tranquilo", "busy": "trabalhando!",
    "hot": "ta quente...", "panic": "TA FERVENDO!!", "scared": "opa, deu erro!",
    "angry": "quanto erro...", "happy": "eba!", "curious": "que barulho?",
    "netheavy": "rede pesada!",
    "walk": "passeando...", "high": "flutuando...",
    "game": "modo game!", "gamehot": "jogo quente!",
}
MOOD_COLOR = {"sleep": COOL, "calm": OK, "busy": ACCENT, "hot": WARN, "panic": HOT,
              "scared": HOT, "angry": WARN, "happy": OK, "curious": PINK,
              "netheavy": PINK,
              "walk": COOL, "coffee": WARN, "smoke": DIM, "fish": COOL,
              "snack": ACCENT, "high": PINK, "game": ACCENT, "gamehot": WARN}
MOOD_TITLE.update({"coffee": "tomando cafe", "smoke": "fumando um",
                   "fish": "pescando", "snack": "lanchando"})
for g in GESTURES:
    MOOD_TITLE[g] = "tudo tranquilo"
    MOOD_COLOR[g] = OK
for v in POMO_FOCUS_VARIANTS:
    MOOD_TITLE[v] = "foco total!"
    MOOD_COLOR[v] = ACCENT


def level(v, warn, hot):
    return HOT if v >= hot else (WARN if v >= warn else OK)


def txt(d, s, x, y, font, col, anchor="lm"):
    d.text((x, y), s, font=font, fill=col, anchor=anchor)


def card(d, x, y, w, h, title=None):
    d.rounded_rectangle([x, y, x + w, y + h], 4, fill=CARD, outline=CARD_HI)
    if title:
        txt(d, title, x + 6, y + 8, F1, DIM)


def header(d, host, linked, clock="13:06"):
    d.rectangle([0, 0, SW, HDR], fill=ACCENT_DK)
    d.rectangle([0, HDR - 2, SW, HDR], fill=ACCENT)
    d.ellipse([6, 7, 14, 15], fill=ACCENT)
    for cx in (5, 10, 15):
        cy = 4 if cx == 10 else 6
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=ACCENT)
    txt(d, "MIKE MONITOR", 22, 10, F2, ACCENT)
    # relogio de Brasilia (campos "hh"/"mm" do agente, ver mike_agent.py)
    txt(d, clock if linked else "--:--", SW // 2 + 8, 10, F1, ACCENT, anchor="mm")
    txt(d, host if linked else "sem sinal", SW - 6, 10, F2,
        TEXT if linked else DIM, anchor="rm")


def gauge(d, cx, cy, r, v, label, valid):
    ir = r - 9
    a0, a1 = 30, 330
    # angulo 0 = 6h, sentido horario  ->  converte para o sistema do PIL
    def pil(a):
        return a + 90
    aend = a0 + (a1 - a0) * (v / 100.0 if valid else 0)
    col = level(v, 60, 85) if valid else TRACK
    box = [cx - r, cy - r, cx + r, cy + r]
    if aend > a0 + 1:
        d.arc(box, pil(a0), pil(aend), fill=col, width=r - ir)
    if aend < a1 - 1:
        d.arc(box, pil(aend), pil(a1), fill=TRACK, width=r - ir)
    txt(d, f"{int(v + 0.5)}" if valid else "--", cx, cy - 4, F4,
        TEXT if valid else DIM, anchor="mm")
    txt(d, label, cx, cy + 18, F2, DIM, anchor="mm")


def bar(d, x, y, w, h, label, pct, right, warn, hot):
    txt(d, label, x, y + h / 2, F2, DIM)
    bx, bw = x + 34, w - 34 - 58
    d.rounded_rectangle([bx, y, bx + bw, y + h], 2, outline=CARD_HI)
    fill = int((bw - 2) * max(0, min(100, pct)) / 100)
    if fill:
        d.rectangle([bx + 1, y + 1, bx + fill, y + h - 1], fill=level(pct, warn, hot))
    txt(d, right, x + w, y + h / 2, F2, TEXT, anchor="rm")


NAV_BAR_H = 18


def dots(d, active):
    for i in range(SCREENS):
        c = ACCENT if i == active else CARD_HI
        r = 3 if i == active else 2
        cx = SW // 2 - (SCREENS - 1) * 6 + i * 12
        d.ellipse([cx - r, SH - 7 - r, cx + r, SH - 7 + r], fill=c)
    # menuzinho de navegacao (voltar / avancar), fixo em todas as telas
    y = SH - NAV_BAR_H
    txt(d, "<", 27, y + NAV_BAR_H // 2, F2, DIM, anchor="mm")
    txt(d, ">", SW - 27, y + NAV_BAR_H // 2, F2, DIM, anchor="mm")


def paste_mike(img, mood, x, y, scale=3, phase=0):
    sheet = Image.open(os.path.join(os.path.dirname(__file__), "..",
                                    "preview", "mike_frames.png"))
    order = []
    for m in MOODS:
        for p in range(PHASES[m]):
            order.append(m)
    idx = order.index(mood) + phase
    fw = sheet.width // len(order)
    frame = sheet.crop((idx * fw, 0, (idx + 1) * fw, sheet.height))
    frame = frame.resize((40 * scale, 36 * scale), Image.NEAREST)
    # o preview vem com fundo escuro; recompoe sobre o cartao
    bgpatch = Image.new("RGB", frame.size, CARD)
    px = frame.load()
    bp = bgpatch.load()
    for yy in range(frame.height):
        for xx in range(frame.width):
            r, g, b = px[xx, yy][:3]
            if (r, g, b) != (24, 26, 32):
                bp[xx, yy] = (r, g, b)
    img.paste(bgpatch, (x, y))


# ------------------------------------------------------------------ telas ---
def tela0(s, mood="busy"):
    img = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(img)
    header(d, s["host"], s["linked"])
    card(d, 2, HDR + 2, 126, 186)
    card(d, 132, HDR + 2, 186, 108)
    card(d, 132, HDR + 112, 186, 76)

    if mood == "walk":
        # o firmware desenha o passeio em escala 2, deslocando na horizontal
        paste_mike(img, mood, 5 + 20, HDR + 6 + 30, scale=2, phase=1)
    else:
        paste_mike(img, mood, 5, HDR + 6)
    d = ImageDraw.Draw(img)
    txt(d, MOOD_TITLE[mood], 65, HDR + 126, F2, MOOD_COLOR[mood], anchor="mm")
    txt(d, s["top"], 65, HDR + 146, F2, DIM, anchor="mm")
    txt(d, s["uptime"], 65, HDR + 168, F2, TEXT, anchor="mm")

    gauge(d, 178, HDR + 50, 36, s["cpu"], "CPU", True)
    gauge(d, 272, HDR + 50, 36, s["gpu"], "GPU", s["gpu"] >= 0)
    txt(d, f"{s['cput']:.0f} C", 178, HDR + 96, F2, level(s["cput"], 75, 85), anchor="mm")
    txt(d, f"{s['gput']:.0f} C", 272, HDR + 96, F2, level(s["gput"], 75, 85), anchor="mm")

    bar(d, 140, HDR + 120, 172, 12, "RAM", s["ram"], f"{s['ramu']:.1f}/{s['ramt']:.0f}G", 75, 90)
    bar(d, 140, HDR + 138, 172, 12, "DSK", s["dsk"], f"{s['dskf']:.0f}G livre", 80, 92)
    txt(d, f"v {s['rx']:.1f} MB/s", 140, HDR + 168, F2, COOL)
    txt(d, f"^ {s['tx']:.1f} MB/s", 228, HDR + 168, F2, PINK)
    dots(d, 0)
    return img


def plot(d, x, y, w, h, data, col, unit):
    d.rectangle([x, y, x + w, y + h], fill=CARD)
    for i in range(1, 4):
        for gx in range(x, x + w, 6):
            d.point((gx, y + h * i // 4), fill=CARD_HI)
    dark = tuple(c // 3 for c in col)
    prev = None
    n = min(len(data), w)
    for i in range(n):
        v = data[-1 - i]
        px = x + w - 1 - i
        py = y + h - 1 - int((h - 1) * v / 100)
        d.line([(px, py), (px, y + h - 1)], fill=dark)
        if prev is not None:
            d.line([(px + 1, prev), (px, py)], fill=col)
        prev = py
    txt(d, f"{int(data[-1])}{unit}", x + w - 2, y - 6, F2, col, anchor="rm")


def tela1(hist):
    img = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(img)
    header(d, "zipo-pc", True)
    card(d, 2, HDR + 2, 156, 96, "CPU %")
    card(d, 162, HDR + 2, 156, 96, "GPU %")
    card(d, 2, HDR + 102, 156, 96, "RAM %")
    card(d, 162, HDR + 102, 156, 96, "TEMP C")
    plot(d, 8, HDR + 18, 144, 74, hist["cpu"], ACCENT, "%")
    plot(d, 168, HDR + 18, 144, 74, hist["gpu"], OK, "%")
    plot(d, 8, HDR + 118, 144, 74, hist["ram"], COOL, "%")
    plot(d, 168, HDR + 118, 144, 74, hist["tmp"], HOT, "C")
    dots(d, 1)
    return img


def tela2(s):
    img = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(img)
    header(d, s["host"], True)
    card(d, 2, HDR + 2, 156, 108, "CPU")
    card(d, 162, HDR + 2, 156, 108, "GPU")
    card(d, 2, HDR + 116, 316, 72, "SISTEMA")

    for cx, t, sub in ((78, s["cput"], f"{s['cores']} nucleos  {s['cpuf']:.0f} MHz"),
                       (238, s["gput"], f"NVIDIA  {s['gpuw']:.0f} W")):
        txt(d, f"{int(t + 0.5)}", cx, HDR + 46, F7, level(t, 75, 85), anchor="mm")
        txt(d, "C", cx + 42, HDR + 38, F4, level(t, 75, 85))
        txt(d, sub, cx, HDR + 80, F2, DIM, anchor="mm")

    txt(d, f"load {s['load']:.2f}", 10, HDR + 136, F2, TEXT)
    txt(d, f"fan {s['fan']} rpm", 110, HDR + 136, F2, TEXT)
    txt(d, f"swap {s['swap']:.0f}%", 212, HDR + 136, F2, TEXT)
    txt(d, f"disco R {s['dr']:.1f}  W {s['dw']:.1f} MB/s", 10, HDR + 160, F2, TEXT)
    txt(d, f"vram {s['vram']:.0f}%", 220, HDR + 160, F2, TEXT)
    dots(d, 2)
    return img


def tela3(s, logs):
    img = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(img)
    header(d, s["host"], True)
    card(d, 2, HDR + 2, 316, 44)
    card(d, 2, HDR + 50, 316, 138, "JOURNALCTL")

    for cx, lbl, val, col in ((58, "ERROS", str(logs["err"]), HOT if logs["err"] else OK),
                              (158, "AVISOS", str(logs["warn"]), WARN if logs["warn"] else OK),
                              (262, "ERR/MIN", f"{logs['rate']:.1f}",
                               level(logs["rate"], 1.0, 3.0))):
        txt(d, lbl, cx, HDR + 13, F2, DIM, anchor="mm")
        txt(d, val, cx, HDR + 33, F4, col, anchor="mm")

    y0 = HDR + 73
    for i, (prio, unit, msg) in enumerate(logs["lines"][:6]):
        y = y0 + i * 20
        c = HOT if prio <= 3 else WARN
        d.rounded_rectangle([8, y - 7, 23, y + 8], 2, fill=c)
        txt(d, "E" if prio <= 3 else "W", 15, y, F1, BG, anchor="mm")
        txt(d, unit, 27, y, F1, DIM)
        txt(d, msg, 93, y, F1, TEXT)
    dots(d, 3)
    return img


def button(d, r, label, bg, fg, font):
    x, y, w, h = r
    d.rounded_rectangle([x, y, x + w, y + h], 4, fill=bg, outline=CARD_HI)
    txt(d, label, x + w // 2, y + h // 2, font, fg, anchor="mm")


def tela4(p):
    """p: state, label, mm, ss, frac, cycles, breakmin, mood"""
    img = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(img)
    header(d, "zipo-pc", True)
    card(d, 2, HDR + 2, 126, 186)
    card(d, 132, HDR + 2, 186, 96)
    card(d, 132, HDR + 100, 186, 88)

    paste_mike(img, p["mood"], 5, HDR + 6, phase=p.get("phase", 0))
    d = ImageDraw.Draw(img)
    txt(d, p["moodtxt"], 65, HDR + 126, F2, MOOD_COLOR.get(p["mood"], TEXT), anchor="mm")
    txt(d, f"{p['cycles']} ciclos hoje", 65, HDR + 150, F2, DIM, anchor="mm")
    txt(d, f"pausa de {p['breakmin']} min", 65, HDR + 172, F2, ACCENT, anchor="mm")

    lcol = {"FOCO": HOT, "PAUSA": OK, "PAUSADO": WARN, "PRONTO": DIM}[p["label"]]
    txt(d, p["label"], 225, HDR + 16, F2, lcol, anchor="mm")
    txt(d, f"{p['mm']:02d}:{p['ss']:02d}", 225, HDR + 50, F7,
        DIM if p["label"] == "PAUSADO" else TEXT, anchor="mm")

    bx, by, bw, bh = 144, HDR + 82, 162, 8
    d.rounded_rectangle([bx, by, bx + bw, by + bh], 2, outline=CARD_HI)
    fill = int((bw - 2) * p["frac"])
    if fill:
        d.rectangle([bx + 1, by + 1, bx + fill, by + bh - 1], fill=lcol)

    main_label, main_bg = {"PRONTO": ("COMECAR", OK), "FOCO": ("PAUSAR", WARN),
                           "PAUSA": ("PAUSAR", WARN), "PAUSADO": ("RETOMAR", OK)}[p["label"]]
    button(d, (138, 128, 174, 32), main_label, main_bg, BG, F4)
    sel5 = p["breakmin"] == 5
    button(d, (138, 166, 84, 26), "pausa 5", ACCENT if sel5 else CARD_HI,
           BG if sel5 else TEXT, F2)
    button(d, (228, 166, 84, 26), "pausa 15", ACCENT if not sel5 else CARD_HI,
           BG if not sel5 else TEXT, F2)
    txt(d, "zerar", 225, 203, F1, DIM, anchor="mm")
    txt(d, "use as setas ou toque fora dos botoes", SW // 2, SH - 20, F1, DIM,
        anchor="mm")
    dots(d, 4)
    return img


def main():
    random.seed(7)
    s = dict(host="zipo-pc", linked=True, cpu=74.0, gpu=88.0, cput=79.0, gput=71.0,
             ram=63.0, ramu=10.1, ramt=16, dsk=71.0, dskf=142.0, rx=4.2, tx=0.8,
             top="firefox", uptime="03:41:22", cores=12, cpuf=4250, gpuw=186,
             load=3.14, fan=1620, swap=4, dr=12.4, dw=3.1, vram=61)

    def walk(n, start, lo, hi, step):
        out, v = [], start
        for _ in range(n):
            v = max(lo, min(hi, v + random.uniform(-step, step)))
            out.append(v)
        return out

    hist = dict(cpu=walk(144, 40, 3, 100, 14), gpu=walk(144, 60, 0, 100, 18),
                ram=walk(144, 55, 30, 80, 4), tmp=walk(144, 65, 40, 92, 3))

    logs = dict(err=17, warn=63, rate=2.4, lines=[
        (2, "kernel", "Out of memory: Killed process 4242"),
        (3, "nginx", "upstream timed out while reading"),
        (4, "kernel", "usb 1-3: device descriptor read -71"),
        (3, "postgresql", "conexao recusada em 5432"),
        (4, "bluetoothd", "Failed to set mode: Blocked"),
        (3, "gdm", "Child process died unexpectedly"),
    ])

    pomo_work = dict(label="FOCO", mm=18, ss=42, frac=0.25, cycles=3, breakmin=5,
                     mood="busy", moodtxt="foco total!")
    # as 4 variantes sorteadas ao clicar em "comecar" (ver POMO_FOCUS_MOODS no .ino)
    pomo_focus_variants = [
        dict(label="FOCO", mm=24, ss=10, frac=0.04, cycles=0, breakmin=5,
             mood="busy", moodtxt="foco total!", phase=1),
        dict(label="FOCO", mm=24, ss=10, frac=0.04, cycles=0, breakmin=5,
             mood="hacker", moodtxt="foco total!", phase=1),
        dict(label="FOCO", mm=24, ss=10, frac=0.04, cycles=0, breakmin=5,
             mood="biz", moodtxt="foco total!", phase=1),
        dict(label="FOCO", mm=24, ss=10, frac=0.04, cycles=0, breakmin=5,
             mood="focushappy", moodtxt="foco total!", phase=1),
    ]
    pomo_breaks = [
        dict(label="PAUSA", mm=4, ss=12, frac=0.72, cycles=3, breakmin=5,
             mood="coffee", moodtxt="tomando cafe", phase=1),
        dict(label="PAUSA", mm=3, ss=30, frac=0.30, cycles=5, breakmin=5,
             mood="smoke", moodtxt="fumando um", phase=1),
        dict(label="PAUSA", mm=12, ss=5, frac=0.19, cycles=4, breakmin=15,
             mood="fish", moodtxt="pescando", phase=2),
        dict(label="PAUSA", mm=9, ss=48, frac=0.34, cycles=8, breakmin=15,
             mood="snack", moodtxt="lanchando", phase=1),
    ]

    root = os.path.join(os.path.dirname(__file__), "..", "preview")
    os.makedirs(root, exist_ok=True)
    imgs = [tela0(s, "busy"), tela1(hist), tela2(s), tela3(s, logs),
            tela4(pomo_work)]

    # tira das pausas
    pb = Image.new("RGB", (SW * 4, SH), BG)
    for i, p in enumerate(pomo_breaks):
        pb.paste(tela4(p), (i * SW, 0))
    pb.resize((SW * 4 * 2, SH * 2), Image.NEAREST).save(
        os.path.join(root, "pomodoro_pausas.png"))

    # tira das 4 variantes do foco
    pf = Image.new("RGB", (SW * 4, SH), BG)
    for i, p in enumerate(pomo_focus_variants):
        pf.paste(tela4(p), (i * SW, 0))
    pf.resize((SW * 4 * 2, SH * 2), Image.NEAREST).save(
        os.path.join(root, "pomodoro_foco.png"))
    for i, im in enumerate(imgs):
        im.resize((SW * 2, SH * 2), Image.NEAREST).save(os.path.join(root, f"tela{i}.png"))

    # tira de humores: 2 linhas de 5
    preset = {"sleep": (2, 0, 38, 33), "calm": (24, 12, 47, 41),
              "busy": (74, 88, 68, 66), "hot": (91, 76, 78, 81),
              "panic": (99, 97, 89, 92), "scared": (38, 20, 55, 50),
              "angry": (44, 30, 60, 55), "happy": (18, 8, 44, 40),
              "curious": (30, 15, 50, 45), "netheavy": (35, 20, 52, 47),
              "walk": (3, 1, 36, 32),
              "coffee": (6, 2, 40, 35), "smoke": (5, 2, 39, 34),
              "fish": (4, 1, 38, 33), "snack": (7, 3, 41, 36),
              "hacker": (70, 55, 65, 60), "biz": (65, 50, 63, 58),
              "focushappy": (72, 60, 66, 61), "high": (14, 6, 42, 37),
              "game": (68, 72, 64, 67), "gamehot": (78, 81, 77, 82),
              "stretch": (8, 3, 42, 37), "yawn": (9, 4, 43, 38),
              "groom": (10, 4, 44, 38), "peek": (11, 5, 45, 39)}
    cols = 5
    rows = (len(MOODS) + cols - 1) // cols
    moods = Image.new("RGB", (SW * cols, SH * rows), BG)
    for i, m in enumerate(MOODS):
        s2 = dict(s)
        s2["cpu"], s2["gpu"], s2["cput"], s2["gput"] = preset[m]
        moods.paste(tela0(s2, m), ((i % cols) * SW, (i // cols) * SH))
    moods.save(os.path.join(root, "humores.png"))

    cols, rows = 3, 2
    strip = Image.new("RGB", (SW * cols + 8 * (cols - 1),
                              SH * rows + 8), (0, 0, 0))
    for i, im in enumerate(imgs):
        strip.paste(im, ((i % cols) * (SW + 8), (i // cols) * (SH + 8)))
    strip.save(os.path.join(root, "telas.png"))
    print("ok -> preview/tela0..4.png telas.png humores.png pomodoro_pausas.png pomodoro_foco.png")


if __name__ == "__main__":
    main()
