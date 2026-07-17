#!/bin/bash

# Pacotes oficiais
sudo pacman -S --needed - < packages/pacman.txt

# Pacotes da AUR
yay -S --needed - < packages/aur.txt
