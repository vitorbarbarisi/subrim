#!/usr/bin/env python3
"""Gera subrim_icon.png no padrão dos ícones reais do macOS.

Rode a partir da raiz do repo:  python3 tools/make_icon.py

Três coisas medidas dos ícones do sistema (Calculator/Notes/Reminders, todos
idênticos) em vez de chutadas:

1. Ícones do macOS NÃO são de borda a borda. Num canvas de 1024pt o corpo tem
   818pt, deixando 103pt de padding transparente por lado. Um PNG que preenche
   o canvas inteiro aparece visivelmente maior que todos os vizinhos no Dock.
2. O canto é o "squircle" da Apple, não um arco circular. Um retângulo
   arredondado circular com a mesma curvatura no meio ainda erra nos extremos:
   medido na horizontal, no topo do corpo, o recuo do sistema é 261pt onde um
   arco circular dá 177pt. Uma superelipse de expoente 5 acompanha de perto a
   curva real (recuo 106/46/15 contra 101/46/13 do sistema a 20/60/120pt
   abaixo do topo).
3. A Apple assa uma sombra suave no próprio asset, então um ícone sem sombra
   parece chapado ao lado dos vizinhos. A sombra do sistema alcança 31pt acima
   e 47pt abaixo do corpo — ou seja, deslocada para baixo — com pico perto de
   16% de alpha logo fora da borda.

Igual ao tools/make_icon.py do /dev/visim; muda só a letra, a cor e a saída.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS = 1024
BODY_INSET = 103          # medido: corpo de 818pt num canvas de 1024pt
SQUIRCLE_EXPONENT = 5.0   # superelipse ajustada ao canto contínuo da Apple
SQUIRCLE_POINTS = 3000    # resolução do contorno antes do downsample
SUPERSAMPLE = 3           # PIL não faz antialias de formas; desenha grande e reduz

# Ajustados à sombra dos ícones do sistema, não no olhômetro. Ver nota 3.
SHADOW_OFFSET = 8         # deslocamento para baixo, em pt de canvas
SHADOW_BLUR = 16          # sigma da gaussiana, em pt de canvas
SHADOW_OPACITY = 0.28     # alpha da forma antes do blur

LETTER = "S"
LETTER_FILL = "#ffffff"
# Violeta da mesma paleta do azul do Visim (open-color violet-7 x blue-7), para
# os dois apps ficarem distinguíveis lado a lado no Dock.
BODY_FILL = "#7048e8"
CAP_HEIGHT_RATIO = 0.46   # altura da tinta da letra como fração do corpo

FONT_CANDIDATES = (
    ("/System/Library/Fonts/SFNSRounded.ttf", "Bold"),
    ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", None),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", None),
    ("/System/Library/Fonts/Helvetica.ttc", None),
)

OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "subrim_icon.png")


def load_font(size: int):
    """Primeiro candidato disponível, pedindo a variação Bold quando o arquivo
    é uma fonte variável que a oferece."""
    for path, variation in FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            continue
        if variation:
            try:
                font.set_variation_by_name(variation)
            except Exception:
                pass  # não é fonte variável, ou não tem essa instância nomeada
        return font, os.path.basename(path)
    return ImageFont.load_default(), "default"


def ink_box(draw, text, font):
    """Caixa dos pixels desenhados, que é o que precisa ficar opticamente
    centralizado — e não a caixa de ascender/descender da fonte."""
    return draw.textbbox((0, 0), text, font=font)


def squircle(center: float, half: float, exponent: float, points: int):
    """Contorno de |x/half|^n + |y/half|^n = 1, na parametrização padrão da
    superelipse. O canto do ícone da Apple é essa forma, não um arco circular."""
    power = 2.0 / exponent
    out = []
    for i in range(points):
        angle = 2.0 * math.pi * i / points
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        x = math.copysign(abs(cos_a) ** power, cos_a)
        y = math.copysign(abs(sin_a) ** power, sin_a)
        out.append((center + half * x, center + half * y))
    return out


def build() -> Image.Image:
    scale = SUPERSAMPLE
    size = CANVAS * scale
    inset = BODY_INSET * scale

    half = (size - 2 * inset) / 2.0
    outline = squircle(size / 2.0, half, SQUIRCLE_EXPONENT, SQUIRCLE_POINTS)

    # Sombra: a mesma silhueta, empurrada para baixo e borrada, sob o corpo.
    # RGB preto com alpha vindo da máscara borrada.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(
        [(x, y + SHADOW_OFFSET * scale) for x, y in outline],
        fill=int(255 * SHADOW_OPACITY),
    )
    mask = mask.filter(ImageFilter.GaussianBlur(SHADOW_BLUR * scale))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow.putalpha(mask)

    body = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(body).polygon(outline, fill=BODY_FILL)

    image = Image.alpha_composite(shadow, body)
    draw = ImageDraw.Draw(image)

    body = size - 2 * inset
    target_height = body * CAP_HEIGHT_RATIO

    # A altura da tinta escala linearmente com o corpo da fonte, então uma
    # única correção acerta o tamanho.
    probe_size = int(target_height)
    font, family = load_font(probe_size)
    box = ink_box(draw, LETTER, font)
    measured = box[3] - box[1]
    if measured > 0:
        font, family = load_font(max(1, round(probe_size * target_height / measured)))
        box = ink_box(draw, LETTER, font)

    ink_w = box[2] - box[0]
    ink_h = box[3] - box[1]
    # Desconta -box[:2] para a tinta cair exatamente onde queremos.
    x = (size - ink_w) / 2 - box[0]
    y = (size - ink_h) / 2 - box[1]
    draw.text((x, y), LETTER, fill=LETTER_FILL, font=font)

    print(f"fonte: {family}  |  altura do {LETTER}: {ink_h / scale:.0f}pt "
          f"({ink_h / body:.0%} do corpo)")
    return image.resize((CANVAS, CANVAS), Image.LANCZOS)


if __name__ == "__main__":
    icon = build()
    icon.save(OUT_PATH, "PNG")
    print(f"corpo: {CANVAS - 2 * BODY_INSET}pt em canvas de {CANVAS}pt "
          f"({(CANVAS - 2 * BODY_INSET) / CANVAS:.1%}), "
          f"squircle n={SQUIRCLE_EXPONENT:g}")
    print(f"gravado: {OUT_PATH}")
