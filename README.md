# Mini-ERP de Estoque com Lançamentos Contábeis Automáticos

Protótipo de ERP em Python que conecta a operação de um pequeno comércio
(cadastro de produtos, compras e vendas) com a contabilidade: **cada
movimentação de estoque gera, automaticamente, os lançamentos contábeis em
partidas dobradas correspondentes** — exatamente o tipo de integração que
sistemas de gestão (Omie, Contimatic, SAP, etc.) fazem por trás das telas de
operação.

A motivação do projeto é juntar duas frentes: experiência prática com
implantação de ERPs e rotinas contábeis, e desenvolvimento de software —
mostrando, em código, como uma operação de estoque "vira" contabilidade.

## Regras contábeis aplicadas

O projeto usa o método do **custo médio ponderado** para valorizar o estoque,
e gera os lançamentos em partidas dobradas (todo débito tem uma contrapartida
a crédito de mesmo valor):

| Operação | Lançamento gerado |
|---|---|
| **Compra** (entrada de estoque) | `D – Estoque de Mercadorias` / `C – Fornecedores a Pagar` |
| **Venda** (saída de estoque) — receita | `D – Clientes (a receber)` / `C – Receita de Vendas` (pelo valor de venda) |
| **Venda** (saída de estoque) — custo | `D – CMV (Custo da Mercadoria Vendida)` / `C – Estoque de Mercadorias` (pelo custo médio) |

Cada venda gera **dois** lançamentos simultâneos — um para reconhecer a
receita pelo preço de venda, outro para baixar o estoque pelo custo médio.
Essa separação é o que permite, depois, calcular a margem bruta (Receita −
CMV) diretamente do razão.

## Como rodar

Requer apenas Python 3.10+ (usa `sqlite3` da biblioteca padrão).

```bash
# Gera um banco SQLite (erp_demo.db) com produtos e um ciclo de compra/venda de exemplo
python erp.py demo

# Consulta a posição de estoque (quantidade, custo médio, valor total)
python erp.py estoque

# Consulta o livro razão (todos os lançamentos contábeis gerados) e os saldos por conta
python erp.py razao
```

### Exemplo de saída (`python erp.py demo`)

```
=== Posição de estoque ===
  TEC-001  | Teclado mecânico ABNT2       | qtd:     17 | custo médio: R$   183.93 | valor em estoque: R$    3126.79
  MOU-002  | Mouse sem fio                | qtd:     18 | custo médio: R$    60.00 | valor em estoque: R$    1080.00

=== Livro razão (lançamentos contábeis) ===
  2026-05-02 | D: Estoque de Mercadorias            | C: Fornecedores a Pagar              | R$    3600.00 | Compra de 20 un. de Teclado mecânico ABNT2 (NF 5001 - fornecedor TechParts)
  2026-05-10 | D: Clientes (a receber)              | C: Receita de Vendas                 | R$    2560.00 | Venda de 8 un. de Teclado mecânico ABNT2 (...) — reconhecimento da receita
  2026-05-10 | D: CMV (Custo da Mercadoria Vendida) | C: Estoque de Mercadorias            | R$    1440.00 | Venda de 8 un. de Teclado mecânico ABNT2 (...) — baixa do estoque pelo custo médio
  ...

=== Saldos por conta (débito − crédito) ===
  CMV (Custo da Mercadoria Vendida)| débitos: R$    2399.21 | créditos: R$       0.00 | saldo: R$    2399.21
  ...

  Soma de todos os saldos: R$ 0.00 (deve ser 0,00 — partidas dobradas balanceadas)
```

A última linha é a verificação clássica de partidas dobradas: a soma de todos
os saldos (débito − crédito) de todas as contas precisa ser sempre zero. Se
não for, há um erro na geração dos lançamentos.

## Estrutura do projeto

```
mini-erp-estoque-contabil/
├── erp.py              # modelo de dados, regras de negócio e CLI
└── tests/
    └── test_erp.py     # testes das regras de estoque e geração contábil
```

## Testes

```bash
pip install pytest
pytest tests/
```

Cobrem: cálculo do custo médio ponderado em compras sucessivas, geração
correta dos lançamentos de compra e venda (contas e valores), bloqueio de
venda com estoque insuficiente, e o balanceamento das partidas dobradas
(soma dos saldos = zero) após uma sequência de operações.

## Possíveis evoluções

- Relatório de margem bruta por produto/período (Receita − CMV direto do razão).
- Suporte a múltiplos depósitos/filiais.
- API REST simples para integrar com uma interface web ou mobile (Flutter).

## Stack

`Python` · `SQLite` (`sqlite3`, biblioteca padrão) · `SQL` · `pytest`
