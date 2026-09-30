# The upstream Garage image is FROM scratch (no shell, root-owned volumes), so we wrap
# the binary in a pinned Alpine base to get a non-root user and a bootstrap script.
FROM dxflrs/garage:v2.4.1 AS garage

FROM alpine:3.24.2
RUN addgroup -g 10001 -S garage \
    && adduser -u 10001 -S -G garage -H -h /var/lib/garage garage \
    && mkdir -p /var/lib/garage/meta /var/lib/garage/data \
    && chown -R garage:garage /var/lib/garage
COPY --from=garage /garage /usr/local/bin/garage
COPY deploy/object-storage/entrypoint.sh /usr/local/bin/entrypoint.sh
VOLUME ["/var/lib/garage/meta", "/var/lib/garage/data"]
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
