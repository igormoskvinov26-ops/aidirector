"""Названия ролей отдельным модулем.

Маршрутам они нужны, а импортировать их из app.main нельзя: main импортирует
сами маршруты, и получилось бы кольцо.
"""

ROLE_OWNER = "owner"
ROLE_OPERATOR = "operator"
ROLE_MASTER = "master"
