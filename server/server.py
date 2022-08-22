import argparse
import asyncio
import json
import logging
import functools
import time
from random import randint

# 65535
SEPARATOR = b'\xFF\xFF'
TUNNEL_MAP = {}

fmt = '%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s'
logging.basicConfig(format=fmt, level=logging.INFO)


def encode_msg(msg):
    if type(msg) == bytes:
        return msg + SEPARATOR
    return msg.encode() + SEPARATOR


def decode_msg(msg: bytes):
    return msg.strip(SEPARATOR).decode()


async def heart_beat(writer, last_heartbeat):
    while True:
        if time.time() - last_heartbeat[0] > 20:
            writer.close()
            raise asyncio.exceptions.TimeoutError()
        await asyncio.sleep(10)


async def parse_msg(reader: asyncio.StreamReader, writer):
    try:
        last_heartbeat = [time.time(), 0]
        heartbeat_task = asyncio.create_task(heart_beat(writer, last_heartbeat))
        while True:
            data = await reader.readuntil(SEPARATOR)
            data = decode_msg(data)
            if data == 'pong':
                # TODO: record last pong
                continue
            if data == 'ping':
                last_heartbeat[0] = time.time()
                writer.write(encode_msg('pong'))
                await writer.drain()
            logging.info(data)
    except asyncio.IncompleteReadError as e:
        logging.exception(e)
    finally:
        heartbeat_task.cancel()
        logging.info("Close the connection")
        writer.close()


async def join_pipe(reader, writer):
    try:
        while not reader.at_eof():
            data = await reader.read(2048)
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def make_pipe(pipe_reader: asyncio.StreamReader, pipe_writer: asyncio.StreamWriter, message: dict):
    # parse msg
    if not message:
        logging.error(f"No pipe make message")
        return

    logging.info(f"make pipe for {message}")
    payload = message['payload']
    server_id = int(payload['server_id'])
    endpoint_reader, endpoint_writer = TUNNEL_MAP[server_id]

    # make pipe
    task_list = [
        asyncio.create_task(join_pipe(pipe_reader, endpoint_writer)),
        asyncio.create_task(join_pipe(endpoint_reader, pipe_writer)),
    ]

    await asyncio.wait(task_list)
    logging.info("pipe %d disconnected", server_id)


async def make_endpoint(tunnel_server_id, tunnel_reader: asyncio.StreamReader, tunnel_writer: asyncio.StreamWriter,
                        endpoint_reader: asyncio.StreamReader, endpoint_writer: asyncio.StreamWriter):
    server_id = randint(0, 19260817)
    TUNNEL_MAP[server_id] = (endpoint_reader, endpoint_writer)

    endpoint_addr = endpoint_writer.get_extra_info('peername')
    tunnel_addr = tunnel_writer.get_extra_info('peername')
    logging.info(f"serving endpoint {endpoint_addr}, current tunnel is {tunnel_addr}")
 
    server_id = randint(0, 19260817)
    TUNNEL_MAP[server_id] = (endpoint_reader, endpoint_writer)

    try:
        tunnel_writer.write(encode_msg(f'start proxy at {server_id}'))
        await tunnel_writer.drain()
    except Exception as e:
        logging.error(e, exc_info=True)


async def make_endpoint_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, server_id, message, data):
    # TODO: 将异常发送到客户端
    try:
        logging.info(functools.partial(make_endpoint, server_id, reader, writer))
        tunnel_server = await asyncio.start_server(
            functools.partial(make_endpoint, server_id, reader, writer), message['remote_addr'], message['remote_port']
        )
        await tunnel_server.start_serving()
        logging.info(f"listening endpoint on : {(message['remote_addr'], message['remote_port'])!r}")
    except Exception as e:
        logging.error(e, exc_info=True)
        writer.write(encode_msg(str(e)))
        await writer.drain()
        writer.close()
        return

    writer.write(data)
    await writer.drain()

    # hreat_beat, deal instraction
    tasks_list = []
    try:
        tasks_list = [
            asyncio.create_task(parse_msg(reader, writer))
        ]
        await asyncio.wait(tasks_list, return_when=asyncio.tasks.FIRST_EXCEPTION)
    finally:
        for t in tasks_list:
            t.cancel()
        logging.info("Close the tunnel_server")
        writer.close()
        tunnel_server.close()


async def make_tunnel(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    # 从流中读取数据直至遇到 separator
    data = await reader.readuntil(SEPARATOR)
    message = data.strip(SEPARATOR).decode()
    address = writer.get_extra_info('peername')

    logging.info(f"Received {message} from {address}")

    message = json.loads(message)

    # 生成一个隧道
    server_id = randint(0, 19260817)
    TUNNEL_MAP[server_id] = (reader, writer)

    # parse msg
    logging.info(decode_msg(data))
    msg_type = message['type']

    if msg_type == 'PLUG_IN':
        logging.info('PLUG_IN')
        return await make_pipe(reader, writer, message)
    if msg_type == 'CONNECTOR':
        logging.info('CONNECTOR')
        return await make_endpoint_server(reader, writer, server_id, message, data)


async def run():
    """
    创建网络服务并开始接受连接
    :return:
    """
    my_server = await asyncio.start_server(make_tunnel, host='0.0.0.0', port=9876)
    await my_server.serve_forever()


def main():
    asyncio.run(run())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="intranet_penetration server")
    parser.add_argument('--host', default='0.0.0.0', help="Server host(ip)")
    parser.add_argument('--port', default='9876', help="Server port")
    parser.add_argument('--debug', help="Turn on debug mod", action='store_true')
    args = parser.parse_args()
    SERVER_ADDR = (args.host, args.port)
    logging.info("intranet_penetration server listening on {}".format(SERVER_ADDR))
    main()
