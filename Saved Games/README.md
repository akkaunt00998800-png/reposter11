# eSIM CLI Emulator

Профессиональный CLI‑эмулятор устройства с eSIM (EID/IMEI), эмуляция LPA, работа с SM‑DP+ и SMS‑модуль.

**ВНИМАНИЕ**: Коды активации eSIM работают **ОДИН РАЗ**. Если скрипт неправильно сработает, код станет недействительным и eSIM перестанет работать. Используйте только с тестовыми данными или будьте очень осторожны с реальными кодами.

## Особенности

- ✅ Эмуляция индивидуального устройства с уникальными EID/IMEI
- ✅ Установка eSIM‑профилей через SM‑DP+ (пользователь вводит адрес и код активации)
- ✅ Поиск профиля по номеру телефона (MSISDN)
- ✅ Эмуляция SMS (отправка/приём)
- ✅ Защита от повторного использования activation code (одноразовые коды)
- ✅ Безопасное хранение данных (локальный JSON, маскирование чувствительных данных)
- ✅ Профессиональный код с обработкой ошибок

## Установка

```bash
cd "c:\Users\Kab_4_PC_4\Saved Games"
# Зависимости не требуются - используется только стандартная библиотека Python
```

## Быстрый старт

```bash
# Инициализация виртуального устройства
python esim_cli.py init

# Показать информацию об устройстве
python esim_cli.py device show

# Добавить eSIM профиль (пользователь вводит SM-DP+ адрес и код активации)
python esim_cli.py profile add --smdp https://smdp.example.com --activation-code LPA:1$smdp.example.com$ABC123 --msisdn +1234567890

# Список профилей
python esim_cli.py profile list

# Найти профиль по номеру телефона
python esim_cli.py profile find-by-phone +1234567890

# Отправить SMS
python esim_cli.py sms send --to +9876543210 --text "Hello"

# Показать входящие SMS
python esim_cli.py sms inbox
```

## Команды

### Управление устройством

```bash
# Инициализация нового виртуального устройства
python esim_cli.py init [--device-id ID] [--eid EID] [--imei IMEI] [--model MODEL] [--os OS]

# Показать текущее устройство
python esim_cli.py device show

# Список всех устройств
python esim_cli.py device list
```

### Работа с eSIM профилями

```bash
# Добавить профиль (КРИТИЧЕСКИ ВАЖНО: код активации используется ОДИН РАЗ!)
python esim_cli.py profile add --smdp <SM-DP+_ADDRESS> --activation-code <CODE> [--confirmation-code CODE] [--msisdn PHONE]

# Список профилей на устройстве
python esim_cli.py profile list

# Найти профиль по номеру телефона
python esim_cli.py profile find-by-phone <MSISDN>

# Активировать профиль
python esim_cli.py profile set-active <PROFILE_ID>

# Отключить профиль
python esim_cli.py profile disable <PROFILE_ID>

# Удалить профиль
python esim_cli.py profile delete <PROFILE_ID>
```

### SMS эмуляция

```bash
# Отправить SMS
python esim_cli.py sms send --to <MSISDN> --text "Message"

# Показать входящие SMS
python esim_cli.py sms inbox

# Смоделировать входящее SMS
python esim_cli.py sms simulate-incoming --from <MSISDN> --text "Message"
```

## ⚠️ КРИТИЧЕСКИ ВАЖНО: Activation Codes

**Коды активации eSIM работают ТОЛЬКО ОДИН РАЗ.**

- Если скачивание профиля завершится ошибкой, код станет **недействительным**
- Повторное использование того же кода **невозможно**
- Скрипт автоматически отслеживает использованные коды и блокирует повторное использование
- Если код уже использован, вы получите ошибку с предупреждением

**Рекомендации:**
- Используйте только с тестовыми данными или будьте очень осторожны
- Убедитесь, что SM‑DP+ адрес правильный перед запуском
- Если что-то пошло не так, обратитесь к оператору за новым кодом активации

## Архитектура

- **device.py** - Модель виртуального устройства (EID, IMEI, профили)
- **profile.py** - Модель eSIM профиля (ICCID, оператор, MSISDN, статус)
- **smdp_client.py** - Клиент для работы с SM‑DP+ сервером (mock реализация)
- **lpa_emulator.py** - Эмулятор Local Profile Assistant (LPA)
- **sms_emulator.py** - Эмулятор SMS модуля
- **storage.py** - Хранение состояния (JSON, без шифрования)
- **cli.py** - Интерфейс командной строки

## Безопасность и ограничения

- ✅ Все данные хранятся локально в `~/.esim_cli/state.json` (без шифрования для простоты)
- ✅ Чувствительные идентификаторы (EID/IMEI/ICCID) маскируются в выводе
- ✅ Отслеживание одноразовых activation codes
- ⚠️ Текущая реализация использует **mock SM‑DP+** (генерирует фейковые профили)
- ⚠️ Для работы с реальными операторами потребуется:
  - Реальный SM‑DP+ провайдер (eSIM Go, Roamify и т.д.)
  - Их официальное API
  - Строгий комплаенс GSMA SGP.22/GDPR/локальных законов связи

## Примеры использования

### Полный цикл работы

```bash
# 1. Инициализация устройства
python esim_cli.py init

# 2. Добавление профиля (пользователь вводит реальные данные)
python esim_cli.py profile add \
  --smdp https://smdp.operator.com \
  --activation-code LPA:1$smdp.operator.com$YOUR_CODE \
  --confirmation-code 1234 \
  --msisdn +1234567890

# 3. Проверка профилей
python esim_cli.py profile list

# 4. Поиск по номеру
python esim_cli.py profile find-by-phone +1234567890

# 5. Работа с SMS
python esim_cli.py sms send --to +9876543210 --text "Test"
python esim_cli.py sms inbox
```

## Технические детали

- **EID**: 32-значный уникальный идентификатор встроенного чипа eSIM
- **IMEI**: 15-значный международный идентификатор мобильного оборудования
- **ICCID**: 19-20 цифр, идентификатор SIM карты
- **MSISDN**: Номер телефона (Mobile Station International Subscriber Directory Number)
- **SM‑DP+**: Subscription Manager Data Preparation сервер
- **LPA**: Local Profile Assistant (системный компонент для управления профилями)

## Лицензия

Для внутреннего использования. Используйте ответственно.
