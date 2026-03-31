# Contribuindo com o INFinance 🤝

Obrigado por contribuir com o projeto.

Este documento define o fluxo recomendado para manter qualidade, segurança e consistência do sistema.

## Sumário

- [Como começar](#como-começar-)
- [Tipos de contribuição](#tipos-de-contribuição-)
- [Padrões técnicos](#padrões-técnicos-)
- [Checklist antes de abrir PR](#checklist-antes-de-abrir-pr-)
- [Diretrizes de Pull Request](#diretrizes-de-pull-request-)

## 🚀 Como começar 

1. Faça um fork do projeto (ou use branch de feature no repositório principal).
2. Crie uma branch descritiva:
   - `feat/nome-da-feature`
   - `fix/nome-do-bug`
   - `docs/nome-da-documentacao`
3. Execute o ambiente local:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Ou no Windows, via script automatizado:

```bat
infinance.bat
```

## 🧩 Tipos de contribuição 

- Correções de bugs.
- Melhorias de UX/UI responsiva.
- Refino de regras fiscais e simulações.
- Melhorias de segurança.
- Evolução de exportações e relatórios.
- Ajustes de documentação.

## 🧱 Padrões técnicos 

- Backend em Flask deve manter foco em clareza e previsibilidade.
- Evite duplicação de lógica de negócio.
- Preserve compatibilidade com banco SQLite atual (`infinance.db`).
- Em formulários POST, mantenha proteção CSRF.
- Em alterações visuais, preserve o padrão premium/responsivo do sistema.
- Mantenha textos e labels em **português do Brasil**.

## ✅ Checklist antes de abrir PR 

- [ ] O sistema sobe localmente sem erro.
- [ ] Fluxos principais testados manualmente:
  - [ ] Dashboard
  - [ ] Empresa
  - [ ] Clientes
  - [ ] Serviços
  - [ ] Entradas
  - [ ] Despesas
  - [ ] Relatório mensal
  - [ ] DAS/Fator R
  - [ ] Simulador
- [ ] Exportações validadas (CSV/XLSX/TXT/PDF) para a área alterada.
- [ ] Sem regressão visual em desktop e mobile.
- [ ] Segurança preservada (CSRF, headers, sessão).
- [ ] Documentação atualizada (`README.md`, se aplicável).

## 📌 Diretrizes de Pull Request 

Inclua no PR:

- Contexto do problema.
- O que foi alterado.
- Evidências (prints, logs ou passos de reprodução).
- Riscos e impactos.
- Passo a passo de validação.

Modelo recomendado:

```md
## Contexto
...

## Alterações
...

## Como validar
1. ...
2. ...

## Riscos
...
```

---

Contribuições que elevem segurança, confiabilidade e experiência do usuário têm prioridade. 💚
