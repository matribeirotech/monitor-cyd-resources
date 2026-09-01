#!/usr/bin/env python3
"""
gen_mike.py - Gera os sprites do Mike (pixel art 40x36, 4bpp indexado)
Saidas:
  firmware/mike_monitor/mike_sprites.h   -> dados para o ESP32
  preview/mike_frames.png                -> folha de sprites ampliada (conferencia visual)
"""
from PIL import Image, ImageDraw
import math, os, textwrap

W, H = 40, 36
SCALE_PREVIEW = 6

# ---------------------------------------------------------------- paleta ----
# indice: (R,G,B).  0 = transparente
# MIKE = gato tuxedo: pelo azul-escuro/preto, peito e patas brancos, olhos amarelos.
PALETTE = [
    (255, 0, 255),   # 0  transparente (magenta magico)
    (11, 14, 26),    # 1  K  contorno
    (35, 43, 71),    # 2  F  pelo base (navy escuro)
    (20, 26, 46),    # 3  D  sombra do pelo
    (244, 248, 255), # 4  L  branco (focinho/peito/patas)
    (255, 154, 168), # 5  P  rosa (orelha/nariz/lingua)
    (214, 224, 240), # 6  W  branco sombreado
    (245, 210, 31),  # 7  G  iris amarela
    (12, 12, 16),    # 8  B  pupila
    (111, 211, 255), # 9  S  suor / azul
    (207, 239, 255), # 10 Z  zzz
    (59, 71, 112),   # 11 H  brilho do pelo
    (255, 92, 92),   # 12 R  vermelho alerta
    (26, 33, 56),    # 13 K2 contorno suave
    (255, 176, 59),  # 14 Y  ambar (iris escura)
    (166, 116, 72),  # 15 BR marrom (caneca, lanche, vara de pesca)
]
T, K, F, D, L, P, WS, G, B, S, Z, HL, R, K2, Y, BR = range(16)
# ATENCAO: nao usar o nome "W" para cor -- W eh a largura do canvas.


def new_frame():
    img = Image.new("P", (W, H), T)
    img.putpalette([c for rgb in PALETTE for c in rgb])
    return img


def mirror_x(x):
    return W - 1 - x


# ---------------------------------------------------------------- corpo -----
def draw_tail(d, phase, puffed=False):
    """phase 0..5 -> posicao da cauda (direita da tela)"""
    pts = {
        0: [(28, 32), (33, 30), (36, 25), (35, 20)],
        1: [(28, 32), (34, 31), (37, 27), (37, 22)],
        2: [(28, 32), (33, 32), (37, 30), (38, 25)],
        3: [(28, 32), (34, 29), (36, 23), (33, 18)],
        4: [(28, 32), (33, 28), (34, 20), (34, 12)],   # arrepiada, pra cima
        5: [(28, 32), (34, 33), (38, 33), (39, 29)],   # chicoteando baixo
    }[phase]
    w_out, w_in = (7, 5) if puffed else (5, 3)
    d.line(pts, fill=K, width=w_out, joint="curve")
    d.line(pts, fill=F, width=w_in, joint="curve")
    if puffed:  # espinhos de pelo arrepiado ao longo da cauda
        for i in range(1, len(pts)):
            x, y = pts[i]
            d.polygon([(x - 4, y), (x - 6, y - 2), (x - 3, y - 2)], fill=F, outline=K)
            d.polygon([(x + 4, y), (x + 6, y - 2), (x + 3, y - 2)], fill=F, outline=K)
    # ponta branca (tuxedo)
    d.ellipse([pts[-1][0] - 2, pts[-1][1] - 2, pts[-1][0] + 1, pts[-1][1] + 1], fill=L, outline=K)


