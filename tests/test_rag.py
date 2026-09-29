import httpx
import pytest

from app.core.config import get_settings
from app.domain.knowledge import (
    AGREEMENT_SCORE,
    Hit,
    interleave,
    is_relevant,
    reciprocal_rank_fusion,
)
from app.integrations.rag.index import KnowledgeIndex, entry_hash, entry_to_node

ENTRY = {
    "id": "dostavka-i-oplata:delivery",
    "title": "Доставка заказов",
    "category": "delivery",
    "keywords": ["доставка", "сдэк", "курьер"],
    "answer": "Доставка осуществляется службой СДЭК.",
    "upsell": "",
    "sensitive": False,
    "source_url": "https://o-complex.com/dostavka-i-oplata/",
}


def make_hit(fused: float, dense: float | None) -> Hit:
    return Hit("id", "t", "product", False, "a", "u", "https://x", fused, dense)


def test_entry_hash_changes_with_answer() -> None:
    changed = {**ENTRY, "answer": "Другой текст."}

    assert entry_hash(ENTRY) == entry_hash(dict(ENTRY))
    assert entry_hash(ENTRY) != entry_hash(changed)


def test_entry_to_node_puts_keywords_in_text_and_hides_metadata_from_embedding() -> None:
    node = entry_to_node(ENTRY)

    assert "Ключевые слова: доставка, сдэк, курьер." in node.text
    assert node.metadata["entry_id"] == ENTRY["id"]
    assert "answer" in node.excluded_embed_metadata_keys
    assert node.ref_doc_id == ENTRY["id"]


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    scores = reciprocal_rank_fusion(["a", "b", "c"], ["b", "d"])

    assert max(scores, key=scores.__getitem__) == "b"
    assert scores["b"] > scores["a"] > scores["d"]


def test_interleave_gives_each_subquestion_its_best_entry() -> None:
    topic = ["detox", "sets", "antiotek"]
    payment = ["payment", "order-process"]

    assert interleave([topic, payment, ["detox", "sets"]], limit=4) == ["detox", "payment", "sets", "order-process"]


def test_interleave_single_ranking_keeps_order() -> None:
    assert interleave([["a", "b", "c"]], limit=2) == ["a", "b"]


def test_interleave_empty() -> None:
    assert interleave([], limit=3) == []


def test_is_relevant_by_dense_score() -> None:
    assert is_relevant([make_hit(0.016, 0.85)], min_dense_score=0.81)
    assert not is_relevant([make_hit(0.016, 0.79)], min_dense_score=0.81)


def test_is_relevant_when_both_retrievers_agree() -> None:
    assert is_relevant([make_hit(AGREEMENT_SCORE, 0.5)], min_dense_score=0.81)


def test_is_relevant_empty() -> None:
    assert not is_relevant([], min_dense_score=0.81)


def embeddings_available() -> bool:
    try:
        return httpx.get(f"{get_settings().embeddings_url}/health", timeout=2, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not embeddings_available(), reason="сервис эмбеддингов недоступен")
@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("Сколько стоит цеолит макс?", "product-zeolite-max-67"),
        ("Как можно оплатить заказ?", "dostavka-i-oplata:payment"),
        ("Хочу стать вашим дистрибьютором", "optovoye-sotrudnichestvo:wholesale-partnership"),
    ],
)
def test_search_finds_expected_entry_first(query: str, expected_id: str) -> None:
    hits = KnowledgeIndex(get_settings()).search(query, top_k=3)

    assert hits[0].entry_id == expected_id


@pytest.mark.skipif(not embeddings_available(), reason="сервис эмбеддингов недоступен")
@pytest.mark.parametrize("query", ["как настроить роутер wifi", "какая сегодня погода в Москве", "привет"])
def test_search_marks_offtopic_queries_irrelevant(query: str) -> None:
    settings = get_settings()

    hits = KnowledgeIndex(settings).search(query, top_k=3)

    assert not is_relevant(hits, settings.rag_min_dense_score)


def test_entry_node_carries_promo_price_in_metadata_and_changes_hash() -> None:
    with_promo = {**ENTRY, "price_rub": 4090, "promo_price_rub": 3490}

    assert entry_to_node(with_promo).metadata["promo_price_rub"] == 3490
    assert entry_hash(with_promo) != entry_hash({**with_promo, "promo_price_rub": 3000})
