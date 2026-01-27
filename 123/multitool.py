import asyncio
import configparser
from telethon import TelegramClient, events
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact
import os
import re
from colorama import init, Fore, Style
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.types import Channel, Chat
import requests
import json
import time
from bs4 import BeautifulSoup
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact, InputUser
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPeerChannel, InputPeerUser
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
import random
import time
from datetime import datetime, timedelta


# Инициализация colorama для цветного текста
init()

config = configparser.ConfigParser()

if not os.path.exists('config.ini'):
    config['SETTINGS'] = {}
    with open('config.ini', 'w') as configfile:
        config.write(configfile)

def load_settings(section, key):
    """Загрузка настроек"""
    config.read('config.ini')
    return config.get(section, key, fallback=None)

async def setup_delay():
    """Настройка задержки между действиями"""
    print_banner()
    print(f"{Fore.YELLOW}НАСТРОЙКА ЗАДЕРЖКИ{Style.RESET_ALL}")
    print()
    
    current_delay = get_delay()
    print(f"{Fore.GREEN}Текущая задержка: {current_delay} секунд{Style.RESET_ALL}")
    print()
    print(f"{Fore.YELLOW}Выберите тип задержки:{Style.RESET_ALL}")
    print("1. Фиксированная задержка")
    print("2. Случайная задержка в диапазоне")
    print()
    
    try:
        delay_type = int(input("Выберите вариант (1 или 2): "))
        
        if delay_type == 1:
            # Фиксированная задержка
            try:
                fixed_delay = float(input("Введите фиксированную задержку (секунды): "))
                if 0.1 <= fixed_delay <= 60:
                    save_settings('SETTINGS', 'delay', f"fixed:{fixed_delay}")
                    print(f"{Fore.GREEN}Фиксированная задержка установлена: {fixed_delay} секунд{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}Задержка должна быть от 0.1 до 60 секунд!{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Введите число!{Style.RESET_ALL}")
                
        elif delay_type == 2:
            # Случайная задержка
            try:
                min_delay = float(input("Введите минимальную задержку (секунды): "))
                max_delay = float(input("Введите максимальную задержку (секунды): "))
                
                if 0.1 <= min_delay <= max_delay <= 60:
                    save_settings('SETTINGS', 'delay', f"random:{min_delay}:{max_delay}")
                    print(f"{Fore.GREEN}Случайная задержка установлена: от {min_delay} до {max_delay} секунд{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}Некорректный диапазон! Должно быть: 0.1 ≤ min ≤ max ≤ 60{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Введите числа!{Style.RESET_ALL}")
                
        else:
            print(f"{Fore.RED}Неверный выбор!{Style.RESET_ALL}")
            
    except ValueError:
        print(f"{Fore.RED}Введите число!{Style.RESET_ALL}")
    
    time.sleep(2)

def get_delay():
    """Получить текущую задержку (фиксированную или случайную)"""
    delay_str = load_settings('SETTINGS', 'delay')
    
    if delay_str:
        if delay_str.startswith('fixed:'):
            # Фиксированная задержка
            try:
                fixed_delay = float(delay_str.split(':')[1])
                return fixed_delay if 0.1 <= fixed_delay <= 60 else 3.0
            except (ValueError, IndexError):
                return 3.0
                
        elif delay_str.startswith('random:'):
            # Случайная задержка
            try:
                parts = delay_str.split(':')
                min_delay = float(parts[1])
                max_delay = float(parts[2])
                if 0.1 <= min_delay <= max_delay <= 60:
                    return random.uniform(min_delay, max_delay)
            except (ValueError, IndexError):
                return random.uniform(2, 5)  # Значение по умолчанию
    
    # Значение по умолчанию - случайная задержка 2-5 секунд
    return random.uniform(2, 5)

def get_delay_info():
    """Получить информацию о настройки задержки для отображения"""
    delay_str = load_settings('SETTINGS', 'delay')
    
    if delay_str:
        if delay_str.startswith('fixed:'):
            try:
                fixed_delay = float(delay_str.split(':')[1])
                return f"Фиксированная: {fixed_delay}с"
            except:
                return "Случайная: 2-5с"
                
        elif delay_str.startswith('random:'):
            try:
                parts = delay_str.split(':')
                min_delay = float(parts[1])
                max_delay = float(parts[2])
                return f"Случайная: {min_delay}-{max_delay}с"
            except:
                return "Случайная: 2-5с"
    
    return "Случайная: 2-5с (по умолчанию)"

def save_settings(section, key, value):
    """Сохранение настроек"""
    config.read('config.ini')
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, str(value))
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
        