def draw_spikes(d, jitter=0):
    """pelo em pe: espinhos no topo da cabeca e nas costas"""
    for x in range(9, 32, 4):
        h = 3 + ((x + jitter) % 3)
        d.polygon([(x - 2, 6), (x, 6 - h), (x + 2, 6)], fill=F, outline=K)
    for x, y in ((10, 22), (8, 26), (30, 22), (32, 26)):
        dx = -3 if x < 20 else 3
        d.polygon([(x, y - 2), (x + dx, y - 4), (x + dx // 2, y + 1)], fill=F, outline=K)


def draw_question(d, phase):
    x, y = 30, 4 - phase
    d.arc([x, y, x + 6, y + 6], 160, 20, fill=Z)
    d.line([(x + 3, y + 5), (x + 3, y + 8)], fill=Z)
    d.point((x + 3, y + 10), fill=Z)


def draw_exclaim(d, phase):
    for x in (6, 33):
        y = 3 + (phase % 2)
        d.line([(x, y), (x, y + 5)], fill=R)
        d.point((x, y + 7), fill=R)


def draw_body(d, squash=0):
    top = 19 + squash
    d.ellipse([9, top, 30, 35], fill=F, outline=K)
    # sombra lateral
    d.ellipse([9, top + 2, 14, 33], fill=D)
    d.ellipse([25, top + 2, 30, 33], fill=D)
    # peitilho branco tuxedo (formato de gravata)
    d.polygon([(19, top), (24, top + 6), (25, 34), (14, 34), (15, top + 6)], fill=L)
    d.polygon([(19, top + 2), (22, top + 7), (19, top + 10), (17, top + 7)], fill=WS)
    # patinhas brancas da frente
    for cx in (13, 26):
        d.ellipse([cx - 3, 30, cx + 3, 35], fill=L, outline=K)
        d.line([(cx - 1, 32), (cx - 1, 34)], fill=K)
        d.line([(cx + 1, 32), (cx + 1, 34)], fill=K)


def draw_ears(d, droop=0):
    """droop 0 = em pe, 1 = meio, 2 = caidas"""
    if droop == 0:
        left = [(9, 11), (12, 1), (18, 8)]
        inner = [(11, 9), (12, 4), (15, 8)]
    elif droop == 1:
        left = [(8, 12), (10, 3), (18, 9)]
        inner = [(10, 10), (11, 6), (15, 9)]
    elif droop == 3:                      # totalmente para tras (bravo/assustado)
        left = [(6, 10), (4, 14), (15, 12)]
        inner = [(8, 11), (7, 13), (13, 12)]
    else:
        left = [(7, 13), (7, 6), (17, 10)]
        inner = [(9, 11), (9, 8), (14, 10)]
    d.polygon(left, fill=F, outline=K)
    d.polygon(inner, fill=P)
    right = [(mirror_x(x), y) for x, y in left]
    rinner = [(mirror_x(x), y) for x, y in inner]
    d.polygon(right, fill=F, outline=K)
    d.polygon(rinner, fill=P)


def draw_head(d):
    d.ellipse([7, 4, 32, 22], fill=F, outline=K)
    # sombra nas laterais da cabeca
    d.ellipse([7, 8, 12, 20], fill=D)
    d.ellipse([27, 8, 32, 20], fill=D)
    # mancha branca (blaze) estreita subindo do focinho ate a testa
    d.polygon([(20, 5), (22, 12), (21, 17), (18, 17), (17, 12)], fill=L)
    # brilho no topo da cabeca
    d.line([(12, 8), (15, 6)], fill=HL)
    d.line([(25, 6), (28, 8)], fill=HL)


def draw_muzzle(d, mouth="smile"):
    d.ellipse([14, 15, 25, 22], fill=L)
    # nariz
    d.polygon([(18, 15), (21, 15), (19, 17)], fill=P, outline=K)
    if mouth == "smile":
        d.arc([15, 16, 19, 20], 0, 140, fill=K)
        d.arc([20, 16, 24, 20], 40, 180, fill=K)
    elif mouth == "flat":
        d.line([(17, 19), (22, 19)], fill=K)
    elif mouth == "tongue":
        d.arc([15, 16, 19, 20], 0, 140, fill=K)
        d.arc([20, 16, 24, 20], 40, 180, fill=K)
        d.ellipse([18, 19, 21, 22], fill=P, outline=K)
    elif mouth == "open":
        d.ellipse([17, 18, 22, 22], fill=K)
        d.ellipse([18, 20, 21, 22], fill=P)
    elif mouth == "sleep":
        d.arc([17, 17, 22, 20], 20, 160, fill=K)
    elif mouth == "frown":
        d.arc([16, 19, 23, 23], 180, 360, fill=K)
    elif mouth == "grin":
        d.chord([16, 17, 23, 22], 0, 180, fill=K, outline=K)
        d.chord([17, 19, 22, 22], 0, 180, fill=P)
    elif mouth == "hiss":
        d.polygon([(16, 18), (23, 18), (22, 22), (17, 22)], fill=K)
        d.polygon([(17, 18), (18, 20), (19, 18)], fill=L)   # presas
        d.polygon([(20, 18), (21, 20), (22, 18)], fill=L)
    # bigodes brancos (contrastam no pelo escuro)
    for y0, y1 in ((17, 16), (19, 19)):
        d.line([(12, y1), (5, y0 - 2)], fill=L)
        d.line([(27, y1), (34, y0 - 2)], fill=L)


def draw_eyes(d, kind="open", look=0):
    """kind: open | wide | closed | happy | half ; look: -1,0,1 desloca a pupila"""
    for cx in (14, 25):
        if kind == "closed":
            d.arc([cx - 4, 9, cx + 3, 14], 200, 340, fill=L)
            continue
        if kind == "happy":
            d.arc([cx - 4, 8, cx + 3, 14], 190, 350, fill=Y)
            continue
        if kind == "tiny":            # olhos arregalados, pupila minuscula (susto)
            box = [cx - 5, 6, cx + 4, 17]
            d.ellipse(box, fill=L, outline=K)
            icx = (box[0] + box[2]) // 2 + look
            icy = (box[1] + box[3]) // 2
            d.ellipse([icx - 1, icy - 1, icx + 1, icy + 1], fill=B)
            continue
        if kind == "angry":           # olhos semicerrados com sobrancelha em V
            box = [cx - 4, 9, cx + 3, 15]
            d.ellipse(box, fill=G, outline=K)
            icx = (box[0] + box[2]) // 2 + look
            d.ellipse([icx - 1, 10, icx + 1, 14], fill=B)
            if cx < 20:
                d.line([(cx - 5, 6), (cx + 3, 9)], fill=K)
                d.line([(cx - 5, 7), (cx + 3, 10)], fill=K)
            else:
                d.line([(cx + 4, 6), (cx - 4, 9)], fill=K)
                d.line([(cx + 4, 7), (cx - 4, 10)], fill=K)
            continue
        if kind == "high":             # vermelhos, semicerrados, pupilas vesgas
            box = [cx - 4, 10, cx + 3, 15]
            d.ellipse(box, fill=R, outline=K)
            look2 = 1 if cx < 20 else -1     # cruza os olhos um pro outro
            icx = (box[0] + box[2]) // 2 + look2
            icy = (box[1] + box[3]) // 2
            d.ellipse([icx - 1, icy - 2, icx + 1, icy + 2], fill=B)
            continue
        if kind == "wide":
            box = [cx - 4, 7, cx + 3, 16]
            ir = 3
        elif kind == "half":
            box = [cx - 4, 10, cx + 3, 14]
            ir = 2
        else:
            box = [cx - 4, 8, cx + 3, 15]
            ir = 2
        d.ellipse(box, fill=G, outline=K)
        icx = (box[0] + box[2]) // 2 + look
        icy = (box[1] + box[3]) // 2
        # borda ambar
        d.arc(box, 0, 360, fill=Y)
        # pupila em fenda vertical (gato)
        d.ellipse([icx - 1, icy - ir, icx + 1, icy + ir], fill=B)
        d.point((icx - 1, icy - ir), fill=L)


def draw_sweat(d, n, phase):
    spots = [(34, 8 + phase), (5, 11 + phase), (31, 3 + phase)]
    for i in range(min(n, len(spots))):
        x, y = spots[i]
        d.polygon([(x, y - 2), (x + 2, y + 2), (x - 2, y + 2)], fill=S, outline=K)
        d.point((x - 1, y + 1), fill=L)


def draw_zzz(d, phase):
    base = [(30, 6), (33, 2)]
    for i, (x, y) in enumerate(base):
        y -= phase
        if y < 0:
            continue
        size = 3 + i
        d.line([(x, y), (x + size, y)], fill=Z)
        d.line([(x + size, y), (x, y + size)], fill=Z)
        d.line([(x, y + size), (x + size, y + size)], fill=Z)


def draw_angry_marks(d):
    d.line([(9, 5), (13, 7)], fill=R)
    d.line([(9, 7), (13, 5)], fill=R)
    d.line([(30, 5), (26, 7)], fill=R)
    d.line([(30, 7), (26, 5)], fill=R)


# ------------------------------------------- atividades da pausa do pomodoro --
def draw_coffee(d, phase):
    """Caneca ao lado do Mike. Fica na lateral de proposito: em frente ao peito
    o vapor nao teria para onde subir, e o desenho vira um borrao marrom."""
    d.rectangle([28, 26, 36, 33], fill=BR, outline=K)
    d.rectangle([29, 27, 35, 29], fill=K2)              # cafe
    d.arc([35, 27, 39, 32], 270, 90, fill=K)            # asa
    for i, x0 in enumerate((29, 33)):
        y = 22 - phase * 3 - i * 3
        if y > 1:
            d.arc([x0, y, x0 + 3, y + 4], 100, 280, fill=WS)


def draw_cigarette(d, phase):
    """Cigarro na boca e fumaca subindo pela direita."""
    d.rectangle([24, 19, 29, 20], fill=L, outline=K)
    d.point((30, 19), fill=R)
    d.point((30, 20), fill=Y)
    for i in range(3):
        y = 15 - i * 4 - phase
        x = 30 + i
        if y > 0 and x < 36:
            d.arc([x, y, x + 4, y + 4], 90, 300, fill=WS)


def draw_fishing(d, phase):
    """Vara de pesca na patinha, boia balancando, peixe no ultimo quadro."""
    d.line([(26, 28), (37, 9)], fill=BR, width=2)
    d.line([(37, 9), (38, 20)], fill=WS)
    by = 20 + (phase % 2)
    d.ellipse([36, by, 39, by + 3], fill=R, outline=K)
    if phase == 2:                                       # fisgou!
        d.polygon([(32, 29), (37, 27), (37, 31)], fill=S, outline=K)
        d.point((34, 28), fill=K)


def draw_paw_wash(d, phase):
    """Pata levantada perto do rosto -- gesto de gato se limpando."""
    pos = {0: (9, 17), 1: (12, 11), 2: (9, 19)}[phase]
    px, py = pos
    d.ellipse([px - 3, py - 3, px + 3, py + 4], fill=L, outline=K)
    d.line([(px - 1, py + 3), (px - 1, py + 7)], fill=K)
    d.line([(px + 1, py + 3), (px + 1, py + 7)], fill=K)


def draw_blunt(d, phase):
    """Um "back" na boca com fumaca grossa subindo -- easter egg das 16:20."""
    d.rectangle([24, 19, 30, 21], fill=BR, outline=K)
    d.point((31, 19), fill=R)                            # brasa
    d.point((31, 20), fill=Y)
    for i in range(4):
        y = 14 - i * 4 - phase
        x = 31 + (i % 2)
        if y > -2 and x < 38:
            d.arc([x, y, x + 5, y + 5], 60, 320, fill=WS)


def draw_hoodie(d, phase):
    """Capuz de moletom cobrindo o topo da cabeca -- vibe gato hacker."""
    d.chord([5, 1, 34, 23], 180, 360, fill=K)
    d.polygon([(5, 9), (1, 16), (7, 14)], fill=K)         # dobra lateral esq
    d.polygon([(34, 9), (38, 16), (32, 14)], fill=K)      # dobra lateral dir
    dy = phase % 2
    d.line([(16, 19), (15, 24 + dy)], fill=L, width=1)    # cordoes
    d.line([(23, 19), (24, 24 + dy)], fill=L, width=1)


def draw_laptop(d, phase):
    """Notebook aberto na altura do peito, tela acesa (glow piscando)."""
    d.polygon([(13, 27), (27, 27), (25, 33), (15, 33)], fill=K, outline=K)  # teclado
    d.polygon([(14, 18), (26, 18), (27, 27), (13, 27)], fill=K, outline=K)  # tela
    d.rectangle([16, 20, 24, 25], fill=(S if phase % 2 == 0 else HL))


def draw_sunglasses(d):
    """Oculos escuro cobrindo os olhos -- vibe homem de negocios."""
    d.rectangle([9, 10, 30, 14], fill=K)
    d.rectangle([10, 11, 17, 13], fill=K2)
    d.rectangle([22, 11, 29, 13], fill=K2)
    d.point((13, 11), fill=L)
    d.point((25, 11), fill=L)


def draw_suit(d):
    """Lapelas escuras por cima do peitilho branco + gravata vermelha."""
    d.polygon([(14, 22), (19, 27), (14, 34)], fill=K, outline=HL)
    d.polygon([(25, 22), (20, 27), (25, 34)], fill=K, outline=HL)
    d.polygon([(18, 22), (21, 22), (19, 27)], fill=R, outline=K)


def draw_briefcase(d):
    """Maletinha na pata."""
    d.rectangle([29, 27, 39, 34], fill=BR, outline=K)
    d.rectangle([33, 25, 36, 27], fill=BR, outline=K)     # alca
    d.line([(29, 30), (39, 30)], fill=K)


def draw_controller(d, phase):
    """Controle de video game na altura do peito -- modo game."""
    d.rounded_rectangle([9, 26, 30, 33], 3, fill=K, outline=K)
    d.ellipse([12, 27, 16, 31], fill=D, outline=K)        # analogico esq
    d.ellipse([22, 27, 26, 31], fill=D, outline=K)        # analogico dir
    d.point((28, 28), fill=(Y if phase % 2 == 0 else R))  # botao piscando


def draw_fan(d, phase):
    """Ventilador de mesa ligado, girando -- entra quando o modo game esquenta."""
    cx, cy, r = 6, 7, 5
    d.line([(cx, cy + r), (cx, cy + r + 3)], fill=K, width=2)   # pezinho
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=K, fill=WS)
    for k in range(3):
        a = math.radians(phase * 55 + k * 120)
        x2 = cx + round(r * 0.75 * math.cos(a))
        y2 = cy + round(r * 0.75 * math.sin(a))
        d.line([(cx, cy), (x2, y2)], fill=S, width=2)
    d.point((cx, cy), fill=K)


def draw_router(d, phase):
    """Roteador wifi numa pata, antenas e luz piscando -- rede pesada."""
    d.rounded_rectangle([26, 27, 38, 33], 2, fill=K, outline=K)
    d.line([(28, 27), (26, 22)], fill=D, width=1)         # antena esq
    d.line([(36, 27), (38, 22)], fill=D, width=1)         # antena dir
    lit = (Y if phase % 2 == 0 else S)
    for i, x in enumerate((29, 32, 35)):
        d.point((x, 30), fill=(lit if i == phase % 3 else K2))


def draw_head_scratch(d, phase):
    """Pata coçando a cabeça do lado da orelha -- confuso com o tanto de rede."""
    cx, cy = 29, 7 + (phase % 2)
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 4], fill=L, outline=K)
    d.line([(cx - 1, cy + 3), (cx - 1, cy + 6)], fill=K)
    d.line([(cx + 1, cy + 3), (cx + 1, cy + 6)], fill=K)


