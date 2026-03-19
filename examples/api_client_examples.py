"""
Примеры использования Yarbot API
Примеры клиентского кода для взаимодействия с FastAPI
"""

import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime


class YarbotAPIClient:
    """Клиент для работы с Yarbot API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """Инициализация клиента.
        
        Args:
            base_url: Базовый URL API (по умолчанию http://localhost:8000)
        """
        self.base_url = base_url
        self.api_url = f"{base_url}/api/v1"
        self.client = httpx.AsyncClient()
    
    async def close(self):
        """Закрыть соединение."""
        await self.client.aclose()
    
    # ==================== Organizations ====================
    
    async def get_organizations(self, telegram_id: int) -> List[Dict[str, Any]]:
        """Получить список организаций пользователя.
        
        Args:
            telegram_id: Telegram ID пользователя
            
        Returns:
            Список организаций
        """
        response = await self.client.get(
            f"{self.api_url}/organizations",
            params={"telegram_id": telegram_id}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_organization(self, organization_id: int) -> Dict[str, Any]:
        """Получить детали организации.
        
        Args:
            organization_id: ID организации
            
        Returns:
            Детали организации
        """
        response = await self.client.get(
            f"{self.api_url}/organizations/{organization_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def create_organization(
        self,
        name: str,
        code: str,
        address: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Создать организацию.
        
        Args:
            name: Название организации
            code: Код организации
            address: Адрес (необязательно)
            phone: Телефон (необязательно)
            
        Returns:
            Созданная организация
        """
        data = {
            "name": name,
            "code": code,
            "address": address,
            "phone": phone,
        }
        response = await self.client.post(
            f"{self.api_url}/organizations",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    async def update_organization(
        self,
        organization_id: int,
        name: Optional[str] = None,
        code: Optional[str] = None,
        address: Optional[str] = None,
        phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Обновить организацию.
        
        Args:
            organization_id: ID организации
            name: Новое название (необязательно)
            code: Новый код (необязательно)
            address: Новый адрес (необязательно)
            phone: Новый телефон (необязательно)
            
        Returns:
            Обновленная организация
        """
        data = {}
        if name is not None:
            data["name"] = name
        if code is not None:
            data["code"] = code
        if address is not None:
            data["address"] = address
        if phone is not None:
            data["phone"] = phone
        
        response = await self.client.put(
            f"{self.api_url}/organizations/{organization_id}",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    async def get_organization_employees(
        self,
        organization_id: int,
        include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """Получить список сотрудников организации.
        
        Args:
            organization_id: ID организации
            include_deleted: Включить удаленных сотрудников
            
        Returns:
            Список сотрудников
        """
        response = await self.client.get(
            f"{self.api_url}/organizations/{organization_id}/employees",
            params={"include_deleted": include_deleted}
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Employees ====================
    
    async def get_employees(
        self,
        organization_id: int,
        include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """Получить список сотрудников.
        
        Args:
            organization_id: ID организации
            include_deleted: Включить удаленных сотрудников
            
        Returns:
            Список сотрудников
        """
        response = await self.client.get(
            f"{self.api_url}/employees",
            params={
                "organization_id": organization_id,
                "include_deleted": include_deleted
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def get_employee(self, employee_id: int) -> Dict[str, Any]:
        """Получить детали сотрудника.
        
        Args:
            employee_id: ID сотрудника
            
        Returns:
            Детали сотрудника
        """
        response = await self.client.get(
            f"{self.api_url}/employees/{employee_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def create_employee(
        self,
        organization_id: int,
        employee_type_id: int,
        full_name: str,
        position: Optional[str] = None,
        phone: Optional[str] = None,
        telegram_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Создать сотрудника.
        
        Args:
            organization_id: ID организации
            employee_type_id: ID типа сотрудника
            full_name: ФИО
            position: Должность (необязательно)
            phone: Телефон (необязательно)
            telegram_id: Telegram ID (необязательно)
            
        Returns:
            Созданный сотрудник
        """
        data = {
            "organization_id": organization_id,
            "employee_type_id": employee_type_id,
            "full_name": full_name,
            "position": position,
            "phone": phone,
            "telegram_id": telegram_id,
        }
        response = await self.client.post(
            f"{self.api_url}/employees",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    async def delete_employee(self, employee_id: int) -> Dict[str, Any]:
        """Удалить сотрудника (soft delete).
        
        Args:
            employee_id: ID сотрудника
            
        Returns:
            Сообщение об успехе
        """
        response = await self.client.delete(
            f"{self.api_url}/employees/{employee_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def restore_employee(self, employee_id: int) -> Dict[str, Any]:
        """Восстановить удаленного сотрудника.
        
        Args:
            employee_id: ID сотрудника
            
        Returns:
            Сообщение об успехе
        """
        response = await self.client.post(
            f"{self.api_url}/employees/{employee_id}/restore"
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Criteria ====================
    
    async def get_criteria(
        self,
        organization_id: Optional[int] = None,
        evaluation_type_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Получить список критериев.
        
        Args:
            organization_id: ID организации (необязательно)
            evaluation_type_id: ID типа оценки (необязательно)
            
        Returns:
            Список критериев
        """
        params = {}
        if organization_id:
            params["organization_id"] = organization_id
        if evaluation_type_id:
            params["evaluation_type_id"] = evaluation_type_id
        
        response = await self.client.get(
            f"{self.api_url}/criteria",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    async def create_criterion(
        self,
        organization_id: int,
        evaluation_type_id: int,
        name: str,
        code: str,
        value_type: str = "boolean",
        description: Optional[str] = None,
        sort_order: Optional[int] = None
    ) -> Dict[str, Any]:
        """Создать критерий.
        
        Args:
            organization_id: ID организации
            evaluation_type_id: ID типа оценки
            name: Название критерия
            code: Код критерия
            value_type: Тип значения (boolean, string, number)
            description: Описание (необязательно)
            sort_order: Порядок сортировки (необязательно)
            
        Returns:
            Созданный критерий
        """
        data = {
            "organization_id": organization_id,
            "evaluation_type_id": evaluation_type_id,
            "name": name,
            "code": code,
            "value_type": value_type,
            "description": description,
            "sort_order": sort_order,
        }
        response = await self.client.post(
            f"{self.api_url}/criteria",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Criterion Sets ====================
    
    async def get_criterion_sets(
        self,
        organization_id: int,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """Получить список наборов критериев.
        
        Args:
            organization_id: ID организации
            include_inactive: Включить неактивные наборы
            
        Returns:
            Список наборов критериев
        """
        response = await self.client.get(
            f"{self.api_url}/criterion-sets",
            params={
                "organization_id": organization_id,
                "include_inactive": include_inactive
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def create_criterion_set(
        self,
        organization_id: int,
        name: str,
        criterion_ids: List[int],
        description: Optional[str] = None,
        is_default: bool = False
    ) -> Dict[str, Any]:
        """Создать набор критериев.
        
        Args:
            organization_id: ID организации
            name: Название набора
            criterion_ids: Список ID критериев
            description: Описание (необязательно)
            is_default: Является ли дефолтным
            
        Returns:
            Созданный набор критериев
        """
        data = {
            "organization_id": organization_id,
            "name": name,
            "criterion_ids": criterion_ids,
            "description": description,
            "is_default": is_default,
        }
        response = await self.client.post(
            f"{self.api_url}/criterion-sets",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    async def import_criterion_sets_from_excel(
        self,
        organization_id: int,
        file_path: str
    ) -> Dict[str, Any]:
        """Импортировать наборы критериев из Excel.
        
        Args:
            organization_id: ID организации
            file_path: Путь к Excel файлу
            
        Returns:
            Результат импорта
        """
        with open(file_path, "rb") as f:
            files = {"file": f}
            response = await self.client.post(
                f"{self.api_url}/criterion-sets/import-excel",
                params={"organization_id": organization_id},
                files=files
            )
        response.raise_for_status()
        return response.json()
    
    # ==================== Evaluations ====================
    
    async def get_evaluation(self, evaluation_id: int) -> Dict[str, Any]:
        """Получить детали оценки.
        
        Args:
            evaluation_id: ID оценки
            
        Returns:
            Детали оценки
        """
        response = await self.client.get(
            f"{self.api_url}/evaluations/{evaluation_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def create_evaluation(
        self,
        filled_by_employee_id: int,
        evaluated_employee_id: int,
        criterion_set_id: int,
        evaluation_date: datetime,
        criterion_values: Dict[int, Any],
        comments: Optional[Dict[int, str]] = None
    ) -> Dict[str, Any]:
        """Создать оценку.
        
        Args:
            filled_by_employee_id: ID сотрудника, заполняющего оценку
            evaluated_employee_id: ID оцениваемого сотрудника
            criterion_set_id: ID набора критериев
            evaluation_date: Дата оценки
            criterion_values: Словарь значений критериев {criterion_id: value}
            comments: Словарь комментариев {criterion_id: comment} (необязательно)
            
        Returns:
            Созданная оценка
        """
        data = {
            "filled_by_employee_id": filled_by_employee_id,
            "evaluated_employee_id": evaluated_employee_id,
            "criterion_set_id": criterion_set_id,
            "evaluation_date": evaluation_date.isoformat(),
            "criterion_values": criterion_values,
            "comments": comments,
        }
        response = await self.client.post(
            f"{self.api_url}/evaluations",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Analytics ====================
    
    async def get_criteria_statistics(
        self,
        organization_id: int,
        criterion_ids: Optional[List[int]] = None,
        employee_ids: Optional[List[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        evaluation_type_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Получить статистику по критериям.
        
        Args:
            organization_id: ID организации
            criterion_ids: Список ID критериев (необязательно)
            employee_ids: Список ID сотрудников (необязательно)
            date_from: Дата начала периода (необязательно)
            date_to: Дата окончания периода (необязательно)
            evaluation_type_id: ID типа оценки (необязательно)
            
        Returns:
            Статистика по критериям
        """
        data = {
            "organization_id": organization_id,
            "criterion_ids": criterion_ids,
            "employee_ids": employee_ids,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "evaluation_type_id": evaluation_type_id,
        }
        response = await self.client.post(
            f"{self.api_url}/analytics/criteria-statistics",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    async def get_average_scores(
        self,
        organization_id: int,
        group_by: str = "criterion",
        criterion_ids: Optional[List[int]] = None,
        employee_ids: Optional[List[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Получить средние оценки.
        
        Args:
            organization_id: ID организации
            group_by: Группировка: criterion, employee, date
            criterion_ids: Список ID критериев (необязательно)
            employee_ids: Список ID сотрудников (необязательно)
            date_from: Дата начала периода (необязательно)
            date_to: Дата окончания периода (необязательно)
            
        Returns:
            Средние оценки
        """
        data = {
            "organization_id": organization_id,
            "group_by": group_by,
            "criterion_ids": criterion_ids,
            "employee_ids": employee_ids,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        }
        response = await self.client.post(
            f"{self.api_url}/analytics/average-scores",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Invitations ====================
    
    async def create_invitation(
        self,
        inviter_telegram_id: int,
        organization_id: int,
        ttl: int = 604800  # 7 дней по умолчанию
    ) -> Dict[str, Any]:
        """Создать код приглашения.
        
        Args:
            inviter_telegram_id: Telegram ID создателя приглашения
            organization_id: ID организации
            ttl: Время жизни в секундах (по умолчанию 7 дней)
            
        Returns:
            Код приглашения
        """
        data = {
            "inviter_telegram_id": inviter_telegram_id,
            "organization_id": organization_id,
            "ttl": ttl,
        }
        response = await self.client.post(
            f"{self.api_url}/invitations",
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    async def get_invitation(self, code: str) -> Dict[str, Any]:
        """Получить информацию о приглашении.
        
        Args:
            code: Код приглашения
            
        Returns:
            Информация о приглашении
        """
        response = await self.client.get(
            f"{self.api_url}/invitations/{code}"
        )
        response.raise_for_status()
        return response.json()
    
    async def use_invitation(self, code: str) -> Dict[str, Any]:
        """Использовать приглашение.
        
        Args:
            code: Код приглашения
            
        Returns:
            Информация о приглашении
        """
        response = await self.client.post(
            f"{self.api_url}/invitations/{code}/use"
        )
        response.raise_for_status()
        return response.json()


# ==================== Примеры использования ====================

async def example_usage():
    """Примеры использования API клиента."""
    client = YarbotAPIClient("http://localhost:8000")
    
    try:
        # 1. Создать организацию
        print("1. Создание организации...")
        org = await client.create_organization(
            name="Моя организация",
            code="MY_ORG",
            address="г. Москва, ул. Примерная, 1",
            phone="+7 (999) 123-45-67"
        )
        print(f"Создана организация: {org['name']} (ID: {org['id']})")
        
        # 2. Создать сотрудника
        print("\n2. Создание сотрудника...")
        employee = await client.create_employee(
            organization_id=org['id'],
            employee_type_id=1,
            full_name="Иванов Иван Иванович",
            position="Менеджер",
            phone="+7 (999) 111-22-33"
        )
        print(f"Создан сотрудник: {employee['full_name']} (ID: {employee['id']})")
        
        # 3. Создать критерий
        print("\n3. Создание критерия...")
        criterion = await client.create_criterion(
            organization_id=org['id'],
            evaluation_type_id=1,
            name="Пунктуальность",
            code="PUNCTUALITY",
            value_type="boolean",
            description="Приходит вовремя на работу"
        )
        print(f"Создан критерий: {criterion['name']} (ID: {criterion['id']})")
        
        # 4. Создать набор критериев
        print("\n4. Создание набора критериев...")
        criterion_set = await client.create_criterion_set(
            organization_id=org['id'],
            name="Аттестация 2024",
            criterion_ids=[criterion['id']],
            description="Критерии для аттестации 2024 года",
            is_default=True
        )
        print(f"Создан набор: {criterion_set['name']} (ID: {criterion_set['id']})")
        
        # 5. Получить аналитику
        print("\n5. Получение аналитики...")
        analytics = await client.get_average_scores(
            organization_id=org['id'],
            group_by="employee"
        )
        print(f"Аналитика: {analytics}")
        
        # 6. Создать приглашение
        print("\n6. Создание приглашения...")
        invitation = await client.create_invitation(
            inviter_telegram_id=123456789,
            organization_id=org['id']
        )
        print(f"Создан код приглашения: {invitation['code']}")
        
        print("\n✅ Все операции выполнены успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    finally:
        await client.close()


if __name__ == "__main__":
    import asyncio
    
    # Запустить примеры
    asyncio.run(example_usage())