def print_banner():
    os.system('cls' if os.name == 'nt' else 'clear')
    print(Fore.CYAN + "==========================================")
    print("           МУЛЬТИТУЛ v2.0")
    print("==========================================" + Style.RESET_ALL)
    print()

def load_api_credentials():
    config.read('config.ini')
    api_id = load_settings('API', 'api_id')
    api_hash = load_settings('API', 'api_hash')
    return api_id, api_hash

def save_api_credentials(api_id, api_hash):
    save_settings('API', 'api_id', api_id)
    save_settings('API', 'api_hash', api_hash)

async def setup_proxy(client):
    proxy_type = input("Тип прокси (socks5/http): ")
    proxy_host = input("Хост прокси: ")
    proxy_port = input("Порт прокси: ")
    proxy_user = input("Логин прокси (если есть): ") or None
    proxy_pass = input("Пароль прокси (если есть): ") or None
    
    proxy = (proxy_type, proxy_host, int(proxy_port), proxy_user, proxy_pass)
    save_settings('PROXY', 'current', str(proxy))
    return proxy

def parse_user_line(line):
    """Парсит строку с информацией о пользователе"""
    user_data = {}
    
    # Ищем ID
    id_match = re.search(r'ID: (\d+)', line)
    if id_match:
        user_data['id'] = int(id_match.group(1))
    
    # Ищем username
    username_match = re.search(r'Username: @(\w+)', line)
    if username_match:
        user_data['username'] = username_match.group(1)
    
    # Ищем phone
    phone_match = re.search(r'Phone: (\+?\d+)', line)
    if phone_match:
        user_data['phone'] = phone_match.group(1)
    
    # Ищем first name
    first_name_match = re.search(r'First Name: ([^|]+)', line)
    if first_name_match:
        user_data['first_name'] = first_name_match.group(1).strip()
    
    return user_data

async def select_message_by_reply(client):
    """Выбор сообщения через ответ командой .сообщение"""
    print(f"{Fore.YELLOW}ВЫБОР СООБЩЕНИЯ ДЛЯ РАССЫЛКИ{Style.RESET_ALL}")
    print()
    print(f"{Fore.CYAN}Инструкция:{Style.RESET_ALL}")
    print("1. Найдите сообщение которое хотите переслать")
    print("2. Ответьте на него командой:")
    print(f"{Fore.GREEN}.сообщение{Style.RESET_ALL}")
    print("3. Бот автоматически выберет это сообщение для рассылки")
    print()
    print(f"{Fore.YELLOW}Ожидание команды .сообщение...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}Для отмены нажмите Ctrl+C{Style.RESET_ALL}")
    print()
    
    # Создаем Future для ожидания сообщения
    message_future = asyncio.Future()
    
    # Обработчик команды .сообщение
    @client.on(events.NewMessage(pattern=r'\.сообщение'))
    async def message_select_handler(event):
        try:
            # Проверяем, что это ответ на какое-то сообщение
            if not event.is_reply:
                await event.reply("❌ Эта команда должна быть ответом на сообщение которое вы хотите переслать!")
                return
            
            # Получаем сообщение на которое ответили
            replied_message = await event.get_reply_message()
            
            if not replied_message:
                await event.reply("❌ Не удалось получить сообщение для пересылки!")
                return
            
            # Сохраняем данные сообщения
            message_data = {
                'original_message': replied_message,
                'chat': await event.get_chat(),
                'text': replied_message.text,
                'media': replied_message.media,
                'entities': replied_message.entities
            }
            
            # Отправляем подтверждение
            preview_text = replied_message.text[:100] + "..." if replied_message.text and len(replied_message.text) > 100 else replied_message.text or "📷 Медиа-сообщение"
            
            await event.reply(
                f"✅ Сообщение выбрано для рассылки!\n"
                f"📝 Предпросмотр: {preview_text}\n"
                f"💬 Чат: {getattr(message_data['chat'], 'title', getattr(message_data['chat'], 'username', 'ЛС'))}\n"
                f"🖼️ Медиа: {'Да' if replied_message.media else 'Нет'}\n"
                f"🎨 Форматирование: {'Да' if replied_message.entities else 'Нет'}"
            )
            
            print(f"{Fore.GREEN}✅ Сообщение выбрано для рассылки!{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Текст: {preview_text}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Чат: {getattr(message_data['chat'], 'title', getattr(message_data['chat'], 'username', 'ЛС'))}{Style.RESET_ALL}")
            
            # Устанавливаем результат в Future
            if not message_future.done():
                message_future.set_result(message_data)
                
        except Exception as e:
            print(f"{Fore.RED}Ошибка при выборе сообщения: {str(e)}{Style.RESET_ALL}")
            if not message_future.done():
                message_future.set_exception(e)
    
    # Ждем сообщение в течение 60 секунд
    try:
        message_data = await asyncio.wait_for(message_future, timeout=60)
        # Удаляем обработчик после успешного получения сообщения
        client.remove_event_handler(message_select_handler)
        return message_data
        
    except asyncio.TimeoutError:
        print(f"{Fore.RED}Время ожидания истекло. Сообщение не было выбрано.{Style.RESET_ALL}")
        client.remove_event_handler(message_select_handler)
        return None
    except KeyboardInterrupt:
        print(f"{Fore.YELLOW}Выбор сообщения отменен{Style.RESET_ALL}")
        client.remove_event_handler(message_select_handler)
        return None

