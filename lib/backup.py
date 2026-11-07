#!/usr/bin/env python3
"""Portable, explicit dotfile snapshots and Arch package setup (stdlib only)."""
import argparse
import hashlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()


def lines(path):
    if not path.exists():
        return []
    return list(dict.fromkeys(s.split('#', 1)[0].strip() for s in path.read_text().splitlines()
                             if s.split('#', 1)[0].strip()))


def relative(value):
    p = Path(value)
    if p.is_absolute() or '..' in p.parts or not p.parts or p == Path('.'):
        raise ValueError(f'Caminho relativo inválido: {value}')
    # Never collect credentials or internal bookkeeping through the manifest.
    if p.parts[0] in {'.ssh', '.gnupg', '.aws', '.git', '.local', '.cache', '.backup-rollback'}:
        raise ValueError(f'Caminho reservado/privado: {value}')
    return p


def paths(profile):
    result = [relative(x) for x in lines(ROOT / 'profiles/common.txt') + lines(ROOT / f'profiles/{profile}.txt')]
    result = sorted(set(result), key=lambda p: (len(p.parts), str(p)))
    return [p for p in result if not any(parent in result for parent in p.parents if parent != Path('.'))]


def safe_target(base, rel):
    target = base / rel
    if not target.parent.resolve().is_relative_to(base.resolve()):
        raise ValueError(f'Diretório pai aponta para fora do destino: {rel}')
    return target


def check_tree(path, *, follow_links=False, ancestors=(), store=None):
    if path.is_symlink() and not follow_links:
        raise ValueError(f'Link simbólico não permitido no snapshot: {path}')
    if follow_links:
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(f'Link quebrado, cíclico ou inacessível: {path}') from error
        if not resolved.is_relative_to(HOME.resolve()):
            raise ValueError(f'Destino aponta para fora do HOME: {path}')
        relative(str(resolved.relative_to(HOME.resolve())))
        if store is not None and store.is_relative_to(resolved) and resolved.is_dir():
            raise ValueError(f'O destino do backup está dentro dos arquivos selecionados: {path}')
        if resolved in ancestors:
            raise ValueError(f'Ciclo de diretórios por link simbólico: {path}')
        ancestors = (*ancestors, resolved)
    if path.is_dir():
        for child in path.iterdir():
            check_tree(child, follow_links=follow_links, ancestors=ancestors, store=store)
    elif not path.is_file():
        raise ValueError(f'Arquivo especial não suportado: {path}')


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def checksums(base, selected):
    result = {}
    for rel in selected:
        source = base / rel
        files = sorted(source.rglob('*')) if source.is_dir() else [source]
        for item in files:
            if item.is_file():
                digest = hashlib.sha256()
                with item.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                result[str(item.relative_to(base))] = digest.hexdigest()
    return result


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]


def run(argv, dry=False):
    print('+', ' '.join(map(str, argv)), flush=True)
    if not dry:
        subprocess.run(argv, check=True)


def packages(profile, kind):
    items = lines(ROOT / f'packages/{kind}.txt') + lines(ROOT / f'profiles/{profile}.{kind}.txt')
    for item in items:
        if not re.fullmatch(r'[a-zA-Z0-9@_+][a-zA-Z0-9@_.+:-]*', item):
            raise ValueError(f'Nome de pacote inválido: {item}')
    return sorted(set(items))


def install(args):
    if os.geteuid() == 0:
        raise ValueError('Execute como usuário comum; sudo será usado apenas pelo pacman.')
    official, aur = packages(args.profile, 'pacman'), packages(args.profile, 'aur')
    if not args.dry_run:
        for tool in ['pacman', 'sudo'] + (['yay'] if aur else []):
            if not shutil.which(tool):
                raise ValueError(f'Instale {tool} antes de continuar (doctor mostra dependências).')
    if official:
        run(['sudo', 'pacman', '-Syu', '--needed', '--', *official], args.dry_run)
    if aur:
        run(['yay', '-S', '--needed', '--', *aur], args.dry_run)


