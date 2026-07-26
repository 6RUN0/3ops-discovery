FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

RUN apk add --no-cache net-snmp

COPY snmpd.conf /etc/snmp/snmpd.conf

EXPOSE 161/udp

# -f foreground, -Lo log to stdout; the v3 user is created from snmpd.conf.
ENTRYPOINT ["snmpd", "-f", "-Lo", "-C", "-c", "/etc/snmp/snmpd.conf"]