async def spam_messages(client, users_file=None):
    """Спам в ЛС с пересылкой выбранного сообщения"""
    try:
        # Выбираем сообщение для пересылки
        print(f"{Fore.YELLOW}Выбор сообщения для спама в ЛС...{Style.RESET_ALL}")
        message_data = await select_message_by_reply(client)
        
        if not message_data:
            print(f"{Fore.RED}Не удалось выбрать сообщение!{Style.RESET_ALL}")
            return
        
        # Загрузка пользователей
        if not users_file:
            users_file = input(f"{Fore.YELLOW}Введите путь к файлу с пользователями: {Style.RESET_ALL}")
        
        users_to_spam = load_users_from_file(users_file)
        
        if not users_to_spam:
            print(f"{Fore.RED}Не найдено пользователей в файле!{Style.RESET_ALL}")
            return
        
        # Выбор количества
        print(f"{Fore.YELLOW}Всего пользователей в файле: {len(users_to_spam)}{Style.RESET_ALL}")
        max_users_input = input("Сколько пользователей проспамить? (Enter - всех): ")
        
        if max_users_input.strip():
            max_users = int(max_users_input)
            users_to_spam = users_to_spam[:max_users]
        
        # Настройка задержки
        print(f"{Fore.YELLOW}Настройка задержки:{Style.RESET_ALL}")
        try:
            delay_choice = input("Использовать настройки задержки из конфига? (y/n): ").lower()
            if delay_choice == 'n':
                custom_delay = float(input("Введите задержку между сообщениями (секунды): "))
                use_custom_delay = True
            else:
                use_custom_delay = False
        except:
            use_custom_delay = False
        
        print(f"{Fore.GREEN}Будет отправлено сообщений: {len(users_to_spam)}{Style.RESET_ALL}")
        
        success_count = 0
        
        for i, user_data in enumerate(users_to_spam, 1):
            try:
                if 'username' in user_data:
                    user_entity = await client.get_entity(user_data['username'])
                elif 'id' in user_data:
                    user_entity = await client.get_entity(user_data['id'])
                else:
                    continue
                
                # ПЕРЕСЫЛАЕМ оригинальное сообщение (сохраняются все эмодзи и форматирование)
                await client.forward_messages(
                    user_entity,
                    message_data['original_message']
                )
                
                success_count += 1
                
                # Прогресс каждые 10 пользователей
                if i % 10 == 0:
                    print(f"{Fore.YELLOW}[Прогресс] Отправлено: {i}/{len(users_to_spam)}{Style.RESET_ALL}")
                
                # Задержка
                if use_custom_delay:
                    await asyncio.sleep(custom_delay)
                else:
                    delay = get_delay()
                    await asyncio.sleep(delay)
                
            except Exception as e:
                print(f"{Fore.RED}[!] Ошибка отправки: {str(e)}{Style.RESET_ALL}")
                continue
        
        print(f"{Fore.GREEN}Успешно отправлено: {success_count} сообщений{Style.RESET_ALL}")
                
    except Exception as e:
        print(f"{Fore.RED}Ошибка спама: {str(e)}{Style.RESET_ALL}")

