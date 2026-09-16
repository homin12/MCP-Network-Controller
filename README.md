# MCP Network Controller

Прототип системы управления конфигурациями сети на основе протокола Model Context Protocol (MCP), многоагентной архитектуры и локальных LLM.

## Быстрый старт

### Клонирование репозитория

```bash
git clone <repo-url>
cd MCP-Network-Controller
```
### Настройка GNS3

* Установите и запустите GNS3.

* Включите REST API (по умолчанию на порту 3080).

* Создайте проект с маршрутизаторами

* Получите PROJECT_ID: 
```bash
curl http://localhost:3080/v2/projects
```

### Запуск всех сервисов

```bash
docker-compose up -d
```
### Загрузка LLM-модели
```bash
docker exec -it ollama ollama pull qwen2.5-coder:14b
```
### Проверка работоспособности
```bash
curl http://localhost:5000/health
```
```bash
curl http://localhost:8000/health
```
```bash
curl http://localhost:11434/api/tags
```
```bash
curl http://localhost:9996/api/v2/version
```
### Открытие Swagger UI

Откройте в браузере для проверки сценариев: http://localhost:8000/docs