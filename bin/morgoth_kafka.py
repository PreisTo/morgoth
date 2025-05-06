#!/usr/bin/python

from gcn_kafka import Consumer
from morgoth import morgoth_config
from morgoth.handler import handler
from lxml.etree import fromstring


# Warning: don't share the client secret with others.
consumer = Consumer(
    client_id=morgoth_config["kafka"]["client_id"],
    client_secret=morgoth_config["kafka"]["client_secret"],
)

consumer.subscribe(["gcn.classic.voevent.FERMI_GBM_FLT_POS"])


while True:
    for message in consumer.consume(timeout=1):
        if message.error():
            print(message.error())
            continue
        # Print the topic and message ID
        print(f"topic={message.topic()}, offset={message.offset()}")
        value = message.value()
        print(value)
        handler(value, fromstring(value))
