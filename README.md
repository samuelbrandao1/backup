# Mesmos programas e configurações nas duas máquinas

Na máquina em que você fez mudanças:

```bash
./backup save
```

No outro computador:

```bash
./backup apply
```

**Só isso no dia a dia.** Execute dentro da pasta do repositório. Não existem perfis para escolher, snapshots para transferir ou commits para fazer manualmente.

## Primeira vez no outro computador

Com Arch Linux, Python 3, Git e sudo disponíveis, clone e aplique:

```bash
git clone https://github.com/samuelbrandao1/backup.git ~/backup
cd ~/backup && ./backup apply
```

O Git precisa estar autenticado para enviar com `save`. Se você já usa este repositório para fazer push, continue com a mesma autenticação. Caso contrário, configure uma vez: `gh auth login` e `gh auth setup-git` (requer github-cli). Configure também seu nome e email do Git se ainda não estiverem definidos.

## O que cada comando faz

**`save`** copia suas configurações para `dotfiles/`, registra a lista de pacotes explicitamente instalados via pacman/AUR, cria um commit e envia ao GitHub. Links de dotfiles são seguidos: o GitHub recebe arquivos reais. Se um caminho estiver ausente nesta máquina, mantém a última cópia compartilhada. Para parar de compartilhar um caminho, remova a linha de `files.txt` e execute `save`.

**`apply`** baixa a versão do GitHub, instala os pacotes que faltam e substitui as configurações locais pela versão compartilhada. Prepara yay, Oh My Zsh e os três plugins usados no seu Zsh quando necessários. Os gerenciadores mantêm as confirmações de instalação. Não remove programas extras e não força versões iguais dos pacotes: mantenha o Arch atualizado nas duas máquinas.

A inicialização do Homebrew no seu `.zshrc` compartilhado é condicional: funciona mesmo em uma máquina sem Homebrew. Pacotes do Homebrew não são sincronizados. O comando não troca seu shell de login; abra `zsh` ou selecione-o no terminal se necessário.

## O que é compartilhado

A lista está em **`files.txt`**. Inicialmente: Zsh, Starship, Kitty, Lazygit e Yazi, se instalado. Para acrescentar algo, escreva um caminho relativo à sua pasta pessoal:

```text
.config/btop
```

Depois execute `./backup save`. Diretórios são copiados por inteiro. Não inclua configurações específicas de hardware, como monitores, se quiser mantê-las diferentes. `.ssh`, `.aws`, `.gnupg`, caches e caminhos fora do HOME são bloqueados.

## Cuidados que importam

- Use `save` antes de sair de uma máquina e `apply` ao chegar na outra. Faça `apply` antes de começar a editar, para evitar versões divergentes.
- `save` envia os arquivos selecionados ao GitHub. Use repositório privado se houver dados pessoais. Há uma checagem de padrões comuns de credenciais, mas ela não detecta todos os segredos.
- Antes de substituir configurações, `apply` guarda os arquivos anteriores em `~/.backup-rollback/`. O caminho aparece no terminal; `originals/` preserva inclusive os links originais. Não existe exclusão automática dessas cópias.
- Se o Git encontrar alterações locais ou históricos divergentes, o comando interrompe sem forçar sobrescrita. O commit criado por `save` continua guardado localmente se o envio falhar; execute novamente após corrigir a conexão/autenticação.
- Para conferir sem modificar nada: `./backup save --dry-run` ou `./backup apply --dry-run`. A simulação de apply usa a cópia já disponível, sem baixar atualizações.

Os snapshots locais antigos continuam em `snapshots/`, ignorados pelo Git. A ferramenta antiga fica em `lib/backup.py` para recuperação excepcional; ela não faz parte do fluxo cotidiano. `install.sh` é um atalho para `apply`.

## Testes

```bash
python3 -m unittest discover -s tests -v
```
