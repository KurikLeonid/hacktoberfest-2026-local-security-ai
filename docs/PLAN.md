# Local DLP Guard — план хакатона (3 часа)

## Context
Хакатон, команда из 2 человек: они контролируют, код пишет Claude. Делаем локальный DLP на ноутбуке (M1 Pro, 16GB).
Исходящие запросы из браузера в AI-чаты проверяет локальная Gemma 4 по whitelist доменов и политикам.
Каждый запрос получает один из трёх уровней: ALLOW, REVIEW или BLOCK. Security разбирает спорные запросы в локальной админке,
и его решения дописываются в датасет. Датасет сразу используется как примеры для модели, а позже пойдёт в finetune.
Никакие данные не покидают ноутбук.
Репо: https://github.com/KurikLeonid/hocktoberfest-2026-local-security-ai (пустой, публичный).

## Архитектура
```
Chrome ──(системный прокси macOS)──► mitmproxy :8080 + addon
   TLS расшифровывается только для inspect-доменов, остальное passthrough
   addon: адаптер (chatgpt.com / claude.ai / generic) → текст
        → pipeline (Gemma 4 E4B, Ollama) → score → уровень
        ALLOW  → пропустить, запись в лог
        REVIEW → держать запрос, событие → API → SSE в админку + уведомление macOS;
                 Approve → пропустить, Reject или 60 с без ответа → 403
        BLOCK  → 403 + уведомление macOS, событие в очередь (можно отметить false positive)
FastAPI :8000 (127.0.0.1): REST + SSE + статика собранного SPA, SQLite (WAL)
React SPA: Queue | Log | Policies | Dataset
```

## Pipeline классификации (core/classifier.py)
1. **Detect**: Gemma получает текст и отвечает JSON `{findings:[{span, category, reason}]}`. Если находок нет, ALLOW.
2. **Policy filter**: убираем находки, чья категория разрешена домену. Домен вне whitelist означает, что ничего не разрешено, а `credentials` не разрешены никуда. Если ничего не осталось, ALLOW.
3. **Verify**: для каждой оставшейся категории берём из датасета примеры этой категории: ~3 positive и ~3 negative/hard negative, решения security в приоритете. Gemma переоценивает каждую находку и возвращает `{finding_id, is_sensitive, confidence, reason}`.
4. **Score** = максимальный confidence среди подтверждённых нарушений. Если score < `review` (0.5), ALLOW. Если score ≥ `block` (0.85), BLOCK. Между ними REVIEW.
5. Ошибка Ollama, битый JSON или ответ дольше 30 с → BLOCK (fail-closed).
6. Найденные span'ы сохраняются вместе с событием. Админка подсвечивает их в тексте и показывает категорию и причину. Уведомление показывает категорию и замаскированный фрагмент.

## Политики (policies.yaml, hot reload по mtime)
- `categories`: pii, credentials, financial, customer_data, source_code, internal_docs
- `thresholds`: {review: 0.5, block: 0.85}; `review_timeout_s: 60`; `model_timeout_s: 30`
- `models`: {llm: gemma4 E4B (фолбэк E2B), точный тег проверяем при `ollama pull`}
- `inspect_domains`: chatgpt.com, claude.ai (+ домены для generic). Из них строится `allow_hosts` mitmproxy; после изменения нужен рестарт прокси, и админка об этом предупреждает.
- `domains`: claude.ai → [source_code, internal_docs]; chatgpt.com → [] (вне whitelist)
- `skip`: regex путей телеметрии и статики, которые не проверяются

## Датасет
- Строка: `{id, text, span?, category, label: sensitive|not_sensitive, source: hf:<id>|upload|security, created_at}` в SQLite.
- Загрузка в UI: JSONL/CSV в этой схеме.
- Кнопка «Импорт из HF» (качается один раз, дальше всё локально):
  - `gretelai/gretel-pii-masking-en-v1`, ~150 строк. Типы сущностей мапятся в категории: name/email/phone/address/ssn/dob → pii, credit_card/account/iban → financial. Span'ы берутся из `entities`.
  - `nisaefendioglu/synthetic-sensitive-data-in-source-code-n300`: sensitive → credentials (positive), clean и hard_negatives → negative.
