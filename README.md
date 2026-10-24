# Local DLP Guard

Локальный DLP для ноутбука. Исходящие запросы в AI-чаты (ChatGPT, Claude) проверяет локальная **Gemma 4** через Ollama.
Модель сверяет найденные данные с whitelist доменов и политиками. Каждый запрос пропускается, задерживается до решения
security или блокируется. Решения security копятся в датасет: он сразу используется как few-shot, а позже пойдёт в LoRA finetune.
**Ни один байт не уходит за пределы ноутбука.**

План: [docs/PLAN.md](docs/PLAN.md) · журнал выполнения: [docs/PROGRESS.md](docs/PROGRESS.md)

```
Chrome ─(системный прокси)─► mitmproxy :8080 + guard.py ──► chatgpt.com / claude.ai
                                   │ адаптер → текст промпта
                                   ▼
                     Gemma 4 (Ollama) детект → фильтр по whitelist → верификация на примерах из датасета
                                   │ score
               ALLOW (<0.5) ── REVIEW (держим до 60 с, ждём security) ── BLOCK (≥0.85, сразу 403)
                                   │
                  FastAPI :8000 + React админка (SSE) ── решения → датасет → экспорт JSONL для LoRA
```

## Как работает проверка
1. **Detect**: Gemma находит в тексте чувствительные фрагменты и относит их к категориям: `pii`, `credentials`, `financial`, `customer_data`, `source_code`, `internal_docs`.
2. **Policy**: находки, чья категория разрешена домену по whitelist, снимаются. `credentials` запрещены везде.
3. **Verify**: оставшиеся находки Gemma переоценивает на размеченных примерах той же категории. Решения security идут первыми, потом примеры с Hugging Face (включая hard negatives).
4. **Score**: максимальная уверенность среди подтверждённых нарушений определяет уровень ALLOW / REVIEW / BLOCK. Если модель упала или не уложилась в 15 с, запрос получает BLOCK (fail-closed).

В админке подсвечивается, что именно не так: красным нарушения, зелёным разрешённое для домена, серым то, что отклонил верификатор.

## Запуск
Требуется macOS, Homebrew, [uv](https://docs.astral.sh/uv/) и Node.

```bash
brew install ollama
ollama serve &
ollama pull gemma4:e4b
```

```bash
cd backend && uv sync && cd ../frontend && npm install && npm run build && cd ..
```

Первый запуск mitmproxy создаёт CA в `~/.mitmproxy`. Его нужно один раз добавить в доверенные (нужен пароль администратора):

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Запуск всего стека. Скрипт включает системный прокси, а при Ctrl+C выключает его:

```bash
scripts/run.sh
```

Админка: http://127.0.0.1:8000. Без системного прокси (для отладки через `curl -x`): `scripts/run.sh --no-system-proxy`.
Если сеть осталась на прокси: `scripts/dlp-off.sh`.

## Админка
- **Очередь**: запросы на REVIEW с таймером, кнопки Approve/Reject. Сюда же попадают BLOCK, их можно отметить как false positive. Каждое решение превращается в размеченные примеры в датасете.
- **Журнал**: все события, включая ALLOW.
- **Проверить текст**: прогон классификатора без прокси (запасной вариант для демо).
- **Политики**: матрица домены × категории, расшифровка TLS по домену, пороги, таймауты, модель. Импорт и экспорт YAML.
- **Датасет**: импорт с Hugging Face, загрузка своего JSONL/CSV (`text, category, label[, span]`), экспорт JSONL в chat-формате под LoRA.

Датасеты с Hugging Face (качаются один раз, дальше хранятся локально):
- [`gretelai/gretel-pii-masking-en-v1`](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1): PII, финансовые и клиентские данные в документах; даты, города и компании идут как hard negatives.
- [`nisaefendioglu/synthetic-sensitive-data-in-source-code-n300`](https://huggingface.co/datasets/nisaefendioglu/synthetic-sensitive-data-in-source-code-n300): секреты в коде, чистый код, hard negatives.

## Демо-сценарий
1. Импортировать оба датасета HF во вкладке «Датасет».
2. В Chrome под системным прокси открыть ChatGPT и Claude.
3. Отправить внутренний код в **claude.ai**: ALLOW, потому что `source_code` разрешён для корпоративного AI.
4. Тот же код в **chatgpt.com**: REVIEW. Приходит уведомление macOS, в очереди появляется карточка с подсветкой и таймером. Approve, и ответ ChatGPT приходит.
5. AWS-ключ в любой чат: BLOCK. Чат показывает ошибку, уведомление объясняет причину.
6. Письмо клиенту с email, телефоном и картой в chatgpt.com: REVIEW или BLOCK. Reject добавляет пример в датасет, и следующий похожий запрос использует его.
7. Скачать датасет для LoRA.

## Ограничения (вне скоупа хакатона)
Расшифровываются только домены из `inspect_domains`; приложения с certificate pinning и не-HTTP трафик не поддерживаются.
У админки нет авторизации, она слушает только 127.0.0.1. Finetune не входит в скоуп, экспортируется только датасет.
Адаптеры ChatGPT/Claude завязаны на текущие внутренние API этих сайтов.

## Структура
```
backend/  core/ (policies, store, classifier, hf_import, notify) · proxy/ (guard, adapters) · api/app.py
frontend/ Vite + React + TS + Tailwind
scripts/  run.sh · dlp-on.sh · dlp-off.sh
policies.yaml
docs/     PLAN.md · PROGRESS.md
```
