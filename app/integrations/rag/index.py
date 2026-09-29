"""Индекс базы знаний в pgvector через LlamaIndex: индексация и гибридный поиск.

Поиск объединяет векторную близость (эмбеддинги TEI) и полнотекстовый поиск Postgres (конфигурация ``russian``)
методом Reciprocal Rank Fusion. Для порога релевантности сохраняется косинусная близость векторной выдачи.
"""

import hashlib
import json
from dataclasses import replace
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.core.vector_stores.types import VectorStoreQueryMode
from llama_index.embeddings.text_embeddings_inference import TextEmbeddingsInference
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.domain.knowledge import CANDIDATES_PER_RETRIEVER, Hit, interleave, reciprocal_rank_fusion

CHUNKS_TABLE = "kb_chunks"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
METADATA_KEYS = ("entry_id", "title", "category", "sensitive", "answer", "upsell", "source_url", "promo_price_rub")


def entry_hash(entry: dict[str, Any]) -> str:
    """Считает хеш содержимого записи, влияющего на индекс.

    Args:
        entry: Запись из knowledge_base.json.

    Returns:
        SHA-256 в hex; меняется при изменении текста или метаданных записи.
    """
    keys = ("id", "title", "category", "keywords", "answer", "upsell", "sensitive", "price_rub", "promo_price_rub")
    payload = {key: entry.get(key) for key in keys}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def entry_to_node(entry: dict[str, Any]) -> TextNode:
    """Превращает запись базы знаний в узел LlamaIndex.

    В эмбеддинг и полнотекстовый индекс идут заголовок, ответ и ключевые слова; метаданные в них не попадают.

    Args:
        entry: Запись из knowledge_base.json.

    Returns:
        TextNode со ссылкой на «документ» (id записи) для удаления при переиндексации.
    """
    metadata = {
        "entry_id": entry["id"],
        "title": entry["title"],
        "category": entry["category"],
        "sensitive": entry["sensitive"],
        "answer": entry["answer"],
        "upsell": entry["upsell"],
        "source_url": entry["source_url"],
        "promo_price_rub": entry.get("promo_price_rub"),
    }
    text = f"{entry['title']}. {entry['answer']} Ключевые слова: {', '.join(entry['keywords'])}."
    return TextNode(
        id_=entry["id"],
        text=text,
        metadata=metadata,
        excluded_embed_metadata_keys=list(METADATA_KEYS),
        excluded_llm_metadata_keys=list(METADATA_KEYS),
        relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id=entry["id"])},
    )


class KnowledgeIndex:
    """Индекс базы знаний в pgvector с гибридным поиском (реализует порт Retriever).

    Attributes:
        embed_model: Клиент сервиса Text Embeddings Inference.
        vector_store: Хранилище LlamaIndex в таблице ``data_kb_chunks``.
        index: VectorStoreIndex поверх хранилища.
    """

    def __init__(self, settings: Settings) -> None:
        """Подключается к TEI и Postgres.

        Args:
            settings: Настройки приложения (адрес TEI, DSN Postgres, модель и размерность эмбеддингов).
        """
        url = make_url(settings.database_url)
        self.embed_model = TextEmbeddingsInference(
            model_name=settings.embedding_model,
            base_url=settings.embeddings_url,
            text_instruction=PASSAGE_PREFIX,
            query_instruction=QUERY_PREFIX,
            embed_batch_size=16,
            timeout=60,
        )
        self.vector_store = PGVectorStore.from_params(
            host=url.host,
            port=str(url.port or 5432),
            database=url.database,
            user=url.username,
            password=url.password,
            table_name=CHUNKS_TABLE,
            embed_dim=settings.embedding_dim,
            hybrid_search=True,
            text_search_config="russian",
        )
        self.index = VectorStoreIndex.from_vector_store(self.vector_store, embed_model=self.embed_model)
        self._dense = self.index.as_retriever(similarity_top_k=CANDIDATES_PER_RETRIEVER)
        self._sparse = self.index.as_retriever(
            similarity_top_k=CANDIDATES_PER_RETRIEVER, vector_store_query_mode=VectorStoreQueryMode.SPARSE
        )

    def remove(self, entry_ids: list[str]) -> None:
        """Удаляет фрагменты записей из индекса.

        Args:
            entry_ids: Идентификаторы записей.
        """
        for entry_id in entry_ids:
            self.vector_store.delete(ref_doc_id=entry_id)

    def add(self, entries: list[dict[str, Any]]) -> None:
        """Считает эмбеддинги и добавляет записи в индекс.

        Args:
            entries: Записи из knowledge_base.json; ранее проиндексированные версии нужно удалить через remove.
        """
        if entries:
            self.index.insert_nodes([entry_to_node(entry) for entry in entries])

    def search(self, query: str, top_k: int = 4) -> list[Hit]:
        """Ищет записи, релевантные запросу клиента.

        Args:
            query: Текст обращения клиента.
            top_k: Сколько записей вернуть.

        Returns:
            Записи по убыванию итоговой оценки; пустой список, если ничего не найдено.
        """
        dense = self._dense.retrieve(query)
        sparse = self._sparse.retrieve(query)
        nodes = {item.node.node_id: item.node for item in [*dense, *sparse]}
        dense_scores = {item.node.node_id: item.score for item in dense}
        fused = reciprocal_rank_fusion([i.node.node_id for i in dense], [i.node.node_id for i in sparse])
        best = sorted(fused, key=fused.__getitem__, reverse=True)[:top_k]
        return [self._to_hit(nodes[node_id], fused[node_id], dense_scores.get(node_id)) for node_id in best]

    def search_many(self, queries: list[str], top_k: int = 5) -> list[Hit]:
        """Ищет по нескольким запросам и объединяет результаты.

        Порядок задаёт чередование запросов по кругу (interleave); для каждой записи сохраняются лучшая
        косинусная близость и лучшая итоговая оценка среди запросов (они нужны для порога релевантности).

        Args:
            queries: Поисковые запросы (подвопросы обращения).
            top_k: Сколько записей вернуть.

        Returns:
            Записи по убыванию объединённой оценки.
        """
        per_query = [self.search(query, top_k=CANDIDATES_PER_RETRIEVER) for query in queries]
        order = interleave([[hit.entry_id for hit in hits] for hits in per_query], top_k)
        best: dict[str, Hit] = {}
        for hits in per_query:
            for hit in hits:
                known = best.get(hit.entry_id)
                if known is None:
                    best[hit.entry_id] = hit
                    continue
                dense = [score for score in (known.dense_score, hit.dense_score) if score is not None]
                best[hit.entry_id] = replace(
                    known, fused_score=max(known.fused_score, hit.fused_score), dense_score=max(dense, default=None)
                )
        return [best[entry_id] for entry_id in order]

    @staticmethod
    def _to_hit(node: Any, fused_score: float, dense_score: float | None) -> Hit:
        """Собирает Hit из узла LlamaIndex.

        Args:
            node: Найденный узел с метаданными записи.
            fused_score: Оценка Reciprocal Rank Fusion.
            dense_score: Косинусная близость или None.

        Returns:
            Неизменяемый Hit.
        """
        meta = node.metadata
        return Hit(
            entry_id=meta["entry_id"],
            title=meta["title"],
            category=meta["category"],
            sensitive=bool(meta["sensitive"]),
            answer=meta["answer"],
            upsell=meta["upsell"],
            source_url=meta["source_url"],
            fused_score=fused_score,
            dense_score=dense_score,
            promo_price_rub=meta.get("promo_price_rub"),
        )
