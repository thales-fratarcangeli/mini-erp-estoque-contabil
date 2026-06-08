"""Mini-ERP de estoque com geração automática de lançamentos contábeis.

Demonstra como um ERP conecta a operação (cadastro de produtos, compras e
vendas) com a contabilidade: cada movimentação de estoque gera, automática e
imediatamente, os lançamentos contábeis correspondentes em partidas dobradas
(todo débito tem uma contrapartida a crédito de mesmo valor).

Regras contábeis aplicadas (método do custo médio ponderado):

  Compra (entrada de estoque):
      D – Estoque de Mercadorias   /   C – Fornecedores a Pagar

  Venda (saída de estoque), lançada em duas partidas:
      D – Clientes (a receber)     /   C – Receita de Vendas        (pelo valor de venda)
      D – CMV (Custo da Mercadoria Vendida) / C – Estoque de Mercadorias  (pelo custo médio)

Uso como CLI:
    python erp.py demo                       # popula o banco com um cenário de exemplo
    python erp.py estoque                    # mostra a posição atual de estoque
    python erp.py razao                      # mostra o livro razão (lançamentos contábeis)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass

CONTA_ESTOQUE = "Estoque de Mercadorias"
CONTA_FORNECEDORES = "Fornecedores a Pagar"
CONTA_CLIENTES = "Clientes (a receber)"
CONTA_RECEITA = "Receita de Vendas"
CONTA_CMV = "CMV (Custo da Mercadoria Vendida)"


class EstoqueInsuficiente(Exception):
    """Levantada ao tentar vender mais do que existe em estoque."""


@dataclass(frozen=True)
class Lancamento:
    data: str
    historico: str
    conta_debito: str
    conta_credito: str
    valor: float


def criar_banco(conexao: sqlite3.Connection) -> None:
    conexao.executescript(
        """
        CREATE TABLE IF NOT EXISTS produtos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo          TEXT NOT NULL UNIQUE,
            nome            TEXT NOT NULL,
            quantidade      REAL NOT NULL DEFAULT 0,
            custo_medio     REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS movimentacoes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id      INTEGER NOT NULL REFERENCES produtos(id),
            data            TEXT NOT NULL,
            tipo            TEXT NOT NULL CHECK (tipo IN ('compra', 'venda')),
            quantidade      REAL NOT NULL,
            valor_unitario  REAL NOT NULL,
            observacao      TEXT
        );

        CREATE TABLE IF NOT EXISTS lancamentos_contabeis (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            movimentacao_id INTEGER NOT NULL REFERENCES movimentacoes(id),
            data            TEXT NOT NULL,
            historico       TEXT NOT NULL,
            conta_debito    TEXT NOT NULL,
            conta_credito   TEXT NOT NULL,
            valor           REAL NOT NULL
        );
        """
    )
    conexao.commit()


def cadastrar_produto(conexao: sqlite3.Connection, codigo: str, nome: str) -> int:
    cursor = conexao.execute(
        "INSERT INTO produtos (codigo, nome, quantidade, custo_medio) VALUES (?, ?, 0, 0)",
        (codigo, nome),
    )
    conexao.commit()
    return cursor.lastrowid


def _buscar_produto(conexao: sqlite3.Connection, codigo: str) -> sqlite3.Row:
    conexao.row_factory = sqlite3.Row
    produto = conexao.execute("SELECT * FROM produtos WHERE codigo = ?", (codigo,)).fetchone()
    if produto is None:
        raise ValueError(f"Produto não cadastrado: {codigo!r}")
    return produto


def registrar_compra(
    conexao: sqlite3.Connection,
    codigo_produto: str,
    quantidade: float,
    valor_unitario: float,
    data: str,
    observacao: str = "",
) -> list[Lancamento]:
    """Registra uma compra: dá entrada no estoque (recalculando o custo médio
    ponderado) e gera o lançamento contábil de débito em Estoque / crédito em
    Fornecedores a Pagar."""
    produto = _buscar_produto(conexao, codigo_produto)

    quantidade_total = produto["quantidade"] + quantidade
    valor_total_anterior = produto["quantidade"] * produto["custo_medio"]
    valor_total_novo = valor_total_anterior + (quantidade * valor_unitario)
    novo_custo_medio = valor_total_novo / quantidade_total if quantidade_total else 0.0

    conexao.execute(
        "UPDATE produtos SET quantidade = ?, custo_medio = ? WHERE id = ?",
        (quantidade_total, novo_custo_medio, produto["id"]),
    )

    valor_da_operacao = quantidade * valor_unitario
    movimentacao_id = _inserir_movimentacao(
        conexao, produto["id"], data, "compra", quantidade, valor_unitario, observacao
    )

    lancamentos = [
        Lancamento(
            data=data,
            historico=f"Compra de {quantidade:g} un. de {produto['nome']} ({observacao or 'sem observação'})",
            conta_debito=CONTA_ESTOQUE,
            conta_credito=CONTA_FORNECEDORES,
            valor=valor_da_operacao,
        )
    ]
    _gravar_lancamentos(conexao, movimentacao_id, lancamentos)
    conexao.commit()
    return lancamentos


def registrar_venda(
    conexao: sqlite3.Connection,
    codigo_produto: str,
    quantidade: float,
    valor_unitario: float,
    data: str,
    observacao: str = "",
) -> list[Lancamento]:
    """Registra uma venda: dá baixa no estoque pelo custo médio e gera os dois
    lançamentos contábeis correspondentes (receita e custo da mercadoria vendida)."""
    produto = _buscar_produto(conexao, codigo_produto)

    if quantidade > produto["quantidade"]:
        raise EstoqueInsuficiente(
            f"Estoque insuficiente para vender {quantidade:g} un. de {produto['nome']} "
            f"(disponível: {produto['quantidade']:g})"
        )

    custo_medio = produto["custo_medio"]
    custo_da_baixa = quantidade * custo_medio
    valor_da_venda = quantidade * valor_unitario

    conexao.execute(
        "UPDATE produtos SET quantidade = quantidade - ? WHERE id = ?",
        (quantidade, produto["id"]),
    )

    movimentacao_id = _inserir_movimentacao(
        conexao, produto["id"], data, "venda", quantidade, valor_unitario, observacao
    )

    historico_base = f"Venda de {quantidade:g} un. de {produto['nome']} ({observacao or 'sem observação'})"
    lancamentos = [
        Lancamento(
            data=data,
            historico=historico_base + " — reconhecimento da receita",
            conta_debito=CONTA_CLIENTES,
            conta_credito=CONTA_RECEITA,
            valor=valor_da_venda,
        ),
        Lancamento(
            data=data,
            historico=historico_base + " — baixa do estoque pelo custo médio",
            conta_debito=CONTA_CMV,
            conta_credito=CONTA_ESTOQUE,
            valor=custo_da_baixa,
        ),
    ]
    _gravar_lancamentos(conexao, movimentacao_id, lancamentos)
    conexao.commit()
    return lancamentos


def _inserir_movimentacao(
    conexao: sqlite3.Connection,
    produto_id: int,
    data: str,
    tipo: str,
    quantidade: float,
    valor_unitario: float,
    observacao: str,
) -> int:
    cursor = conexao.execute(
        """
        INSERT INTO movimentacoes (produto_id, data, tipo, quantidade, valor_unitario, observacao)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (produto_id, data, tipo, quantidade, valor_unitario, observacao),
    )
    return cursor.lastrowid