async def spam_to_groups(client):
    """Спам по группам с пересылкой выбранного сообщения"""
    try:
        print(f"{Fore.YELLOW}СПАМ ПО ГРУППАМ{Style.RESET_ALL}")
        
        # Выбираем сообщение для пересылки
        print(f"{Fore.YELLOW}Выбор сообщения для спама...{Style.RESET_ALL}")
        message_data = await select_message_by_reply(client)
        
        if not message_data:
            print(f"{Fore.RED}Не удалось выбрать сообщение!{Style.RESET_ALL}")
            return
        
        # Выбор режима получения чатов
        print(f"{Fore.YELLOW}Выберите источник чатов:{Style.RESET_ALL}")
        print("1. Из файла chats.txt")
        print("2. Из диалогов аккаунта")
        
        try:
            source_choice = int(input("Выберите вариант (1 или 2): "))
            if source_choice not in [1, 2]:
                source_choice = 1
        except:
            source_choice = 1
        
        # Получение чатов в зависимости от выбранного режима
        selected_chats = []
        
        if source_choice == 1:
            # Режим из файла
            if not os.path.exists("chats.txt"):
                with open("chats.txt", "w", encoding="utf-8") as f:
                    f.write("")
                print(f"{Fore.YELLOW}Создан файл chats.txt. Добавьте ссылки на чаты.{Style.RESET_ALL}")
                return
            
            try:
                with open("chats.txt", "r", encoding="utf-8") as f:
                    links = [line.strip() for line in f if line.strip()]
                
                for link in links:
                    try:
                        entity = await client.get_entity(link)
                        if hasattr(entity, 'title'):
                            selected_chats.append((entity.id, entity.title, entity))
                    except Exception as e:
                        print(f"{Fore.RED}Ошибка при получении чата {link}: {str(e)}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Ошибка при чтении chats.txt: {str(e)}{Style.RESET_ALL}")
                return
        
        else:
            # Режим из диалогов
            print(f"{Fore.YELLOW}Получаем список чатов...{Style.RESET_ALL}")
            
            chats = []
            groups = []
            
            result = await client(GetDialogsRequest(
                offset_date=None,
                offset_id=0,
                offset_peer=InputPeerEmpty(),
                limit=200,
                hash=0
            ))
            chats.extend(result.chats)
            
            for chat in chats:
                try:
                    if hasattr(chat, 'megagroup') and chat.megagroup:
                        groups.append(chat)
                except:
                    continue
            
            if not groups:
                print(f"{Fore.RED}Не найдено групп/супергрупп!{Style.RESET_ALL}")
                return
            
            # Выбор групп для спама
            print(f"{Fore.YELLOW}Выберите группы для спама (через запятую):{Style.RESET_ALL}")
            for i, group in enumerate(groups):
                print(f"{Fore.GREEN}[{i}] {group.title}{Style.RESET_ALL}")
            
            try:
                selected_indices = input("Номера групп: ").split(',')
                
                for idx in selected_indices:
                    try:
                        group_idx = int(idx.strip())
                        if 0 <= group_idx < len(groups):
                            selected_chats.append((groups[group_idx].id, groups[group_idx].title, groups[group_idx]))
                    except:
                        continue
                
                if not selected_chats:
                    print(f"{Fore.RED}Не выбрано групп!{Style.RESET_ALL}")
                    return
                    
            except:
                print(f"{Fore.RED}Ошибка выбора групп!{Style.RESET_ALL}")
                return
        
        if not selected_chats:
            print(f"{Fore.RED}Чаты не найдены!{Style.RESET_ALL}")
            return
        
        # Настройки спама
        print(f"{Fore.YELLOW}Настройки спама:{Style.RESET_ALL}")
        
        try:
            cycles = int(input("Количество циклов спама: ") or "1")
            delay_between_groups = float(input("Задержка между группами (секунды): ") or "2")
            delay_between_cycles = float(input("Задержка между циклами (секунды): ") or "10")
            
        except:
            cycles = 1
            delay_between_groups = 2
            delay_between_cycles = 10
        
        print(f"{Fore.GREEN}Начинаем спам в {len(selected_chats)} чатов...{Style.RESET_ALL}")
        
        total_sent = 0
        
        for cycle in range(cycles):
            print(f"{Fore.YELLOW}Цикл {cycle + 1}/{cycles}{Style.RESET_ALL}")
            
            for i, (chat_id, chat_title, chat_entity) in enumerate(selected_chats):
                try:
                    # ПЕРЕСЫЛАЕМ оригинальное сообщение
                    await client.forward_messages(
                        chat_entity,
                        message_data['original_message']
                    )
                    
                    print(f"{Fore.GREEN}[Цикл {cycle+1}] Отправлено в: {chat_title}{Style.RESET_ALL}")
                    total_sent += 1
                    
                    # Задержка между группами
                    if i < len(selected_chats) - 1:
                        await asyncio.sleep(delay_between_groups)
                        
                except Exception as e:
                    print(f"{Fore.RED}[!] Ошибка отправки в {chat_title}: {str(e)}{Style.RESET_ALL}")
                    continue
            
            # Задержка между циклами
            if cycle < cycles - 1:
                print(f"{Fore.YELLOW}Пауза между циклами: {delay_between_cycles} секунд{Style.RESET_ALL}")
                await asyncio.sleep(delay_between_cycles)
        
        print(f"{Fore.CYAN}═" * 50)
        print(f"📊 ИТОГ СПАМА ПО ГРУППАМ")
        print(f"├─ Всего циклов: {cycles}")
        print(f"├─ Чатов в цикле: {len(selected_chats)}")
        print(f"├─ Всего отправок: {total_sent}")
        print(f"└─ Источник чатов: {'Файл' if source_choice == 1 else 'Диалоги'}")
        print(f"═" * 50 + Style.RESET_ALL)
                
    except Exception as e:
        print(f"{Fore.RED}Ошибка спама по группам: {str(e)}{Style.RESET_ALL}")

