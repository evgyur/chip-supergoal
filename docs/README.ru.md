# chip-supergoal

**chip-supergoal** — это skill для Hermes, который превращает нетривиальную инженерную задачу в проверяемый, файловый **SuperGoal package** и один стандартный handoff для Hermes `/goal`.

Он нужен для задач, где обычный план в чате слишком хрупкий: production-adjacent изменения, рискованные рефакторы, миграции, безопасность, длинная многофазная разработка и автономное исполнение, где нужны состояние, доказательства и финальный аудит.

English documentation: [`../README.md`](../README.md)

## Что делает skill

`chip-supergoal` — это **planner/compiler**, а не исполнитель.

Он создаёт директорию `.supergoal/` с артефактами:

- `THINKING.md` — цель, ограничения, риски, допущения, использованный контекст.
- `RESEARCH.md` — generated research gate record, если нужны свежие факты или внешний контекст.
- `reports/research.json` — machine-readable отчёт provider/status/sources, когда research gate активен.
- `LOOP_DESIGN.md` — дизайн исполнительного цикла: host, reviewer/judge, проверки, stop conditions, recovery, boundaries.
- `ROADMAP.md` — карта фаз, acceptance criteria, обязательные команды, требования к evidence.
- `runtime/STATE.json` — authoritative execution state; `STATE.md` — его проверяемая human projection.
- `PROTOCOL.md` — самодостаточный протокол для будущего `/goal` запуска.
- `LAUNCH_GOAL.md` — единственный файл с launch body, начинающимся с `SUPERGOAL_GOAL_BODY:`.
- `phases/phase-N.md` — строгие спецификации фаз.
- helper scripts и delivery receipts, если workflow требует доставки файлов.

После этого отдельная Hermes `/goal` сессия читает пакет и выполняет работу.
Завершение валидно только тогда, когда
`python scripts/sgctl.py validate-terminal` принимает точный package-bound
`reports/terminal-record.txt`. Маркеры `AUDIT_COMPLETE` и
`SUPERGOAL_RUN_COMPLETE` нужны для совместимости host, но сами по себе не дают
completion authority.

## Зачем это нужно

У агентной разработки есть типовые провалы:

1. Агент начинает делать, не зафиксировав реальную цель.
2. Длинная задача теряет состояние между turns.
3. “Готово” пишется до тестов, деплоя или доказательств.
4. Рискованные изменения проходят без review.
5. План нельзя безопасно передать другому исполнителю.

`chip-supergoal` закрывает эти провалы через package contract:

- явные фазы;
- обязательные verification commands;
- evidence requirements;
- risk/RPD review gates;
- state и recovery правила;
- строгую позицию launch-marker;
- validation и manifest integrity checks.

## Быстрый старт

Склонируйте или установите репозиторий как Hermes skill directory, затем загрузите skill в Hermes.

Типичный вызов:

```text
/chip-supergoal Build or refactor X end-to-end
```

Проверить репозиторий локально:

Требуется CPython 3.11.9 or newer. CI проверяет 3.11.9 и 3.13.14 как в native
Windows, так и в Ubuntu.

```console
python -m pip install --disable-pip-version-check -r requirements-test.txt
python scripts/test.py
```

Одна и та же команда работает в native Windows и Ubuntu. Unix-only entrypoint
`bash scripts/test.sh` сначала проверяет shell-файлы, затем вызывает тот же
Python runner.

Скомпилировать пример в новый sibling-каталог вне дерева skill (предыдущий
target нужно сначала переместить или удалить):

```console
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../chip-supergoal-example
python scripts/sgctl.py validate-package ../chip-supergoal-example --strict
```

Посмотреть результат:

```console
python -c "from pathlib import Path; print((Path('../chip-supergoal-example') / 'LAUNCH_GOAL.md').read_text(encoding='utf-8'))"
```

## CLI: `sgctl.py`

В репозитории есть `scripts/sgctl.py` — утилита для contract/package операций.

### Research provider gate

Если перед планом нужны свежие факты, добавьте `compatibility.research_gate` в `CONTRACT.json`. Предпочтительный provider — `perplex`; official docs, Context7, generic web search или manual research должны указывать `provider_unavailable_reason`, если Perplex не использовался.

Минимальный satisfied gate:

```json
{
  "compatibility": {
    "research_gate": {
      "required": true,
      "status": "satisfied",
      "provider": "perplex",
      "query": "current facts needed before planning",
      "summary": "Research summary explaining what changed in the plan.",
      "sources": [{"title": "Source", "url": "https://example.com", "provider": "perplex"}],
      "planning_implications": ["Specific phase/spec/acceptance change caused by research"]
    }
  }
}
```

Проверить gate:

```console
python scripts/sgctl.py research-gate examples/brownfield-feature/CONTRACT.json --format json
python scripts/sgctl.py validate-contract examples/brownfield-feature/CONTRACT.json --strict
```

Compile пишет `RESEARCH.md` и `reports/research.json`; `validate-package` ловит drift в обоих файлах.

Основные команды:

```console
# Проверить v3 contract
python scripts/sgctl.py validate-contract examples/brownfield-feature/CONTRACT.json --strict

# Скомпилировать contract в sealed SuperGoal package
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../chip-supergoal-example

# Проверить generated package
python scripts/sgctl.py validate-package ../chip-supergoal-example --strict

# Мигрировать старый v2-style package, если поддерживается
python scripts/sgctl.py migrate-v2 <old-package-root> --out <new-contract-or-package>
```

