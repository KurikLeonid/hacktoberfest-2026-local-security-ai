# Duh'ot'A — локальный DLP для AI-чатов на Gemma 4

<img src="docs/logo-v2.svg" alt="Охранник не даёт сотруднику с бейджем нажать ENTER" width="360">

## 1. Что это и для кого

Сотрудники вставляют в ChatGPT и Claude ключи, таблицы с зарплатами, письма клиентов и данные о здоровье коллег.
За данные из GDPR ст. 9/10 штрафуют сильнее всего, а облачный DLP сам требует отправить текст наружу.

**Duh'ot'A** — прокси на ноутбуке сотрудника. Он читает промпты в AI-чатах, а локальная **Gemma 4** решает:
пропустить (ALLOW), задержать до решения security (REVIEW) или заблокировать (BLOCK). Решения security сразу
становятся примерами для модели. В основном режиме **ни один байт не уходит за пределы ноутбука**.

Для кого: security- и compliance-команды компаний, которые разрешают сотрудникам AI-чаты, но не хотят утечек и штрафов.
Попутно продукт считает нецелевые запросы («рецепт борща» с рабочего ноутбука): они проходят, но видны в статистике.

```
Chrome ─(системный прокси)─► mitmproxy :8080 + guard.py ──► chatgpt.com / claude.ai
                                   │ адаптер → текст промпта
                                   ▼
                     Gemma 4 детект → фильтр по whitelist → верификация на примерах из датасета
                                   │ score
               ALLOW (<0.5) ── REVIEW (держим до 60 с, ждём security) ── BLOCK (≥0.9, сразу 403)
                                   │
                  FastAPI :8000 + React админка (SSE) ── решения → датасет → экспорт JSONL для LoRA
```

## 2. Как запустить

