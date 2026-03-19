# Yarbot FastAPI Application

## Описание

FastAPI приложение для системы оценки сотрудников, разработанное для работы в связке с Telegram ботом на Dioxus фронтенде.

## Архитектура

Приложение использует:
- **FastAPI** - современный веб-фреймворк для построения API
- **Dependency Injector** - для внедрения зависимостей
- **PostgreSQL** - основная база данных
- **Redis** - для кэширования и хранения приглашений
- **SQLAlchemy** - ORM для работы с БД
- **Pydantic** - валидация данных и сериализация

## Установка

### 1. Установить зависимости

```bash
poetry install
```

### 2. Настроить переменные окружения

Создайте `.env` файл с необходимыми переменными (см. существующую конфигурацию для бота).

### 3. Запустить миграции

```bash
alembic upgrade head
```

## Запуск

### Режим разработки

```bash
python fastapi_app.py
```

или

```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Режим продакшена

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Endpoints

API доступен по адресу `http://localhost:8000/api/v1`

### Документация

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Основные группы endpoints:

#### 1. Organizations (`/api/v1/organizations`)

- `GET /organizations` - Список организаций пользователя (требует `telegram_id`)
- `GET /organizations/{id}` - Детали организации
- `POST /organizations` - Создать организацию
- `PUT /organizations/{id}` - Обновить организацию
- `GET /organizations/{id}/employees` - Список сотрудников организации
- `DELETE /organizations/{id}/employees/{employee_id}` - Уволить сотрудника (soft delete)
- `POST /organizations/{id}/employees/{employee_id}/restore` - Восстановить сотрудника

#### 2. Employees (`/api/v1/employees`)

- `GET /employees?organization_id={id}` - Список сотрудников (требует `organization_id`)
- `GET /employees/{id}` - Детали сотрудника
- `POST /employees` - Создать сотрудника
- `PUT /employees/{id}` - Обновить сотрудника
- `DELETE /employees/{id}` - Удалить сотрудника (soft delete)
- `POST /employees/{id}/restore` - Восстановить сотрудника
- `GET /employees/telegram/{telegram_id}` - Получить сотрудника по Telegram ID

#### 3. Criteria (`/api/v1/criteria`)

- `GET /criteria?organization_id={id}` - Список критериев организации
- `GET /criteria?evaluation_type_id={id}` - Список критериев по типу оценки
- `GET /criteria/{id}` - Детали критерия
- `POST /criteria` - Создать критерий
- `PUT /criteria/{id}` - Обновить критерий

#### 4. Criterion Sets (`/api/v1/criterion-sets`)

- `GET /criterion-sets?organization_id={id}` - Список наборов критериев
- `GET /criterion-sets/{id}` - Детали набора
- `POST /criterion-sets` - Создать набор критериев
- `PUT /criterion-sets/{id}` - Обновить набор
- `DELETE /criterion-sets/{id}` - Удалить набор (soft delete)
- `GET /criterion-sets/organization/{id}/default` - Получить дефолтный набор
- `POST /criterion-sets/import-excel` - Импортировать наборы из Excel

#### 5. Evaluations (`/api/v1/evaluations`)

- `GET /evaluations/{id}` - Детали оценки
- `POST /evaluations` - Создать оценку
- `PUT /evaluations/{id}` - Обновить оценку
- `GET /evaluations/{id}/export/excel` - Экспорт в Excel (в разработке)
- `GET /evaluations/{id}/export/pdf` - Экспорт в PDF (в разработке)

#### 6. Evaluation Types (`/api/v1/evaluation-types`)

- `GET /evaluation-types` - Список типов оценок
- `GET /evaluation-types/{id}` - Детали типа оценки
- `POST /evaluation-types` - Создать тип оценки

#### 7. Analytics (`/api/v1/analytics`)

- `POST /analytics/criteria-statistics` - Статистика по критериям
- `POST /analytics/average-scores` - Средние оценки
- `POST /analytics/custom-query` - Кастомный запрос с фильтрами

#### 8. Invitations (`/api/v1/invitations`)

- `POST /invitations` - Создать код приглашения
- `GET /invitations/{code}` - Получить информацию о приглашении
- `POST /invitations/{code}/use` - Использовать приглашение
- `DELETE /invitations/{code}` - Удалить приглашение

#### 9. Users (`/api/v1/users`)

- `GET /users/{telegram_id}?chat_id={chat_id}` - Получить пользователя
- `POST /users` - Создать/синхронизировать пользователя

## Примеры использования

### Создание организации

```bash
curl -X POST "http://localhost:8000/api/v1/organizations" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Моя организация",
    "code": "MY_ORG",
    "address": "г. Москва, ул. Примерная, 1",
    "phone": "+7 (999) 123-45-67"
  }'
```

### Получение списка сотрудников

