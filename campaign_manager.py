"""Модуль для управления рассылками"""
import asyncio
from database import Database


class CampaignManager:
    """Класс для управления запуском, выполнением и остановкой рассылок"""
    
    def __init__(self, db: Database):
        self.db = db
        self.active_campaigns = {}  # {campaign_id: asyncio.Task}
    
    async def start_dm_campaign(self, user_id: int, campaign_id: int, client, 
                                text: str, rounds: int, delay: int):
        """Запускает рассылку по личным сообщениям"""
        try:
            # Получаем настройку авто-подписки
            user = await self.db.get_user(user_id)
            auto_subscribe = user.get('auto_subscribe', 0) == 1 if user else False
            
            # Получаем список личных чатов
            private_chats = await client.get_private_chats()
            
            if not private_chats:
                await self.db.update_campaign_status(campaign_id, 'error')
                return
            
            # Выполняем указанное количество кругов
            sent_total = 0
            success_total = 0
            error_total = 0
            
            for round_num in range(rounds):
                print(f"[CAMPAIGN {campaign_id}] Круг {round_num + 1}/{rounds}, чатов: {len(private_chats)}")
                
                for entity in private_chats:
                    try:
                        result = await client.send_message(entity, text, delay, auto_subscribe)
                        sent_total += 1
                        if result:
                            success_total += 1
                        else:
                            error_total += 1
                        
                        # Обновляем статистику каждые 10 сообщений
                        if sent_total % 10 == 0:
                            await self.db.update_campaign_stats(campaign_id, sent_total, success_total, error_total)
                            sent_total = 0
                            success_total = 0
                            error_total = 0
                    except Exception as e:
                        error_total += 1
                        sent_total += 1
                        error_msg = str(e).lower()
                        # Обрабатываем "Too many requests"
                        if "too many requests" in error_msg or "too many" in error_msg:
                            print(f"[CAMPAIGN {campaign_id}] Too many requests, увеличиваем задержку")
                            await asyncio.sleep(delay * 2)  # Увеличиваем задержку в 2 раза
                        else:
                            print(f"[CAMPAIGN {campaign_id}] Ошибка отправки: {e}")
                        continue
                
                # Задержка между кругами (кроме последнего) - уменьшено для скорости
                if round_num < rounds - 1:
                    await asyncio.sleep(2)
            
            # Финальное обновление статистики
            if sent_total > 0:
                await self.db.update_campaign_stats(campaign_id, sent_total, success_total, error_total)
            
            # Обновляем статус на завершен
            await self.db.update_campaign_status(campaign_id, 'completed')
            
        except asyncio.CancelledError:
            await self.db.update_campaign_status(campaign_id, 'stopped')
            raise
        except Exception as e:
            print(f"Ошибка в рассылке: {e}")
            await self.db.update_campaign_status(campaign_id, 'error')
    
    async def start_folder_campaign(self, user_id: int, campaign_id: int, client,
                                   folder_name: str, rounds: int, delay: int):
        """Запускает рассылку по папкам"""
        try:
            # Получаем текст из БД
            campaign = await self.db.get_campaign(campaign_id)
            if not campaign:
                await self.db.update_campaign_status(campaign_id, 'error')
                return
            
            text = campaign.get('text', '')
            
            # Получаем настройку авто-подписки
            user = await self.db.get_user(user_id)
            auto_subscribe = user.get('auto_subscribe', 0) == 1 if user else False
            
            # Получаем чаты из папки
            folder_chats = await client.get_folder_chats(folder_name)
            
            if not folder_chats:
                await self.db.update_campaign_status(campaign_id, 'error')
                return
            
            # Выполняем указанное количество кругов
            sent_total = 0
            success_total = 0
            error_total = 0
            
            for round_num in range(rounds):
                print(f"[CAMPAIGN {campaign_id}] Круг {round_num + 1}/{rounds}, чатов: {len(folder_chats)}")
                
                for entity in folder_chats:
                    try:
                        result = await client.send_message(entity, text, delay, auto_subscribe)
                        sent_total += 1
                        if result:
                            success_total += 1
                        else:
                            error_total += 1
                        
                        # Обновляем статистику каждые 10 сообщений
                        if sent_total % 10 == 0:
                            await self.db.update_campaign_stats(campaign_id, sent_total, success_total, error_total)
                            sent_total = 0
                            success_total = 0
                            error_total = 0
                    except Exception as e:
                        error_total += 1
                        sent_total += 1
                        error_msg = str(e).lower()
                        # Обрабатываем "Too many requests"
                        if "too many requests" in error_msg or "too many" in error_msg:
                            print(f"[CAMPAIGN {campaign_id}] Too many requests, увеличиваем задержку")
                            await asyncio.sleep(delay * 2)  # Увеличиваем задержку в 2 раза
                        else:
                            print(f"[CAMPAIGN {campaign_id}] Ошибка отправки: {e}")
                        continue
                
                # Задержка между кругами (кроме последнего) - уменьшено для скорости
                if round_num < rounds - 1:
                    await asyncio.sleep(2)
            
            # Финальное обновление статистики
            if sent_total > 0:
                await self.db.update_campaign_stats(campaign_id, sent_total, success_total, error_total)
            
            # Обновляем статус на завершен
            await self.db.update_campaign_status(campaign_id, 'completed')
            
        except asyncio.CancelledError:
            await self.db.update_campaign_status(campaign_id, 'stopped')
            raise
        except Exception as e:
            print(f"Ошибка в рассылке: {e}")
            await self.db.update_campaign_status(campaign_id, 'error')
    
    async def stop_campaign(self, campaign_id: int):
        """Останавливает рассылку"""
        if campaign_id in self.active_campaigns:
            task = self.active_campaigns[campaign_id]
            task.cancel()
            del self.active_campaigns[campaign_id]
            await self.db.update_campaign_status(campaign_id, 'stopped')
            return True
        return False