def draw_snack(d, phase):
    """Sanduiche apoiado no peitilho branco, sumindo mordida a mordida.
    Fica na altura do peito (nao das patas) para o marrom contrastar."""
    w = (10, 7, 4)[phase]
    d.rectangle([15, 22, 15 + w, 29], fill=BR, outline=K)
    d.rectangle([15, 24, 15 + w, 25], fill=Y)            # recheio
    d.rectangle([15, 26, 15 + w, 27], fill=L)            # queijo
    for cx, cy in ((12, 33), (27, 32), (24, 34))[:phase + 1]:
        d.point((cx, cy), fill=BR)                       # migalhas


# ------------------------------------------------------- caminhada (perfil) --
def draw_walk(d, phase):
    """Mike de perfil, virado para a direita, ciclo de 4 quadros.
    Ordem de desenho: cauda -> pernas -> corpo -> cabeca, para tudo se encaixar."""
    top = 16 + (0, 1, 0, 1)[phase]          # sobe/desce 1px = passada
    legs = {                                 # x das (traseiras), (dianteiras)
        0: ((10, 15), (21, 26)),
        1: ((9, 17), (20, 27)),
        2: ((11, 14), (22, 25)),
        3: ((12, 16), (19, 27)),
    }[phase]

    # Nessa escala formas retangulares leem melhor que elipses, e o branco
    # precisa ser usado com parcimonia: se sobrar, vira um borrao so.

    # cauda, atras de tudo
    tail = [(11, top + 5), (6, top + 3), (4, top - 4)]
    d.line(tail, fill=K, width=5, joint="curve")
    d.line(tail, fill=F, width=3, joint="curve")

    # pernas: traseiras mais escuras para dar profundidade
    for grp, shade in ((legs[0], D), (legs[1], F)):
        for lx in grp:
            d.rectangle([lx - 1, top + 8, lx + 1, top + 13], fill=shade, outline=K)
            d.rectangle([lx - 2, top + 12, lx + 2, top + 14], fill=L, outline=K)

    # corpo
    d.rounded_rectangle([10, top, 27, top + 10], 4, fill=F, outline=K)
    d.rectangle([14, top + 8, 24, top + 9], fill=WS)           # barriga (faixa fina)

    # cabeca, desenhada depois do corpo para o contorno separar as duas
    d.rounded_rectangle([24, top - 4, 35, top + 6], 3, fill=F, outline=K)
    d.polygon([(25, top - 3), (27, top - 10), (31, top - 3)], fill=F, outline=K)
    d.polygon([(27, top - 4), (27, top - 7), (29, top - 4)], fill=P)
    d.rectangle([31, top + 2, 34, top + 5], fill=L)            # focinho
    d.point((35, top + 3), fill=P)                             # narizinho
    d.rectangle([28, top - 1, 28, top], fill=G)                # olho
    d.line([(34, top + 2), (38, top + 1)], fill=L)             # bigodes
    d.line([(34, top + 3), (38, top + 5)], fill=L)


