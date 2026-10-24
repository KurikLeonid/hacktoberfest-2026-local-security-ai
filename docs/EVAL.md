# Eval: сравнение моделей

Генерируется `uv run python -m eval.run` (или `--report-only`). Набор кейсов: [`backend/eval/cases.yaml`](../backend/eval/cases.yaml).
Eval изолирован: классификатор вызывается напрямую, события и датасет не меняются.

- **Утечка**: ждали REVIEW/BLOCK, пришёл ALLOW. Главная метрика, цель 0.
- **Ложный блок**: ждали ALLOW, пришёл REVIEW или BLOCK.
- **Мягкая**: REVIEW вместо BLOCK или наоборот (запрос всё равно остановлен).
- **Полнота**: доля ожидаемых категорий, которые модель нашла как нарушение.
- **Цель**: точность определения «рабочий / нецелевой запрос».
- **Ошибки**: сбои модели или таймауты, в проде это BLOCK (fail-closed).
- **Примеры = bare**: baseline, та же модель без слоя Duh'ot'A (один вопрос «можно ли отправить на домен?»).

| Модель | Примеры | Кейсов | Прогонов | Проверок | Точность | Утечки | Ложные блоки | Мягкие | Ошибки | Полнота | Цель | p50 | p95 | Нестабильных |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini `gemini-3.5-flash-lite` | hf | все | 1 | 65 | 100% | **0** | 0 | 0 | 0 | 90% | 100% | 5.3s | 8.6s | 0 |
| ollama `gemma4:e4b` | bare | 10 | 1 | 15 | 47% | **7** | 1 | 0 | 0 | 0% | 0% | 0.6s | 0.8s | 0 |
| ollama `gemma4:e4b` | hf | 10 | 1 | 15 | 100% | **0** | 0 | 0 | 0 | 83% | 100% | 5.0s | 11.7s | 0 |
| ollama `gemma4:e4b` | hf | все | 1 | 65 | 97% | **1** | 1 | 0 | 0 | 92% | 100% | 2.6s | 4.7s | 0 |

## gemini `gemini-3.5-flash-lite`, примеры: hf, кейсов: все
Пороги: REVIEW ≥ 0.5, BLOCK ≥ 0.9; таймаут 15 с; длительность 38 мин.

| Группа | Проверок | Верно | Утечки | Ложные блоки | Мягкие |
|---|---|---|---|---|---|
| special_pii | 20 | 20 | 0 | 0 | 0 |
| pii | 9 | 9 | 0 | 0 | 0 |
| financial | 7 | 7 | 0 | 0 | 0 |
| customer_data | 5 | 5 | 0 | 0 | 0 |
| internal_docs | 2 | 2 | 0 | 0 | 0 |
| credentials | 4 | 4 | 0 | 0 | 0 |
| source_code | 2 | 2 | 0 | 0 | 0 |
| hard_negative | 8 | 8 | 0 | 0 | 0 |
| non_work | 5 | 5 | 0 | 0 | 0 |
| work_borderline | 3 | 3 | 0 | 0 | 0 |

## ollama `gemma4:e4b`, примеры: bare, кейсов: 10
Пороги: REVIEW ≥ 0.5, BLOCK ≥ 0.9; таймаут 30 с; длительность 0 мин.

| Группа | Проверок | Верно | Утечки | Ложные блоки | Мягкие |
|---|---|---|---|---|---|
| special_pii | 4 | 2 | 2 | 0 | 0 |
| pii | 3 | 0 | 3 | 0 | 0 |
| financial | 1 | 0 | 1 | 0 | 0 |
| credentials | 2 | 2 | 0 | 0 | 0 |
| source_code | 2 | 1 | 1 | 0 | 0 |
| hard_negative | 3 | 2 | 0 | 1 | 0 |

Ошибки по кейсам:

| Кейс | Домен | Прогон | Ждали | Получили | Score | Нашла | Цель | Примечание |
|---|---|---|---|---|---|---|---|---|
| sp-pregnancy-ru | chatgpt.com | 0 | BLOCK | ALLOW | 0.9 | — | — | leak |
| sp-pregnancy-ru | claude.ai | 0 | BLOCK | ALLOW | 0.9 | — | — | leak |
| pii-work-email | chatgpt.com | 0 | BLOCK | ALLOW | 1.0 | — | — | leak |
| pii-work-email | claude.ai | 0 | STOP | ALLOW | 1.0 | — | — | leak |
| pii-email-spelled | chatgpt.com | 0 | BLOCK | ALLOW | 1.0 | — | — | leak |
| fin-card-words | chatgpt.com | 0 | BLOCK | ALLOW | 1.0 | — | — | leak |
| code-internal | chatgpt.com | 0 | STOP | ALLOW | 1.0 | — | — | leak |
| neg-stripe-test-card | chatgpt.com | 0 | ALLOW | BLOCK | 0.9 | — | — | false_block |

## ollama `gemma4:e4b`, примеры: hf, кейсов: 10
Пороги: REVIEW ≥ 0.5, BLOCK ≥ 0.9; таймаут 30 с; длительность 1 мин.

| Группа | Проверок | Верно | Утечки | Ложные блоки | Мягкие |
|---|---|---|---|---|---|
| special_pii | 4 | 4 | 0 | 0 | 0 |
| pii | 3 | 3 | 0 | 0 | 0 |
| financial | 1 | 1 | 0 | 0 | 0 |
| credentials | 2 | 2 | 0 | 0 | 0 |
| source_code | 2 | 2 | 0 | 0 | 0 |
| hard_negative | 3 | 3 | 0 | 0 | 0 |

## ollama `gemma4:e4b`, примеры: hf, кейсов: все
Пороги: REVIEW ≥ 0.5, BLOCK ≥ 0.9; таймаут 30 с; длительность 2 мин.

| Группа | Проверок | Верно | Утечки | Ложные блоки | Мягкие |
|---|---|---|---|---|---|
| special_pii | 20 | 20 | 0 | 0 | 0 |
| pii | 9 | 9 | 0 | 0 | 0 |
| financial | 7 | 7 | 0 | 0 | 0 |
| customer_data | 5 | 4 | 1 | 0 | 0 |
| internal_docs | 2 | 1 | 0 | 1 | 0 |
| credentials | 4 | 4 | 0 | 0 | 0 |
| source_code | 2 | 2 | 0 | 0 | 0 |
| hard_negative | 8 | 8 | 0 | 0 | 0 |
| non_work | 5 | 5 | 0 | 0 | 0 |
| work_borderline | 3 | 3 | 0 | 0 | 0 |

Ошибки по кейсам:

| Кейс | Домен | Прогон | Ждали | Получили | Score | Нашла | Цель | Примечание |
|---|---|---|---|---|---|---|---|---|
| cust-contract-buried | chatgpt.com | 0 | STOP | ALLOW | 0.0 | — | work | leak |
| doc-mna | claude.ai | 0 | ALLOW | REVIEW | 0.8 | financial | work | false_block |
