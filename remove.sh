#!/bin/bash

if [ -s packages/remove.txt ]; then
    sudo pacman -Rns $(cat packages/remove.txt)
fi
