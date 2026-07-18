#!/bin/bash

# Pacotes oficiais
sudo pacman -Syu --needed - < packages/pacman.txt

# Pacotes da AUR
yay -Syu --needed - < packages/aur.txt

# Oh-My-Zsh installation
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