# Остальные функции остаются без изменений
async def invite_users(client, group_username=None, users_file=None):
    try:
        # Если не указаны параметры - показываем выбор чата
        if not group_username:
            print(f"{Fore.YELLOW}Получаем список чатов...{Style.RESET_ALL}")
            
            chats = []
            last_date = None
            chunk_size = 100
            groups = []
            
            result = await client(GetDialogsRequest(
                offset_date=last_date,
                offset_id=0,
                offset_peer=InputPeerEmpty(),
                limit=chunk_size,
                hash=0
            ))
            chats.extend(result.chats)
            
            for chat in chats:
                try:
                    if hasattr(chat, 'megagroup') and chat.megagroup:
                        groups.append(chat)
                except:
                    continue
            
            if not groups:
                print(f"{Fore.RED}Не найдено групп/супергрупп!{Style.RESET_ALL}")
                return
            
            # Показываем список групп
            print(f"{Fore.YELLOW}Выберите группу для инвайта:{Style.RESET_ALL}")
            for i, group in enumerate(groups):
                print(f"{Fore.GREEN}[{i}] {group.title}{Style.RESET_ALL}")
            
            try:
                g_index = int(input(f"{Fore.YELLOW}Введите номер группы: {Style.RESET_ALL}"))
                target_group = groups[g_index]
                group_entity = InputPeerChannel(target_group.id, target_group.access_hash)
            except (ValueError, IndexError):
                print(f"{Fore.RED}Неверный выбор группы!{Style.RESET_ALL}")
                return
        
        else:
            # Если группа указана напрямую
            entity = await client.get_entity(group_username)
            group_entity = InputPeerChannel(entity.id, entity.access_hash)
        
        # Запрос файла с пользователями если не указан
        if not users_file:
            users_file = input(f"{Fore.YELLOW}Введите путь к файлу с пользователями: {Style.RESET_ALL}")
        
        # Чтение пользователей из файла
        users_to_add = []
        try:
            with open(users_file, 'r', encoding='UTF-8') as f:
                # Парсим CSV или текстовый файл
                if users_file.endswith('.csv'):
                    import csv
                    reader = csv.reader(f, delimiter=",", lineterminator="\n")
                    next(reader, None)  # Пропускаем заголовок
                    for row in reader:
                        if len(row) >= 4:
                            users_to_add.append({
                                'username': row[0],
                                'id': int(row[1]),
                                'access_hash': int(row[2]),
                                'name': row[3]
                            })
                else:
                    # Текстовый файл с нашим форматом
                    for line in f:
                        user_data = parse_user_line(line.strip())
                        if 'id' in user_data or 'username' in user_data:
                            users_to_add.append(user_data)
        
        except Exception as e:
            print(f"{Fore.RED}Ошибка чтения файла: {str(e)}{Style.RESET_ALL}")
            return
        
        if not users_to_add:
            print(f"{Fore.RED}Не найдено пользователей в файле!{Style.RESET_ALL}")
            return
        
        # Выбор количества
        print(f"{Fore.YELLOW}Всего пользователей в файле: {len(users_to_add)}{Style.RESET_ALL}")
        max_users_input = input("Сколько пользователей добавить? (Enter - всех): ")
        
        if max_users_input.strip():
            max_users = int(max_users_input)
            users_to_add = users_to_add[:max_users]
        
        print(f"{Fore.GREEN}Будет добавлено пользователей: {len(users_to_add)}{Style.RESET_ALL}")
        
        # Выбор режима добавления
        print(f"{Fore.YELLOW}[1] Добавлять по user_id")
        print(f"[2] Добавлять по username{Style.RESET_ALL}")
        
        try:
            mode = int(input(f"{Fore.YELLOW}Выберите режим: {Style.RESET_ALL}"))
            if mode not in [1, 2]:
                mode = 1
        except:
            mode = 1
        
        # Тихий режим
        print(f"{Fore.YELLOW}Режим вывода:{Style.RESET_ALL}")
        print("1. Тихий режим (только итог)")
        print("2. Подробный режим (все сообщения)")
        
        try:
            verbose_mode = int(input("Выберите режим (1 или 2): ")) == 2
        except:
            verbose_mode = False
        
        success_count = 0
        error_count = 0
        
        # Процесс добавления
        for i, user_data in enumerate(users_to_add, 1):
            try:
                if mode == 1 and 'id' in user_data:
                    user_entity = await client.get_entity(user_data['id'])
                    await client(InviteToChannelRequest(group_entity, [user_entity]))
                    success_count += 1
                elif mode == 2 and 'username' in user_data:
                    user_entity = await client.get_entity(user_data['username'])
                    await client(InviteToChannelRequest(group_entity, [user_entity]))
                    success_count += 1
                else:
                    error_count += 1
                    continue
                
                if verbose_mode:
                    user_name = user_data.get('name', user_data.get('username', f'user_{i}'))
                    print(f"{Fore.GREEN}[{i}/{len(users_to_add)}] Добавлен: {user_name}{Style.RESET_ALL}")
                
                # Прогресс каждые 10 пользователей
                if i % 10 == 0 and not verbose_mode:
                    print(f"{Fore.YELLOW}[Прогресс] Обработано: {i}/{len(users_to_add)}{Style.RESET_ALL}")
                
                # Задержка из настроек
                delay = get_delay()
                await asyncio.sleep(delay)
                
            except PeerFloodError:
                print(f"{Fore.RED}[!] Flood Error от Telegram. Останавливаемся.{Style.RESET_ALL}")
                break
            except UserPrivacyRestrictedError:
                error_count += 1
                continue
            except Exception as e:
                error_count += 1
                continue
        
        # Финальный отчет
        print(f"{Fore.CYAN}═" * 50)
        print(f"📊 ИТОГ ИНВАЙТА")
        print(f"├─ Всего пользователей: {len(users_to_add)}")
        print(f"├─ Успешно добавлено: {success_count}")
        print(f"├─ Не удалось добавить: {error_count}")
        print(f"└─ Процент успеха: {success_count/len(users_to_add)*100:.1f}%")
        print(f"═" * 50 + Style.RESET_ALL)
                
    except Exception as e:
        print(f"{Fore.RED}Критическая ошибка: {str(e)}{Style.RESET_ALL}")

