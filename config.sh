#!/usr/bin/env bash
set -euo pipefail
for setting in navigate side-by-side line-numbers; do
    git config --global "delta.$setting" true
done
printf '%s\n' 'Configuração Git aplicada. Para autenticar no GitHub: gh auth login'
