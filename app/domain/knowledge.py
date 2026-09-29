"""Сущности и чистая логика поиска по базе знаний: найденная запись, слияние рейтингов, порог релевантности."""

from dataclasses import dataclass

CANDIDATES_PER_RETRIEVER = 8
RRF_K = 60
AGREEMENT_SCORE = 2 / (RRF_K + CANDIDATES_PER_RETRIEVER)


@dataclass(frozen=True)
class Hit:
    """Найденная запись базы знаний.

    Attributes:
        entry_id: Идентификатор записи (slug страницы или ``страница:тема``).
        title: Заголовок записи.
        category: Категория записи.
        sensitive: Запись затрагивает здоровье: ответ по ней должен быть осторожным.
        answer: Фактический текст записи для ответа клиенту.
        upsell: Подсказка по допродаже, связанная с записью.
        source_url: Страница сайта, откуда взята запись.
        fused_score: Итоговая оценка Reciprocal Rank Fusion (чем больше, тем релевантнее).
        dense_score: Косинусная близость из векторного поиска или None, если запись найдена только по тексту.
        promo_price_rub: Цена по промокоду в рублях, если она есть; подаётся модели отдельной строкой,
            а не в тексте записи, чтобы промокод не звучал в каждом ответе.
    """

    entry_id: str
    title: str
    category: str
    sensitive: bool
    answer: str
    upsell: str
    source_url: str
    fused_score: float
    dense_score: float | None
    promo_price_rub: int | None = None


def reciprocal_rank_fusion(*rankings: list[str]) -> dict[str, float]:
    """Объединяет несколько ранжирований методом Reciprocal Rank Fusion.

    Args:
        *rankings: Списки идентификаторов, упорядоченные от лучшего к худшему.

    Returns:
        Словарь «идентификатор -> суммарная оценка».
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def interleave(rankings: list[list[str]], limit: int) -> list[str]:
    """Чередует несколько ранжирований, чтобы каждый подвопрос получил свои лучшие записи.

    Сумма рангов (RRF) отдала бы всё место теме, общей для нескольких запросов, и вытеснила бы ответ на узкий
    подвопрос («как оплатить»); чередование по кругу этого не допускает.

    Args:
        rankings: Списки идентификаторов, упорядоченные от лучшего к худшему; порядок списков задаёт приоритет.
        limit: Сколько идентификаторов вернуть.

    Returns:
        Идентификаторы без повторов в порядке обхода «по кругу».
    """
    result: list[str] = []
    for position in range(max((len(ranking) for ranking in rankings), default=0)):
        for ranking in rankings:
            if position < len(ranking) and ranking[position] not in result:
                result.append(ranking[position])
    return result[:limit]


def is_relevant(hits: list[Hit], min_dense_score: float) -> bool:
    """Решает, есть ли в найденном что-то по теме обращения.

    Запись считается подходящей, если векторная близость выше порога либо её нашли оба поиска (векторный и
    текстовый): в этом случае итоговая оценка почти вдвое выше, чем у записи, найденной одним из них.

    Args:
        hits: Результат поиска по базе знаний.
        min_dense_score: Минимальная косинусная близость (настройка ``rag_min_dense_score``).

    Returns:
        True, если ответ можно строить на найденных записях; False — обращение вне базы знаний.
    """
    return any(
        (hit.dense_score is not None and hit.dense_score >= min_dense_score) or hit.fused_score >= AGREEMENT_SCORE
        for hit in hits
    )
