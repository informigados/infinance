# INFinance 💚

Plataforma premium de controle **financeiro e fiscal** para agências e empresas brasileiras, com foco em operação real: entradas, despesas, relatórios, simulação tributária e gestão de DAS/Fator R.

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1.3-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-CSS_Compilado-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![CI](https://github.com/INformigados/infinance/actions/workflows/ci.yml/badge.svg)](https://github.com/INformigados/infinance/actions/workflows/ci.yml)
[![Exportações](https://img.shields.io/badge/Exportações-CSV%20%7C%20XLSX%20%7C%20TXT%20%7C%20PDF-0F766E)](#exportacoes-inteligentes)
[![Status](https://img.shields.io/badge/Status-Produção-16A34A)](#visao-geral)
[![Licença](https://img.shields.io/badge/Licença-MIT-16A34A)](#licenca)

## 📚 Sumário

- [Visão geral](#visao-geral)
- [Funcionalidades](#funcionalidades)
- [Stack técnica](#stack-tecnica)
- [Segurança aplicada](#seguranca-aplicada)
- [Requisitos](#requisitos)
- [Como executar](#como-executar)
- [Variáveis de ambiente](#variaveis-de-ambiente)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Página Sobre](#pagina-sobre)
- [Exportações inteligentes](#exportacoes-inteligentes)
- [Build de executável e instalador](#build-de-executavel-e-instalador)
- [CI no GitHub Actions](#ci-no-github-actions)
- [Roadmap imediato](#roadmap-imediato)
- [Contribuição e segurança](#contribuicao-e-seguranca)
- [Aviso importante](#aviso-importante)

<a id="visao-geral"></a>
## 🎯 Visão geral

O INFinance foi projetado para centralizar a operação financeira/fiscal de negócios de serviço no Brasil, permitindo:

- Controle de clientes, serviços e movimentações.
- Estimativa tributária por tipo de operação.
- Gestão de despesas e resultado mensal.
- Simulação de DAS com suporte a múltiplos anexos e Fator R.
- Exportação de dados em formatos prontos para operação e análise.

<a id="funcionalidades"></a>
## ✅ Funcionalidades 

### Operação financeira

- Cadastro de **clientes** (PF/PJ).
- Cadastro de **serviços** com:
  - tipo do serviço;
  - alíquota personalizada;
  - CNAE e descrição;
  - anexo (I, II, III, IV, V ou III/V);
  - aplicabilidade de Fator R.
- Cadastro de **entradas/receitas** com:
  - canal PF/PJ;
  - status da entrada;
  - emissão de nota;
  - estimativa de tributos por cenário.
- Cadastro de **despesas/saídas** com categorias e recorrência (fixa/variável).
- CRUD completo para clientes, serviços, entradas e despesas.
- Busca textual e paginação nas listagens para operação com bases maiores.

### Gestão e inteligência

- **Dashboard executivo** com totais, margens e indicadores.
- **Relatório mensal consolidado** com insights automáticos.
- **Simulador** de entrada fiscal.
- **DAS/Fator R avançado** com cenários por anexos.
- **Autenticação com RBAC básico** (`admin`, `operator`, `viewer`) e gestão de usuários.
- Gestão de usuários com criação, renomeação, redefinição de senha e exclusão segura (usuário padrão protegido).

### Interface e UX

- Layout responsivo (desktop, tablet e mobile).
- Navegação por abas com estado ativo.
- Menu mobile com botão de ícone (hambúrguer/fechar).
- Favicon e identidade visual do sistema.
- Paginação numérica nas listagens com filtros preservados.
- Feedback visual de envio em formulários (`Processando...`) para evitar cliques duplicados.
- Feedback de geração nos links de exportação (`Gerando...`) para downloads pesados.

<a id="stack-tecnica"></a>
## 🧰 Stack técnica 

- **Backend:** Flask 3.1.3 (Python)
- **Banco:** SQLite (`infinance.db`)
- **Frontend:** Jinja2 + Tailwind CSS compilado (`static/vendor/tailwind.compiled.css`)
- **Exportações:** CSV, XLSX (openpyxl), TXT, PDF (reportlab)

<a id="seguranca-aplicada"></a>
## 🔐 Segurança aplicada 

- Proteção CSRF em formulários (`before_request`).
- Cabeçalhos de segurança HTTP (`X-Frame-Options`, `CSP`, etc.).
- `CSP` restritiva com `script-src 'self'` e `style-src 'self'` (sem `unsafe-inline`).
- `SESSION_COOKIE_HTTPONLY` e `SESSION_COOKIE_SAMESITE=Lax`.
- `SESSION_COOKIE_SECURE` configurado de forma condicional (ambiente).
- `SECRET_KEY` com suporte a env var e fallback persistente em `.infinance.secret`.
- Bloqueio padrão de bind remoto (exige `INFINANCE_ALLOW_REMOTE=1` para exposição externa).
- Inicialização do banco com proteção contra execução duplicada.

Para processo de reporte de vulnerabilidades, veja [SECURITY.md](SECURITY.md).

<a id="requisitos"></a>
## 📦 Requisitos

- Python 3.x
- Pip atualizado
- Node.js 20+ (para build do CSS Tailwind)
- Windows (script `.bat`) ou ambiente compatível para execução manual

Dependências Python:

- Flask==3.1.3
- openpyxl==3.1.5
- reportlab==4.4.10

<a id="como-executar"></a>
## 🚀 Como executar

### 1) Windows (recomendado)

```bat
infinance.bat
```

O script:

- cria `.venv` se necessário;
- instala/atualiza dependências;
- encontra porta disponível automaticamente;
- carrega/gera chave local;
- inicia a aplicação e abre no navegador.

Credenciais iniciais (quando não informadas por variável de ambiente):

- Usuário: `admin`
- Senha: `Admin@123` (troca recomendada no primeiro acesso)

### 2) Execução manual (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Aplicação padrão: `http://127.0.0.1:5000`

<a id="variaveis-de-ambiente"></a>
## ⚙️ Variáveis de ambiente 

| Variável | Descrição | Exemplo |
| --- | --- | --- |
| `INFINANCE_HOST` | Host de bind do servidor Flask | `127.0.0.1` |
| `INFINANCE_PORT` | Porta de execução | `5000` |
| `INFINANCE_DEBUG` | Ativa debug em localhost | `0` / `1` |
| `INFINANCE_ALLOW_REMOTE` | Permite bind externo (somente se necessário) | `0` / `1` |
| `INFINANCE_WAITRESS_THREADS` | Número de threads do Waitress no modo produção | `8` |
| `INFINANCE_ADMIN_USER` | Usuário admin inicial no bootstrap | `admin` |
| `INFINANCE_ADMIN_PASSWORD` | Senha admin inicial no bootstrap | `SenhaForte123!` |
| `INFINANCE_SECRET_KEY` | Chave secreta da sessão (prioridade máxima) | `chave_forte` |
| `SECRET_KEY` | Alternativa para chave secreta | `chave_forte` |
| `INFINANCE_SESSION_COOKIE_SECURE` | Força cookie secure (`true`/`false`) | `true` |
| `INFINANCE_NO_BROWSER` | Evita abrir navegador no `.bat` | `1` |
| `INFINANCE_DATA_DIR` | Diretório de dados no executável (DB/chave) | `C:\Dados\INFinance` |

Se nenhuma chave for informada, o sistema usa `.infinance.secret` como fallback persistente.

<a id="estrutura-do-projeto"></a>
## 🗂️ Estrutura do projeto 

```text
infinance/
├─ .github/workflows/ci.yml
├─ app.py
├─ core/
│  └─ access_control.py
├─ infinance.spec
├─ infinance.bat
├─ installer/INFinance.iss
├─ requirements.txt
├─ requirements-build.txt
├─ scripts/
│  ├─ build_executable.ps1
│  └─ build_installer.ps1
├─ static/
│  ├─ app.css
│  ├─ app.js
│  ├─ infinance-icon.svg
│  └─ vendor/
│     ├─ tailwind.compiled.css
│     └─ tailwind.input.css
├─ tailwind.config.js
├─ package.json
├─ package-lock.json
├─ templates/
│  └─ *.html
├─ tests/
│  ├─ test_auth_and_calculations.py
│  └─ test_routes_smoke.py
├─ infinance.db
└─ .infinance.secret
```

<a id="pagina-sobre"></a>
## 👤 Página Sobre

A rota `/about` apresenta o propósito do projeto, pilares do produto e os autores.
É uma área institucional para reforçar contexto, confiança e identidade do INFinance.

<a id="exportacoes-inteligentes"></a>
## 📤 Exportações inteligentes 

O sistema exporta com filtro mensal (`?month=YYYY-MM`) nas rotas de export:

- Entradas: **CSV, XLSX, TXT, PDF**
- Despesas: **CSV, XLSX, TXT, PDF**
- Relatório mensal: **CSV, XLSX, TXT, PDF**

<a id="build-de-executavel-e-instalador"></a>
## 🖥️ Build de executável e instalador

### 1) Gerar executável com PyInstaller

```powershell
& "C:\Program Files\nodejs\npm.cmd" ci
& "C:\Program Files\nodejs\npm.cmd" run build:css
python -m pip install -r requirements.txt -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\scripts\build_executable.ps1 -Clean
```

Saída esperada:

- `dist\INFinance\INFinance.exe`
- dados locais do app (DB/chave): `%LOCALAPPDATA%\INFinance`

### 2) Gerar instalador com Inno Setup

Pré-requisito: Inno Setup 6 instalado (`ISCC.exe`).

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
```

Saída esperada:

- `dist\installer\INFinance-Setup.exe`

<a id="ci-no-github-actions"></a>
## 🧪 CI no GitHub Actions

Workflow incluído em `.github/workflows/ci.yml` com:

- instalação de dependências;
- build de CSS Tailwind compilado (`npm ci && npm run build:css`);
- auditoria de dependências com `pip-audit`;
- validação de compilação (`compileall`);
- testes de smoke (`unittest`) das rotas principais.
- cobertura adicional de RBAC e fluxo CRUD essencial em testes automatizados.
- validação de endpoints de exportação com conferência de MIME e `Content-Disposition`.
- testes dedicados para fluxo de autenticação (`login/logout`) e cálculos fiscais de borda.

<a id="roadmap-imediato"></a>
## 🛣️ Roadmap imediato 

- Integração opcional de CNAE por API pública (com cache e validação).
- Ampliação de automações operacionais e governança.
- Evolução contínua de UX e acessibilidade premium.

## 📝 Registro de alterações

### 31-03-2026 (1.0.0)

- Lançamento inicial.

<a id="contribuicao-e-seguranca"></a>
## 🤝 Contribuição e segurança

- Guia de contribuição: [CONTRIBUTING.md](CONTRIBUTING.md)
- Política de segurança: [SECURITY.md](SECURITY.md)

<a id="aviso-importante"></a>
## ⚠️ Aviso importante

As simulações e projeções tributárias do INFinance são apoio à gestão.  
O fechamento fiscal/oficial deve ser validado com a contabilidade responsável.

<a id="autores"></a>
## 👥 Autores

- [INformigados](https://github.com/informigados)
- [Alex Brito](https://github.com/AlexBritoDEV)

<a id="licenca"></a>
## 📄 Licença

Este projeto está licenciado sob a Licença MIT. Consulte [`LICENSE`](LICENSE) para obter detalhes.