def load_users_from_file(users_file):
    """Загрузка пользователей из файла"""
    users_to_add = []
    try:
        with open(users_file, 'r', encoding='UTF-8') as f:
            if users_file.endswith('.csv'):
                import csv
                reader = csv.reader(f, delimiter=",", lineterminator="\n")
                next(reader, None)
                for row in reader:
                    if len(row) >= 4:
                        users_to_add.append({
                            'username': row[0],
                            'id': int(row[1]),
                            'access_hash': int(row[2]),
                            'name': row[3]
                        })
            else:
                for line in f:
                    user_data = parse_user_line(line.strip())
                    if 'id' in user_data or 'username' in user_data:
                        users_to_add.append(user_data)
    except:
        pass
    return users_to_add
        
async def parse_chat(client, chat_link=None):
    try:
        # Если не указана ссылка - показываем выбор чата
        if not chat_link:
            print(f"{Fore.YELLOW}Получаем список чатов...{Style.RESET_ALL}")
            
            chats = []
            last_date = None
            chunk_size = 200
            groups = []
            
            result = await client(GetDialogsRequest(
                offset_date=last_date,
                offset_id=0,
                offset_peer=InputPeerEmpty(),
                limit=chunk_size,
                hash=0
            ))
            chats.extend(result.chats)
            
            for chat in chats:
                try:
                    if hasattr(chat, 'megagroup') and chat.megagroup:
                        groups.append(chat)
                except:
                    continue
            
            if not groups:
                print(f"{Fore.RED}Не найдено групп/супергрупп!{Style.RESET_ALL}")
                return
            
            # Показываем список групп
            print(f"{Fore.YELLOW}Выберите группу для парсинга:{Style.RESET_ALL}")
            for i, group in enumerate(groups):
                print(f"{Fore.GREEN}[{i}] {group.title}{Style.RESET_ALL}")
            
            try:
                g_index = int(input(f"{Fore.YELLOW}Введите номер группы: {Style.RESET_ALL}"))
                target_group = groups[g_index]
                entity = target_group
            except (ValueError, IndexError):
                print(f"{Fore.RED}Неверный выбор группы!{Style.RESET_ALL}")
                return
        else:
            # Если ссылка указана напрямую
            entity = await client.get_entity(chat_link)
        
        # Спрашиваем имя файла для сохранения
        filename = input("Введите имя файла для сохранения (без .txt): ")
        if not filename:
            filename = f"parsed_users_{int(time.time())}"
        
        filename += ".txt"
        filepath = os.path.join(os.getcwd(), filename)  # Сохраняем в текущую папку
        
        print(f"{Fore.YELLOW}Собираем участников...{Style.RESET_ALL}")
        
        # Получаем всех участников
        all_participants = await client.get_participants(entity, aggressive=True)
        
        print(f"{Fore.YELLOW}Сохраняем в файл...{Style.RESET_ALL}")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for user in all_participants:
                user_info = []
                
                if user.id:
                    user_info.append(f"ID: {user.id}")
                if user.username:
                    user_info.append(f"Username: @{user.username}")
                if user.first_name:
                    user_info.append(f"First Name: {user.first_name}")
                if user.last_name:
                    user_info.append(f"Last Name: {user.last_name}")
                if user.phone:
                    user_info.append(f"Phone: {user.phone}")
                if hasattr(user, 'access_hash'):
                    user_info.append(f"Access Hash: {user.access_hash}")
                
                if user_info:
                    f.write(" | ".join(user_info) + "\n")
        
        print(f"{Fore.GREEN}Чат успешно пропарсен! Найдено {len(all_participants)} пользователей.{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Данные сохранены в файл: {filepath}{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}Ошибка парсинга: {str(e)}{Style.RESET_ALL}")

