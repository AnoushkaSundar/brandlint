# Runs the dev server rather than a production build. docker-compose.yml sets
# NEXT_PUBLIC_API_URL when the container starts, and a production build would fix
# that value at build time and ignore it.
FROM node:22.23.4-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
