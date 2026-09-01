#!/usr/bin/env python3
"""
_hoist_prototypes.py - Reproduz o pre-processamento que o Arduino/PlatformIO faz
no .ino: gerar prototipos de todas as funcoes e injeta-los NO TOPO do arquivo.

E por causa disso que um tipo declarado no meio do .ino e usado como parametro
de funcao quebra o build ("'Rect' does not name a type"): o prototipo aparece
antes da declaracao do tipo. Tipos usados em assinaturas tem que vir de header.

Uso (normalmente via tools/check_firmware.sh):
    python3 tools/_hoist_prototypes.py entrada.ino saida.cpp
"""
import re
import sys

SIG = re.compile(
    r'^((?:static\s+|const\s+)*[A-Za-z_][\w:*&\s]*?[\s*&]+[A-Za-z_]\w*\s*\([^;{]*\))\s*\{\s*$')
KEYWORDS = {'if', 'for', 'while', 'switch', 'else', 'do',
            'struct', 'enum', 'class', 'return'}


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src = open(sys.argv[1]).read()
    lines = src.split('\n')

    protos, first = [], None
    for i, ln in enumerate(lines):
        m = SIG.match(ln)
        if not m:
            continue
        sig = m.group(1)
        name = re.search(r'([A-Za-z_]\w*)\s*\(', sig).group(1)
        if name in KEYWORDS:
            continue
        protos.append(sig + ';')
        if first is None:
            first = i

    if first is None:
        sys.exit('nenhuma funcao de nivel superior encontrada')

    out = (lines[:first]
           + ['// ---- prototipos injetados (simula o build do .ino) ----']
           + protos + [''] + lines[first:])
    with open(sys.argv[2], 'w') as f:
        f.write('\n'.join(out) + '\nSerialC Serial;\n')
    print(f'{len(protos)} prototipos injetados antes da linha {first + 1}')


if __name__ == '__main__':
    main()
