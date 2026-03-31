# Política de Segurança do INFinance 🔐

Este documento descreve como reportar vulnerabilidades e como tratamos incidentes de segurança.

## Versões suportadas

Atualmente, o projeto mantém uma linha principal em evolução contínua.

| Versão | Suporte |
| --- | --- |
| Atual (branch principal em produção) | ✅ |
| Versões antigas sem manutenção ativa | ⚠️ Limitado |

## Como reportar uma vulnerabilidade

Se você identificar uma falha de segurança:

1. **Não** abra issue pública com detalhes sensíveis.
2. Compartilhe o reporte de forma privada com o mantenedor responsável do projeto (canal interno do time/repositório).
3. Inclua as informações abaixo:
   - tipo da vulnerabilidade;
   - impacto potencial;
   - passos para reprodução;
   - evidências (payload, request/response, prints, logs);
   - sugestão de mitigação, se houver.

## O que esperar após o reporte

- Confirmação inicial de recebimento.
- Triagem técnica para classificar severidade e impacto.
- Definição de correção e priorização.
- Retorno com status até a resolução.

## Boas práticas para quem contribui

- Não remover proteções CSRF.
- Não enfraquecer cabeçalhos de segurança HTTP.
- Não expor segredos em código, logs ou commits.
- Preservar configuração de cookies de sessão e política de sessão.
- Evitar inclusão de arquivos sensíveis no versionamento (`.infinance.secret`, bancos locais, etc.).

## Escopo de segurança atual do sistema

O INFinance já implementa mecanismos importantes:

- validação CSRF em rotas de escrita;
- cabeçalhos de segurança (CSP, X-Frame-Options, etc.);
- cookies com `HttpOnly`, `SameSite` e suporte a `Secure` condicional;
- chave secreta persistente com fallback local.

## Divulgação responsável

A divulgação pública de detalhes técnicos deve ocorrer **somente após** correção validada em ambiente de produção.
