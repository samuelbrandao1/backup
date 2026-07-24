#!/usr/bin/env bash

set -e

echo "==> Installing official packages..."
sudo pacman -Syu --needed - < packages/pacman.txt

echo "==> Installing AUR packages..."
yay -Syu --needed - < packages/aur.txt

echo "==> Installing Homebrew..."
if ! command -v brew >/dev/null 2>&1; then
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Carrega o brew para esta sessão
if [ -f /home/linuxbrew/.linuxbrew/bin/brew ]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi

echo "==> Installing Oh My Zsh..."
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    RUNZSH=no CHSH=no KEEP_ZSHRC=yes sh -c \
        "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
fi

ZSH_CUSTOM="${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}"
PLUGIN_DIR="$ZSH_CUSTOM/plugins"

mkdir -p "$PLUGIN_DIR"

echo "==> Installing zsh-autosuggestions..."
if [ ! -d "$PLUGIN_DIR/zsh-autosuggestions" ]; then
    git clone https://github.com/zsh-users/zsh-autosuggestions \
        "$PLUGIN_DIR/zsh-autosuggestions"
fi

echo "==> Installing zsh-syntax-highlighting..."
if [ ! -d "$PLUGIN_DIR/zsh-syntax-highlighting" ]; then
    git clone https://github.com/zsh-users/zsh-syntax-highlighting \
        "$PLUGIN_DIR/zsh-syntax-highlighting"
fi

echo "==> Installing zsh-vi-mode..."
if [ ! -d "$PLUGIN_DIR/zsh-vi-mode" ]; then
    git clone https://github.com/jeffreytse/zsh-vi-mode \
        "$PLUGIN_DIR/zsh-vi-mode"
fi

echo "==> Installing Atuin..."
if ! command -v atuin >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -LsSf https://setup.atuin.sh | sh
fi

echo "==> Setting Zsh as default shell..."
if [ "$SHELL" != "$(which zsh)" ]; then
    chsh -s "$(which zsh)"
fi

echo
echo "Installation complete."
echo "Log out and log back in for shell changes to take effect."
