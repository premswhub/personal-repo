import json
import time
import flask
import kafka
import redis
import threading
import datetime
from websocket import create_connection

# Kafka Topic name (Topic with retention of 3 Hours)
TOPIC = "bitcoin"

# Kafka Producer and Consumer Initialization
producer = kafka.KafkaProducer(bootstrap_servers='localhost:9092',
                               value_serializer=lambda v: json.dumps(v).encode('utf-8'))

consumer = kafka.KafkaConsumer(bootstrap_servers='localhost:9092',
                               auto_offset_reset='earliest',
                               value_deserializer=lambda m: json.loads(m.decode('utf-8')))

# Bitcoin Websocket Details
wss = create_connection("wss://ws.blockchain.info/inv")
wss.send(json.dumps({"op":"unconfirmed_sub"}))

# Redis Initialization
redis_host = "localhost"
redis_port = 6379
PER_MINUTE = 'transactions_per_minute'
TRANSACTIONS = 'transactions'
HIGH_VALUE = 'high_value_hash'

r = redis.StrictRedis(host=redis_host, port=redis_port)

# Flask App
app = flask.Flask(__name__)
app.url_map.strict_slashes = False

# Rest APIs
@app.route('/')
def index():
    return("Welcome to bitcoin Stream")

## Print the last 100 Transaction Dump
@app.route('/show_transactions')
def show_trans():
    return flask.Response(r.lrange(TRANSACTIONS, 0, 99), mimetype="text/plain")

# Rate of transaction on minute basic along with the minimum value filter for last one hour
@app.route('/transactions_count_per_minute/<min_value>')
def trans_per_min(min_value):
    out = "minute\tcount\n"
    values = sorted(r.zrange(PER_MINUTE, 0, -1, withscores=True), reverse=True)
    for value in sorted(values[0:60]):
        if (int(value[1]) > int(min_value)):
            continue
        out += '{}\t{}\n'.format(value[0].decode('ascii'), int(value[1]))
    return flask.Response(out, mimetype="text/plain")


# Prints 5 highest values
@app.route('/high_value_addr')
def high_value():
    out = 'address\ttotal_value\n'
    values = r.zrevrange(HIGH_VALUE, 0, 4, withscores=True)
    for value in values:
        out += '{}\t{}\n'.format(value[0].decode('ascii'), int(value[1]))
    return flask.Response(out, mimetype="text/plain")

# Receive stream from Bitcoin WS and stream to Kafka and Redis
def kproducer():
    while True:
        result = wss.recv()
        print(len(result.split('\n')))
        producer.send(TOPIC, result)
        jresult = json.loads(result)
        HHMM = datetime.datetime.fromtimestamp(jresult['x']['time']).strftime('%H:%M')
        r.zincrby(PER_MINUTE, 1, HHMM)
        r.rpush(TRANSACTIONS, json.dumps(jresult).encode('utf-8'))
        for res in jresult['x']['inputs']:
            r.zadd(HIGH_VALUE, {res['prev_out']['addr']: res['prev_out']['value']} )

# Consume log from Kafka ( Log retention of 3 Hours has been set on Topic Level )
def kconsumer():
    consumer.subscribe([TOPIC])
    consumer.poll()
    for message in consumer:
        print(message.timestamp)

if __name__ == "__main__":
    tproducer = threading.Thread(target=kproducer)
    tconsumer = threading.Thread(target=kconsumer)
    tproducer.start()
    tconsumer.start()
    # App can be accessed using http://0.0.0.0:8000
    app.run(host='0.0.0.0', port=8000, debug=True)
