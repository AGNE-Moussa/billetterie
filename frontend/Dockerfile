# Image du front : build Vite dans une étape Node, puis Nginx qui sert dist/.
# Contexte de construction : frontend/ (voir .dockerignore) ; ni e2e/ ni les tests n'y entrent.

# --- Étape 1 : build -------------------------------------------------------------------------
FROM node:22.20.0-alpine AS build
WORKDIR /app

# Dépendances d'abord : cette couche reste en cache tant que le lockfile ne change pas.
COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.ts tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build

# --- Étape 2 : service -----------------------------------------------------------------------
# Image finale sans Node ni node_modules : seulement Nginx et les fichiers construits.
# Variante non privilégiée : Nginx tourne sous l'utilisateur nginx (UID 101), jamais root,
# et écoute donc sur un port non privilégié (8080).
FROM nginxinc/nginx-unprivileged:1.28.0-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
