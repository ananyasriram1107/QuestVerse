# QuestVerse frontend image: two stages.
#   Stage 1 (build): Node compiles the React + Vite app into plain static files (dist/).
#   Stage 2 (serve): a tiny nginx image serves those files. Node is NOT in the final image.
#
# VITE_API_BASE_URL is baked into the JavaScript at build time. It must be the address the
# BROWSER uses to reach the API (http://localhost:8010), not a Docker service name.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8010
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
