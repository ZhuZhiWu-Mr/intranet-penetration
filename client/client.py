import json
import logging
import argparse
import asyncio
from asyncio import FIRST_COMPLETED

# Extranet Address
SERVER_ADDR = ('', 9876)

SEPARATOR = b'\xFF\xFF'
TUNNEL_MAP = {}

fmt = '%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s'
logging.basicConfig(format=fmt, level=logging.INFO)


def encode_msg(msg):
    if type(msg) == dict:
        return encode_msg(json.dumps(msg))
    if type(msg) == bytes:
        return msg + SEPARATOR
    return msg.encode() + SEPARATOR


def decode_msg(msg: bytes):
    return msg.strip(SEPARATOR).decode()


async def join_pipe(reader, writer):
    try:
        # 如果缓冲区为空并且 feed_eof() 被调用，则返回 True
        while not reader.at_eof():
            data = await reader.read(2048)
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def start_proxy(tunnel_info: dict, msg: str):
    logging.info(f"start proxy. tunnel_info={tunnel_info}, msg={msg}")
    # 本地连接
    local_reader, local_writer = await asyncio.open_connection(tunnel_info['local_addr'], tunnel_info['local_port'])

    # make pipe
    remote_reader, remote_writer = await asyncio.open_connection(*SERVER_ADDR)
    # 1. hand shake
    data = {
        'type': 'PLUG_IN',
        'payload': {
            "server_id": msg.split()[-1]
        }
    }
    remote_writer.write(encode_msg(data))
    # remote_writer.write(encode_msg('hello'))
    await remote_writer.drain()

    task_list = [
        asyncio.create_task(join_pipe(local_reader, remote_writer)),
        asyncio.create_task(join_pipe(remote_reader, local_writer)),
    ]

    await asyncio.wait(task_list)
    logging.info(f"tunnel {data} disconnected")


async def parse_msg(server_reader: asyncio.StreamReader, server_writer, tunnel_info):
    tunnel_info = json.loads(tunnel_info)
    try:
        while True:
            data = await server_reader.readuntil(SEPARATOR)
            data = decode_msg(data)
            if data == 'pong':
                # TODO: record last pong
                continue

            logging.debug(data)
            if data == 'ping':
                server_writer.write(encode_msg('pong'))
                await server_writer.drain()

            if 'start proxy' in data:
                asyncio.create_task(start_proxy(tunnel_info, data))

    except asyncio.IncompleteReadError as e:
        logging.error(e, exc_info=True)
    finally:
        logging.info("Close the connection")
        server_writer.close()


async def heart_beat(writer):
    """
    心跳检测
    :param writer:
    :return:
    """
    while True:
        writer.write(encode_msg('ping'))
        await writer.drain()
        await asyncio.sleep(10)


async def make_tunnel(config):
    config = json.dumps(config)
    server_reader, server_writer = await asyncio.open_connection(*SERVER_ADDR)
    # 握手
    server_writer.write(encode_msg(config))
    # 等待直到可以适当地恢复写入到流
    await server_writer.drain()
    data = await server_reader.readuntil(SEPARATOR)
    data = decode_msg(data)
    logging.info(f"==========={data}")

    tasks_list = [
        asyncio.create_task(heart_beat(server_writer)),
        asyncio.create_task(parse_msg(server_reader, server_writer, config))
    ]

    await asyncio.wait(tasks_list)


CONFIGS = [{
    "type": "CONNECTOR",
    "local_addr": "127.0.0.1",
    "local_port": "9000",
    "remote_addr": "127.0.0.1",
    "remote_port": "9876"
}]


async def run():
    task_list = [
        asyncio.create_task(make_tunnel(config), name=str(config)) for config in CONFIGS
    ]
    done, pending = await asyncio.wait(task_list, return_when=FIRST_COMPLETED)
    while True:
        task_list = [task for task in pending]
        for task in done:
            task_id = int(task.get_name())
            logging.info(f"Retring {task_id}: {CONFIGS[task_id]}")
            task_list.append(
                asyncio.create_task(make_tunnel(CONFIGS[task_id]), name=str(task_id))
            )
        done, pending = await asyncio.wait(task_list, return_when=FIRST_COMPLETED)


def main():
    asyncio.run(run())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="intranet_penetration client")
    parser.add_argument('--host', help="Server host(ip)")
    parser.add_argument('--port', help="Server port", default=9876)
    parser.add_argument('--debug', help="Turn on debug mod", action='store_true')
    args = parser.parse_args()
    if args.host and args.port:
        SERVER_ADDRESS = (args.host, args.port)
    logging.basicConfig()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    main()
