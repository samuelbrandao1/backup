# Laptop e desktop com as mesmas configurações

Na máquina em que você fez mudanças:

```bash
./backup save
```

Na outra máquina:

```bash
./backup apply
```

`save` copia as configurações selecionadas, cria um commit e envia ao GitHub.
`apply` baixa do GitHub, guarda as configurações anteriores, aplica as novas e instala os aplicativos que faltam.

## Primeira vez no outro computador

Requer Arch Linux, Python 3, Git e sudo. Para aplicativos AUR, requer yay ou paru.

```bash
git clone https://github.com/samuelbrandao1/backup.git ~/backup
cd ~/backup
./backup apply
```

O Git precisa estar autenticado para enviar. Se já consegue fazer push neste repositório, não precisa configurar novamente.

## Onde está cada coisa

| Arquivo | Função |
| --- | --- |
| `backup` | Todo o código, dividido em leitura, save, pacotes e apply |
| `files.txt` | Configurações que você quer compartilhar, relativas ao HOME |
| `dotfiles/` | Cópias dessas configurações, versionadas no GitHub |
| `packages/pacman.txt` | Aplicativos dos repositórios oficiais |
| `packages/aur.txt` | Aplicativos AUR |
| `tests/test_backup.py` | Testes com pastas temporárias e Git local |

Para compartilhar uma configuração nova, acrescente o caminho a `files.txt` e execute `save`.
Para compartilhar um programa novo, acrescente o nome à lista de pacotes correspondente e execute `save`.

**As listas de pacotes são intencionais: save não as sobrescreve com todos os pacotes da máquina.** Isso evita levar drivers Intel para um desktop AMD, trocar bootloader ou substituir componentes do Omarchy. O sistema operacional e os drivers ficam sob controle de cada computador.

## Conflitos de pacotes

O comando consulta `pacman -T`: variantes que fornecem o mesmo pacote também contam como instaladas. Não tenta substituir `neovim-git` por `neovim`, por exemplo, quando a variante declara esse fornecimento.

As configurações são aplicadas antes da instalação. Se pacman/yay falhar, o erro completo aparece e o comando termina com falha; ele não informa sucesso nem força remoções. As configurações continuam aplicadas. Para resolver um conflito específico, são necessários os nomes dos pacotes que aparecem nas linhas anteriores a “conflicting dependencies”. Após corrigir, execute `apply` novamente.

## Comportamento e recuperação

- Faça `apply` antes de começar a editar na outra máquina; faça `save` ao terminar. Históricos divergentes são recusados pelo Git, sem force push.
- Diretórios selecionados são substituídos por inteiro. Os anteriores ficam em `~/.backup-rollback/DATA/`, com os mesmos caminhos relativos ao HOME e preservando os links originais. O caminho aparece no terminal. Para recuperação manual, mova o arquivo atual para outro local e recoloque a cópia anterior no caminho original.
- `save` segue links dentro do HOME e envia arquivos reais. Rejeita ciclos, links quebrados, arquivos especiais e destinos privados ou fora do HOME. Caminhos ausentes mantêm a cópia compartilhada anterior, se existir.
- Somente os caminhos de `files.txt` são sincronizados. Não inclua credenciais. A checagem de padrões comuns de segredos é limitada; use repositório privado para dados pessoais.
- O Zsh compartilhado funciona sem Homebrew. Oh My Zsh e os três plugins usados são preparados se necessário. Homebrew e a troca do shell de login não são automatizados.
- Para simular: `./backup save --dry-run` ou `./backup apply --dry-run`. A simulação não baixa atualizações.
- Snapshots antigos permanecem em `snapshots/`, fora do Git; seus arquivos podem ser recuperados manualmente de `files/`.

Para testar o código: `python3 -m unittest discover -s tests -v`.