Требуется macOS, Homebrew, [uv](https://docs.astral.sh/uv/) и Node. Первая польза — через ~5 минут после установки
(без учёта загрузки модели): открыть админку, вкладка «Проверить текст», вставить текст — ответ за 1–5 с.

```bash
brew install ollama && ollama serve &
ollama pull gemma4:e4b
```

```bash
cp backend/.env.example backend/.env
cd backend && uv sync && cd ../frontend && npm install && npm run build && cd ..
```

Только админка и проверка текста, без изменения сетевых настроек:

```bash
scripts/run.sh --no-system-proxy
```

Перехват браузера: один раз доверить CA mitmproxy (создаётся при первом запуске, нужен пароль администратора),
потом запустить с системным прокси. При Ctrl+C прокси выключается; если сеть осталась на прокси — `scripts/dlp-off.sh`.

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
```

```bash
scripts/run.sh
```

Админка: http://127.0.0.1:8000 — очередь, журнал, «Проверить текст», политики, датасет (кнопка «Импорт из HF»).

## 3. Экспертиза: что зашили и откуда это знание

| Что | Где в коде | Откуда знание |
|---|---|---|
| Таксономия: `pii`, `special_pii` (GDPR ст. 9/10: здоровье, вес, беременность, биометрия, религия, происхождение, ориентация, профсоюз, политика, судимости, **включая непрямую идентификацию**), `credentials`, `financial`, `customer_data`, `source_code`, `internal_docs` | `CATEGORY_HELP` в [backend/core/classifier.py](backend/core/classifier.py) | GDPR ст. 9, 10, 83; практика DLP/security-команд |
| Шкала уверенности: 0.9+ только однозначный вред, 0.5–0.85 — нужен человек | промпт `verify` там же | калибровка на eval (см. ниже) |
| Обфускация: карта словами, `name dot surname at company`, транслит, таблицы, данные в длинном тексте; hard negatives: публичные отчёты, исторические личности, тестовые карты Stripe | промпт `detect` там же, кейсы в [backend/eval/cases.yaml](backend/eval/cases.yaml) | типовые обходы DLP |
| Правила «куда что можно»: whitelist доменов × категорий, `never_allowed` | [policies.yaml](policies.yaml) | политика компании, редактируется в админке |
| Размеченные примеры для few-shot | SQLite-датасет, импорт [backend/core/hf_import.py](backend/core/hf_import.py) | [gretelai/gretel-pii-masking-en-v1](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1), [nisaefendioglu/synthetic-sensitive-data-in-source-code-n300](https://huggingface.co/datasets/nisaefendioglu/synthetic-sensitive-data-in-source-code-n300) + решения security |
| Граница «рабочий / нецелевой запрос» | `purpose` в [policies.yaml](policies.yaml) | правило компании |

Где вызывается модель: `detect()` и `verify()` → `_chat()` в [backend/core/classifier.py](backend/core/classifier.py).

## 4. Модель и её лицензия

- **Основной режим: Gemma 4 E4B локально через Ollama** (`gemma4:e4b`). Лицензия: Apache License 2.0 — файл
  лицензии поставляется вместе с весами (`ollama show gemma4:e4b --license`), страница модели:
  https://ollama.com/library/gemma4.
- **Опциональный режим: Gemma 4 31B через Gemini API** (`gemma-4-31b-it`) — для слабых ноутбуков и для трека
  «Best Use of Gemma 4». Включается в `backend/.env`: `DLP_LLM_PROVIDER=gemini`, `GEMINI_MODEL=gemma-4-31b-it`,
  `GEMINI_API_KEY=...`. **В этом режиме проверяемый текст уходит в Google** — админка показывает это красной плашкой.
  Интеграция: `_chat_gemini()` в [backend/core/classifier.py](backend/core/classifier.py). Условия: https://ai.google.dev/gemini-api/terms.
- Gemini flash-lite использовался только как временная замена при разработке (пока качалась Gemma); в продукте его нет.

## 5. Доказательство: с Duh'ot'A лучше, чем с той же моделью без него

Те же 10 кейсов (15 проверок: часть идёт на два домена), та же **Gemma 4 E4B** на ноутбуке.
«Голая» Gemma получает один вопрос «можно ли отправить это на <домен>?» — без категорий, whitelist, примеров и калибровки
(`uv run python -m eval.run --provider ollama --examples bare --only ...`).

| | Голая Gemma 4 E4B | Duh'ot'A на Gemma 4 E4B |
|---|---|---|
| Верных решений | 7 / 15 (47%) | **15 / 15 (100%)** |
| Утечки (пропустила то, что нельзя) | **7**: беременность сотрудницы, рабочий email в подписи, email словами, карта прописью, внутренний код в ChatGPT | **0** |
| Ложные блоки | 1 (тестовая карта Stripe 4242…) | **0** |
| Задержка p50 | 0.6 с | 5.0 с |

Разницу дают таксономия GDPR, whitelist доменов, примеры из датасета и шкала калибровки. Полный набор — 42 кейса
(65 проверок) на EN/RU: GDPR ст. 9/10, PII, финансы, клиенты, секреты, hard negatives, нецелевые. Gemma 4 E4B — 97% верных,
1 утечка, 1 ложный блок. Отдельно 2 кейса prompt injection — оба BLOCK. Детали и все прогоны — [docs/EVAL.md](docs/EVAL.md),
сырые результаты — `backend/eval/results/`.

## Где не работает

- Расшифровываются только домены из `inspect_domains`; приложения с certificate pinning, не-HTTP трафик, вложения-картинки и PDF не проверяются.
- Base64 и другие кодировки не распознаются.
- Адаптеры ChatGPT/Claude завязаны на текущие внутренние API этих сайтов.
- MLX-сборка `gemma4:e4b` на Mac с 16 ГБ занимает 12–17 ГБ; большие таблицы проверяются до ~13 с. Квантованная `gemma4:e4b-it-qat` должна быть быстрее (не проверено).
- Уверенность модели «плавает» на ±0.05: пограничный код иногда идёт в BLOCK вместо REVIEW.
- У админки нет авторизации, она слушает только 127.0.0.1. Finetune не сделан, экспортируется только датасет.

## Безопасность

- Prompt injection: проверяемый текст передаётся модели как недоверенные данные, промпты запрещают выполнять инструкции из него; кейсы `prompt_injection` в eval («ignore previous instructions…») блокируются.
- Fail-closed: ошибка модели, невалидный ответ или таймаут → BLOCK.
- Ключи только в `backend/.env` (в `.gitignore`), шаблон — `backend/.env.example`. Тесты и eval — только обезличенные синтетические данные.
- Продукт не даёт юридических советов: категории GDPR используются как правила фильтрации, а не как консультация.

## Структура
```
backend/  core/ (policies, store, classifier, hf_import, notify) · proxy/ (guard, adapters) · api/app.py · eval/ · tests/
frontend/ Vite + React + TS + Tailwind
scripts/  run.sh · dlp-on.sh · dlp-off.sh
policies.yaml · AGENTS.md · LICENSE (MIT)
docs/     PLAN.md · PROGRESS.md · EVAL.md
```

Лицензия проекта: [MIT](LICENSE).
