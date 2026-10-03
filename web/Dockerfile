# 声のCanva Web UI (Next.js)
# Build: docker build --build-arg NEXT_BASE_PATH=/canva -t voice-canva-web web/
# Run:   docker run -p 3000:3000 -e CANVA_API_URL=http://voice-canva:8770 voice-canva-web
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# basePath とクライアント側 API プレフィックスはビルド時に焼き込まれる
ARG NEXT_BASE_PATH=""
ARG NEXT_PUBLIC_BASE_PATH=""
ARG CANVA_API_URL="http://127.0.0.1:8770"
ENV NEXT_BASE_PATH=$NEXT_BASE_PATH \
    NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH \
    CANVA_API_URL=$CANVA_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
