from typing import NewType
from uuid import UUID

OrganizationId = NewType("OrganizationId", UUID)
DepartmentId = NewType("DepartmentId", UUID)
UserId = NewType("UserId", UUID)
