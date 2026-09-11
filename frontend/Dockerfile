# Сборка фронта. В проде статику отдаёт бэкенд из backend/static,
# этот образ нужен только для docker-compose-разработки.
FROM node:22-alpine

WORKDIR /app

# npm ci ставит ровно то, что в lock-файле — в отличие от npm install,
# который мог подтянуть другие версии.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
