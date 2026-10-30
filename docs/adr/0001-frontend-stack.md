# ADR 0001: Frontend Stack — Vite com TypeScript Vanilla vs Framework

## Contexto
O frontend original do FinTrack consistia em um único arquivo `index.html` com mais de 3.600 linhas, mesclando marcação HTML, regras de CSS inline e scripts com variáveis globais no objeto `window`. O sistema é servido diretamente pelo backend FastAPI como uma aplicação de página única (SPA / MPA híbrida), com autenticação criptograficamente assinada por cookie de mesma origem (`SameSite=Strict`, `HttpOnly`, `Secure`).

Para assegurar segurança máxima, conformidade com Content Security Policy estrita (`script-src 'self'`), testes unitários e tipagem estática integrada à API do FastAPI, foi necessário modernizar o ferramental de desenvolvimento e build do frontend.

## Decisão
Adotamos **Vite + TypeScript estrito (Vanilla DOM) + Vitest**:

1. **Vite como Bundler**:
   - Compilação ultra-rápida via esbuild e Rollup.
   - Geração determinística de assets com hash de conteúdo (`/assets/[name]-[hash].js`), permitindo caching HTTP agressivo e seguro (`Cache-Control: public, max-age=31536000, immutable`).
   - Servidor de desenvolvimento com proxy transparente para os endpoints `/api`, `/auth` e `/login` do backend FastAPI, preservando a política de mesma origem e cookies `SameSite=Strict`.

2. **TypeScript Estrito (`noImplicitAny`, `strict: true`)**:
   - Tipos estáticos gerados diretamente da especificação OpenAPI do backend FastAPI via `scripts/export_openapi.py` e `openapi-typescript`.
   - Cliente HTTP tipado (`openapi-fetch`), prevenindo divergências de contrato em tempo de compilação sem custos adicionais de runtime.

3. **Arquitetura Modular Vanilla (sem framework pesado)**:
   - Mantém a interface leve, eliminando custos de hidratação, Virtual DOM ou runtime overhead desnecessário para o escopo atual.
   - Padrão arquitetural reativo limpo com Store simples pub/sub (`state.ts`), componentes desacoplados (`components/`) e delegação centralizada de eventos via atributos `data-action`.

4. **Docker Multi-Stage**:
   - Estágio 1 (`node:20-slim`) executa `npm ci` e `npm run build`, produzindo o diretório hermético `frontend/dist`.
   - Estágio 2/3 (`python:3.12-slim`) recebe apenas os artefatos estáticos compilados em `frontend/dist`, eliminando dependências Node do container de produção.

## Critérios para Migração Futura para Framework (React / Vue / Svelte)
Esta decisão de manter TypeScript Vanilla deve ser reavaliada caso surjam os seguintes requisitos:

1. **Redesenho Visual Completo ou Sistema de Design Complexo**:
   - Adoção de bibliotecas avançadas de componentes (Tailwind UI, Radix, Shadcn/ui) que demandem abstrações de componentes JSX/SFC.
2. **Gerenciamento de Estado Altamente Concorrente**:
   - Múltiplas abas ativas, sincronização em tempo real via WebSockets (ex.: conciliação multi-dispositivo) onde o Virtual DOM ou reatividade por sinal (Signals) traga ganhos expressivos de manutenibilidade.
3. **Formulários Dinâmicos e Validação Client-side Extensiva**:
   - Criação de fluxos wizard ou telas com centenas de inputs dinâmicos onde bibliotecas como React Hook Form ou Zod integrado façam diferença mensurável.

## Consequências
- **Positivas**: Bundle compilado extremamente enxuto (~75 kB gzipped incluindo Chart.js); zero dependência de CDN externa; CSP estrita sem 'unsafe-inline'; tipagem estática e testes unitários com Vitest rodando em < 1.5s.
- **Negativas / Atenção**: A manipulação de nós de DOM e renderização condicional exige cuidado redobrado com funções de escape (`escapeHtml` / `dom.ts`) para evitar vulnerabilidades de XSS.
