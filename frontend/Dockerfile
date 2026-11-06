FROM node:22.23.4-alpine3.24@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS build
WORKDIR /app
COPY --chown=node:node package.json package-lock.json .npmrc ./
# Build tools are needed only in this discarded build stage.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci && chown -R node:node /app
USER node
COPY --chown=node:node --chmod=0755 . ./
RUN npm run build

FROM nginx:1.30.6-alpine3.24@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949 AS runtime
# High port and writable temporary files allow a non-root, read-only runtime.
RUN sed -i '/^user[[:space:]]/d; s@^pid[[:space:]].*;@pid /tmp/nginx.pid;@' /etc/nginx/nginx.conf
USER nginx
COPY --chmod=0644 proxy_params_wcp.conf /etc/nginx/proxy_params_wcp.conf
COPY --chmod=0644 nginx.conf /etc/nginx/conf.d/default.conf
# Exact public hostnames are deployment configuration, not a wildcard. The
# localhost defaults preserve container/CI health probes.
ARG NGINX_SERVER_NAMES="localhost 127.0.0.1"
RUN sed -i "s|__NGINX_SERVER_NAMES__|${NGINX_SERVER_NAMES}|g" /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
# Probe loopback directly even when Docker injects an outbound HTTP proxy.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -Y off -q -O /dev/null http://127.0.0.1:8080/ || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