# ---------------------------------------------------------------- frames ----
def build(mood, phase):
    img = new_frame()
    d = ImageDraw.Draw(img)

    if mood == "sleep":
        # respiracao: 0,1,0  +  Zzz subindo
        squash = (0, 1, 0)[phase]
        draw_tail(d, (0, 2, 0)[phase])
        draw_body(d, squash)
        draw_ears(d, droop=2)
        draw_head(d)
        draw_muzzle(d, "sleep")
        draw_eyes(d, "closed")
        draw_zzz(d, phase)

    elif mood == "calm":
        # 0 parado | 1 olhando de lado | 2 piscando | 3 orelha mexendo
        draw_tail(d, (0, 1, 0, 2)[phase])
        draw_body(d)
        draw_ears(d, droop=1 if phase == 3 else 0)
        draw_head(d)
        draw_muzzle(d, "smile")
        draw_eyes(d, "happy" if phase == 2 else "open",
                  look=(0, -1, 0, 1)[phase])

    elif mood == "busy":
        draw_tail(d, (2, 3, 5)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "flat")
        draw_eyes(d, "wide", look=(-1, 0, 1)[phase])

    elif mood == "hot":
        draw_tail(d, (1, 2, 1)[phase])
        draw_body(d, squash=1)
        draw_ears(d, droop=1)
        draw_head(d)
        draw_muzzle(d, "tongue")
        draw_eyes(d, "half")
        draw_sweat(d, 2, phase)

    elif mood == "panic":
        draw_tail(d, (3, 1, 4)[phase])
        draw_body(d)
        draw_ears(d, droop=2)
        draw_head(d)
        draw_muzzle(d, "open")
        draw_eyes(d, "wide", look=0)
        draw_sweat(d, 3, phase)
        draw_angry_marks(d)

    elif mood == "scared":
        # pelo em pe, cauda arrepiada, pupila minuscula, "!" dos dois lados
        draw_tail(d, 4, puffed=True)
        draw_body(d)
        draw_ears(d, droop=3)
        draw_head(d)
        draw_spikes(d, jitter=phase)
        draw_muzzle(d, "open")
        draw_eyes(d, "tiny", look=(0, -1, 1)[phase])
        draw_exclaim(d, phase)

    elif mood == "angry":
        draw_tail(d, (5, 2, 5)[phase])
        draw_body(d)
        draw_ears(d, droop=3)
        draw_head(d)
        draw_muzzle(d, "hiss" if phase == 1 else "frown")
        draw_eyes(d, "angry", look=(-1, 0, 1)[phase])
        draw_angry_marks(d)

    elif mood == "happy":
        # pulinho: o corpo sobe 2px no quadro do meio
        draw_tail(d, 4)
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "grin")
        draw_eyes(d, "happy")

    elif mood == "curious":
        draw_tail(d, (1, 0)[phase])
        draw_body(d)
        draw_ears(d, droop=0 if phase == 0 else 1)
        draw_head(d)
        draw_muzzle(d, "smile")
        draw_eyes(d, "open", look=1)
        draw_question(d, phase)

    elif mood == "netheavy":
        # rede pesada (escala do "curious"): 4 quadros trocando -- ponto de
        # interrogacao, orelha em pe olhando pro canto, e o roteador na pata
        # com a outra na cabeca (2 quadros, coçando de confuso)
        if phase == 0:
            draw_tail(d, 1)
            draw_body(d)
            draw_ears(d, droop=0)
            draw_head(d)
            draw_muzzle(d, "smile")
            draw_eyes(d, "open", look=1)
            draw_question(d, 0)
        elif phase == 1:
            draw_tail(d, 0)
            draw_body(d)
            draw_ears(d, droop=0)
            draw_head(d)
            draw_muzzle(d, "flat")
            draw_eyes(d, "wide", look=-1)
        else:
            draw_tail(d, 2)
            draw_body(d)
            draw_ears(d, droop=1)
            draw_head(d)
            draw_muzzle(d, "open" if phase == 3 else "flat")
            draw_eyes(d, "half")
            draw_router(d, phase)
            draw_head_scratch(d, phase)

    elif mood == "coffee":
        draw_tail(d, (0, 1, 0)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "smile")
        draw_eyes(d, "happy" if phase == 1 else "half")
        draw_coffee(d, phase)

    elif mood == "smoke":
        draw_tail(d, (1, 2, 1)[phase])
        draw_body(d)
        draw_ears(d, droop=1)
        draw_head(d)
        draw_muzzle(d, "flat")
        draw_eyes(d, "half", look=(0, 1, -1)[phase])
        draw_cigarette(d, phase)

    elif mood == "fish":
        draw_tail(d, (0, 2, 4)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "grin" if phase == 2 else "smile")
        draw_eyes(d, "wide" if phase == 2 else "open", look=1)
        draw_fishing(d, phase)

    elif mood == "snack":
        draw_tail(d, (1, 0, 1)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "grin" if phase == 1 else "smile")
        draw_eyes(d, "happy" if phase == 1 else "open")
        draw_snack(d, phase)

    elif mood == "walk":
        draw_walk(d, phase)

    # ------------------------------------------------- variantes do foco ----
    # Sorteadas ao clicar em "comecar" o pomodoro (ver POMO_FOCUS_MOODS no
    # .ino) -- a mesma cara de sempre ("busy"), ou uma destas 3 fantasias.
    elif mood == "hacker":
        draw_tail(d, (2, 3, 2)[phase])
        draw_body(d)
        draw_ears(d, droop=2)             # quase escondidas pelo capuz
        draw_head(d)
        draw_hoodie(d, phase)
        draw_muzzle(d, "flat")
        draw_eyes(d, "wide", look=(-1, 0, 1)[phase])
        draw_laptop(d, phase)

    elif mood == "biz":
        draw_tail(d, (2, 3, 2)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "flat")
        draw_sunglasses(d)
        draw_suit(d)
        draw_briefcase(d)

    elif mood == "focushappy":
        draw_tail(d, (2, 4, 2)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "grin")
        draw_eyes(d, "happy" if phase == 1 else "open", look=(-1, 0, 1)[phase])

    # ----------------------------------------------- easter egg das 16:20 ---
    elif mood == "high":
        # chapado: olhos vermelhos vesgos, sorriso banguela, bem relaxado
        draw_tail(d, (2, 5, 2)[phase])
        draw_body(d, squash=1)
        draw_ears(d, droop=2)
        draw_head(d)
        draw_muzzle(d, "grin")
        draw_eyes(d, "high")
        draw_blunt(d, phase)

    # ------------------------------------------------------- modo game ------
    elif mood == "game":
        # controle na mao, todo concentrado no jogo
        draw_tail(d, (2, 3, 2)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "open" if phase == 1 else "smile")
        draw_eyes(d, "wide", look=(-1, 0, 1)[phase])
        draw_controller(d, phase)

    elif mood == "gamehot":
        # mesma coisa, mas a placa esquentou: sua e liga o ventilador
        draw_tail(d, (2, 3, 2)[phase])
        draw_body(d, squash=1)
        draw_ears(d, droop=1)
        draw_head(d)
        draw_muzzle(d, "tongue")
        draw_eyes(d, "half")
        draw_controller(d, phase)
        draw_sweat(d, 2, phase)
        draw_fan(d, phase)

    # ---------------------------------------------------- gestos ociosos ----
    # Nao sao humores de verdade (o firmware nunca cai neles via computeMood):
    # o loop principal sorteia um destes de vez em quando para tocar por cima
    # do humor calmo/dormindo, so' para o Mike parecer mais vivo na tela 0/4.
    elif mood == "stretch":
        # espreguicando: peito afunda, boca entreaberta no auge do alongamento
        draw_tail(d, (2, 4, 2)[phase])
        draw_body(d, squash=(0, 2, 1)[phase])
        draw_ears(d, droop=1)
        draw_head(d)
        draw_muzzle(d, "open" if phase == 1 else "flat")
        draw_eyes(d, "closed" if phase == 1 else "half")

    elif mood == "yawn":
        draw_tail(d, (0, 1, 0)[phase])
        draw_body(d)
        draw_ears(d, droop=(1, 2, 1)[phase])
        draw_head(d)
        draw_muzzle(d, "open" if phase == 1 else "flat")
        draw_eyes(d, "closed" if phase == 1 else "half")

    elif mood == "groom":
        draw_tail(d, (0, 1, 0)[phase])
        draw_body(d)
        draw_ears(d, droop=1)
        draw_head(d)
        draw_muzzle(d, "smile")
        draw_eyes(d, "half")
        draw_paw_wash(d, phase)

    elif mood == "peek":
        # vira a cabeca para o lado como se tivesse ouvido algo, e volta
        draw_tail(d, (1, 5, 1)[phase])
        draw_body(d)
        draw_ears(d, droop=0)
        draw_head(d)
        draw_muzzle(d, "smile")
        draw_eyes(d, "open", look=(-1, 1, 0)[phase])
        if phase == 1:
            draw_question(d, 0)

    # deslocamento vertical (pulo do "happy", respiracao do "calm",
    # afundada do "stretch")
    dy = 0
    if mood == "happy":
        dy = (0, -3, -1)[phase]
    if mood == "stretch":
        dy = (0, 3, 1)[phase]
    if dy:
        moved = new_frame()
        moved.paste(img, (0, dy))
        img = moved

    return img


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