def snapshot(args):
    selected = paths(args.profile)
    store = args.store.expanduser().resolve()
    available = []
    for rel in selected:
        source = safe_target(HOME, rel)
        if not source.exists() and not source.is_symlink():
            print(f'Ausente, ignorado: {rel}')
            continue
        check_tree(source, follow_links=True, store=store)
        if source.is_symlink():
            print(f'Link: {rel} → {source.resolve()} (copiar conteúdo)')
        available.append(rel)
    if not available:
        raise ValueError('Nenhum arquivo selecionado existe. Edite profiles/*.txt.')
    for rel in available:
        print(f'Backup: {rel}')
    if args.dry_run:
        return
    store = args.store.expanduser().resolve()
    if any(store.is_relative_to((HOME / p).resolve()) for p in available):
        raise ValueError('O destino do backup não pode estar dentro dos arquivos selecionados.')
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = store / stamp()
    destination.mkdir(mode=0o700)
    # An incomplete snapshot has no manifest and cannot be restored.
    for rel in available:
        copy(HOME / rel, destination / 'files' / rel)
    metadata = dict(version=1, profile=args.profile, host=os.uname().nodename,
                    created=dt.datetime.now(dt.timezone.utc).isoformat(), paths=list(map(str, available)),
                    sha256=checksums(destination / 'files', available))
    if shutil.which('pacman'):
        for filename, flags in [('pacman.txt', '-Qqen'), ('aur.txt', '-Qqem')]:
            inventory = subprocess.run(['pacman', flags], capture_output=True, text=True)
            if inventory.returncode == 0:
                (destination / filename).write_text(inventory.stdout)
    (destination / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Snapshot criado: {destination}')


def restore(args):
    source = args.snapshot.expanduser().resolve()
    meta = json.loads((source / 'manifest.json').read_text())
    if meta.get('version') != 1 or not isinstance(meta.get('paths'), list) or not meta['paths']:
        raise ValueError('Manifesto inválido ou versão incompatível.')
    selected = [relative(x) for x in meta['paths']]
    if len(set(selected)) != len(selected) or any(p in q.parents for p in selected for q in selected if p != q):
        raise ValueError('Manifesto contém caminhos duplicados ou sobrepostos.')
    for rel in selected:
        check_tree(safe_target(source / 'files', rel))
        safe_target(HOME, rel)
        print(f'Restaurar: {rel}')
    if 'sha256' in meta and checksums(source / 'files', selected) != meta['sha256']:
        raise ValueError('Integridade do snapshot inválida (SHA-256).')
    if args.dry_run:
        return
    rollback = HOME / '.backup-rollback' / stamp()
    rollback.mkdir(parents=True, mode=0o700)
    journal = []
    try:
        for rel in selected:
            target = HOME / rel
            existed = target.exists() or target.is_symlink()
            if existed:
                saved = rollback / 'files' / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                check_tree(target, follow_links=True)
                copy(target, saved)
                original = rollback / 'originals' / rel
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(original))
            journal.append((rel, existed))
            copy(source / 'files' / rel, target)
    except Exception:
        for rel, existed in reversed(journal):
            target = HOME / rel
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            if existed:
                shutil.move(str(rollback / 'originals' / rel), str(target))
        raise
    old = [str(rel) for rel, existed in journal if existed]
    (rollback / 'manifest.json').write_text(json.dumps(dict(version=1, paths=old), indent=2) + '\n')
    print(f'Restaurado. Arquivos anteriores: {rollback}')


def main():
    parser = argparse.ArgumentParser(description='Backup e instalação entre laptop e desktop.')
    parser.add_argument('command', choices=['save', 'restore', 'install', 'setup', 'list', 'doctor', 'remove'])
    parser.add_argument('snapshot', nargs='?', type=Path, help='Diretório do snapshot para restore')
    parser.add_argument('--profile', choices=['laptop', 'desktop'], default='laptop')
    parser.add_argument('--store', type=Path, default=ROOT / 'snapshots', help='Destino dos snapshots')
    parser.add_argument('--dry-run', action='store_true', help='Mostrar ações sem modificar arquivos')
    args = parser.parse_args()
    if args.command == 'restore' and not args.snapshot:
        parser.error('restore exige o caminho de um snapshot')
    if args.snapshot and args.command != 'restore':
        parser.error('snapshot só é aceito por restore')
    if args.command == 'save':
        snapshot(args)
    elif args.command == 'restore':
        restore(args)
    elif args.command in ['install', 'setup']:
        install(args)
        if args.command == 'setup':
            run(['git', 'config', '--global', 'delta.navigate', 'true'], args.dry_run)
            run(['git', 'config', '--global', 'delta.side-by-side', 'true'], args.dry_run)
            run(['git', 'config', '--global', 'delta.line-numbers', 'true'], args.dry_run)
    elif args.command == 'remove':
        items = packages(args.profile, 'remove')
        if items:
            run(['sudo', 'pacman', '-Rns', '--', *items], args.dry_run)
        else:
            print('Lista de remoção vazia.')
    elif args.command == 'list':
        for manifest in sorted(args.store.expanduser().glob('*/manifest.json')):
            print(manifest.parent)
    elif args.command == 'doctor':
        missing = []
        for tool in ['git', 'pacman', 'sudo', 'yay']:
            found = shutil.which(tool)
            print(f'{tool}: {found or "AUSENTE"}')
            if not found:
                missing.append(tool)
        for profile in ['laptop', 'desktop']:
            print(f'{profile}: {len(paths(profile))} caminhos, {len(packages(profile, "pacman"))} pacotes oficiais, {len(packages(profile, "aur"))} AUR')
        if missing:
            return 1
    return 0


if __name__ == '__main__':
    os.umask(0o077)
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Erro: {error}', file=sys.stderr)
        sys.exit(1)
