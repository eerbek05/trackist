.PHONY: up build down logs

# Normal start — kod değişmedi, sadece container'ları kaldır
up:
	docker-compose up --remove-orphans

# Kod değişti, image'ları yeniden build et, sonra kaldır
build:
	docker-compose up --build --remove-orphans

down:
	docker-compose down

logs:
	docker-compose logs -f
