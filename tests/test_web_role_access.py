from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.routers import web_auth
from app.api.routers.web import employees_data, evaluations_data


EMPLOYEE_TYPES = [
    {"id": 1, "name": "Сотрудник", "code": "employee", "is_administrator": False},
    {"id": 2, "name": "Менеджер", "code": "manager", "is_administrator": False},
    {"id": 3, "name": "Администратор", "code": "admin", "is_administrator": True},
]


def employee(employee_id: int, organization_id: int, employee_type_id: int, name: str):
    return SimpleNamespace(
        id=employee_id,
        organization_id=organization_id,
        employee_type_id=employee_type_id,
        full_name=name,
        position=None,
        is_active=True,
        telegram_id=None,
        meta={},
    )


def evaluation(
    evaluation_id: int,
    organization_id: int,
    target_id: int,
    filler_id: int,
    status: str,
    score: float | None,
):
    return SimpleNamespace(
        id=evaluation_id,
        organization_id=organization_id,
        evaluated_employee_id=target_id,
        filled_by_employee_id=filler_id,
        evaluation_type_id=10,
        criterion_set_id=20,
        status=status,
        score_percentage=score,
        created_at=f"2026-07-{evaluation_id:02d}T10:00:00",
    )


class FakeEmployeeService:
    def __init__(self, employees):
        self.employees = list(employees)

    async def get_employee_types(self):
        return EMPLOYEE_TYPES

    async def get_by_organization_id(self, organization_id):
        return [item for item in self.employees if item.organization_id == organization_id]

    async def get_by_id(self, employee_id):
        return next((item for item in self.employees if item.id == employee_id), None)


class FakeEvaluationService:
    def __init__(self, evaluations):
        self.evaluations = list(evaluations)

    async def get_by_organization_id(self, organization_id):
        return [item for item in self.evaluations if item.organization_id == organization_id]

    async def get_by_id(self, evaluation_id):
        return next((item for item in self.evaluations if item.id == evaluation_id), None)


class FakeEvaluationTypeService:
    async def get_all(self, organization_id):
        return [SimpleNamespace(id=10, name="Проверка смены")]


class UnusedService:
    """Dependency placeholder for branches that must reject before service use."""


def make_client(current_employee, employees, evaluations=()):
    app = FastAPI()
    app.include_router(employees_data.router, prefix="/api/web")
    app.include_router(evaluations_data.router, prefix="/api/web")
    app.include_router(web_auth.router, prefix="/api")

    employee_service = FakeEmployeeService(employees)
    evaluation_service = FakeEvaluationService(evaluations)

    async def current_employee_override():
        return current_employee

    async def employee_service_override():
        return employee_service

    async def evaluation_service_override():
        return evaluation_service

    async def evaluation_type_service_override():
        return FakeEvaluationTypeService()

    async def unused_service_override():
        return UnusedService()

    app.dependency_overrides[web_auth.get_current_web_employee_pin_fresh] = current_employee_override
    app.dependency_overrides[deps.get_employee_service] = employee_service_override
    app.dependency_overrides[deps.get_evaluation_service] = evaluation_service_override
    app.dependency_overrides[deps.get_evaluation_type_service] = evaluation_type_service_override
    app.dependency_overrides[deps.get_invitation_service] = unused_service_override
    app.dependency_overrides[deps.get_organization_service] = unused_service_override
    app.dependency_overrides[deps.get_criterion_service] = unused_service_override
    app.dependency_overrides[deps.get_criterion_set_service] = unused_service_override
    app.dependency_overrides[deps.get_criterion_value_repository] = unused_service_override
    return TestClient(app)


def test_employee_gets_only_self_from_employees_endpoint():
    me = employee(1, 100, 1, "Иван Сотрудник")
    colleague = employee(2, 100, 1, "Анна Коллега")
    with make_client(me, [me, colleague]) as client:
        response = client.get("/api/web/employees")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [me.id]


def test_manager_and_admin_get_only_their_organization_employees():
    manager = employee(1, 100, 2, "Менеджер")
    admin = employee(2, 100, 3, "Администратор")
    colleague = employee(3, 100, 1, "Сотрудник")
    foreign = employee(4, 200, 1, "Чужая организация")

    for actor in (manager, admin):
        with make_client(actor, [manager, admin, colleague, foreign]) as client:
            response = client.get("/api/web/employees")

        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {manager.id, admin.id, colleague.id}
        assert foreign.id not in {item["id"] for item in response.json()}


def test_employee_cannot_change_role_or_delete_employee():
    me = employee(1, 100, 1, "Сотрудник")
    colleague = employee(2, 100, 1, "Коллега")
    with make_client(me, [me, colleague]) as client:
        role_response = client.put(
            f"/api/web/employees/{colleague.id}/role",
            json={"employee_type_id": 2},
        )
        delete_response = client.delete(f"/api/web/employees/{colleague.id}")

    assert role_response.status_code == 403
    assert delete_response.status_code == 403


def test_employee_cannot_manage_invitations():
    me = employee(1, 100, 1, "Сотрудник")
    with make_client(me, [me]) as client:
        list_response = client.get("/api/web/invitations")
        create_response = client.post(
            "/api/web/invitations",
            json={
                "employee_type_id": 1,
                "contact_email": "new@example.com",
                "ttl_seconds": 3600,
            },
        )
        revoke_response = client.delete("/api/web/invitations/example-code")
        standalone_response = client.post(
            "/api/web/auth/invite-standalone",
            json={"ttl_seconds": 3600},
        )

    assert list_response.status_code == 403
    assert create_response.status_code == 403
    assert revoke_response.status_code == 403
    assert standalone_response.status_code == 403


def test_employee_cannot_get_foreign_or_unrelated_evaluation():
    me = employee(1, 100, 1, "Сотрудник")
    colleague = employee(2, 100, 1, "Коллега")
    unrelated = evaluation(1, 100, colleague.id, colleague.id, "completed", 90.0)
    foreign = evaluation(2, 200, me.id, me.id, "completed", 95.0)

    with make_client(me, [me, colleague], [unrelated, foreign]) as client:
        unrelated_response = client.get(f"/api/web/evaluations/{unrelated.id}/detail")
        foreign_response = client.get(f"/api/web/evaluations/{foreign.id}/detail")

    assert unrelated_response.status_code == 403
    assert foreign_response.status_code == 403


def test_employee_average_source_contains_only_related_completed_evaluations():
    me = employee(1, 100, 1, "Сотрудник")
    colleague = employee(2, 100, 1, "Коллега")
    rows = [
        evaluation(1, 100, me.id, colleague.id, "completed", 80.0),
        evaluation(2, 100, colleague.id, me.id, "completed", 60.0),
        evaluation(3, 100, me.id, colleague.id, "in_progress", 100.0),
        evaluation(4, 100, colleague.id, colleague.id, "completed", 10.0),
        evaluation(5, 200, me.id, me.id, "completed", 100.0),
    ]

    with make_client(me, [me, colleague], rows) as client:
        response = client.get("/api/web/evaluations")

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} == {1, 2, 3}
    completed_scores = [
        item["score_percentage"]
        for item in payload
        if item["status"] == "completed" and item["score_percentage"] is not None
    ]
    assert completed_scores == [80.0, 60.0]
    assert sum(completed_scores) / len(completed_scores) == 70.0
