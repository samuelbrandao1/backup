#!/bin/bash

# Pacotes oficiais
sudo pacman -Syu --needed - < packages/pacman.txt

# Pacotes da AUR
yay -Syu --needed - < packages/aur.txt
