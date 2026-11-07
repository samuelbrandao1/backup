#!/usr/bin/env python3
"""Two-command GitHub dotfile sync. No third-party Python dependencies."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import backup as core

ROOT = core.ROOT
HOME = core.HOME
MANAGED = ['backup', 'lib', 'tests', 'README.md', '.gitignore', 'files.txt',
           'dotfiles', 'packages', 'profiles', 'install.sh', 'config.sh', 'remove.sh']


def git(*args, capture=False):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def selected():
    items = sorted(set(core.relative(x) for x in core.lines(ROOT / 'files.txt')),
                   key=lambda p: (len(p.parts), str(p)))
    return [p for p in items if not any(parent in items for parent in p.parents)]


def clean():
    if git('status', '--porcelain', capture=True).strip():
        raise ValueError('Há alterações locais no repositório. Execute ./backup save nesta máquina primeiro.')


def scan_secrets(directory):
    patterns = [rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
                rb'gh[pousr]_[A-Za-z0-9]{20,}', rb'github_pat_[A-Za-z0-9_]{20,}',
                rb'AKIA[0-9A-Z]{16}', rb'sk-(?:proj-)?[A-Za-z0-9_-]{24,}',
                rb'(?im)^\s*(?:export\s+)?[\w]*(?:TOKEN|PASSWORD|SECRET|API_KEY)\s*=\s*[\'"]?(?!\$)[A-Za-z0-9_+/=-]{12,}']
    for path in directory.rglob('*'):
        if path.is_file():
            data = path.read_bytes()
            if any(re.search(pattern, data) for pattern in patterns):
                raise ValueError(f'Possível segredo em {path.relative_to(directory)}. Remova-o antes de enviar ao GitHub.')


def capture(destination):
    available = []
    for rel in selected():
        source = core.safe_target(HOME, rel)
        if not source.exists() and not source.is_symlink():
            print(f'Ausente, mantendo versão do GitHub se existir: {rel}')
            old = ROOT / 'dotfiles/files' / rel
            if old.exists():
                core.check_tree(old)
                core.copy(old, destination / 'files' / rel)
                available.append(rel)
            continue
        core.check_tree(source, follow_links=True, store=ROOT)
        core.copy(source, destination / 'files' / rel)
        available.append(rel)
        print(f'Configuração: {rel}')
    if not available:
        raise ValueError('Nenhuma configuração encontrada. Confira files.txt.')
    # The original shell config assumes Linuxbrew exists at a fixed location.
    # Make that initialization conditional in the shared copy, leaving HOME untouched.
    zshrc = destination / 'files/.zshrc'
    if zshrc.is_file():
        text = zshrc.read_text()
        original = 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv zsh)"'
        replacement = '[[ ! -x /home/linuxbrew/.linuxbrew/bin/brew ]] || ' + original
        text = re.sub(r'(?m)^' + re.escape(original) + r'$', lambda _: replacement, text)
        zshrc.write_text(text)
    scan_secrets(destination)
    manifest = dict(version=1, paths=list(map(str, available)),
                    sha256=core.checksums(destination / 'files', available))
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def inventory():
    if not shutil.which('pacman'):
        raise ValueError('A sincronização de pacotes exige Arch Linux com pacman.')
    result = {}
    for kind, flags in [('pacman', '-Qqen'), ('aur', '-Qqem')]:
        query = subprocess.run(['pacman', flags], capture_output=True, text=True)
        # pacman exits 1 for an empty query result, too.
        if query.returncode not in (0, 1) or (query.returncode == 1 and query.stderr.strip()):
            raise ValueError(f'Não foi possível listar pacotes: {query.stderr.strip()}')
        items = sorted(set(query.stdout.splitlines()))
        for item in items:
            if not re.fullmatch(r'[a-zA-Z0-9@_+][a-zA-Z0-9@_.+:-]*', item):
                raise ValueError(f'Pacote inválido: {item}')
        result[kind] = '\n'.join(items) + ('\n' if items else '')
    return result


def save(dry=False):
    git('remote', 'get-url', 'origin', capture=True)
    inventories = inventory()
    with tempfile.TemporaryDirectory(prefix='backup-save-') as temporary:
        staging = Path(temporary) / 'dotfiles'
        staging.mkdir()
        capture(staging)
        if dry:
            print('Simulação: coletar pacotes, criar commit e enviar ao GitHub.')
            return
        old = ROOT / 'dotfiles'
        if old.exists():
            shutil.rmtree(old)
        shutil.move(str(staging), str(old))
    for kind, text in inventories.items():
        (ROOT / f'packages/{kind}.txt').write_text(text)
    git('add', '--', *[p for p in MANAGED if (ROOT / p).exists()])
    staged = git('diff', '--cached', '--name-only', capture=True).splitlines()
    if any(not any(p == root or p.startswith(root + '/') for root in MANAGED) for p in staged):
        raise ValueError('Há arquivos de fora do backup no stage do Git. Revise antes de continuar.')
    if staged:
        git('commit', '-m', 'Sincroniza pacotes e configurações')
    # Never merge conflicting configurations automatically or force push.
    git('fetch', 'origin')
    branch = git('branch', '--show-current', capture=True).strip()
    if not branch:
        raise ValueError('Selecione uma branch antes de sincronizar.')
    remote_ref = f'refs/remotes/origin/{branch}'
    exists = subprocess.run(['git', '-C', str(ROOT), 'show-ref', '--verify', '--quiet', remote_ref])
    if exists.returncode == 0:
        relation = git('rev-list', '--left-right', '--count', f'HEAD...{remote_ref}', capture=True).split()
        ahead, behind = map(int, relation)
        if behind:
            if ahead:
                raise ValueError('As duas máquinas têm commits diferentes. Seu backup está salvo localmente; resolva a divergência Git antes de enviar. Nenhum arquivo remoto foi sobrescrito.')
            raise ValueError('O GitHub tem uma versão mais nova. Execute ./backup apply antes de salvar.')
    git('push', '--set-upstream', 'origin', branch)
    print('Pronto. Pacotes e configurações enviados ao GitHub.')


def install_packages(dry=False):
    if not shutil.which('pacman') or not shutil.which('sudo'):
        raise ValueError('apply exige Arch Linux, pacman e sudo.')
    wanted = {}
    for kind in ['pacman', 'aur']:
        wanted[kind] = core.packages('common', kind)
    installed = set(subprocess.run(['pacman', '-Qq'], check=True, capture_output=True, text=True).stdout.splitlines())
    missing = {kind: [p for p in items if p not in installed] for kind, items in wanted.items()}
    if missing['pacman']:
        core.run(['sudo', 'pacman', '-Syu', '--needed', '--', *missing['pacman']], dry)
    if missing['aur']:
        helper = shutil.which('yay') or shutil.which('paru')
        if not helper:
            core.run(['sudo', 'pacman', '-Syu', '--needed', '--', 'base-devel', 'git'], dry)
            if dry:
                print('+ preparar yay com makepkg e instalar pacotes AUR')
                return
            with tempfile.TemporaryDirectory(prefix='backup-yay-') as directory:
                source = Path(directory) / 'yay'
                core.run(['git', 'clone', '--depth=1', 'https://aur.archlinux.org/yay.git', str(source)])
                subprocess.run(['makepkg', '-si'], cwd=source, check=True)
            helper = 'yay'
        core.run([helper, '-S', '--needed', '--', *missing['aur']], dry)


def shell_tools(dry=False):
    zshrc = ROOT / 'dotfiles/files/.zshrc'
    if not zshrc.exists() or 'oh-my-zsh.sh' not in zshrc.read_text():
        return
    targets = [
        (HOME / '.oh-my-zsh', 'https://github.com/ohmyzsh/ohmyzsh.git'),
        (HOME / '.oh-my-zsh/custom/plugins/zsh-autosuggestions', 'https://github.com/zsh-users/zsh-autosuggestions.git'),
        (HOME / '.oh-my-zsh/custom/plugins/zsh-syntax-highlighting', 'https://github.com/zsh-users/zsh-syntax-highlighting.git'),
        (HOME / '.oh-my-zsh/custom/plugins/zsh-vi-mode', 'https://github.com/jeffreytse/zsh-vi-mode.git'),
    ]
    for target, url in targets:
        if not target.exists():
            core.run(['git', 'clone', '--depth=1', url, str(target)], dry)


def apply_local(dry=False):
    # Validate the committed files before installing anything.
    source = ROOT / 'dotfiles'
    meta = json.loads((source / 'manifest.json').read_text())
    items = [core.relative(x) for x in meta['paths']]
    if meta.get('version') != 1 or not items:
        raise ValueError('Backup inválido no repositório. Execute save na máquina de origem.')
    for rel in items:
        core.check_tree(core.safe_target(source / 'files', rel))
        core.safe_target(HOME, rel)
    if core.checksums(source / 'files', items) != meta.get('sha256'):
        raise ValueError('Configurações alteradas sem save. Refaça o save na origem.')
    install_packages(dry)
    shell_tools(dry)
    args = argparse.Namespace(snapshot=source, dry_run=dry)
    core.restore(args)
    print('Pronto. Pacotes e configurações aplicados.' if not dry else 'Simulação concluída.')


def main():
    parser = argparse.ArgumentParser(description='save: enviar para GitHub. apply: baixar e aplicar nesta máquina.')
    parser.add_argument('command', choices=['save', 'apply'])
    parser.add_argument('--dry-run', action='store_true', help='Conferir sem alterar ou enviar')
    parser.add_argument('--apply-local', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == 'save':
        save(args.dry_run)
    elif args.apply_local or args.dry_run:
        apply_local(args.dry_run)
    else:
        clean()
        git('pull', '--ff-only')
        # Run the version just downloaded, rather than the old Python code.
        os.execv(sys.executable, [sys.executable, str(ROOT / 'lib/sync.py'), 'apply', '--apply-local'])


if __name__ == '__main__':
    os.umask(0o077)
    try:
        # flock on the directory prevents concurrent operations, without a lock file.
        lock = os.open(ROOT, os.O_RDONLY)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            main()
        finally:
            os.close(lock)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Erro: {error}', file=sys.stderr)
        sys.exit(1)
