FROM postgres:16-alpine
COPY infra/postgres/nextfarm-postgres-entrypoint.sh /usr/local/bin/nextfarm-postgres-entrypoint.sh
RUN chmod +x /usr/local/bin/nextfarm-postgres-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/nextfarm-postgres-entrypoint.sh"]
CMD ["postgres"]