# Gestos ociosos (indices em MOODS/MOOD_* que o firmware sorteia por cima do
# humor calmo/dormindo -- ver GESTURE_MOODS no .ino). Ficam no fim da lista
# de propósito: assim os indices dos humores "de verdade" (0..13) nao mudam
# se algum gesto novo for adicionado.
GESTURES = ["stretch", "yawn", "groom", "peek"]


def to_4bpp(img):
    px = img.load()
    out = bytearray()
    for y in range(H):
        for x in range(0, W, 2):
            hi = px[x, y] & 0x0F
            lo = px[x + 1, y] & 0x0F
            out.append((hi << 4) | lo)
    return out


def main():
    root = os.path.join(os.path.dirname(__file__), "..")
    frames, index = [], []
    for m in MOODS:
        start = len(frames)
        for p in range(PHASES[m]):
            frames.append((m, p, build(m, p)))
        index.append((m, start, PHASES[m]))

    # ---- preview ----
    sheet = Image.new("RGB", (W * SCALE_PREVIEW * len(frames), H * SCALE_PREVIEW), (24, 26, 32))
    for i, (m, p, im) in enumerate(frames):
        rgb = im.convert("RGB")
        mask = im.point(lambda v: 0 if v == 0 else 255, mode="1")
        big = rgb.resize((W * SCALE_PREVIEW, H * SCALE_PREVIEW), Image.NEAREST)
        bigmask = mask.resize((W * SCALE_PREVIEW, H * SCALE_PREVIEW), Image.NEAREST)
        sheet.paste(big, (i * W * SCALE_PREVIEW, 0), bigmask)
    os.makedirs(os.path.join(root, "preview"), exist_ok=True)
    sheet.save(os.path.join(root, "preview", "mike_frames.png"))

    # ---- header ----
    lines = []
    lines.append("// mike_sprites.h - GERADO POR tools/gen_mike.py, nao editar a mao")
    lines.append("#pragma once")
    lines.append("#include <Arduino.h>")
    lines.append("")
    lines.append(f"#define MIKE_W {W}")
    lines.append(f"#define MIKE_H {H}")
    lines.append(f"#define MIKE_FRAMES {len(frames)}")
    lines.append(f"#define MIKE_BYTES_PER_FRAME {W * H // 2}")
    lines.append("")
    lines.append("// paleta RGB565 (indice 0 = transparente)")
    lines.append("static const uint16_t MIKE_PAL[16] PROGMEM = {")
    vals = []
    for r, g, b in PALETTE:
        vals.append("0x%04X" % (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))
    lines.append("  " + ", ".join(vals))
    lines.append("};")
    lines.append("")
    lines.append("// humores")
    for i, (m, start, n) in enumerate(index):
        lines.append(f"#define MOOD_{m.upper()} {i}")
    lines.append(f"#define MOOD_COUNT {len(index)}")
    lines.append("")
    lines.append("static const uint8_t MIKE_MOOD_START[MOOD_COUNT] = {" +
                 ", ".join(str(s) for _, s, _ in index) + "};")
    lines.append("static const uint8_t MIKE_MOOD_LEN[MOOD_COUNT]   = {" +
                 ", ".join(str(n) for _, _, n in index) + "};")
    lines.append("")
    lines.append("// gestos ociosos: indices de MOOD_* que o firmware sorteia por cima do")
    lines.append("// humor calmo/dormindo, so' para variar a animacao (ver mike_monitor.ino)")
    lines.append(f"#define MIKE_GESTURE_COUNT {len(GESTURES)}")
    lines.append("static const uint8_t MIKE_GESTURES[MIKE_GESTURE_COUNT] = {" +
                 ", ".join(f"MOOD_{g.upper()}" for g in GESTURES) + "};")
    lines.append("")
    lines.append("// pixels: 4 bits por pixel, 2 pixels por byte, linha a linha")
    lines.append("static const uint8_t MIKE_DATA[MIKE_FRAMES][MIKE_BYTES_PER_FRAME] PROGMEM = {")
    for m, p, im in frames:
        data = to_4bpp(im)
        body = ", ".join("0x%02X" % b for b in data)
        wrapped = textwrap.wrap(body, 96)
        lines.append(f"  {{ // {m} #{p}")
        for wl in wrapped:
            lines.append("    " + wl)
        lines.append("  },")
    lines.append("};")
    lines.append("")

    out = os.path.join(root, "firmware", "mike_monitor", "mike_sprites.h")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write("\n".join(lines))
    print(f"ok: {len(frames)} frames -> {out}")
    print(f"    preview -> preview/mike_frames.png")


if __name__ == "__main__":
    main()