```bash
curl -X GET "http://localhost:8000/api/v1/employees?organization_id=1"
```

### Создание критерия

```bash
curl -X POST "http://localhost:8000/api/v1/criteria" \
  -H "Content-Type: application/json" \
  -d '{
    "organization_id": 1,
    "evaluation_type_id": 1,
    "name": "Пунктуальность",
    "code": "PUNCTUALITY",
    "description": "Приходит вовремя на работу",
    "value_type": "boolean"
  }'
```

### Получение аналитики

```bash
curl -X POST "http://localhost:8000/api/v1/analytics/average-scores" \
  -H "Content-Type: application/json" \
  -d '{
    "organization_id": 1,
    "group_by": "employee",
    "date_from": "2024-01-01T00:00:00",
    "date_to": "2024-12-31T23:59:59"
  }'
```

### Импорт критериев из Excel

```bash
curl -X POST "http://localhost:8000/api/v1/criterion-sets/import-excel?organization_id=1" \
  -F "file=@criteria.xlsx"
```

## Формат Excel для импорта

Для импорта наборов критериев используйте Excel файл со следующей структурой:

| Название набора | Вопрос критерия | Тип |
|----------------|-----------------|-----|
| Аттестация 2024 | Пунктуальность | bool |
| Аттестация 2024 | Качество работы | num |
| Аттестация 2024 | Комментарий | str |

**Типы значений:**
- `bool` / `boolean` - Булево значение (да/нет)
- `num` / `number` - Числовое значение
- `str` / `string` - Строковое значение

## Структура проекта

```
app/
├── api/
│   ├── __init__.py
│   ├── deps.py              # Зависимости FastAPI
│   ├── main.py              # Главный файл приложения
│   ├── schemas.py           # Pydantic схемы
│   └── routers/             # API роутеры
│       ├── organizations.py
│       ├── employees.py
│       ├── criteria.py
│       ├── criterion_sets.py
│       ├── evaluations.py
│       ├── evaluation_types.py
│       ├── analytics.py
│       ├── invitations.py
│       └── users.py
├── infra/                   # Инфраструктурный слой
│   └── database/           
│       ├── models/          # SQLAlchemy модели
│       └── repository/      # Репозитории
├── internal/                # Бизнес-логика
│   └── usecases/           # Сервисы
└── tgbot/                   # Telegram бот
```

## Интеграция с Dioxus приложением

API разработан для использования с фронтенд-приложением на Dioxus со следующими маршрутами:

- `/` - Главная страница
- `/organizations` - Список организаций (только для админов)
- `/organizations/:id` - Детали организации
- `/employees` - Список сотрудников
- `/employees/:id` - Детали сотрудника
- `/criteria` - Список критериев
- `/criteria/:id` - Детали критерия
- `/criterion-sets` - Наборы критериев
- `/criterion-sets/:id` - Детали набора
- `/evaluations` - Список оценок
- `/evaluations/new` - Создание новой оценки
- `/evaluations/:id` - Детали оценки
- `/analytics` - Аналитика

## CORS

По умолчанию CORS настроен на прием запросов со всех источников (`allow_origins=["*"]`).

**Для продакшена** обязательно измените настройки CORS в `app/api/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Укажите конкретные домены
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

## Безопасность

### Текущая реализация

В текущей версии API не имеет встроенной аутентификации. Предполагается, что:
- API работает за reverse proxy (nginx, traefik)
- Аутентификация выполняется на уровне фронтенда или middleware
- Для продакшена рекомендуется добавить OAuth2/JWT аутентификацию

### Рекомендации для продакшена

1. Добавить JWT токены для аутентификации
2. Реализовать role-based access control (RBAC)
3. Использовать HTTPS
4. Настроить rate limiting
5. Добавить логирование всех запросов

## Мониторинг

### Health Check

```bash
curl http://localhost:8000/health
```

Ответ:
```json
{
  "status": "healthy"
}
```

## Разработка

### Добавление нового endpoint

1. Создайте Pydantic схемы в `app/api/schemas.py`
2. Добавьте endpoint в соответствующий роутер в `app/api/routers/`
3. При необходимости создайте новый сервис в `app/internal/usecases/`
4. Добавьте dependency в `app/api/deps.py`
5. Подключите роутер в `app/api/main.py`

### Тестирование

Используйте Swagger UI для тестирования endpoints:
http://localhost:8000/docs

## Troubleshooting

### Ошибка подключения к БД

Проверьте настройки подключения в `.env` файле и убедитесь, что PostgreSQL запущен.

### Ошибка импорта Excel

Убедитесь, что:
- Файл имеет формат `.xlsx` или `.xls`
- Первая строка может быть заголовком (будет пропущена автоматически)
- В файле минимум 3 колонки
- Типы указаны корректно: `bool`, `str`, `num`

## License

Лицензия проекта (если применимо)