## Модель безопасности

### Поддерживаемые runtime-плоскости

Compiler, validator, state journal, audit, archive, delivery receipts и terminal
authority работают через package-local Python authority — напрямую в native
Windows и Ubuntu. Bash-файлы остаются только Unix compatibility wrappers и не
дублируют security policy. Пакеты из предыдущих alpha нужно recompile, чтобы в
них попали актуальные runtime и schemas.

Только `python scripts/sgctl.py finalize` может создать
`reports/terminal-record.txt`. Completion остаётся неавторизованным, пока
`python scripts/sgctl.py validate-terminal` не проверит текущие sealed package,
authoritative state, пересчитанный audit, inventory и delivery state.

ZIP публикуется только как external archive за пределами package. Delivery
передаёт проверенный reservation snapshot и удерживает read-only Windows handle
или anonymous POSIX copy до запуска транспорта. Native delivery пишет
многострочный JSON через `--authorization-out` и читает его через
`--authorization-file`, не полагаясь на PowerShell array/string coercion.
Privacy scan проверяет все
tracked files, включая force-tracked runtime paths, и untracked files рабочего
дерева вне runtime/private state directories, но не чужие пользовательские
каталоги. Настоящий внешний Hermes GoalManager probe в репозитории не поставляется:
reserved integration hook всегда skipped и не является release evidence.
Hermetic GoalManager simulator всегда входит в aggregate suite.

### Граница planner/executor

Skill планирует и компилирует. Он **не выполняет** implementation phases сам. Это намеренная граница: пакет должен быть читаемым, проверяемым и исполнимым отдельной стандартной `/goal` сессией.

### Один launch body

Настоящий launch body должен быть ровно один — в `LAUNCH_GOAL.md`.

Другие файлы могут объяснять процесс запуска, но не должны содержать ещё одну реальную строку:

`SUPERGOAL_GOAL_BODY:`

Это защищает от случайного запуска stale/duplicate goal.

### Sealed package

Generated package содержит `MANIFEST.json`: path, sha256, bytes, mode и package fingerprint.

`validate-package` ловит:

- ручное изменение generated Markdown относительно `CONTRACT.json`;
- drift hash/size/mode;
- лишние unsealed файлы;
- отсутствие обязательных файлов;
- unsafe/duplicate manifest paths;
- неправильное место launch-marker.

### Защита от destructive overwrite

Compiler отказывается писать в опасные targets:

- произвольные существующие директории, которые не являются sealed package;
- package с другим goal ID;
- изменённый contract без корректного `contract_revision`;
- source-container targets;
- started/runtime packages с runtime state или delivery output.

## Структура репозитория

```text
.
├── SKILL.md                      # Hermes skill entrypoint и operating contract
├── README.md                     # English documentation
├── docs/README.ru.md             # Русская документация
├── lib/chip_supergoal/           # Contract, compiler, validator, state, audit logic
├── scripts/                      # sgctl и verification/probe scripts
├── spec/                         # JSON schemas и policy catalogs
├── templates/                    # Templates generated package
├── references/                   # Детальные workflow/invariant references
├── examples/                     # Example contracts
└── tests/                        # Unit, semantic, rendering, security, migration, e2e tests
```

## Тесты

Полный локальный gate:

```console
python -m pip install --disable-pip-version-check -r requirements-test.txt
python scripts/test.py
```

Дополнительный Unix-only shell gate:

```bash
bash scripts/test.sh
```

Python tests напрямую:

```console
python -m unittest discover -s tests
```

Полезные focused tests:

```console
python -m unittest tests.rendering.test_compile_determinism
python -m unittest tests.semantic.test_sgctl_semantic_validation
python -m unittest tests.security.test_archive_symlink tests.security.test_forged_receipt
```

## Workflow разработки

1. Измените code/templates/references/tests.
2. Запустите focused tests для изменённой зоны.
3. Запустите `python scripts/test.py` в Windows или Ubuntu.
4. В Unix-only окружении дополнительно запустите `bash scripts/test.sh`.
5. Скомпилируйте example package и провалидируйте его strict mode.
6. Проверьте, что реальный `SUPERGOAL_GOAL_BODY:` есть только в `templates/LAUNCH_GOAL.md`.

Финальный gate:

```console
python scripts/test.py
python scripts/sgctl.py compile examples/brownfield-feature/CONTRACT.json --out ../chip-supergoal-final
python scripts/sgctl.py validate-package ../chip-supergoal-final --strict
```

На Unix-only хостах перед релизом дополнительно запустите
`bash scripts/test.sh` как shell-quality gate.

## Public-use notes

Репозиторий содержит public-safe source skill и validation harness. Runtime state, локальные generated `.supergoal/` packages, credentials, receipts, caches и deployment artifacts не должны попадать в git.

Если адаптируете skill под другой agent runtime, сохраняйте инварианты:

- одна launch surface;
- явная граница planner/executor;
- validation generated package;
- никакого false completion без final audit;
- risk-aware review gates;
- state recovery и blocker semantics.

## Лицензия

MIT. См. [`../LICENSE`](../LICENSE).
