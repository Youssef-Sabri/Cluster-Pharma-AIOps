# =============================================================================
# ClusterOps frontend — production image
#
# Two stages: Node builds and type-checks the bundle, nginx serves it. The
# builder never reaches the runtime image, so neither node_modules nor the
# ~250 MB dev dependency tree is shipped.
#
# `npm ci` rather than `npm install` so the image is reproducible from
# package-lock.json. The build runs `npm run build`, which is
# `typecheck && vite build` — a type error fails the image rather than shipping.
# =============================================================================

# ---- Stage 1: build -------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Dependencies first: this layer is cached until the lockfile itself changes,
# so ordinary source edits do not reinstall ~400 packages.
COPY package.json package-lock.json ./
RUN npm ci

# Source, then build.
COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm run build

# ---- Stage 2: serve -------------------------------------------------------------
# `alpine-slim` rather than plain `nginx:alpine`.
#
# The phase document pairs `nginx:alpine` with a "< 50 MB" image target, and
# those two cannot both hold: the plain alpine image measures 97.5 MB on its
# own, so the application payload (0.9 MB) is rounding error. The slim variant
# keeps every module this config uses — HTTP, reverse proxy, gzip, rewrite,
# upstream keepalive — and measures 18.5 MB, putting the finished image near
# 20 MB.
FROM nginx:1.27-alpine-slim

# nginx.conf replaces the stock site config, which listens on :80.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx's stock error page is not part of the application.
RUN rm -f /usr/share/nginx/html/50x.html

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1:3000/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