async def add_account():
    print_banner()
    print(f"{Fore.YELLOW}ДОБАВЛЕНИЕ АККАУНТА{Style.RESET_ALL}")
    print()
    
    phone = input("Введите номер телефона: ")
    
    # Проверяем сохраненные API credentials
    api_id, api_hash = load_api_credentials()
    
    if not api_id or not api_hash:
        print(f"{Fore.YELLOW}API данные не найдены. Введите вручную:{Style.RESET_ALL}")
        api_id = input("Введите API ID: ")
        api_hash = input("Введите API Hash: ")
        save_api_credentials(api_id, api_hash)
    
    use_proxy = input("Использовать прокси? (y/n): ").lower()
    proxy = None
    
    if use_proxy == 'y':
        proxy = await setup_proxy(None)
    
    client = TelegramClient(f'sessions/{phone}', api_id, api_hash, proxy=proxy)
    await client.start()
    
    save_settings('ACCOUNTS', phone, f'{api_id}:{api_hash}:{proxy}')
    print(f"{Fore.GREEN}Аккаунт успешно добавлен!{Style.RESET_ALL}")
    await client.disconnect()

async def setup_api():
    print_banner()
    print(f"{Fore.YELLOW}НАСТРОЙКА API{Style.RESET_ALL}")
    print()
    
    api_id = input("Введите API ID: ")
    api_hash = input("Введите API Hash: ")
    
    save_api_credentials(api_id, api_hash)
    print(f"{Fore.GREEN}API данные сохранены!{Style.RESET_ALL}")

