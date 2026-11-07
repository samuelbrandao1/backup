#!/usr/bin/env python3
"""Compatibilidade: versões antigas de apply reiniciam por este caminho após git pull."""
import os
from pathlib import Path
import sys

args = ['--local' if value == '--apply-local' else value for value in sys.argv[1:]]
os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve().parents[1] / 'backup'), *args])
