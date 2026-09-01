#!/usr/bin/env bash
# check_firmware.sh - Confere o firmware sem precisar da placa nem do toolchain
# do ESP32. Compila o .ino contra stubs das bibliotecas, com os prototipos
# hoisted igual o Arduino/PlatformIO faz.
#
# Pega erros de sintaxe, tipo, formato de printf e -- importante -- o caso de
# um tipo declarado no meio do .ino ser usado em assinatura de funcao.
#
# NAO substitui `pio run`: nao valida a API real da TFT_eSPI nem o tamanho do
# binario. E uma rede de seguranca rapida (roda em ~1 s).
#
# Uso:  ./tools/check_firmware.sh
set -euo pipefail

cd "$(dirname "$0")/.."
SRC=firmware/mike_monitor
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cp tools/stubs/*.h "$TMP/"
cp "$SRC"/mike_sprites.h "$SRC"/ui_theme.h "$TMP/"

python3 tools/_hoist_prototypes.py "$SRC/mike_monitor.ino" "$TMP/sketch.cpp"

echo "compilando..."
if g++ -fsyntax-only -std=gnu++17 -Wall -Wextra -Wformat -I"$TMP" "$TMP/sketch.cpp"; then
    echo "OK: firmware passou na checagem"
else
    echo "FALHOU"
    exit 1
fi
