# Сравнение local_bot.py и webhook_bot.py

## ✅ Оба бота теперь идентичны по функционалу!

### Общие характеристики:

| Параметр | local_bot.py | webhook_bot.py |
|----------|--------------|----------------|
| **Режим работы** | Polling (long polling) | Webhook |
| **Telegram диалоги** | ✅ Все | ✅ Все |
| **API endpoints** | ✅ Только `/api/webapp/*` | ✅ Только `/api/webapp/*` |
| **База данных** | ✅ Прямой доступ | ✅ Прямой доступ |
| **Веб-формы** | ✅ ChaCha20 токены | ✅ ChaCha20 токены |
| **CORS** | ✅ Конфигурируемый | ✅ Конфигурируемый |
| **Порт** | 8000 | 8000 |

### Различия:

#### 1. **Режим получения обновлений**

**local_bot.py:**
```python
# Polling - бот сам опрашивает Telegram
await dp.start_polling(bot)
```

**webhook_bot.py:**
```python
# Webhook - Telegram отправляет обновления на ваш сервер
@app.post("/webhook")
async def webhook_handler(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot=bot, update=update)
```

#### 2. **Требования к инфраструктуре**

**local_bot.py:**
- ✅ Работает везде (локально, за NAT, без белого IP)
- ✅ Не требует домен
- ✅ Не требует SSL сертификат
- ⚠️ Больше нагрузка на Telegram API (постоянные запросы)

**webhook_bot.py:**
- ✅ Меньше нагрузка (Telegram сам шлёт обновления)
- ✅ Быстрее отклик
- ⚠️ Требует публичный домен с HTTPS
- ⚠️ Требует SSL сертификат
- ⚠️ Требует переменные окружения: `WEBHOOK_URL`, `WEBHOOK_SECRET`

### Конфигурация

#### local_bot.py
```bash
# Минимум
TGBOT_TOKEN=your_bot_token
DATABASE_URL=postgresql+asyncpg://...
REDIS_DSN=redis://redis:6379/0
```

#### webhook_bot.py
```bash
# Дополнительно к минимуму
WEBHOOK_URL=https://yourdomain.com
WEBHOOK_PATH=/webhook
WEBHOOK_SECRET=random_secret_token
```

### Когда использовать какой?

#### Используйте **local_bot.py** если:
- 🏠 Разработка локально
- 🔒 Сервер за NAT/firewall
- 💻 Нет публичного домена
- 🚀 Быстрый старт без настройки DNS

#### Используйте **webhook_bot.py** если:
- 🌐 Production с доменом
- ⚡ Нужна максимальная производительность
- 📊 Высокая нагрузка (много пользователей)
- 🔐 Есть SSL сертификат

### Идентичная функциональность

Оба бота предоставляют:

1. **Telegram диалоги:**
   - ✅ Управление организациями
   - ✅ Управление сотрудниками
   - ✅ Управление критериями
   - ✅ Проведение оценок
   - ✅ Аналитика с AI
   - ✅ Экспорт в PDF/Excel

2. **API веб-форм:**
   - ✅ `GET /api/webapp/form/{token}` - получить форму
   - ✅ `POST /api/webapp/form/{token}/submit` - отправить форму
   - ✅ `POST /api/webapp/token` - создать токен (внутренний)

3. **Безопасность:**
   - ✅ ChaCha20Poly1305 шифрование токенов
   - ✅ Replay protection
   - ✅ Token expiry
   - ✅ CORS защита
   - ✅ Закрытые порты БД

### Запуск

#### local_bot.py
```bash
# Docker
docker-compose up -d

# Или напрямую
python local_bot.py
```

#### webhook_bot.py
```bash
# Настроить переменные окружения
export WEBHOOK_URL=https://yourdomain.com
export WEBHOOK_SECRET=$(openssl rand -hex 32)

# Docker (требует модификации docker-compose.yml)
docker-compose -f docker-compose-webhook.yml up -d

# Или напрямую
python webhook_bot.py
```

### Рекомендации

**Для разработки:** `local_bot.py` ✅  
**Для production:** `webhook_bot.py` ✅

Оба варианта полностью функциональны и безопасны!

---

**Обновлено:** 2026-02-08  
**Статус:** ✅ Синхронизированы
