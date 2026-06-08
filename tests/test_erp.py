import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from erp import (
    CONTA_CLIENTES,
    CONTA_CMV,
    CONTA_ESTOQUE,
    CONTA_FORNECEDORES,
    CONTA_RECEITA,
    EstoqueInsuficiente,
    cadastrar_produto,
    criar_banco,
    livro_razao,
    posicao_de_estoque,
    registrar_compra,
    registrar_venda,
    saldo_por_conta,
)


@pytest.fixture()
def banco() -> sqlite3.Connection:
    conexao = sqlite3.connect(":memory:")
    criar_banco(conexao)
    cadastrar_produto(conexao, "TEC-001", "Teclado mecânico ABNT2")
    yield conexao
    conexao.close()


def test_compra_atualiza_quantidade_e_custo_medio(banco: sqlite3.Connection):
    registrar_compra(banco, "TEC-001", quantidade=10, valor_unitario=100.00, data="2026-05-01")
    registrar_compra(banco, "TEC-001", quantidade=10, valor_unitario=120.00, data="2026-05-05")

    produto = posicao_de_estoque(banco)[0]
    # Custo médio ponderado: (10*100 + 10*120) / 20 = 110
    assert produto["quantidade"] == pytest.approx(20)
    assert produto["custo_medio"] == pytest.approx(110.00)


def test_compra_gera_lancamento_de_debito_em_estoque_e_credito_em_fornecedores(banco: sqlite3.Connection):
    registrar_compra(banco, "TEC-001", quantidade=10, valor_unitario=100.00, data="2026-05-01")

    lancamentos = livro_razao(banco)
    assert len(lancamentos) == 1
    assert lancamentos[0]["conta_debito"] == CONTA_ESTOQUE
    assert lancamentos[0]["conta_credito"] == CONTA_FORNECEDORES
    assert lancamentos[0]["valor"] == pytest.approx(1000.00)


def test_venda_da_baixa_no_estoque_pelo_custo_medio(banco: sqlite3.Connection):
    registrar_compra(banco, "TEC-001", quantidade=10, valor_unitario=100.00, data="2026-05-01")
    registrar_venda(banco, "TEC-001", quantidade=4, valor_unitario=180.00, data="2026-05-10")

    produto = posicao_de_estoque(banco)[0]
    assert produto["quantidade"] == pytest.approx(6)


def test_venda_gera_dois_lancamentos_receita_e_cmv(banco: sqlite3.Connection):
    registrar_compra(banco, "TEC-001", quantidade=10, valor_unitario=100.00, data="2026-05-01")
    registrar_venda(banco, "TEC-001", quantidade=4, valor_unitario=180.00, data="2026-05-10")

    lancamentos = livro_razao(banco)
    lancamentos_da_venda = [l for l in lancamentos if "Venda" in l["historico"]]
    assert len(lancamentos_da_venda) == 2

    receita = next(l for l in lancamentos_da_venda if l["conta_credito"] == CONTA_RECEITA)
    assert receita["conta_debito"] == CONTA_CLIENTES
    assert receita["valor"] == pytest.approx(4 * 180.00)

    cmv = next(l for l in lancamentos_da_venda if l["conta_debito"] == CONTA_CMV)
    assert cmv["conta_credito"] == CONTA_ESTOQUE
    assert cmv["valor"] == pytest.approx(4 * 100.00)  # baixa pelo custo médio, não pelo preço de venda


def test_venda_acima_do_estoque_disponivel_levanta_erro(banco: sqlite3.Connection):
    registrar_compra(banco, "TEC-001", quantidade=5, valor_unitario=100.00, data="2026-05-01")

    with pytest.raises(EstoqueInsuficiente):
        registrar_venda(banco, "TEC-001", quantidade=10, valor_unitario=180.00, data="2026-05-10")

    # a tentativa de venda não deve ter alterado o estoque
    produto = posicao_de_estoque(banco)[0]
    assert produto["quantidade"] == pytest.approx(5)


def test_partidas_dobradas_ficam_balanceadas(banco: sqlite3.Connection):
    registrar_compra(banco, "TEC-001", quantidade=10, valor_unitario=100.00, data="2026-05-01")
    registrar_venda(banco, "TEC-001", quantidade=4, valor_unitario=180.00, data="2026-05-10")
    registrar_compra(banco, "TEC-001", quantidade=5, valor_unitario=110.00, data="2026-05-15")
    registrar_venda(banco, "TEC-001", quantidade=3, valor_unitario=190.00, data="2026-05-20")

    saldos = saldo_por_conta(banco)
    soma_dos_saldos = sum(linha["saldo"] for linha in saldos)

    # Em partidas dobradas, a soma de (débitos - créditos) de todas as contas é sempre zero.
    assert soma_dos_saldos == pytest.approx(0.0)
