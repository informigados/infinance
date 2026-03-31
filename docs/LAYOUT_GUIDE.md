# Guia Interno de Layout — INFinance 🎨

Este guia define os padrões visuais e de estrutura para novas telas e refatorações.

Objetivo: manter o sistema consistente, premium e fácil de evoluir.

## 1) Estrutura base de página

Toda tela de formulário deve seguir:

1. Card principal com `w-full rounded-3xl bg-slate-900 border border-slate-800 p-6` (ou `p-5` em cards secundários).
2. Título com classe `if-form-title`.
3. Subtítulo explicativo com classe `if-form-subtitle`.
4. Formulário com classe `if-form` + `space-y-4`.

Exemplo:

```html
<section class="w-full rounded-3xl bg-slate-900 border border-slate-800 p-6">
  <h1 class="if-form-title">Título da tela</h1>
  <p class="if-form-subtitle">Descrição curta orientada ao usuário.</p>
  <form method="post" class="if-form space-y-4">
    ...
  </form>
</section>
```

## 2) Padrão de botões

### Tipos disponíveis

- Primário: `if-btn if-btn-primary`
- Secundário (voltar/cancelar): `if-btn if-btn-secondary`
- Ação de edição: `if-btn if-btn-sm if-btn-warning`
- Ação destrutiva: `if-btn if-btn-sm if-btn-danger`
- Botão full-width: adicionar `if-btn-block`

### Linha de ações de formulário

Sempre usar `if-actions` para manter alinhamento mobile/desktop:

```html
<div class="if-actions">
  <button type="submit" class="if-btn if-btn-primary if-btn-block">Salvar</button>
  <a href="..." class="if-btn if-btn-secondary if-btn-block">Voltar</a>
</div>
```

## 3) Padrão para tabelas e CRUD

- Botões de ação da tabela devem ser curtos (`if-btn-sm`) e consistentes:
  - Editar: `if-btn if-btn-sm if-btn-warning`
  - Excluir: `if-btn if-btn-sm if-btn-danger`
- Evitar variações locais de cor/tamanho sem necessidade de contexto.

## 4) Tipografia e espaçamento

- Título principal do card: `if-form-title`
- Subtítulo do card: `if-form-subtitle`
- Espaçamento entre campos: `space-y-4`
- Grids com `gap-4` (ou `gap-6` em blocos maiores)

## 5) Responsividade

- Mobile-first.
- Evitar largura fixa para cards principais; preferir `w-full`.
- Quando houver sidebar + tabela, usar `grid` com breakpoint (`lg`/`xl`) e fallback empilhado no mobile.

## 6) Acessibilidade e UX

- Inputs, selects, textareas e botões devem manter foco visível.
- Botões devem ter textos claros e acionáveis.
- Ações destrutivas devem manter confirmação (`data-confirm`).

## 7) Checklist rápido para nova tela

- [ ] Título e subtítulo no padrão.
- [ ] Formulário com `if-form`.
- [ ] Botões no padrão `if-btn`.
- [ ] Ações alinhadas com `if-actions`.
- [ ] Responsivo em mobile e desktop.
- [ ] Consistente com o tema atual (cores e bordas).