- Решение security по каждой находке: Reject → `sensitive`, Approve/false positive → `not_sensitive`.
- Экспорт JSONL в chat-формате под LoRA (сам finetune вне скоупа).

## Структура репо
- `backend/` (uv, Python 3.12; системный python 3.14, поэтому версию пиним)
  - `proxy/guard.py`: mitmproxy addon (async hold для REVIEW, опрос решения в SQLite)
  - `proxy/adapters.py`: chatgpt (`POST /backend-api/.../conversation`, `messages[].content.parts`), claude (`POST /api/organizations/*/chat_conversations/*/completion`, `prompt`), generic (текстовое тело). Endpoint'ы сверяем вживую по логу mitmproxy.
  - `core/classifier.py`, `core/policies.py`, `core/store.py`, `core/hf_import.py`, `core/notify.py` (osascript)
  - `api/app.py`: FastAPI. `/api/events`, `/api/events/{id}/decision`, `/api/stream` (SSE), `/api/policies` (GET/PUT, импорт/экспорт YAML), `/api/dataset` (list/upload/import-hf/export). Внутренний `POST /internal/event` вызывается из addon.
- `frontend/`: Vite + React + TS + Tailwind
  - Queue: карточки с подсвеченными span'ами, таймер 60 с, Approve/Reject (Approve на BLOCK = false positive)
  - Log, Policies (матрица домены × категории, слайдеры порогов, импорт/экспорт YAML), Dataset (таблица, загрузка, импорт HF, экспорт)
- `scripts/`: `dlp-on.sh` / `dlp-off.sh` (networksetup на активном интерфейсе), `run.sh` (Ollama, API, mitmdump; trap → dlp-off)
- `policies.yaml`, `README.md` (запуск и демо-сценарий)

## Milestones (~3 ч)
Монорепо (`backend/`, `frontend/`, `scripts/`, `docs/`). Каждый milestone заканчивается коммитом `M<n>: …`.
- `docs/PLAN.md`: этот план без изменений (оригинал для сравнения).
- `docs/PROGRESS.md`: журнал по milestone'ам: что сделано, отклонения от плана и почему, что вырезано, время, как проверено.
Пуш в https://github.com/KurikLeonid/hocktoberfest-2026-local-security-ai.git (main) по окончании всех milestone'ов.

1. **M0** (0:00–0:20): клонировать репо, `docs/PLAN.md` + пустой `docs/PROGRESS.md`, `brew install ollama mitmproxy`, `ollama pull` Gemma 4 E4B, скелет uv и Vite
2. **M1** (0:20–1:00): policies, store, двухэтапный pipeline, CLI-проверка на примерах
3. **M2** (1:00–1:30): addon, адаптеры, уровни, hold, уведомления, dlp-on/off
4. **M3** (1:30–2:20): API, SSE, SPA (Queue → Log → Dataset → Policies)
5. **M4** (2:20–2:40): импорт HF, запись решений, экспорт
6. **M5** (2:40–3:00): прогон демо, README, финальная запись в PROGRESS.md, push
Если не успеваем, режем по порядку: адаптер claude.ai → форма политик (остаётся только YAML) → generic-фолбэк.

## Что делаете вы (Claude не может)
- Установить CA mitmproxy в Keychain (`~/.mitmproxy/mitmproxy-ca-cert.pem`, нужен пароль)
- Запустить `dlp-on` (может понадобиться пароль) и залогиниться в ChatGPT и Claude в Chrome

## Вне скоупа
Расшифровка доменов вне конфига, приложения с pinning, не-HTTP трафик, авторизация админки (только localhost), реальный finetune, удалённые алерты.

## Проверка
- `uv run python -m core.classifier "<текст>" --domain chatgpt.com` для трёх кейсов (безобидный вопрос, код с AWS-ключом, письмо с PII) выдаёт ожидаемые уровни
- `curl -x 127.0.0.1:8080 https://chatgpt.com/...` с телом в формате ChatGPT выдаёт 403 или зависает в REVIEW; в админке появляется карточка
- Живое демо: один и тот же внутренний код в claude.ai → ALLOW, в chatgpt.com → REVIEW/BLOCK с подсветкой. Ключ → BLOCK везде. Approve в REVIEW → ответ в чате приходит. Reject → строка в датасете, повторный похожий запрос использует её как пример.
- Остановили `run.sh` → системный прокси выключен, сеть работает.
