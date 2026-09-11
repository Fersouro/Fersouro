"""Diretorios transitorios da gold nao podem virar dataset.

Um Ctrl+C ou queda de energia no meio da escrita deixa ".staging-<run_id>"
(parquet truncado) ou ".old" (copia anterior) no disco. Registrado como view,
o staging quebrado derruba TODA consulta ao lake -- nao so a do modelo que
falhou. Foi o que aconteceu em producao: um 'datalake query' qualquer passou a
responder "File ... too small to be a Parquet file".
"""

from datalake.storage.paths import gold_model_dirs, is_transient_dir


def _com_parquet(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "data.parquet").write_bytes(b"PAR1")
    return pasta


def test_reconhece_transitorios():
    from pathlib import Path

    assert is_transient_dir(Path("gold/demanda_pecas.staging-20260910T201300-9d7a8ce3"))
    assert is_transient_dir(Path("gold/demanda_pecas.old"))
    assert not is_transient_dir(Path("gold/demanda_pecas"))
    # Nome legitimo que apenas contem "old" nao pode ser confundido.
    assert not is_transient_dir(Path("gold/pecas_old_stock"))


def test_gold_model_dirs_ignora_staging_e_old(tmp_path):
    gold = tmp_path / "gold"
    _com_parquet(gold / "estoque_pecas")
    _com_parquet(gold / "demanda_pecas")
    _com_parquet(gold / "demanda_pecas.staging-20260910T201300-9d7a8ce3")
    _com_parquet(gold / "estoque_pecas.old")

    assert sorted(gold_model_dirs(gold)) == ["demanda_pecas", "estoque_pecas"]


def test_gold_model_dirs_ignora_pasta_sem_parquet(tmp_path):
    gold = tmp_path / "gold"
    _com_parquet(gold / "estoque_pecas")
    (gold / "vazia").mkdir()

    assert sorted(gold_model_dirs(gold)) == ["estoque_pecas"]


def test_gold_model_dirs_sem_raiz(tmp_path):
    assert gold_model_dirs(tmp_path / "nao_existe") == {}