async def main():
    print_banner()
    
    # Проверяем API настройки
    api_id, api_hash = load_api_credentials()
    if not api_id or not api_hash:
        print(f"{Fore.YELLOW}API данные не настроены. Сначала настройте API.{Style.RESET_ALL}")
        await setup_api()
    
    while True:
        print(f"{Fore.YELLOW}ГЛАВНОЕ МЕНЮ{Style.RESET_ALL}")
        delay_info = get_delay_info()
        print(f"{Fore.CYAN}Задержка: {delay_info}{Style.RESET_ALL}")
        print("1. Инвайтер")
        print("2. Добавить аккаунт")
        print("3. Парсер чатов")
        print("4. Спамер в ЛС")
        print("5. Спам по группам")  
        print("6. Настройки прокси")
        print("7. Настройки API")
        print("8. Настройка задержки")
        print("9. Выход")
        print()
        
        choice = input("Выберите опцию: ")
        
        if choice == "1":
            print_banner()
            print(f"{Fore.YELLOW}ИНВАЙТЕР{Style.RESET_ALL}")

            accounts = [acc for acc in config['ACCOUNTS']] if 'ACCOUNTS' in config else []
            if not accounts:
                print(f"{Fore.RED}Нет добавленных аккаунтов!{Style.RESET_ALL}")
                continue
            print("Доступные аккаунты:")
            for i, acc in enumerate(accounts, 1):
                print(f"{i}. {acc}")

            acc_choice = int(input("Выберите аккаунт: ")) - 1
            phone = accounts[acc_choice]
            acc_api_id, acc_api_hash, proxy_str = config['ACCOUNTS'][phone].split(':')

            proxy = eval(proxy_str) if proxy_str != 'None' else None

            client = TelegramClient(f'sessions/{phone}', acc_api_id, acc_api_hash, proxy=proxy)
            await client.start()
            await invite_users(client)
            await client.disconnect()
            
        elif choice == "2":
            await add_account()
            
        elif choice == "3":
            print_banner()
            print(f"{Fore.YELLOW}ПАРСЕР ЧАТОВ{Style.RESET_ALL}")
            
            accounts = [acc for acc in config['ACCOUNTS']] if 'ACCOUNTS' in config else []
            if not accounts:
                print(f"{Fore.RED}Нет добавленных аккаунтов!{Style.RESET_ALL}")
                continue
                
            print("Доступные аккаунты:")
            for i, acc in enumerate(accounts, 1):
                print(f"{i}. {acc}")
                
            acc_choice = int(input("Выберите аккаунт: ")) - 1
            phone = accounts[acc_choice]
            acc_api_id, acc_api_hash, proxy_str = config['ACCOUNTS'][phone].split(':')
            
            proxy = eval(proxy_str) if proxy_str != 'None' else None
            
            client = TelegramClient(f'sessions/{phone}', acc_api_id, acc_api_hash, proxy=proxy)
            await client.start()
            await parse_chat(client)
            await client.disconnect()
            
        elif choice == "4":
            print_banner()
            print(f"{Fore.YELLOW}СПАМЕР В ЛС{Style.RESET_ALL}")

            accounts = [acc for acc in config['ACCOUNTS']] if 'ACCOUNTS' in config else []
            if not accounts:
                print(f"{Fore.RED}Нет добавленных аккаунтов!{Style.RESET_ALL}")
                continue

            print("Доступные аккаунты:")
            for i, acc in enumerate(accounts, 1):
                print(f"{i}. {acc}")

            acc_choice = int(input("Выберите аккаунт: ")) - 1
            phone = accounts[acc_choice]
            acc_api_id, acc_api_hash, proxy_str = config['ACCOUNTS'][phone].split(':')

            proxy = eval(proxy_str) if proxy_str != 'None' else None

            client = TelegramClient(f'sessions/{phone}', acc_api_id, acc_api_hash, proxy=proxy)
            await client.start()

            await spam_messages(client)

            await client.disconnect()

        elif choice == "5":
            print_banner()
            print(f"{Fore.YELLOW}СПАМ ПО ГРУППАМ{Style.RESET_ALL}")
            
            accounts = [acc for acc in config['ACCOUNTS']] if 'ACCOUNTS' in config else []
            if not accounts:
                print(f"{Fore.RED}Нет добавленных аккаунтов!{Style.RESET_ALL}")
                continue
                
            print("Доступные аккаунты:")
            for i, acc in enumerate(accounts, 1):
                print(f"{i}. {acc}")
                
            acc_choice = int(input("Выберите аккаунт: ")) - 1
            phone = accounts[acc_choice]
            acc_api_id, acc_api_hash, proxy_str = config['ACCOUNTS'][phone].split(':')
            
            proxy = eval(proxy_str) if proxy_str != 'None' else None
            
            client = TelegramClient(f'sessions/{phone}', acc_api_id, acc_api_hash, proxy=proxy)
            await client.start()
            await spam_to_groups(client)
            await client.disconnect()
            
        elif choice == "6":
            print_banner()
            print(f"{Fore.YELLOW}НАСТРОЙКИ ПРОКСИ{Style.RESET_ALL}")
            await setup_proxy(None)
            
        elif choice == "7":
            await setup_api()
            
        elif choice == "8":
            await setup_delay()
            
        elif choice == "9":
            print(f"{Fore.GREEN}Выход из программы...{Style.RESET_ALL}")
            break
            
        else:
            print(f"{Fore.RED}Неверный выбор! Попробуйте снова.{Style.RESET_ALL}")
        
        # Пауза перед возвратом в меню
        input(f"\n{Fore.YELLOW}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        print_banner()


if __name__ == "__main__":
    if not os.path.exists('sessions'):
        os.makedirs('sessions')
    
    asyncio.run(main())