def _gravar_lancamentos(
    conexao: sqlite3.Connection, movimentacao_id: int, lancamentos: list[Lancamento]
) -> None:
    conexao.executemany(
        """
        INSERT INTO lancamentos_contabeis
            (movimentacao_id, data, historico, conta_debito, conta_credito, valor)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (movimentacao_id, l.data, l.historico, l.conta_debito, l.conta_credito, l.valor)
            for l in lancamentos
        ],
    )


def posicao_de_estoque(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    conexao.row_factory = sqlite3.Row
    return conexao.execute(
        """
        SELECT codigo, nome, quantidade, custo_medio,
               (quantidade * custo_medio) AS valor_em_estoque
        FROM produtos
        ORDER BY codigo
        """
    ).fetchall()


def livro_razao(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    conexao.row_factory = sqlite3.Row
    return conexao.execute(
        """
        SELECT data, historico, conta_debito, conta_credito, valor
        FROM lancamentos_contabeis
        ORDER BY data, id
        """
    ).fetchall()


def saldo_por_conta(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    """Calcula o saldo de cada conta contábil (somatório de débitos − créditos),
    útil para conferir rapidamente se o razão está balanceado."""
    conexao.row_factory = sqlite3.Row
    return conexao.execute(
        """
        WITH movimentos AS (
            SELECT conta_debito  AS conta, valor AS debito, 0 AS credito FROM lancamentos_contabeis
            UNION ALL
            SELECT conta_credito AS conta, 0 AS debito, valor AS credito FROM lancamentos_contabeis
        )
        SELECT conta,
               SUM(debito)  AS total_debitos,
               SUM(credito) AS total_creditos,
               SUM(debito) - SUM(credito) AS saldo
        FROM movimentos
        GROUP BY conta
        ORDER BY conta
        """
    ).fetchall()


def popular_cenario_de_exemplo(conexao: sqlite3.Connection) -> None:
    """Cria produtos e registra um pequeno ciclo de compra/venda para demonstração."""
    cadastrar_produto(conexao, "TEC-001", "Teclado mecânico ABNT2")
    cadastrar_produto(conexao, "MOU-002", "Mouse sem fio")

    registrar_compra(conexao, "TEC-001", quantidade=20, valor_unitario=180.00, data="2026-05-02", observacao="NF 5001 - fornecedor TechParts")
    registrar_compra(conexao, "MOU-002", quantidade=30, valor_unitario=60.00, data="2026-05-02", observacao="NF 5001 - fornecedor TechParts")
    registrar_venda(conexao, "TEC-001", quantidade=8, valor_unitario=320.00, data="2026-05-10", observacao="NF 9001 - cliente Loja Central")
    registrar_compra(conexao, "TEC-001", quantidade=10, valor_unitario=190.00, data="2026-05-15", observacao="NF 5042 - fornecedor TechParts (reposição)")
    registrar_venda(conexao, "MOU-002", quantidade=12, valor_unitario=110.00, data="2026-05-18", observacao="NF 9002 - cliente Loja Central")
    registrar_venda(conexao, "TEC-001", quantidade=5, valor_unitario=325.00, data="2026-05-22", observacao="NF 9003 - cliente Papelaria União")


def _imprimir_estoque(conexao: sqlite3.Connection) -> None:
    print("=== Posição de estoque ===")
    for produto in posicao_de_estoque(conexao):
        print(
            f"  {produto['codigo']:8s} | {produto['nome']:28s} | "
            f"qtd: {produto['quantidade']:>6.0f} | custo médio: R$ {produto['custo_medio']:>8.2f} | "
            f"valor em estoque: R$ {produto['valor_em_estoque']:>10.2f}"
        )


def _imprimir_razao(conexao: sqlite3.Connection) -> None:
    print("=== Livro razão (lançamentos contábeis) ===")
    for lanc in livro_razao(conexao):
        print(
            f"  {lanc['data']} | D: {lanc['conta_debito']:32s} | C: {lanc['conta_credito']:32s} "
            f"| R$ {lanc['valor']:>10.2f} | {lanc['historico']}"
        )

    print()
    print("=== Saldos por conta (débito − crédito) ===")
    saldo_total = 0.0
    for linha in saldo_por_conta(conexao):
        print(
            f"  {linha['conta']:32s} | débitos: R$ {linha['total_debitos']:>10.2f} "
            f"| créditos: R$ {linha['total_creditos']:>10.2f} | saldo: R$ {linha['saldo']:>10.2f}"
        )
        saldo_total += linha["saldo"]

    # Em partidas dobradas, a soma de todos os saldos (débito − crédito) é
    # sempre zero — é a verificação clássica de que o razão está balanceado.
    print(f"\n  Soma de todos os saldos: R$ {saldo_total:.2f} (deve ser 0,00 — partidas dobradas balanceadas)")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "comando",
        choices=["demo", "estoque", "razao"],
        help="'demo' popula o banco de exemplo; 'estoque' e 'razao' exibem os relatórios",
    )
    parser.add_argument("--banco", default="erp_demo.db", help="caminho do arquivo SQLite (padrão: erp_demo.db)")
    args = parser.parse_args()

    conexao = sqlite3.connect(args.banco)
    try:
        criar_banco(conexao)
        if args.comando == "demo":
            ja_existem_produtos = conexao.execute("SELECT COUNT(*) FROM produtos").fetchone()[0] > 0
            if ja_existem_produtos:
                print(f"O banco '{args.banco}' já contém dados. Apague o arquivo para gerar o cenário do zero.")
                return
            popular_cenario_de_exemplo(conexao)
            print(f"Cenário de exemplo gravado em '{args.banco}'.\n")
            _imprimir_estoque(conexao)
            print()
            _imprimir_razao(conexao)
        elif args.comando == "estoque":
            _imprimir_estoque(conexao)
        elif args.comando == "razao":
            _imprimir_razao(conexao)
    finally:
        conexao.close()


if __name__ == "__main__":
    main()
