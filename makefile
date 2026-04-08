.PHONY: test build rebuild

test:
	@echo 🧪 Запуск тестов...
	pytest tests/ -v --tb=short
	@echo ✅ Тесты пройдены.

build: test
	@echo 🐳 Сборка Docker-образа...
	docker-compose up -d --build
	@echo ✅ Образ собран.

rebuild:
	@echo 🔥 Принудительная пересборка...
	docker-compose up --no-cache